"""
收藏夹路由模块
注册所有收藏相关路由
"""
from flask import Blueprint
from controllers.favorite_controller import (
    list_favorites, create_favorite, delete_favorite, create_history_favorite
)
from middleware.auth_middleware import token_required

favorite_bp = Blueprint('favorite', __name__, url_prefix='/api/v1')

# 所有收藏接口需要登录
favorite_bp.route('/favorites', methods=['GET'])(token_required(list_favorites))
favorite_bp.route('/favorites', methods=['POST'])(token_required(create_favorite))
favorite_bp.route('/favorites/history', methods=['POST'])(token_required(create_history_favorite))
favorite_bp.route('/favorites/<int:favorite_id>', methods=['DELETE'])(token_required(delete_favorite))
