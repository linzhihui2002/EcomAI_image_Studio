"""
历史记录路由模块
注册所有历史记录相关路由
"""
from flask import Blueprint
from controllers.history_controller import (
    create_history, list_history, get_history_detail_ep, delete_history_ep,
    share_history, unshare_history_ep, list_team_history
)
from middleware.auth_middleware import token_required

history_bp = Blueprint('history', __name__, url_prefix='/api/v1')

# 所有历史记录接口需要登录
history_bp.route('/history', methods=['POST'])(token_required(create_history))
history_bp.route('/history', methods=['GET'])(token_required(list_history))
history_bp.route('/history/<int:record_id>', methods=['GET'])(token_required(get_history_detail_ep))
history_bp.route('/history/<int:record_id>', methods=['DELETE'])(token_required(delete_history_ep))
history_bp.route('/history/<int:record_id>/share', methods=['POST'])(token_required(share_history))
history_bp.route('/history/<int:record_id>/share', methods=['DELETE'])(token_required(unshare_history_ep))
history_bp.route('/history/team/<int:team_id>', methods=['GET'])(token_required(list_team_history))