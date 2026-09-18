"""
AI 图片编辑器路由模块
- 工具注册表查询（前端工具栏数据源）
- 工具异步执行（ARQ 任务）与任务状态查询（降级轮询通道，SSE 走 /api/v1/sse/tasks/<task_id>）
- 编辑文档（图层）管理：创建 / 详情 / 更新 / 列表
- 保存到历史记录（复用 history_service，sub_category='editor'）
"""
import os

from flask import Blueprint, request, jsonify, g

from middleware.auth_middleware import token_required
import services.task_queue as task_queue
from services.image_storage_service import get_image_path
from services.history_service import save_history
from services.auth_service import AuthError
from controllers.editor.tools.registry import get_tool, list_tools, validate_params
from controllers.editor.layers import validate_layers
from controllers.editor.agent.planner import generate_plan
from controllers.editor.agent.validate import validate_plan as validate_agent_plan
from controllers.editor.agent.executor import cancel_key
from models.editor_document import EditorDocumentModel
from models.editor_task import EditorTaskModel

editor_bp = Blueprint('editor', __name__, url_prefix='/api/v1/editor')

# 本服务图片 URL 标识
_URL_MARKER = '/api/v1/images/'

document_model = EditorDocumentModel()
task_model = EditorTaskModel()


# ========== 响应与校验辅助 ==========

def _success(data=None, message='success', http_status=200):
    """统一成功响应"""
    return jsonify({'code': 0, 'message': message, 'data': data}), http_status


def _error(message, code=4001, http_status=400):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': None}), http_status


def _check_source_image(image_url):
    """
    校验来源图：仅支持本服务图片地址（/api/v1/images/，文件须存在）或 data URI
    合法返回 None，否则返回错误文案
    """
    if not isinstance(image_url, str) or not image_url.strip():
        return 'image_url 不能为空'
    url = image_url.strip()
    if url.startswith('data:image/'):
        return None
    idx = url.find(_URL_MARKER)
    if idx < 0:
        return '仅支持本服务图片地址（/api/v1/images/）或 data URI'
    filename = url[idx + len(_URL_MARKER):]
    # 文件名安全检查：存储目录为扁平结构，禁止路径分隔符与目录穿越
    if not filename or '..' in filename or '/' in filename or '\\' in filename:
        return '无效的图片地址'
    if not os.path.isfile(get_image_path(filename)):
        return '来源图片不存在'
    return None


# ========== 工具注册表与执行 ==========

@editor_bp.route('/tools', methods=['GET'])
@token_required
def get_editor_tools():
    """
    GET /api/v1/editor/tools — 工具注册表（前端工具栏数据源）

    Response:
    {
        "code": 0, "message": "success",
        "data": [
            {"name": "color_adjust", "label": "色彩调整", "description": "...",
             "module": "basic", "params_schema": {...}}, ...
        ]
    }
    """
    return _success(list_tools())


@editor_bp.route('/tools/<tool>/execute', methods=['POST'])
@token_required
def execute_editor_tool(tool):
    """
    POST /api/v1/editor/tools/<tool>/execute — 提交工具执行异步任务

    Request Body:
    {
        "image_url": "/api/v1/images/xxx.png",   // 必填，本服务图片地址或 data URI
        "params": {...}                           // 可选，按该工具 params_schema 校验
    }

    Response:
    {"code": 0, "message": "success", "data": {"task_id": "xxx", "status": "queued"}}
    """
    tool_def = get_tool(tool)
    if tool_def is None:
        return _error(f'工具不存在: {tool}', code=4004, http_status=404)

    data = request.get_json(silent=True)
    if not data:
        return _error('请求参数不能为空')

    image_url = data.get('image_url')
    error = _check_source_image(image_url)
    if error:
        return _error(error)

    params = data.get('params') or {}
    try:
        validate_params(tool_def['params_schema'], params)
    except ValueError as e:
        return _error(str(e))

    user_id = g.current_user['user_id']
    # 提交异步任务（task_id 由任务队列生成）
    task_id = task_queue.submit_task('editor_tool_execute', {
        'tool': tool,
        'image_url': image_url,
        'params': params,
        'user_id': user_id,
    }, module='editor')

    # 落库任务记录（归属校验 + Redis 过期后的降级查询）
    task_model.create(task_id=task_id, user_id=user_id, tool=tool, params=params, status='queued')

    return _success({'task_id': task_id, 'status': 'queued'})


