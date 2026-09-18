"""
公开公告路由模块
无需认证，供前端公告栏展示
"""
from flask import Blueprint
from controllers.admin_controller import get_public_announcements

announcement_bp = Blueprint('announcement', __name__, url_prefix='/api/v1')

announcement_bp.route('/announcements', methods=['GET'])(get_public_announcements)