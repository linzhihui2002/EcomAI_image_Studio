"""
认证路由模块
注册所有认证相关路由
"""
from flask import Blueprint
from controllers.auth_controller import (
    register, login, get_me, admin_profile, user_profile,
    send_code, login_with_code, reset_password,
    get_user_profile, get_balance, get_points_records
)
from middleware.auth_middleware import token_required, require_role

auth_bp = Blueprint('auth', __name__, url_prefix='/api/v1')

# 公开接口（无需认证）
auth_bp.route('/auth/register', methods=['POST'])(register)
auth_bp.route('/auth/login', methods=['POST'])(login)
auth_bp.route('/auth/send-code', methods=['POST'])(send_code)
auth_bp.route('/auth/login/code', methods=['POST'])(login_with_code)
auth_bp.route('/auth/reset-password', methods=['POST'])(reset_password)

# 需要登录的接口
auth_bp.route('/auth/me', methods=['GET'])(token_required(get_me))

# 需要管理员权限的接口
auth_bp.route('/admin/profile', methods=['GET'])(
    token_required(require_role('admin')(admin_profile))
)

# 用户资产查询接口
auth_bp.route('/user/profile', methods=['GET'])(token_required(get_user_profile))
auth_bp.route('/user/balance', methods=['GET'])(token_required(get_balance))
auth_bp.route('/user/points-records', methods=['GET'])(token_required(get_points_records))