@editor_bp.route('/tasks/<task_id>', methods=['GET'])
@token_required
def get_editor_task(task_id):
    """
    GET /api/v1/editor/tasks/<task_id> — 查询任务状态（归属校验，降级轮询通道）

    Response:
    {
        "code": 0, "message": "success",
        "data": {
            "task_id": "xxx", "tool": "color_adjust",
            "status": "queued|running|completed|failed",
            "step": "处理中", "pct": 40,
            "result": {"image_url": "...", "width": 100, "height": 100, "tool": "..."},
            "error": null,
            "created_at": "...", "updated_at": "..."
        }
    }
    """
    row = task_model.find_by_task_id(task_id)
    if row is None:
        return _error('任务不存在', code=4004, http_status=404)
    if row['user_id'] != g.current_user['user_id']:
        return _error('无权查看该任务', code=1003, http_status=403)

    # Redis 实时状态优先，DB 记录兜底（任务过期后仍可查到结果）
    state = task_queue.get_task(task_id)
    if state:
        status = state.get('status') or row.get('status') or 'queued'
        step = state.get('step') or ''
        pct = state.get('pct', 0)
        result = state.get('result')
        error = state.get('error')
    else:
        status = row.get('status') or 'queued'
        step, pct = '', 0
        result = {'image_url': row['result_url']} if row.get('result_url') else None
        error = row.get('error')

    return _success({
        'task_id': task_id,
        'tool': row.get('tool'),
        'status': status,
        'step': step,
        'pct': pct,
        'result': result,
        'error': error,
        'created_at': row.get('created_at'),
        'updated_at': row.get('updated_at'),
    })


# ========== 编辑文档（图层）管理 ==========

@editor_bp.route('/documents', methods=['POST'])
@token_required
def create_editor_document():
    """
    POST /api/v1/editor/documents — 创建编辑文档

    Request Body:
    {
        "source_image_id": "xxx.png",  // 可选，来源图片标识
        "title": "我的设计",            // 可选，默认 ''
        "layers": [...]                 // 可选，默认 []，结构见 controllers/editor/layers.py
    }

    Response (201):
    {"code": 0, "message": "创建成功", "data": {"id": 1, "user_id": 1, "source_image_id": "...",
     "title": "...", "layers": [...], "created_at": "...", "updated_at": "..."}}
    """
    data = request.get_json(silent=True) or {}

    title = data.get('title')
    if title is not None and not isinstance(title, str):
        return _error('title 必须为字符串')
    source_image_id = data.get('source_image_id')
    if source_image_id is not None and not isinstance(source_image_id, str):
        return _error('source_image_id 必须为字符串')
    layers = data.get('layers')
    if layers is None:
        layers = []
    try:
        validate_layers(layers)
    except ValueError as e:
        return _error(str(e))

    user_id = g.current_user['user_id']
    doc_id = document_model.create(
        user_id=user_id,
        source_image_id=source_image_id,
        title=(title or '').strip(),
        layers=layers,
    )
    return _success(document_model.find_by_id(doc_id, user_id), message='创建成功', http_status=201)


@editor_bp.route('/documents/<int:document_id>', methods=['GET'])
@token_required
def get_editor_document(document_id):
    """
    GET /api/v1/editor/documents/<document_id> — 文档详情（含 layers，校验归属）

    Response:
    {"code": 0, "message": "success", "data": { id, user_id, source_image_id, title,
     layers: [...], created_at, updated_at }}
    """
    doc = document_model.find_by_id(document_id, g.current_user['user_id'])
    if doc is None:
        return _error('文档不存在', code=4004, http_status=404)
    return _success(doc)


@editor_bp.route('/documents/<int:document_id>', methods=['PUT'])
@token_required
def update_editor_document(document_id):
    """
    PUT /api/v1/editor/documents/<document_id> — 更新文档（自动保存用）

    Request Body:
    {"title": "...", "layers": [...]}   // title 与 layers 至少提供一个

    Response:
    {"code": 0, "message": "保存成功", "data": { 更新后的完整文档 }}
    """
    user_id = g.current_user['user_id']
    data = request.get_json(silent=True)
    if not data:
        return _error('请求参数不能为空')

    title = data.get('title')
    layers = data.get('layers')
    if title is None and layers is None:
        return _error('title 与 layers 至少提供一个')
    if title is not None and not isinstance(title, str):
        return _error('title 必须为字符串')
    if layers is not None:
        try:
            validate_layers(layers)
        except ValueError as e:
            return _error(str(e))

    updated = document_model.update(
        document_id, user_id,
        title=(title.strip() if title is not None else None),
        layers=layers,
    )
    if not updated:
        return _error('文档不存在', code=4004, http_status=404)
    return _success(document_model.find_by_id(document_id, user_id), message='保存成功')


