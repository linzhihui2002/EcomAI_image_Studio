"""
充值中心路由模块
注册定价方案和兑换码相关路由
"""
from flask import Blueprint
from controllers.purchase_controller import get_pricing_plans, redeem_code
from middleware.auth_middleware import token_required

purchase_bp = Blueprint('purchase', __name__, url_prefix='/api/v1')

# 公开接口（无需认证）
purchase_bp.route('/pricing-plans', methods=['GET'])(get_pricing_plans)

# 需要登录的接口
purchase_bp.route('/purchase/redeem', methods=['POST'])(token_required(redeem_code))