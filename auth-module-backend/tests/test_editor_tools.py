"""
编辑器模块单元测试
- 工具注册表结构与入参校验
- PIL 纯函数（color_adjust / crop / flip / rotate）
- 图层文档结构校验
- 路由集成（fakeredis 打桩 task_queue + Flask test_client 全流程）
"""
import sys
import os
import io
import asyncio
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
import pymysql
from PIL import Image

import services.task_queue as tq
import controllers.editor.tools.tasks  # noqa: F401  触发 editor_tool_execute 任务注册（生产由 worker.py import）
from controllers.editor.tools import imaging
from controllers.editor.tools.registry import (
    EDITOR_TOOLS, get_tool, list_tools, validate_params,
)
from controllers.editor.layers import validate_layers
from config import get_config

# 测试专用用户 ID（编辑器表无外键约束，可直接使用）
USER_A = 999001
USER_B = 999002

_MIGRATION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'migrations', '2026_09_16_editor_tables.sql'
)


# ========== 环境准备 ==========

def _ensure_editor_tables():
    """在模型目标库（get_config() 对应库）确保编辑器两张表存在（幂等）"""
    c = get_config()
    with open(_MIGRATION_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    conn = pymysql.connect(
        host=c.MYSQL_HOST, port=c.MYSQL_PORT,
        user=c.MYSQL_USER, password=c.MYSQL_PASSWORD,
        database=c.MYSQL_DATABASE, charset='utf8mb4',
    )
    try:
        with conn.cursor() as cursor:
            for stmt in (s.strip() for s in content.split(';')):
                if not stmt:
                    continue
                # 去掉注释行后执行
                pure = '\n'.join(
                    line for line in stmt.split('\n')
                    if line.strip() and not line.strip().startswith('--')
                ).strip()
                if pure:
                    cursor.execute(pure)
        conn.commit()
    finally:
        conn.close()


def _cleanup_test_rows():
    """清理测试用户的编辑器数据（编辑器表无外键，直接删除）"""
    c = get_config()
    conn = pymysql.connect(
        host=c.MYSQL_HOST, port=c.MYSQL_PORT,
        user=c.MYSQL_USER, password=c.MYSQL_PASSWORD,
        database=c.MYSQL_DATABASE, charset='utf8mb4',
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM editor_task WHERE user_id IN (%s, %s)', (USER_A, USER_B))
            cursor.execute('DELETE FROM editor_document WHERE user_id IN (%s, %s)', (USER_A, USER_B))
        conn.commit()
    finally:
        conn.close()


# ========== fixtures ==========

@pytest.fixture()
def fake_server():
    """fakeredis 服务实例（同步/异步客户端共享，保证数据互通）"""
    import fakeredis
    return fakeredis.FakeServer()


@pytest.fixture()
def fake_sync_redis(fake_server, monkeypatch):
    """用 fakeredis 替换 task_queue 的同步 Redis 连接"""
    import fakeredis
    r = fakeredis.FakeStrictRedis(server=fake_server, decode_responses=True)
    monkeypatch.setattr(tq, 'get_sync_redis', lambda: r)
    return r


def _make_ctx(fake_server):
    """构造带 fakeredis 异步连接的 worker ctx（每次 asyncio.run 需新建连接）"""
    from fakeredis import aioredis as fake_aioredis
    return {'redis': fake_aioredis.FakeRedis(server=fake_server, decode_responses=True)}


@pytest.fixture()
def app(fake_server, fake_sync_redis, monkeypatch):
    """测试应用：fakeredis 打桩 submit_task 并同步执行真实任务函数（模拟 worker 消费）"""
    _ensure_editor_tables()
    from app import create_app
    app = create_app('testing')
    app.config['TESTING'] = True

    def fake_submit(name, payload, module=''):
        """打桩 submit_task：记录入参 + 同步跑完任务（模拟 worker 执行）"""
        task_id = uuid.uuid4().hex
        ctx = _make_ctx(fake_server)
        asyncio.run(tq.TASK_REGISTRY[name](ctx, payload, task_id))
        return task_id

    monkeypatch.setattr(tq, 'submit_task', fake_submit)

    yield app

    _cleanup_test_rows()


@pytest.fixture()
def client(app):
    """Flask 测试客户端"""
    return app.test_client()


def _auth_header(user_id):
    """生成测试 JWT 的 Authorization 头"""
    from utils.security import generate_token
    token = generate_token(user_id, f'editor_{user_id}@test.com', 'user')
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture()
def header_a():
    return _auth_header(USER_A)


@pytest.fixture()
def header_b():
    return _auth_header(USER_B)


@pytest.fixture()
def source_image_url():
    """生成 100x100 测试 PNG 并存入图片存储，返回可访问 URL（用后清理文件）"""
    from services.image_storage_service import save_image_bytes, get_image_path
    img = Image.new('RGB', (100, 100), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    url = save_image_bytes(buf.getvalue(), USER_A, 'png', prefix='editor_test')
    yield url
    # 清理测试图片文件
    filename = url.rsplit('/', 1)[-1]
    try:
        os.remove(get_image_path(filename))
    except OSError:
        pass


def _run_tool(func, png_bytes, params):
    """工具纯函数辅助：PIL Image 进、PNG bytes 出"""
    img = Image.open(io.BytesIO(png_bytes))
    out = func(img, params)
    buf = io.BytesIO()
    out.save(buf, format='PNG')
    return buf.getvalue()


# ========== 工具注册表 ==========

class TestRegistry:
    """工具注册表结构测试"""

    def test_registry_structure(self):
        """每个工具必须含 name/label/description/module/params_schema/func"""
        assert len(EDITOR_TOOLS) >= 4
        names = [t['name'] for t in EDITOR_TOOLS]
        assert len(names) == len(set(names)), '工具名不得重复'
        for tool in EDITOR_TOOLS:
            assert isinstance(tool['name'], str) and tool['name']
            assert isinstance(tool['label'], str) and tool['label']
            assert isinstance(tool['description'], str) and tool['description']
            # Task 9 起包含 AI 工具（module='ai'）
            assert tool['module'] in ('basic', 'ai')
            assert isinstance(tool['params_schema'], dict)
            assert callable(tool['func'])

    def test_get_tool(self):
        """get_tool：存在返回定义，不存在返回 None"""
        assert get_tool('color_adjust') is EDITOR_TOOLS[0]
        assert get_tool('nonexistent_tool') is None

    def test_list_tools_excludes_func(self):
        """list_tools：不含 func 函数引用，保留 name/label/params_schema"""
        tools = list_tools()
        assert len(tools) == len(EDITOR_TOOLS)
        for tool in tools:
            assert 'func' not in tool
            assert tool['name'] and tool['label']
            assert isinstance(tool['params_schema'], dict)  # AI 工具可为空 schema

    def test_validate_params_ok(self):
        """合法参数通过校验"""
        schema = get_tool('color_adjust')['params_schema']
        assert validate_params(schema, {'brightness': 20, 'contrast': -10}) is True
        assert validate_params(schema, {}) is True  # 全部可选

    def test_validate_params_out_of_range(self):
        """数值越界抛 ValueError"""
        schema = get_tool('color_adjust')['params_schema']
        with pytest.raises(ValueError, match='范围'):
            validate_params(schema, {'brightness': 200})

    def test_validate_params_missing_required(self):
        """缺少必填参数抛 ValueError"""
        schema = get_tool('crop')['params_schema']
        with pytest.raises(ValueError, match='缺少必填参数'):
            validate_params(schema, {'x': 0, 'y': 0})

    def test_validate_params_wrong_type(self):
        """类型错误抛 ValueError（布尔不是数字）"""
        schema = get_tool('color_adjust')['params_schema']
        with pytest.raises(ValueError, match='数字'):
            validate_params(schema, {'brightness': True})

    def test_validate_params_choices(self):
        """枚举值校验（rotate.angle）"""
        schema = get_tool('rotate')['params_schema']
        assert validate_params(schema, {'angle': 90}) is True
        with pytest.raises(ValueError, match='仅支持'):
            validate_params(schema, {'angle': 45})


# ========== PIL 纯函数 ==========

class TestImaging:
    """图像处理纯函数测试"""

    @pytest.fixture()
    def png_bytes(self):
        """100x100 测试 PNG"""
        img = Image.new('RGB', (100, 100), (180, 60, 40))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_color_adjust_keeps_size(self, png_bytes):
        """color_adjust：输出为合法 PNG 且尺寸不变"""
        out = _run_tool(imaging.color_adjust, png_bytes,
                        {'brightness': 20, 'contrast': 10, 'saturation': -15, 'temperature': 30})
        assert Image.open(io.BytesIO(out)).size == (100, 100)

    def test_color_adjust_invalid_range(self, png_bytes):
        """color_adjust：参数越界抛中文 ValueError"""
        img = Image.open(io.BytesIO(png_bytes))
        with pytest.raises(ValueError, match='超出允许范围'):
            imaging.color_adjust(img, {'brightness': 150})

    def test_color_adjust_missing_params_object(self):
        """color_adjust：params 非 dict 抛 ValueError"""
        with pytest.raises(ValueError, match='参数'):
            imaging.color_adjust(Image.new('RGB', (10, 10)), None)

    def test_crop_valid(self, png_bytes):
        """crop：正常裁剪 50x50"""
        out = _run_tool(imaging.crop, png_bytes, {'x': 10, 'y': 20, 'width': 50, 'height': 50})
        assert Image.open(io.BytesIO(out)).size == (50, 50)

    def test_crop_out_of_bounds(self, png_bytes):
        """crop：越界抛中文 ValueError（含边界提示）"""
        img = Image.open(io.BytesIO(png_bytes))
        with pytest.raises(ValueError, match='边界'):
            imaging.crop(img, {'x': 60, 'y': 0, 'width': 50, 'height': 50})

    def test_crop_missing_param(self, png_bytes):
        """crop：缺参数抛中文 ValueError"""
        img = Image.open(io.BytesIO(png_bytes))
        with pytest.raises(ValueError, match='缺少必填参数'):
            imaging.crop(img, {'x': 0, 'y': 0, 'width': 10})

    def test_flip_horizontal(self):
        """flip：水平镜像（尺寸不变，左右像素互换）"""
        img = Image.new('RGB', (4, 2))
        img.putpixel((0, 0), (255, 0, 0))
        img.putpixel((3, 0), (0, 0, 255))
        out = imaging.flip(img, {'horizontal': True})
        assert out.size == (4, 2)
        assert out.getpixel((0, 0)) == (0, 0, 255)
        assert out.getpixel((3, 0)) == (255, 0, 0)

    def test_flip_vertical(self):
        """flip：垂直镜像（尺寸不变，上下像素互换）"""
        img = Image.new('RGB', (4, 2))
        img.putpixel((0, 0), (255, 0, 0))
        img.putpixel((0, 1), (0, 0, 255))
        out = imaging.flip(img, {'vertical': True})
        assert out.size == (4, 2)
        assert out.getpixel((0, 0)) == (0, 0, 255)
        assert out.getpixel((0, 1)) == (255, 0, 0)

    def test_flip_both(self):
        """flip：双向翻转（对角镜像）"""
        img = Image.new('RGB', (4, 2))
        img.putpixel((0, 0), (255, 0, 0))
        out = imaging.flip(img, {'horizontal': True, 'vertical': True})
        assert out.size == (4, 2)
        assert out.getpixel((3, 1)) == (255, 0, 0)

    def test_flip_no_direction(self):
        """flip：未指定方向抛中文 ValueError"""
        with pytest.raises(ValueError, match='翻转方向'):
            imaging.flip(Image.new('RGB', (10, 10)), {})

    def test_rotate_90(self):
        """rotate：90 度顺时针 30x20 → 20x30"""
        out = imaging.rotate(Image.new('RGB', (30, 20)), {'angle': 90})
        assert out.size == (20, 30)

    def test_rotate_180(self):
        """rotate：180 度 30x20 → 30x20"""
        out = imaging.rotate(Image.new('RGB', (30, 20)), {'angle': 180})
        assert out.size == (30, 20)

    def test_rotate_invalid_angle(self):
        """rotate：非法角度抛中文 ValueError"""
        with pytest.raises(ValueError, match='90/180/270'):
            imaging.rotate(Image.new('RGB', (10, 10)), {'angle': 45})


# ========== 图层结构校验 ==========

class TestLayers:
    """图层文档结构校验测试"""

    def _valid_layer(self, **overrides):
        layer = {'id': 'layer-1', 'type': 'image', 'url': '/api/v1/images/a.png',
                 'x': 0, 'y': 0, 'width': 100, 'height': 100, 'z': 0}
        layer.update(overrides)
        return layer

    def test_valid_layers(self):
        """合法图层（单层/多层/text 类型）通过校验"""
        validate_layers([self._valid_layer()])
        validate_layers([])
        validate_layers([self._valid_layer(id='t1', type='text', text='Hello', opacity=0.5,
                                           visible=False, locked=True, rotation=15)])

    def test_not_a_list(self):
        """layers 非数组抛 ValueError"""
        with pytest.raises(ValueError, match='数组'):
            validate_layers({'id': 'x'})

    def test_missing_id(self):
        """缺少 id 抛 ValueError"""
        layer = self._valid_layer()
        layer.pop('id')
        with pytest.raises(ValueError, match='id'):
            validate_layers([layer])

    def test_invalid_type(self):
        """type 非法抛 ValueError"""
        with pytest.raises(ValueError, match='type'):
            validate_layers([self._valid_layer(type='shape')])

    def test_missing_position(self):
        """缺少必填坐标抛 ValueError"""
        layer = self._valid_layer()
        layer.pop('height')
        with pytest.raises(ValueError, match='height'):
            validate_layers([layer])

    def test_opacity_out_of_range(self):
        """opacity 越界抛 ValueError"""
        with pytest.raises(ValueError, match='opacity'):
            validate_layers([self._valid_layer(opacity=1.5)])

    def test_image_layer_requires_url(self):
        """image 图层必须提供 url"""
        layer = self._valid_layer()
        layer.pop('url')
        with pytest.raises(ValueError, match='url'):
            validate_layers([layer])


# ========== 路由集成（fakeredis 打桩） ==========

class TestToolRoutes:
    """工具端点路由测试"""

    def test_get_tools_requires_token(self, client):
        """未登录访问工具列表 → 401"""
        resp = client.get('/api/v1/editor/tools')
        assert resp.status_code == 401

    def test_get_tools(self, client, header_a):
        """GET /tools：返回工具列表（无 func）"""
        resp = client.get('/api/v1/editor/tools', headers=header_a)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['code'] == 0
        names = [t['name'] for t in data['data']]
        assert 'color_adjust' in names
        assert all('func' not in t for t in data['data'])

    def test_execute_unknown_tool_404(self, client, header_a):
        """执行不存在的工具 → 404"""
        resp = client.post('/api/v1/editor/tools/nonexistent/execute',
                           headers=header_a, json={'image_url': '/api/v1/images/x.png'})
        assert resp.status_code == 404

    def test_execute_param_invalid_400(self, client, header_a, source_image_url):
        """参数越界 → 400"""
        resp = client.post('/api/v1/editor/tools/color_adjust/execute',
                           headers=header_a,
                           json={'image_url': source_image_url, 'params': {'brightness': 999}})
        assert resp.status_code == 400
        assert 'brightness' in resp.get_json()['message']

    def test_execute_missing_image_url_400(self, client, header_a):
        """缺少 image_url → 400"""
        resp = client.post('/api/v1/editor/tools/color_adjust/execute',
                           headers=header_a, json={'params': {}})
        assert resp.status_code == 400

    def test_execute_source_image_not_exist_400(self, client, header_a):
        """来源图不存在 → 400"""
        resp = client.post('/api/v1/editor/tools/color_adjust/execute',
                           headers=header_a,
                           json={'image_url': '/api/v1/images/not_exist_abc123.png'})
        assert resp.status_code == 400
        assert '不存在' in resp.get_json()['message']

    def test_execute_full_flow(self, client, header_a, source_image_url):
        """全流程：提交 → 任务完成 → 结果图可访问（100x100 PNG）"""
        resp = client.post('/api/v1/editor/tools/color_adjust/execute',
                           headers=header_a,
                           json={'image_url': source_image_url,
                                 'params': {'brightness': 20, 'temperature': 25}})
        assert resp.status_code == 200
        task_id = resp.get_json()['data']['task_id']

        resp = client.get(f'/api/v1/editor/tasks/{task_id}', headers=header_a)
        assert resp.status_code == 200
        state = resp.get_json()['data']
        assert state['status'] == 'completed'
        assert state['result']['width'] == 100 and state['result']['height'] == 100

        # 结果图可直接 GET（images 路由无需认证）
        result_url = state['result']['image_url']
        resp = client.get(result_url)
        assert resp.status_code == 200
        out = Image.open(io.BytesIO(resp.data))
        assert out.format == 'PNG' and out.size == (100, 100)

    def test_execute_task_failure_path(self, client, header_a, source_image_url):
        """失败路径：flip 未指定方向 → 任务 failed + 中文错误信息"""
        resp = client.post('/api/v1/editor/tools/flip/execute',
                           headers=header_a, json={'image_url': source_image_url, 'params': {}})
        assert resp.status_code == 200
        task_id = resp.get_json()['data']['task_id']

        resp = client.get(f'/api/v1/editor/tasks/{task_id}', headers=header_a)
        state = resp.get_json()['data']
        assert state['status'] == 'failed'
        assert '翻转方向' in state['error']

    def test_task_ownership_403(self, client, header_a, header_b, source_image_url):
        """归属校验：B 查询 A 的任务 → 403"""
        resp = client.post('/api/v1/editor/tools/color_adjust/execute',
                           headers=header_a,
                           json={'image_url': source_image_url, 'params': {'brightness': 10}})
        task_id = resp.get_json()['data']['task_id']

        resp = client.get(f'/api/v1/editor/tasks/{task_id}', headers=header_b)
        assert resp.status_code == 403

    def test_task_not_found_404(self, client, header_a):
        """查询不存在的任务 → 404"""
        resp = client.get('/api/v1/editor/tasks/deadbeefdeadbeefdeadbeefdeadbeef', headers=header_a)
        assert resp.status_code == 404


class TestDocumentRoutes:
    """编辑文档端点测试"""

    def _create_doc(self, client, header, title='测试文档', layers=None):
        if layers is None:
            layers = [{'id': 'l1', 'type': 'image', 'url': '/api/v1/images/a.png',
                       'x': 0, 'y': 0, 'width': 100, 'height': 100}]
        return client.post('/api/v1/editor/documents', headers=header,
                           json={'title': title, 'layers': layers})

    def test_document_crud_flow(self, client, header_a, source_image_url):
        """文档创建 → 详情 → 更新 → 列表 全流程"""
        # 创建（含 image 图层，url 用真实存储地址）
        layers = [{'id': 'l1', 'type': 'image', 'url': source_image_url,
                   'x': 10, 'y': 10, 'width': 100, 'height': 100, 'z': 1, 'opacity': 0.9}]
        resp = self._create_doc(client, header_a, title='测试文档', layers=layers)
        assert resp.status_code == 201
        doc = resp.get_json()['data']
        assert doc['title'] == '测试文档' and doc['layers'] == layers

        # 详情（图层原样读回）
        resp = client.get(f"/api/v1/editor/documents/{doc['id']}", headers=header_a)
        assert resp.status_code == 200
        assert resp.get_json()['data']['layers'] == layers

        # 更新（自动保存：替换图层 + 改标题）
        new_layers = [{'id': 't1', 'type': 'text', 'text': '限时特惠', 'x': 0, 'y': 0,
                       'width': 200, 'height': 40}]
        resp = client.put(f"/api/v1/editor/documents/{doc['id']}", headers=header_a,
                          json={'title': '更新后', 'layers': new_layers})
        assert resp.status_code == 200
        updated = resp.get_json()['data']
        assert updated['title'] == '更新后' and updated['layers'] == new_layers

        # 列表（倒序、含 total）
        resp = client.get('/api/v1/editor/documents', headers=header_a)
        assert resp.status_code == 200
        listing = resp.get_json()['data']
        assert listing['total'] >= 1
        assert any(item['id'] == doc['id'] for item in listing['items'])
        assert all('layers' not in item for item in listing['items'])

    def test_document_invalid_layers_400(self, client, header_a):
        """非法图层 → 400"""
        resp = client.post('/api/v1/editor/documents', headers=header_a,
                           json={'layers': [{'id': 'l1', 'type': 'image', 'x': 0, 'y': 0}]})
        assert resp.status_code == 400

    def test_document_update_requires_payload(self, client, header_a):
        """PUT 空 body → 400"""
        resp = self._create_doc(client, header_a)
        doc_id = resp.get_json()['data']['id']
        resp = client.put(f'/api/v1/editor/documents/{doc_id}', headers=header_a, json={})
        assert resp.status_code == 400

    def test_document_ownership_404(self, client, header_a, header_b):
        """归属校验：B 查询 A 的文档 → 404（按无权限处理，不暴露存在性）"""
        resp = self._create_doc(client, header_a)
        doc_id = resp.get_json()['data']['id']
        resp = client.get(f'/api/v1/editor/documents/{doc_id}', headers=header_b)
        assert resp.status_code == 404

    def test_save_history(self, client, header_a, source_image_url, monkeypatch):
        """保存到历史：调用 history_service（category=ai_toolbox, sub_category=editor）"""
        import routes.editor_routes as er
        captured = {}

        def fake_save_history(**kwargs):
            captured.update(kwargs)
            return 12345

        monkeypatch.setattr(er, 'save_history', fake_save_history)

        resp = self._create_doc(client, header_a, title='历史测试')
        doc_id = resp.get_json()['data']['id']

        resp = client.post(f'/api/v1/editor/documents/{doc_id}/save-history',
                           headers=header_a, json={'result_image_url': source_image_url})
        assert resp.status_code == 201
        assert resp.get_json()['data'] == {'history_id': 12345}
        assert captured['category'] == 'ai_toolbox'
        assert captured['sub_category'] == 'editor'
        assert captured['title'] == '历史测试'
        assert captured['output_data'] == {'result_image': source_image_url}

    def test_save_history_missing_url_400(self, client, header_a):
        """保存历史缺少 result_image_url → 400"""
        resp = self._create_doc(client, header_a)
        doc_id = resp.get_json()['data']['id']
        resp = client.post(f'/api/v1/editor/documents/{doc_id}/save-history',
                           headers=header_a, json={})
        assert resp.status_code == 400

    def test_save_history_doc_not_found_404(self, client, header_a):
        """保存历史：文档不存在 → 404"""
        resp = client.post('/api/v1/editor/documents/99999999/save-history',
                           headers=header_a, json={'result_image_url': '/api/v1/images/a.png'})
        assert resp.status_code == 404
