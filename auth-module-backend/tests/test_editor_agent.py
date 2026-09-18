"""
编辑器 Agent 测试（Task 9 AI 工具 + Task 10 规划/执行引擎）

- validate_plan 单测：未知工具 / 缺参数 / 枚举非法 / 循环依赖 / 依赖补全 / 拓扑序
- planner 单测：LLM 调用 monkeypatch（合法/非法 JSON），解析重试与 repair 逻辑
- executor 单测：fakeredis + 3 步计划（含依赖），工具函数假实现，
  断言执行顺序 / cancel / retry_from_step
- 集成测试：RUN_AGENT_INTEGRATION=1 时执行（需真实 Redis + MySQL + 后台 worker，
  LLM 优先走真实 key，失败时 monkeypatch planner 的 LLM 函数）
"""
import sys
import os
import io
import json
import time
import uuid
import asyncio
import base64

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from PIL import Image

import services.task_queue as tq
import controllers.editor.tools.tasks  # noqa: F401  触发 editor_tool_execute 注册
import controllers.editor.agent.executor  # noqa: F401  触发 editor_agent_execute 注册
from controllers.editor.agent.validate import validate_plan
from controllers.editor.agent import planner
from controllers.editor.tools.registry import (
    EDITOR_TOOLS, get_tool, list_tools,
)
from controllers.editor.tools.ai_imaging import (
    _flood_remove_white, _diffusion_fill, _decode_selection_mask,
    _selection_to_api_mask, _nearest_api_size,
)

RUN_INTEGRATION = os.environ.get('RUN_AGENT_INTEGRATION') == '1'

# 集成测试专用用户（编辑器表无外键约束）
USER_INT = 999010


# ========== 通用辅助 ==========

def _plan(*steps):
    return {'steps': list(steps)}


def _step(sid, tool, params=None, depends_on=None):
    return {'id': sid, 'tool': tool, 'params': params or {}, 'depends_on': depends_on or []}


def _make_ctx(fake_server):
    """worker ctx（fakeredis 异步客户端；decode_responses=False 使 get 返回 bytes，
    与生产 arq 连接一致，保证中间产物 bytes 可直接喂给 PIL）"""
    from fakeredis import aioredis as fake_aioredis
    return {'redis': fake_aioredis.FakeRedis(server=fake_server, decode_responses=False)}


