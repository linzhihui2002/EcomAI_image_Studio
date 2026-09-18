"""
管理后台控制器
处理 HTTP 请求参数校验、调用业务服务、格式化响应
所有接口均需管理员权限（由路由层 require_role('admin') 保证）
"""
import traceback
from flask import request, jsonify, g
from services.admin_service import (
    get_dashboard_stats as fetch_dashboard_stats,
    get_all_pricing_plans as fetch_all_plans,
    create_plan as do_create_plan,
    update_plan as do_update_plan,
    delete_plan as do_delete_plan,
    toggle_plan_active as do_toggle_plan,
    get_all_feature_pricings as fetch_all_feature_pricings,
    create_feature_pricing as do_create_feature_pricing,
    update_feature_pricing as do_update_feature_pricing,
    toggle_feature_pricing_active as do_toggle_feature_pricing,
    delete_feature_pricing as do_delete_feature_pricing,
    get_feature_key_options as do_get_feature_key_options,
    get_team_consumptions as fetch_team_consumptions,
    get_all_redemption_codes as fetch_all_codes,
    generate_code as do_generate_code,
    delete_code as do_delete_code,
    get_all_announcements as fetch_all_announcements,
    create_announcement as do_create_announcement,
    update_announcement as do_update_announcement,
    delete_announcement as do_delete_announcement,
    toggle_announcement_active as do_toggle_announcement,
    get_public_announcements as fetch_public_announcements,
)
from services.auth_service import AuthError


def success_response(data=None, message='success', code=0):
    """统一成功响应"""
    return jsonify({'code': code, 'message': message, 'data': data})


def error_response(code, message, http_status=400, data=None):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': data}), http_status


# ==================== 仪表盘统计 ====================

def get_dashboard_stats():
    """GET /api/v1/admin/stats"""
    try:
        stats = fetch_dashboard_stats()
        return success_response(stats, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] get_dashboard_stats error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)