@editor_bp.route('/documents', methods=['GET'])
@token_required
def list_editor_documents():
    """
    GET /api/v1/editor/documents — 当前用户文档列表（updated_at 倒序，不含 layers）

    Response:
    {"code": 0, "message": "success", "data": {"items": [{id, title, updated_at, ...}], "total": n}}
    """
    items = document_model.list_by_user(g.current_user['user_id'])
    return _success({'items': items, 'total': len(items)})


@editor_bp.route('/documents/<int:document_id>/save-history', methods=['POST'])
@token_required
def save_editor_document_history(document_id):
    """
    POST /api/v1/editor/documents/<document_id>/save-history — 保存到历史记录

    Request Body:
    {"result_image_url": "/api/v1/images/xxx.png"}   // 必填，编辑结果图地址

    Response (201):
    {"code": 0, "message": "保存成功", "data": {"history_id": 123}}
    """
    user_id = g.current_user['user_id']
    doc = document_model.find_by_id(document_id, user_id)
    if doc is None:
        return _error('文档不存在', code=4004, http_status=404)

    data = request.get_json(silent=True) or {}
    result_image_url = data.get('result_image_url')
    if not isinstance(result_image_url, str) or not result_image_url.strip():
        return _error('result_image_url 不能为空')

    layers = doc.get('layers') or []
    try:
        record_id = save_history(
            user_id=user_id,
            category='ai_toolbox',
            sub_category='editor',
            title=(doc.get('title') or '').strip() or None,  # 空标题走 history_service 自动生成
            input_data={
                'document_id': document_id,
                'source_image_id': doc.get('source_image_id'),
                'layers_count': len(layers),
            },
            output_data={'result_image': result_image_url.strip()},
        )
    except AuthError as e:
        return _error(e.message, code=e.code, http_status=e.http_status)

    return _success({'history_id': record_id}, message='保存成功', http_status=201)


# ========== Agent 修图规划与执行（Task 10） ==========

AGENT_TASK_NAME = 'editor_agent'


@editor_bp.route('/agent/plan', methods=['POST'])
@token_required
def agent_plan():
    """
    POST /api/v1/editor/agent/plan — AI 生成修图计划（同步，LLM 一次调用约 3-8 秒）

    Request Body:
    {
        "instruction": "把背景换成白色摄影棚，再放大 2 倍",  // 必填，中文编辑指令
        "document_id": 1,        // 可选，来源文档（仅作上下文，规划不读图）
        "image_url": "/api/v1/images/xxx.png"  // 可选，来源图片（仅作上下文）
    }

    Response:
    {
        "code": 0, "message": "success",
        "data": {
            "plan": {"steps": [{"id": "step-1", "tool": "upscale", "params": {...},
                                "depends_on": []}]},
            "order": ["step-1"],        // 拓扑执行序列
            "errors": ["..."]           // 仅校验不通过时返回（计划不落库）
        }
    }
    """
    data = request.get_json(silent=True) or {}
    instruction = data.get('instruction')
    if not isinstance(instruction, str) or not instruction.strip():
        return _error('instruction 不能为空')
    document_id = data.get('document_id')
    if document_id is not None and not isinstance(document_id, int):
        return _error('document_id 必须为整数')

    try:
        result = generate_plan(instruction.strip(),
                               user_id=g.current_user['user_id'])
    except Exception as e:
        return _error(f'AI 规划失败: {e}', code=5002, http_status=502)

    if result.get('error'):
        return _error(result['error'].get('message', 'AI 规划失败'),
                      code=5002, http_status=502)

    payload = {'plan': result.get('plan'), 'order': result.get('order', [])}
    if result.get('errors'):
        payload['errors'] = result['errors']
    return _success(payload)


