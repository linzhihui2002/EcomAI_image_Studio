"""
功能定价公开查询路由模块
仅登录用户可查询启用的功能定价（不需要管理员权限）
GET /api/v1/feature-pricing?category=
"""
import traceback
from flask import Blueprint, request
from controllers.admin_controller import success_response, error_response
from services.feature_pricing_service import list_active_pricings
from middleware.auth_middleware import token_required

feature_pricing_bp = Blueprint('feature_pricing', __name__, url_prefix='/api/v1/feature-pricing')

# 仅返回给前端的公开字段（隐藏 id/is_active/created_at/updated_at/description 等）
_PUBLIC_FIELDS = (
    'feature_key',
    'display_name',
    'category',
    'pricing_type',
    'config',
    'sort_order',
)


def _list_feature_pricings():
    """GET /api/v1/feature-pricing?category="""
    category = (request.args.get('category') or '').strip() or None
    try:
        pricings = list_active_pricings(category)
        # 仅保留公开字段
        result = [{k: p.get(k) for k in _PUBLIC_FIELDS} for p in pricings]
        return success_response({'pricings': result}, 'ok')
    except Exception as e:
        print(f'[FeaturePricingRoute] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# 仅需登录（token_required），不需要管理员角色
feature_pricing_bp.route('', methods=['GET'])(
    token_required(_list_feature_pricings)
)
