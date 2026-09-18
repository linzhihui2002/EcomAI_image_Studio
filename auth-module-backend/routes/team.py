"""
团队路由模块
注册团队创建、加入、查询、邀请码管理、成员管理路由
"""
from flask import Blueprint
from controllers.team_controller import (
    create_team,
    join_team,
    get_my_teams,
    get_invitation,
    refresh_invitation,
    verify_invitation,
    get_team_members,
    dissolve_team,
    transfer_to_team,
    get_team_transfer_logs,
)
from middleware.auth_middleware import token_required

team_bp = Blueprint('team', __name__, url_prefix='/api/v1')

# 团队创建
team_bp.route('/teams', methods=['POST'])(token_required(create_team))

# 通过邀请码加入团队
team_bp.route('/teams/join', methods=['POST'])(token_required(join_team))

# 获取当前用户的团队列表
team_bp.route('/teams/mine', methods=['GET'])(token_required(get_my_teams))

# ---- 邀请码管理（/teams/invitation/verify 必须在 /teams/<int:team_id> 之前注册） ----

# 验证邀请码
team_bp.route('/teams/invitation/verify', methods=['POST'])(token_required(verify_invitation))

# 查看团队邀请码（owner/admin）
team_bp.route('/teams/<int:team_id>/invitation', methods=['GET'])(token_required(get_invitation))

# 刷新邀请码（owner/admin）
team_bp.route('/teams/<int:team_id>/invitation/refresh', methods=['POST'])(token_required(refresh_invitation))

# ---- 团队成员管理 ----

# 获取团队成员列表
team_bp.route('/teams/<int:team_id>/members', methods=['GET'])(token_required(get_team_members))

# ---- 解散团队（owner only） ----

team_bp.route('/teams/<int:team_id>', methods=['DELETE'])(token_required(dissolve_team))

# ---- 转账功能 ----

# 个人向团队转账
team_bp.route('/teams/<int:team_id>/transfer', methods=['POST'])(token_required(transfer_to_team))

# 获取团队转账日志
team_bp.route('/teams/<int:team_id>/transfer-logs', methods=['GET'])(token_required(get_team_transfer_logs))