@editor_bp.route('/agent/execute', methods=['POST'])
@token_required
def agent_execute():
    """
    POST /api/v1/editor/agent/execute — 校验计划并提交异步执行任务

    Request Body:
    {
        "plan": {"steps": [...]},   // 必填，/agent/plan 生成的计划（可人工微调）
        "image_url": "/api/v1/images/xxx.png",  // 与 document_id 二选一，来源图
        "document_id": 1             // 与 image_url 二选一，取文档第一个图片图层
    }

    Response:
    {"code": 0, "message": "success", "data": {"task_id": "xxx", "status": "queued"}}
    """
    data = request.get_json(silent=True)
    if not data:
        return _error('请求参数不能为空')

    plan = data.get('plan')
    validation = validate_agent_plan(plan)
    if not validation['valid']:
        return _error('计划校验失败: ' + '；'.join(validation['errors'][:5]))

    image_url = data.get('image_url')
    document_id = data.get('document_id')
    if document_id is not None and not isinstance(document_id, int):
        return _error('document_id 必须为整数')

    if not image_url and document_id is not None:
        doc = document_model.find_by_id(document_id, g.current_user['user_id'])
        if doc is None:
            return _error('文档不存在', code=4004, http_status=404)
        for layer in (doc.get('layers') or []):
            if layer.get('type') == 'image' and layer.get('url'):
                image_url = layer['url']
                break

    if not image_url:
        return _error('image_url 不能为空（或提供包含图片图层的 document_id）')
    error = _check_source_image(image_url)
    if error:
        return _error(error)

    user_id = g.current_user['user_id']
    task_id = task_queue.submit_task('editor_agent_execute', {
        'plan': plan,
        'document_id': document_id,
        'user_id': user_id,
        'layer_image_url': image_url,
    }, module='editor')

    # 落库记录（params 存计划与来源信息，供单步重试重建任务）
    task_model.create(task_id=task_id, user_id=user_id, tool=AGENT_TASK_NAME, params={
        'plan': plan,
        'layer_image_url': image_url,
        'document_id': document_id,
    }, status='queued')

    return _success({'task_id': task_id, 'status': 'queued'})


def _get_owned_agent_task(task_id):
    """按 task_id 取当前用户的 Agent 任务记录；不满足返回 (None, 错误响应)"""
    row = task_model.find_by_task_id(task_id)
    if row is None:
        return None, _error('任务不存在', code=4004, http_status=404)
    if row['user_id'] != g.current_user['user_id']:
        return None, _error('无权操作该任务', code=1003, http_status=403)
    if row.get('tool') != AGENT_TASK_NAME:
        return None, _error('仅支持 Agent 修图任务', code=4001, http_status=400)
    return row, None


@editor_bp.route('/agent/tasks/<task_id>/cancel', methods=['POST'])
@token_required
def agent_cancel_task(task_id):
    """
    POST /api/v1/editor/agent/tasks/<task_id>/cancel — 取消后续步骤

    写入 Redis 取消标记（agent-plan:<task_id>:cancel），执行器在每步开始前检查。
    Response:
    {"code": 0, "message": "success", "data": {"ok": true}}
    """
    row, err = _get_owned_agent_task(task_id)
    if err:
        return err
    task_queue.get_sync_redis().setex(
        cancel_key(task_id), task_queue.TASK_RESULT_TTL, '1',
    )
    return _success({'ok': True})


@editor_bp.route('/agent/tasks/<task_id>/retry', methods=['POST'])
@token_required
def agent_retry_task(task_id):
    """
    POST /api/v1/editor/agent/tasks/<task_id>/retry — 从指定步骤重试（单步重试）

    Request Body:
    {"step_id": "step-2"}   // 必填，从该步开始重跑（复用原任务已完成步的中间产物）

    Response:
    {"code": 0, "message": "success", "data": {"task_id": "<新task_id>", "status": "queued"}}
    """
    row, err = _get_owned_agent_task(task_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    step_id = data.get('step_id')
    if not isinstance(step_id, str) or not step_id.strip():
        return _error('step_id 不能为空')

    params = row.get('params') or {}
    plan = params.get('plan')
    layer_image_url = params.get('layer_image_url')
    if not plan or not layer_image_url:
        return _error('原任务缺少计划信息，无法重试')

    validation = validate_agent_plan(plan)
    if not validation['valid']:
        return _error('原计划校验失败: ' + '；'.join(validation['errors'][:5]))
    if step_id.strip() not in validation['order']:
        return _error(f'重试步骤不存在: {step_id}')

    user_id = g.current_user['user_id']
    new_task_id = task_queue.submit_task('editor_agent_execute', {
        'plan': plan,
        'document_id': params.get('document_id'),
        'user_id': user_id,
        'layer_image_url': layer_image_url,
        'retry_from_step': step_id.strip(),
        'source_task_id': task_id,
    }, module='editor')

    task_model.create(task_id=new_task_id, user_id=user_id, tool=AGENT_TASK_NAME, params={
        'plan': plan,
        'layer_image_url': layer_image_url,
        'document_id': params.get('document_id'),
        'retry_from_step': step_id.strip(),
        'source_task_id': task_id,
    }, status='queued')

    return _success({'task_id': new_task_id, 'status': 'queued'})