def _png_bytes(size=(100, 100), color=(200, 100, 50)):
    img = Image.new('RGB', size, color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


# ========== AI 工具注册表结构 ==========

class TestAIToolRegistry:
    """Task 9：AI 工具注册表结构"""

    AI_TOOL_NAMES = ['remove_background', 'replace_background',
                     'inpaint_erase', 'inpaint_replace', 'upscale']

    def test_ai_tools_registered(self):
        for name in self.AI_TOOL_NAMES:
            tool = get_tool(name)
            assert tool is not None, f'缺少 AI 工具: {name}'
            assert tool['module'] == 'ai'
            assert callable(tool['func'])
            assert isinstance(tool['params_schema'], dict)

    def test_list_tools_includes_ai(self):
        names = [t['name'] for t in list_tools()]
        assert set(self.AI_TOOL_NAMES).issubset(set(names))

    def test_mask_tools_flagged(self):
        """mask 类工具带 requires_mask=True 便于前端识别"""
        for name in ('inpaint_erase', 'inpaint_replace'):
            assert get_tool(name).get('requires_mask') is True
        assert 'requires_mask' not in get_tool('upscale')

    def test_ai_params_schema(self):
        """params_schema：background_prompt(string) / mask_data_uri(string) /
        prompt(string) / scale(enum [2])"""
        rb = get_tool('replace_background')['params_schema']
        assert rb['background_prompt']['type'] == 'string'
        assert rb['background_prompt']['required'] is True
        for name in ('inpaint_erase', 'inpaint_replace'):
            schema = get_tool(name)['params_schema']
            assert schema['mask_data_uri']['type'] == 'string'
            assert schema['mask_data_uri']['required'] is True
        assert get_tool('inpaint_replace')['params_schema']['prompt']['type'] == 'string'
        scale = get_tool('upscale')['params_schema']['scale']
        assert scale['choices'] == [2] and scale['default'] == 2


# ========== AI 工具 PIL 兜底算法 ==========

class TestAIFallbacks:
    """去白底泛洪 / 扩散填充 / 蒙版转换 纯算法兜底"""

    def test_flood_remove_white(self):
        """白底图泛洪：背景（边缘连通白色）变透明，主体保留"""
        img = Image.new('RGB', (10, 10), (255, 255, 255))
        for x in range(3, 7):
            for y in range(3, 7):
                img.putpixel((x, y), (200, 30, 30))
        out, removed = _flood_remove_white(img)
        assert out.mode == 'RGBA'
        assert removed == 10 * 10 - 16
        assert out.getpixel((0, 0))[3] == 0          # 背景透明
        assert out.getpixel((5, 5))[:3] == (200, 30, 30)  # 主体不透明
        assert out.getpixel((5, 5))[3] == 255

    def test_flood_remove_no_white(self):
        """深色背景图：无法去除任何像素（removed=0）"""
        img = Image.new('RGB', (10, 10), (10, 20, 30))
        _, removed = _flood_remove_white(img)
        assert removed == 0

    def test_diffusion_fill(self):
        """扩散填充：选区被周边颜色延展填充，尺寸不变"""
        img = Image.new('RGB', (20, 20), (0, 120, 255))
        mask = Image.new('L', (20, 20), 0)
        for x in range(8, 12):
            for y in range(8, 12):
                mask.putpixel((x, y), 255)
                img.putpixel((x, y), (255, 0, 0))
        out = _diffusion_fill(img, mask)
        assert out.size == (20, 20)
        # 填充后选区内颜色向周边蓝色靠拢（不再是纯红）
        center = out.getpixel((10, 10))
        assert center[2] > 100, '选区应被周边蓝色延展填充'

    def test_decode_selection_mask(self):
        """蒙版解码：data URI / 纯 base64 / 尺寸缩放 / 非法输入"""
        mask_b64 = base64_png((6, 4))
        m1 = _decode_selection_mask(f'data:image/png;base64,{mask_b64}', (6, 4))
        assert m1.mode == 'L' and m1.size == (6, 4)
        m2 = _decode_selection_mask(mask_b64, (12, 8))
        assert m2.size == (12, 8)
        with pytest.raises(ValueError, match='mask_data_uri'):
            _decode_selection_mask('', (6, 4))
        with pytest.raises(ValueError, match='有效'):
            _decode_selection_mask(base64.b64encode(b'\x00\x01\x02').decode(), (6, 4))

    def test_selection_to_api_mask(self):
        """白=选区 → API 蒙版（选区透明、其余不透明）"""
        mask = Image.new('L', (4, 4), 0)
        mask.putpixel((1, 1), 255)
        api_mask = Image.open(io.BytesIO(_selection_to_api_mask(mask)))
        assert api_mask.mode == 'RGBA'
        assert api_mask.getpixel((1, 1))[3] == 0      # 选区 → 透明（待编辑）
        assert api_mask.getpixel((0, 0))[3] == 255    # 非选区 → 不透明

    def test_nearest_api_size(self):
        assert _nearest_api_size(500, 500) == '1024x1024'
        assert _nearest_api_size(800, 600) == '1536x1024'
        assert _nearest_api_size(600, 800) == '1024x1536'


def base64_png(size):
    """生成全白选区蒙版的 base64 PNG"""
    img = Image.new('L', size, 255)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


# ========== validate_plan ==========

class TestValidatePlan:

    def test_valid_plan_topo_order(self):
        """合法计划：拓扑序正确（依赖在先）"""
        plan = _plan(
            _step('step-1', 'remove_background'),
            _step('step-2', 'upscale', {'scale': 2}, ['step-1']),
            _step('step-3', 'crop', {'x': 0, 'y': 0, 'width': 10, 'height': 10}, ['step-2']),
        )
        result = validate_plan(plan)
        assert result['valid'] is True
        assert result['errors'] == []
        assert result['order'] == ['step-1', 'step-2', 'step-3']

    def test_empty_plan(self):
        for bad in (None, {}, {'steps': []}, {'steps': 'x'}):
            result = validate_plan(bad)
            assert result['valid'] is False
            assert result['errors']

    def test_unknown_tool(self):
        result = validate_plan(_plan(_step('step-1', 'no_such_tool')))
        assert result['valid'] is False
        assert any('未知工具' in e and 'no_such_tool' in e for e in result['errors'])

    def test_missing_required_param(self):
        result = validate_plan(_plan(_step('step-1', 'replace_background', {})))
        assert result['valid'] is False
        assert any('缺少必填参数' in e and 'background_prompt' in e
                   for e in result['errors'])

    def test_invalid_enum_param(self):
        result = validate_plan(_plan(_step('step-1', 'upscale', {'scale': 4})))
        assert result['valid'] is False
        assert any('仅支持' in e for e in result['errors'])

    def test_wrong_param_type(self):
        result = validate_plan(_plan(_step('step-1', 'crop',
                                           {'x': 'a', 'y': 0, 'width': 1, 'height': 1})))
        assert result['valid'] is False
        assert any('数字' in e for e in result['errors'])

    def test_duplicate_ids(self):
        plan = _plan(_step('step-1', 'upscale'), _step('step-1', 'crop',
                     {'x': 0, 'y': 0, 'width': 1, 'height': 1}))
        result = validate_plan(plan)
        assert result['valid'] is False
        assert any('重复' in e for e in result['errors'])

    def test_unknown_dependency_ref(self):
        result = validate_plan(_plan(_step('step-1', 'upscale', {}, ['ghost'])))
        assert result['valid'] is False
        assert any('不存在' in e and 'ghost' in e for e in result['errors'])

    def test_cycle_detected(self):
        """循环依赖：报错且 order 为空"""
        plan = _plan(
            _step('a', 'upscale', {}, ['b']),
            _step('b', 'crop', {'x': 0, 'y': 0, 'width': 1, 'height': 1}, ['a']),
        )
        result = validate_plan(plan)
        assert result['valid'] is False
        assert any('循环' in e for e in result['errors'])
        assert result['order'] == []

    def test_dependency_auto_completion(self):
        """依赖补全：换背景漏写对抠图的依赖时自动补上（只补引用，不加步骤）"""
        plan = _plan(
            _step('cut', 'remove_background'),
            _step('bg', 'replace_background', {'background_prompt': '白色摄影棚'}),
        )
        result = validate_plan(plan)
        assert result['valid'] is True
        bg = next(s for s in plan['steps'] if s['id'] == 'bg')
        assert bg['depends_on'] == ['cut']
        assert result['order'] == ['cut', 'bg']

    def test_dependency_completion_no_extra_step(self):
        """计划中没有抠图步骤时不新增步骤（只做引用级补全）"""
        plan = _plan(_step('bg', 'replace_background',
                           {'background_prompt': '大理石台面'}))
        result = validate_plan(plan)
        assert result['valid'] is True
        assert len(plan['steps']) == 1
        assert plan['steps'][0]['depends_on'] == []

    def test_params_default_filled(self):
        """params/depends_on 缺省被就地补全为空 dict/list"""
        plan = {'steps': [{'id': 'step-1', 'tool': 'remove_background'}]}
        result = validate_plan(plan)
        assert result['valid'] is True
        step = plan['steps'][0]
        assert step['params'] == {} and step['depends_on'] == []


# ========== planner（LLM monkeypatch） ==========

PLAN_OK = _plan(
    _step('step-1', 'remove_background'),
    _step('step-2', 'replace_background',
          {'background_prompt': '白色摄影棚'}, ['step-1']),
)


class TestPlanner:
    """规划器：LLM 返回合法/非法 JSON、解析重试与校验修复"""

    @pytest.fixture()
    def patched_llm(self, monkeypatch):
        """替换 planner 命名空间内的 call_llm_chat，记录调用入参"""
        calls = []

        def install(responses):
            def fake_call_llm_chat(system_prompt='', user_content='', **kwargs):
                calls.append({'system_prompt': system_prompt,
                              'user_content': user_content})
                if isinstance(responses, list):
                    return responses.pop(0)
                return responses

            monkeypatch.setattr(planner, 'call_llm_chat', fake_call_llm_chat)
            return calls

        return install

    def test_valid_json_plan(self, patched_llm):
        """合法 JSON（含 ```json 包裹）→ 计划校验通过"""
        wrapped = '```json\n' + json.dumps(PLAN_OK, ensure_ascii=False) + '\n```'
        calls = patched_llm(wrapped)
        result = planner.generate_plan('把背景换成白色摄影棚')
        assert result['error'] is None
        assert result['errors'] == []
        assert result['order'] == ['step-1', 'step-2']
        assert result['plan']['steps'][1]['params']['background_prompt'] == '白色摄影棚'
        assert len(calls) == 1
        # 工具清单动态注入 system prompt
        assert 'remove_background' in calls[0]['system_prompt']
        assert 'params_schema' in calls[0]['system_prompt']

    def test_invalid_json_then_retry(self, patched_llm):
        """首次输出非法 JSON → 重试一次 LLM 后成功"""
        calls = patched_llm(['这不是JSON', json.dumps(PLAN_OK, ensure_ascii=False)])
        result = planner.generate_plan('抠图再换背景')
        assert result['error'] is None
        assert result['plan'] is not None
        assert result['order'] == ['step-1', 'step-2']
        assert len(calls) == 2, '解析失败应重试一次 LLM'

    def test_invalid_json_twice_structured_error(self, patched_llm):
        """两次都无法解析 → 返回结构化错误"""
        calls = patched_llm(['bad1', 'bad2'])
        result = planner.generate_plan('抠图')
        assert result['plan'] is None
        assert result['error']['code'] == 'PLAN_PARSE_FAILED'
        assert result['error']['message']
        assert len(calls) == 2

    def test_llm_service_error(self, patched_llm, monkeypatch):
        """LLM 服务异常（GenerationError）→ 结构化错误，不重试解析"""
        from services.generation_service import GenerationError

        def boom(**kwargs):
            raise GenerationError(code=5002, message='服务繁忙', http_status=503)

        monkeypatch.setattr(planner, 'call_llm_chat', boom)
        result = planner.generate_plan('抠图')
        assert result['plan'] is None
        assert result['error']['code'] == 'LLM_UNAVAILABLE'

    def test_validation_repair_once(self, patched_llm):
        """首版计划含未知工具 → repair 节点带错误反馈重新生成一次 → 通过"""
        bad_plan = _plan(_step('step-1', 'magic_wand'))
        calls = patched_llm([
            json.dumps(bad_plan, ensure_ascii=False),
            json.dumps(PLAN_OK, ensure_ascii=False),
        ])
        result = planner.generate_plan('把背景换成海边日落')
        assert result['error'] is None
        assert result['errors'] == []
        assert result['order'] == ['step-1', 'step-2']
        assert len(calls) == 2
        # 第二次调用应携带校验错误反馈
        assert '未知工具' in calls[1]['user_content']

    def test_repair_still_invalid(self, patched_llm):
        """修复后仍不通过 → 返回 errors（不再二次修复）"""
        bad = json.dumps(_plan(_step('step-1', 'magic_wand')), ensure_ascii=False)
        calls = patched_llm([bad, bad])
        result = planner.generate_plan('随便修一下')
        assert result['plan'] is not None
        assert result['errors'], '修复后仍应有校验错误'
        assert len(calls) == 2, 'repair 只执行一次'


# ========== executor（fakeredis + 工具假实现） ==========

class TestExecutor:
    """执行引擎：执行顺序 / 产物记录 / cancel / retry_from_step / 失败终止"""

    @pytest.fixture()
    def fake_server(self):
        import fakeredis
        return fakeredis.FakeServer()

    @pytest.fixture()
    def fake_redis(self, fake_server):
        import fakeredis
        return fakeredis.FakeStrictRedis(server=fake_server, decode_responses=True)

    @pytest.fixture()
    def bin_redis(self, fake_server):
        """二进制读取客户端（中间产物 PNG bytes；decode_responses=False）"""
        import fakeredis
        return fakeredis.FakeStrictRedis(server=fake_server, decode_responses=False)

    @pytest.fixture()
    def patched_env(self, fake_server, fake_redis, monkeypatch):
        """打桩：执行顺序记录 + 工具假实现 + 存图/读图假实现 + fakeredis 状态读取"""
        from controllers.editor.agent import executor as ex

        calls = []
        src_png = _png_bytes()

        def fake_tool(name):
            def _fn(img, params):
                calls.append({'tool': name, 'size': img.size})
                return img.copy()
            return _fn

        reg = {
            'color_adjust': {**get_tool('color_adjust'), 'func': fake_tool('color_adjust')},
            'flip': {**get_tool('flip'), 'func': fake_tool('flip')},
            'rotate': {**get_tool('rotate'), 'func': fake_tool('rotate')},
        }
        monkeypatch.setattr(
            'controllers.editor.tools.registry._TOOLS_BY_NAME',
            {**{t['name']: t for t in EDITOR_TOOLS}, **reg},
        )
        # 任务状态读取走 fakeredis（与 worker ctx 共享同一 FakeServer）
        monkeypatch.setattr(tq, 'get_sync_redis', lambda: fake_redis)
        # 读图 / 存图假实现
        saved = []
        monkeypatch.setattr(ex, '_load_image_bytes', lambda url: src_png)
        monkeypatch.setattr(
            ex, 'save_image_bytes',
            lambda data, uid, ext, prefix='img': saved.append(data)
            or f'/api/v1/images/fake_{prefix}_{len(saved)}.png',
        )
        return {'calls': calls, 'saved': saved, 'src_png': src_png,
                'fake_server': fake_server, 'executor': ex}

    def _run(self, env, payload, task_id):
        ctx = _make_ctx(env['fake_server'])
        asyncio.run(env['executor'].editor_agent_execute(ctx, payload, task_id))

    THREE_STEP_PLAN = _plan(
        _step('step-1', 'color_adjust'),
        _step('step-2', 'flip', {'horizontal': True}, ['step-1']),
        _step('step-3', 'rotate', {'angle': 90}, ['step-2']),
    )

    def test_execute_full_plan(self, patched_env, fake_redis, bin_redis):
        """3 步计划按拓扑序执行；每步产物 URL 记录进 result；中间产物写 Redis"""
        task_id = uuid.uuid4().hex
        self._run(patched_env, {
            'plan': self.THREE_STEP_PLAN,
            'user_id': 1,
            'layer_image_url': '/api/v1/images/src.png',
        }, task_id)

        calls = patched_env['calls']
        assert [c['tool'] for c in calls] == ['color_adjust', 'flip', 'rotate']
        assert all(c['size'] == (100, 100) for c in calls)

        state = tq.get_task(task_id)
        assert state['status'] == 'completed'
        result = state['result']
        assert [s['id'] for s in result['steps']] == ['step-1', 'step-2', 'step-3']
        assert all(s['status'] == 'completed' and s['image_url'] for s in result['steps'])
        assert result['final_image_url'] == result['steps'][-1]['image_url']
        assert len(patched_env['saved']) == 3

        # 中间产物 Redis key（TTL 同任务，PNG 字节）
        for sid in ('step-1', 'step-2', 'step-3'):
            key = f'agent-plan:{task_id}:step:{sid}'
            assert fake_redis.exists(key)
            assert fake_redis.ttl(key) > 0
            stored = bin_redis.get(key)
            assert stored and stored[:4] == b'\x89PNG'
        # 进度文案
        assert '步骤 3/3' in state['step']

    def test_cancel_before_steps(self, patched_env, fake_redis):
        """预置取消标记：一步不执行，任务 failed（用户取消后续步骤）"""
        task_id = uuid.uuid4().hex
        fake_redis.set(f'agent-plan:{task_id}:cancel', '1')
        self._run(patched_env, {
            'plan': self.THREE_STEP_PLAN,
            'user_id': 1,
            'layer_image_url': '/api/v1/images/src.png',
        }, task_id)

        assert patched_env['calls'] == []
        state = tq.get_task(task_id)
        assert state['status'] == 'failed'
        assert state['error'] == '用户取消后续步骤'

    def test_step_failure_terminates(self, patched_env, fake_redis, monkeypatch):
        """第 2 步失败：任务终止，error 携带失败步骤与已完成步骤"""

        def boom(img, params):
            patched_env['calls'].append({'tool': 'flip', 'size': img.size})
            raise RuntimeError('模拟工具崩溃')

        monkeypatch.setattr(
            'controllers.editor.tools.registry._TOOLS_BY_NAME',
            {**{t['name']: t for t in EDITOR_TOOLS},
             'color_adjust': get_tool('color_adjust'),
             'flip': {**get_tool('flip'), 'func': boom},
             'rotate': get_tool('rotate')},
        )

        task_id = uuid.uuid4().hex
        self._run(patched_env, {
            'plan': self.THREE_STEP_PLAN,
            'user_id': 1,
            'layer_image_url': '/api/v1/images/src.png',
        }, task_id)

        assert [c['tool'] for c in patched_env['calls']] == ['color_adjust', 'flip']
        state = tq.get_task(task_id)
        assert state['status'] == 'failed'
        error = state['error']
        assert error['failed_step'] == 'step-2'
        assert error['completed_steps'] == ['step-1']
        assert '步骤 2/3' in error['message'] and '模拟工具崩溃' in error['message']

    def test_retry_from_step_reuses_intermediates(self, patched_env, fake_redis):
        """单步重试：复用原任务 step-1 中间产物，只重跑 step-2/step-3"""
        task_id = uuid.uuid4().hex
        fake_redis.set(f'agent-plan:orig-task:step:step-1', patched_env['src_png'])
        self._run(patched_env, {
            'plan': self.THREE_STEP_PLAN,
            'user_id': 1,
            'layer_image_url': '/api/v1/images/src.png',
            'retry_from_step': 'step-2',
            'source_task_id': 'orig-task',
        }, task_id)

        assert [c['tool'] for c in patched_env['calls']] == ['flip', 'rotate']
        state = tq.get_task(task_id)
        assert state['status'] == 'completed'
        result = state['result']
        assert [s['id'] for s in result['steps']] == ['step-2', 'step-3']
        assert result['final_image_url'] == result['steps'][-1]['image_url']
        # 新任务的 step-3 中间产物写入新 task_id 命名空间
        assert fake_redis.exists(f'agent-plan:{task_id}:step:step-3')

    def test_retry_missing_intermediate_fails(self, patched_env, fake_redis):
        """重试时前置中间产物过期 → 任务失败并中文提示"""
        task_id = uuid.uuid4().hex
        self._run(patched_env, {
            'plan': self.THREE_STEP_PLAN,
            'user_id': 1,
            'layer_image_url': '/api/v1/images/src.png',
            'retry_from_step': 'step-2',
            'source_task_id': 'orig-task',
        }, task_id)

        assert patched_env['calls'] == []
        state = tq.get_task(task_id)
        assert state['status'] == 'failed'
        assert '中间产物已过期' in str(state['error'])

    def test_invalid_plan_rejected(self, patched_env, fake_redis):
        """执行前再校验：未知工具的计划直接失败"""
        task_id = uuid.uuid4().hex
        self._run(patched_env, {
            'plan': _plan(_step('step-1', 'magic_wand')),
            'user_id': 1,
            'layer_image_url': '/api/v1/images/src.png',
        }, task_id)

        assert patched_env['calls'] == []
        state = tq.get_task(task_id)
        assert state['status'] == 'failed'
        assert '计划校验失败' in str(state['error'])

    def test_bad_retry_step(self, patched_env, fake_redis):
        """retry_from_step 不在计划中 → 失败"""
        task_id = uuid.uuid4().hex
        self._run(patched_env, {
            'plan': self.THREE_STEP_PLAN,
            'user_id': 1,
            'layer_image_url': '/api/v1/images/src.png',
            'retry_from_step': 'ghost',
        }, task_id)
        state = tq.get_task(task_id)
        assert state['status'] == 'failed'
        assert '重试步骤不存在' in str(state['error'])


# ========== 集成测试（真实 Redis / MySQL / worker / LLM） ==========
# 运行方式：
#   1. 启动 Redis（docker ecomai-redis）与 MySQL
#   2. cd auth-module-backend && python worker.py   （后台 worker）
#   3. set RUN_AGENT_INTEGRATION=1 && python -m pytest tests/test_editor_agent.py -q -k Integration

@pytest.mark.skipif(not RUN_INTEGRATION, reason='设置 RUN_AGENT_INTEGRATION=1 并启动真实 worker 后运行')
class TestAgentIntegration:
    """app.test_client + 真实 worker：plan → execute → 轮询至完成；upscale 真跑"""

    @pytest.fixture(scope='class')
    def real_app(self):
        import pymysql
        from config import get_config
        from app import create_app
        app = create_app('testing')
        app.config['TESTING'] = True
        yield app
        # 清理集成测试数据
        c = get_config()
        conn = pymysql.connect(host=c.MYSQL_HOST, port=c.MYSQL_PORT,
                               user=c.MYSQL_USER, password=c.MYSQL_PASSWORD,
                               database=c.MYSQL_DATABASE, charset='utf8mb4')
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM editor_task WHERE user_id = %s', (USER_INT,))
                cursor.execute('DELETE FROM editor_document WHERE user_id = %s', (USER_INT,))
            conn.commit()
        finally:
            conn.close()

    @pytest.fixture()
    def real_client(self, real_app):
        return real_app.test_client()

    @pytest.fixture()
    def header(self):
        from utils.security import generate_token
        token = generate_token(USER_INT, f'agent_{USER_INT}@test.com', 'user')
        return {'Authorization': f'Bearer {token}'}

    @pytest.fixture()
    def source_image_url(self):
        from services.image_storage_service import save_image_bytes, get_image_path
        buf = io.BytesIO()
        Image.new('RGB', (100, 100), (200, 100, 50)).save(buf, format='PNG')
        url = save_image_bytes(buf.getvalue(), USER_INT, 'png', prefix='editor_agent_it')
        yield url
        try:
            os.remove(get_image_path(url.rsplit('/', 1)[-1]))
        except OSError:
            pass

    def _poll_task(self, client, header, task_id, timeout=300):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            resp = client.get(f'/api/v1/editor/tasks/{task_id}', headers=header)
            assert resp.status_code == 200
            last = resp.get_json()['data']
            if last['status'] in ('completed', 'failed'):
                return last
            time.sleep(2)
        return last

    def test_plan_with_real_llm(self, real_client, header, monkeypatch):
        """POST /agent/plan：优先真实 LLM；key 无效/超时则 monkeypatch LLM 完成链路"""
        resp = real_client.post('/api/v1/editor/agent/plan', headers=header,
                                json={'instruction': '把背景换成白色摄影棚，然后高清放大 2 倍'})
        used_real_llm = resp.status_code == 200 and 'errors' not in resp.get_json()['data']
        if not used_real_llm:
            print('\n[集成说明] 真实 LLM 规划失败（key 无效或超时），'
                  'monkeypatch planner.call_llm_chat 完成集成：',
                  resp.get_json() and resp.get_json().get('message'))

            def fake_llm_chat(system_prompt='', user_content='', **kwargs):
                plan = {'steps': [
                    {'id': 'step-1', 'tool': 'remove_background', 'params': {},
                     'depends_on': []},
                    {'id': 'step-2', 'tool': 'replace_background',
                     'params': {'background_prompt': '白色摄影棚'},
                     'depends_on': ['step-1']},
                    {'id': 'step-3', 'tool': 'upscale', 'params': {'scale': 2},
                     'depends_on': ['step-2']},
                ]}
                return json.dumps(plan, ensure_ascii=False)

            monkeypatch.setattr(planner, 'call_llm_chat', fake_llm_chat)
            resp = real_client.post('/api/v1/editor/agent/plan', headers=header,
                                    json={'instruction': '把背景换成白色摄影棚，然后高清放大 2 倍'})

        assert resp.status_code == 200
        data = resp.get_json()['data']
        assert data['plan'] and data['order']
        print('\n[集成] plan 成功 order =', data['order'])

    def test_plan_missing_instruction_400(self, real_client, header):
        resp = real_client.post('/api/v1/editor/agent/plan', headers=header, json={})
        assert resp.status_code == 400

    def test_execute_and_poll(self, real_client, header, source_image_url, monkeypatch):
        """plan → execute → 真实 worker 执行 → 轮询至 completed，steps 顺序正确"""
        plan = {'steps': [
            {'id': 'step-1', 'tool': 'color_adjust',
             'params': {'brightness': 15}, 'depends_on': []},
            {'id': 'step-2', 'tool': 'rotate', 'params': {'angle': 90},
             'depends_on': ['step-1']},
            {'id': 'step-3', 'tool': 'upscale', 'params': {'scale': 2},
             'depends_on': ['step-2']},
        ]}
        resp = real_client.post('/api/v1/editor/agent/execute', headers=header,
                                json={'plan': plan, 'image_url': source_image_url})
        assert resp.status_code == 200, resp.get_json()
        task_id = resp.get_json()['data']['task_id']

        state = self._poll_task(real_client, header, task_id, timeout=300)
        assert state['status'] == 'completed', f"step={state.get('step')} error={state.get('error')}"
        result = state['result']
        assert [s['id'] for s in result['steps']] == ['step-1', 'step-2', 'step-3']
        assert all(s['image_url'] for s in result['steps'])
        assert result['final_image_url'] == result['steps'][-1]['image_url']

        # 最终图：rotate 90 → 100x100；upscale 2x → 200x200
        img = Image.open(io.BytesIO(real_client.get(result['final_image_url']).data))
        assert img.size == (200, 200)
        print('\n[集成] execute 完成 steps =', [s['id'] for s in result['steps']])

    def test_execute_invalid_plan_400(self, real_client, header):
        plan = {'steps': [{'id': 'step-1', 'tool': 'magic_wand', 'params': {},
                           'depends_on': []}]}
        resp = real_client.post('/api/v1/editor/agent/execute', headers=header,
                                json={'plan': plan, 'image_url': '/api/v1/images/x.png'})
        assert resp.status_code == 400

    def test_cancel_and_retry_endpoints(self, real_client, header, source_image_url):
        """cancel 写标记 + retry 建 新任务（校验归属与 step_id）"""
        plan = {'steps': [
            {'id': 'step-1', 'tool': 'color_adjust', 'params': {'brightness': 10},
             'depends_on': []},
            {'id': 'step-2', 'tool': 'upscale', 'params': {'scale': 2},
             'depends_on': ['step-1']},
        ]}
        resp = real_client.post('/api/v1/editor/agent/execute', headers=header,
                                json={'plan': plan, 'image_url': source_image_url})
        task_id = resp.get_json()['data']['task_id']
        # 等第一步完成，保证中间产物存在（供 retry 复用）
        self._poll_task(real_client, header, task_id, timeout=300)

        resp = real_client.post(f'/api/v1/editor/agent/tasks/{task_id}/cancel',
                                headers=header)
        assert resp.status_code == 200 and resp.get_json()['data'] == {'ok': True}

        resp = real_client.post(f'/api/v1/editor/agent/tasks/{task_id}/retry',
                                headers=header, json={'step_id': 'step-2'})
        assert resp.status_code == 200, resp.get_json()
        new_task_id = resp.get_json()['data']['task_id']
        assert new_task_id != task_id
        state = self._poll_task(real_client, header, new_task_id, timeout=300)
        assert state['status'] == 'completed', state.get('error')
        assert [s['id'] for s in state['result']['steps']] == ['step-2']
        print('\n[集成] retry 完成，仅重跑 step-2')

    def test_upscale_tool_real(self, real_client, header, source_image_url):
        """AI 工具真跑：upscale（通道失败时 LANCZOS 兜底必成功）→ 200x200"""
        resp = real_client.post('/api/v1/editor/tools/upscale/execute', headers=header,
                                json={'image_url': source_image_url, 'params': {}})
        assert resp.status_code == 200, resp.get_json()
        task_id = resp.get_json()['data']['task_id']

        state = self._poll_task(real_client, header, task_id, timeout=300)
        assert state['status'] == 'completed', state.get('error')
        assert state['result']['width'] == 200 and state['result']['height'] == 200
        img = Image.open(io.BytesIO(real_client.get(state['result']['image_url']).data))
        assert img.size == (200, 200)
        print('\n[集成] upscale 真跑完成 200x200')
