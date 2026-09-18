"""用户自备模型服务商（BYOK）路由模块

端点一览（全部需要登录，用户 ID 取自 g.current_user）：
    GET    /api/v1/user/ai-providers                        配置列表 + 总开关
    POST   /api/v1/user/ai-providers                        新增配置
    PUT    /api/v1/user/ai-providers/<provider_id>          更新配置
    DELETE /api/v1/user/ai-providers/<provider_id>          删除配置
    PUT    /api/v1/user/ai-providers/<provider_id>/move     分类内上移/下移
    POST   /api/v1/user/ai-providers/<provider_id>/test     连通性测试
    GET    /api/v1/user/ai-provider-settings                读取自备通道总开关
    PUT    /api/v1/user/ai-provider-settings                设置自备通道总开关

响应统一信封：成功 {"code": 0, "message": "success", "data": ...}；
失败 {"code": <业务码>, "message": <中文提示>, "data": None} + HTTP 状态码。
入参字段一律 snake_case（api_base / api_key / model_name / is_enabled /
use_own_provider / direction）。
"""
import traceback

from flask import Blueprint, request, jsonify, g

from middleware.auth_middleware import token_required
from services.user_ai_provider_service import (
    UserAiProviderError,
    create_provider,
    delete_provider,
    get_settings,
    list_providers,
    move_provider,
    set_use_own_provider,
    test_provider,
    update_provider,
)

user_ai_provider_bp = Blueprint('user_ai_provider', __name__, url_prefix='/api/v1')


def _success(data=None, message='success'):
    """统一成功响应"""
    return jsonify({'code': 0, 'message': message, 'data': data})


def _error(code, message, http_status=400):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': None}), http_status


def _user_id():
    """当前登录用户 ID（由 token_required 注入）"""
    return g.current_user['user_id']


def _to_bool(value):
    """把前端可能传来的字符串/数字开关统一成 bool"""
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes', 'on')
    return bool(value)


def _fail(e, action):
    """把未预期异常转为 5001 响应，并打印中文日志 + 堆栈"""
    print(f'[user_ai_provider] {action}失败: error={e}', flush=True)
    print(traceback.format_exc(), flush=True)
    return _error(5001, f'操作失败: {e}', 500)


@user_ai_provider_bp.route('/user/ai-providers', methods=['GET'])
@token_required
def list_ai_providers():
    """获取当前用户全部自备通道与总开关

    Response data: {use_own_provider: bool, items: [provider_dict, ...]}
    """
    try:
        return _success(list_providers(_user_id()))
    except UserAiProviderError as e:
        return _error(e.code, e.message, e.http_status)
    except Exception as e:
        return _fail(e, '查询自备通道列表')


@user_ai_provider_bp.route('/user/ai-providers', methods=['POST'])
@token_required
def create_ai_provider():
    """新增一条自备通道

    Request Body: {category, name, api_base, api_key, model_name}
    Response data: provider_dict（api_key 只回掩码，不含明文/密文）
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            raise UserAiProviderError('请求参数不能为空')

        provider = create_provider(
            _user_id(),
            data.get('category'),
            data.get('name'),
            data.get('api_base'),
            data.get('api_key'),
            data.get('model_name'),
        )
        return _success(provider)
    except UserAiProviderError as e:
        return _error(e.code, e.message, e.http_status)
    except Exception as e:
        return _fail(e, '新增自备通道')


@user_ai_provider_bp.route('/user/ai-providers/<int:provider_id>', methods=['PUT'])
@token_required
def update_ai_provider(provider_id):
    """更新一条自备通道（只传实际出现的字段；api_key 传空串表示不修改）

    Request Body: {name?, api_base?, api_key?, model_name?, is_enabled?}
    Response data: provider_dict
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            raise UserAiProviderError('请求参数不能为空')

        fields = {}
        if 'name' in data:
            fields['name'] = data['name']
        if 'api_base' in data:
            fields['api_base'] = data['api_base']
        if 'api_key' in data:
            fields['api_key'] = data['api_key']
        if 'model_name' in data:
            fields['model_name'] = data['model_name']
        if 'is_enabled' in data:
            fields['is_enabled'] = _to_bool(data['is_enabled'])

        return _success(update_provider(_user_id(), provider_id, **fields))
    except UserAiProviderError as e:
        return _error(e.code, e.message, e.http_status)
    except Exception as e:
        return _fail(e, '更新自备通道')


@user_ai_provider_bp.route('/user/ai-providers/<int:provider_id>', methods=['DELETE'])
@token_required
def delete_ai_provider(provider_id):
    """删除一条自备通道

    Response data: None，message 为「删除成功」
    """
    try:
        delete_provider(_user_id(), provider_id)
        return _success(message='删除成功')
    except UserAiProviderError as e:
        return _error(e.code, e.message, e.http_status)
    except Exception as e:
        return _fail(e, '删除自备通道')


@user_ai_provider_bp.route('/user/ai-providers/<int:provider_id>/move', methods=['PUT'])
@token_required
def move_ai_provider(provider_id):
    """在分类内上移/下移一条自备通道

    Request Body: {direction: 'up'|'down'}
    Response data: provider_dict
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            raise UserAiProviderError('请求参数不能为空')

        return _success(move_provider(_user_id(), provider_id, data.get('direction')))
    except UserAiProviderError as e:
        return _error(e.code, e.message, e.http_status)
    except Exception as e:
        return _fail(e, '移动自备通道')


@user_ai_provider_bp.route('/user/ai-providers/<int:provider_id>/test', methods=['POST'])
@token_required
def test_ai_provider(provider_id):
    """连通性测试（请求 {api_base}/models）

    Response data: {ok: bool, error: str|None, tested_at: str|None}
    """
    try:
        return _success(test_provider(_user_id(), provider_id))
    except UserAiProviderError as e:
        return _error(e.code, e.message, e.http_status)
    except Exception as e:
        return _fail(e, '测试自备通道')


@user_ai_provider_bp.route('/user/ai-provider-settings', methods=['GET'])
@token_required
def get_ai_provider_settings():
    """读取自备通道总开关

    Response data: {use_own_provider: bool}
    """
    try:
        return _success(get_settings(_user_id()))
    except UserAiProviderError as e:
        return _error(e.code, e.message, e.http_status)
    except Exception as e:
        return _fail(e, '查询自备通道设置')


@user_ai_provider_bp.route('/user/ai-provider-settings', methods=['PUT'])
@token_required
def update_ai_provider_settings():
    """设置自备通道总开关

    Request Body: {use_own_provider: bool}
    Response data: {use_own_provider: bool}
    """
    try:
        data = request.get_json(silent=True)
        if not data or 'use_own_provider' not in data:
            raise UserAiProviderError('use_own_provider 不能为空')

        set_use_own_provider(_user_id(), _to_bool(data['use_own_provider']))
        return _success(get_settings(_user_id()))
    except UserAiProviderError as e:
        return _error(e.code, e.message, e.http_status)
    except Exception as e:
        return _fail(e, '更新自备通道设置')
