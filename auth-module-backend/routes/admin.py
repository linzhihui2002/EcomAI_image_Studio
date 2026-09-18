"""
管理后台路由模块
注册仪表盘、定价方案、功能定价、团队消耗、兑换码、公告管理路由
所有路由均需管理员权限
"""
from flask import Blueprint
from controllers.admin_controller import (
    get_dashboard_stats,
    get_pricing_plans,
    create_pricing_plan,
    update_pricing_plan,
    toggle_pricing_plan,
    delete_pricing_plan,
    get_feature_pricings,
    create_feature_pricing,
    update_feature_pricing,
    toggle_feature_pricing,
    delete_feature_pricing,
    get_feature_key_options,
    get_team_consumptions,
    get_redemption_codes,
    generate_redemption_code,
    delete_redemption_code,
    get_announcements,
    create_announcement,
    update_announcement,
    toggle_announcement,
    delete_announcement,
)
from middleware.auth_middleware import token_required, require_role

admin_bp = Blueprint('admin', __name__, url_prefix='/api/v1/admin')

# ==================== 仪表盘 ====================
admin_bp.route('/stats', methods=['GET'])(
    token_required(require_role('admin')(get_dashboard_stats))
)

# ==================== 定价方案管理 ====================
admin_bp.route('/pricing-plans', methods=['GET'])(
    token_required(require_role('admin')(get_pricing_plans))
)
admin_bp.route('/pricing-plans', methods=['POST'])(
    token_required(require_role('admin')(create_pricing_plan))
)
admin_bp.route('/pricing-plans/<int:plan_id>', methods=['PUT'])(
    token_required(require_role('admin')(update_pricing_plan))
)
admin_bp.route('/pricing-plans/<int:plan_id>/toggle', methods=['PUT'])(
    token_required(require_role('admin')(toggle_pricing_plan))
)
admin_bp.route('/pricing-plans/<int:plan_id>', methods=['DELETE'])(
    token_required(require_role('admin')(delete_pricing_plan))
)

# ==================== 功能定价管理 ====================
admin_bp.route('/feature-pricing', methods=['GET'])(
    token_required(require_role('admin')(get_feature_pricings))
)
admin_bp.route('/feature-pricing', methods=['POST'])(
    token_required(require_role('admin')(create_feature_pricing))
)
admin_bp.route('/feature-pricing/keys', methods=['GET'])(
    token_required(require_role('admin')(get_feature_key_options))
)
admin_bp.route('/feature-pricing/<int:pricing_id>', methods=['PUT'])(
    token_required(require_role('admin')(update_feature_pricing))
)
admin_bp.route('/feature-pricing/<int:pricing_id>/toggle', methods=['PUT'])(
    token_required(require_role('admin')(toggle_feature_pricing))
)
admin_bp.route('/feature-pricing/<int:pricing_id>', methods=['DELETE'])(
    token_required(require_role('admin')(delete_feature_pricing))
)

# ==================== 团队消耗 ====================
admin_bp.route('/team-consumptions', methods=['GET'])(
    token_required(require_role('admin')(get_team_consumptions))
)

# ==================== 兑换码管理 ====================
admin_bp.route('/redemption-codes', methods=['GET'])(
    token_required(require_role('admin')(get_redemption_codes))
)
admin_bp.route('/redemption-codes', methods=['POST'])(
    token_required(require_role('admin')(generate_redemption_code))
)
admin_bp.route('/redemption-codes/<int:code_id>', methods=['DELETE'])(
    token_required(require_role('admin')(delete_redemption_code))
)

# ==================== 公告管理 ====================
admin_bp.route('/announcements', methods=['GET'])(
    token_required(require_role('admin')(get_announcements))
)
admin_bp.route('/announcements', methods=['POST'])(
    token_required(require_role('admin')(create_announcement))
)
admin_bp.route('/announcements/<int:ann_id>', methods=['PUT'])(
    token_required(require_role('admin')(update_announcement))
)
admin_bp.route('/announcements/<int:ann_id>/toggle', methods=['PUT'])(
    token_required(require_role('admin')(toggle_announcement))
)
admin_bp.route('/announcements/<int:ann_id>', methods=['DELETE'])(
    token_required(require_role('admin')(delete_announcement))
)