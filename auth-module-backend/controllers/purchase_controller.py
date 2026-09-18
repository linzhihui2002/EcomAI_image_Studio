"""
充值中心控制器
处理 HTTP 请求参数校验、调用业务服务、格式化响应
"""
from flask import request, jsonify, g
from services.purchase_service import get_pricing_plans as fetch_pricing_plans, redeem_code as do_redeem_code
from services.auth_service import AuthError


def success_response(data=None, message='success', code=0):
    """统一成功响应"""
    return jsonify({'code': code, 'message': message, 'data': data})


def error_response(code, message, http_status=400, data=None):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': data}), http_status


def get_pricing_plans():
    """
    获取定价方案列表
    GET /api/v1/pricing-plans
    """
    try:
        plans = fetch_pricing_plans(is_active_only=True)
        return success_response({'plans': plans}, 'ok')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def redeem_code():
    """
    兑换码兑换
    POST /api/v1/purchase/redeem
    请求体: { "code": "...", "walletType": "personal", "teamId": null }
    """
    # 获取请求参数
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    code = data.get('code', '').strip()
    wallet_type = data.get('walletType', 'personal')
    team_id = data.get('teamId')

    if not code:
        return error_response(3002, '兑换码不能为空', 400)

    if wallet_type not in ('personal', 'team'):
        return error_response(3002, 'walletType 参数无效，必须为 personal 或 team', 400)

    if wallet_type == 'team' and not team_id:
        return error_response(3002, 'team 类型钱包需要提供 teamId', 400)

    try:
        user_id = g.current_user['user_id']
        result = do_redeem_code(user_id, code, wallet_type, team_id)
        return success_response(result, '兑换成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception as e:
        # 兜底处理：数据库异常、系统错误等
        return error_response(5001, '服务器内部错误，请稍后重试', 500)