def get_pricing_plans():
    """GET /api/v1/admin/pricing-plans"""
    try:
        plans = fetch_all_plans()
        return success_response({'plans': plans}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def create_pricing_plan():
    """POST /api/v1/admin/pricing-plans"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    name = (data.get('name') or '').strip()
    price = data.get('price')
    coins = data.get('coins')
    bonus_coins = data.get('bonusCoins', 0)

    if not name:
        return error_response(3002, '方案名称不能为空', 400)
    if price is None or price <= 0:
        return error_response(3002, '价格必须大于0', 400)
    if coins is None or coins <= 0:
        return error_response(3002, '灵感币数量必须大于0', 400)
    if bonus_coins < 0:
        return error_response(3002, '赠送灵感币不能为负数', 400)

    try:
        plan = do_create_plan(name, float(price), int(coins), int(bonus_coins))
        return success_response({'plan': plan}, '创建成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def update_pricing_plan(plan_id):
    """PUT /api/v1/admin/pricing-plans/:planId"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    name = (data.get('name') or '').strip()
    price = data.get('price')
    coins = data.get('coins')
    bonus_coins = data.get('bonusCoins', 0)

    if not name:
        return error_response(3002, '方案名称不能为空', 400)
    if price is None or price <= 0:
        return error_response(3002, '价格必须大于0', 400)
    if coins is None or coins <= 0:
        return error_response(3002, '灵感币数量必须大于0', 400)
    if bonus_coins < 0:
        return error_response(3002, '赠送灵感币不能为负数', 400)

    try:
        plan = do_update_plan(int(plan_id), name, float(price), int(coins), int(bonus_coins))
        return success_response({'plan': plan}, '更新成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def toggle_pricing_plan(plan_id):
    """PUT /api/v1/admin/pricing-plans/:planId/toggle"""
    try:
        result = do_toggle_plan(int(plan_id))
        return success_response(result, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def delete_pricing_plan(plan_id):
    """DELETE /api/v1/admin/pricing-plans/:planId"""
    try:
        do_delete_plan(int(plan_id))
        return success_response(None, '删除成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 功能定价管理 ====================

def get_feature_pricings():
    """GET /api/v1/admin/feature-pricing"""
    try:
        pricings = fetch_all_feature_pricings()
        return success_response({'pricings': pricings}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def create_feature_pricing():
    """POST /api/v1/admin/feature-pricing"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    feature_key = (data.get('featureKey') or '').strip()
    display_name = (data.get('displayName') or '').strip()
    category = (data.get('category') or '').strip()
    pricing_type = data.get('pricingType')
    config = data.get('config')
    description = data.get('description')

    if not feature_key:
        return error_response(3002, 'featureKey 不能为空', 400)
    if not display_name:
        return error_response(3002, 'displayName 不能为空', 400)
    if not category:
        return error_response(3002, 'category 不能为空', 400)
    if pricing_type not in ('per_image_resolution', 'per_use'):
        return error_response(3002, 'pricingType 无效', 400)
    if config is None:
        return error_response(3002, 'config 不能为空', 400)

    try:
        pricing = do_create_feature_pricing(
            feature_key, display_name, category, pricing_type, config, description
        )
        return success_response({'pricing': pricing}, '创建成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def update_feature_pricing(pricing_id):
    """PUT /api/v1/admin/feature-pricing/:pricingId"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    display_name = (data.get('displayName') or '').strip()
    category = (data.get('category') or '').strip()
    pricing_type = data.get('pricingType')
    config = data.get('config')
    description = data.get('description')

    if not display_name:
        return error_response(3002, 'displayName 不能为空', 400)
    if not category:
        return error_response(3002, 'category 不能为空', 400)
    if pricing_type not in ('per_image_resolution', 'per_use'):
        return error_response(3002, 'pricingType 无效', 400)
    if config is None:
        return error_response(3002, 'config 不能为空', 400)

    try:
        pricing = do_update_feature_pricing(
            int(pricing_id), display_name, category, pricing_type, config, description
        )
        return success_response({'pricing': pricing}, '更新成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def toggle_feature_pricing(pricing_id):
    """PUT /api/v1/admin/feature-pricing/:pricingId/toggle"""
    try:
        result = do_toggle_feature_pricing(int(pricing_id))
        return success_response(result, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def delete_feature_pricing(pricing_id):
    """DELETE /api/v1/admin/feature-pricing/:pricingId"""
    try:
        do_delete_feature_pricing(int(pricing_id))
        return success_response(None, '删除成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def get_feature_key_options():
    """GET /api/v1/admin/feature-pricing/keys —— 返回所有可用的功能标识选项"""
    try:
        options = do_get_feature_key_options()
        return success_response({'options': options}, 'ok')
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 团队消耗 ====================

def get_team_consumptions():
    """GET /api/v1/admin/team-consumptions"""
    sort_by = request.args.get('sortBy', 'totalCoinsConsumed')
    order = request.args.get('order', 'desc')

    if order not in ('asc', 'desc'):
        order = 'desc'

    try:
        consumptions = fetch_team_consumptions(sort_by, order)
        return success_response({'consumptions': consumptions}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 兑换码管理 ====================

def get_redemption_codes():
    """GET /api/v1/admin/redemption-codes"""
    status = request.args.get('status', 'all')
    if status not in ('all', 'unused', 'used'):
        status = 'all'

    try:
        codes = fetch_all_codes(status)
        return success_response({'codes': codes}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def generate_redemption_code():
    """POST /api/v1/admin/redemption-codes"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    coins = data.get('coins')
    expires_days = data.get('expiresDays')
    remark = (data.get('remark') or '').strip()
    max_uses = data.get('maxUses', 1)
    max_uses_per_user = data.get('maxUsesPerUser', 1)

    if not coins or coins <= 0:
        return error_response(3002, '灵感币额度必须大于0', 400)
    if not expires_days or expires_days <= 0:
        return error_response(3002, '有效期天数必须大于0', 400)
    if not isinstance(max_uses, int) or max_uses < 1:
        return error_response(3002, '总使用次数必须为正整数', 400)
    if not isinstance(max_uses_per_user, int) or max_uses_per_user < 1:
        return error_response(3002, '单账号使用次数必须为正整数', 400)
    if max_uses_per_user > max_uses:
        return error_response(3002, '单账号使用次数不能大于总使用次数', 400)

    try:
        code = do_generate_code(int(coins), int(expires_days), remark, int(max_uses), int(max_uses_per_user))
        return success_response({'code': code}, '生成成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def delete_redemption_code(code_id):
    """DELETE /api/v1/admin/redemption-codes/:codeId"""
    try:
        do_delete_code(int(code_id))
        return success_response(None, '删除成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 公告管理 ====================

def get_announcements():
    """GET /api/v1/admin/announcements"""
    try:
        announcements = fetch_all_announcements()
        return success_response({'announcements': announcements}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def create_announcement():
    """POST /api/v1/admin/announcements"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    ann_type = data.get('type', 'info')
    is_pinned = data.get('isPinned', False)
    expires_at = data.get('expiresAt') or None

    if not title:
        return error_response(3002, '公告标题不能为空', 400)
    if not content:
        return error_response(3002, '公告内容不能为空', 400)
    if ann_type not in ('info', 'warning', 'success', 'important'):
        return error_response(3002, '公告类型无效', 400)

    created_by = g.current_user.get('email', '')

    try:
        announcement = do_create_announcement(title, content, ann_type, bool(is_pinned), created_by, expires_at)
        return success_response({'announcement': announcement}, '发布成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def update_announcement(ann_id):
    """PUT /api/v1/admin/announcements/:annId"""
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    ann_type = data.get('type', 'info')
    is_pinned = data.get('isPinned', False)
    expires_at = data.get('expiresAt') or None

    if not title:
        return error_response(3002, '公告标题不能为空', 400)
    if not content:
        return error_response(3002, '公告内容不能为空', 400)
    if ann_type not in ('info', 'warning', 'success', 'important'):
        return error_response(3002, '公告类型无效', 400)

    try:
        announcement = do_update_announcement(int(ann_id), title, content, ann_type, bool(is_pinned), expires_at)
        return success_response({'announcement': announcement}, '更新成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def toggle_announcement(ann_id):
    """PUT /api/v1/admin/announcements/:annId/toggle"""
    try:
        result = do_toggle_announcement(int(ann_id))
        return success_response(result, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


def delete_announcement(ann_id):
    """DELETE /api/v1/admin/announcements/:annId"""
    try:
        do_delete_announcement(int(ann_id))
        return success_response(None, '删除成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)


# ==================== 公开公告 ====================

def get_public_announcements():
    """GET /api/v1/announcements（无需认证）"""
    try:
        announcements = fetch_public_announcements()
        return success_response({'announcements': announcements}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        print(f'[AdminController] error: {e}')
        traceback.print_exc()
        return error_response(5001, '服务器内部错误', 500)