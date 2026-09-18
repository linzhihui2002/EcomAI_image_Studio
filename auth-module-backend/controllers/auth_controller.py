"""
认证控制器
处理 HTTP 请求参数校验、调用业务服务、格式化响应
"""
import traceback
from flask import request, jsonify, g
from services.auth_service import register_user, login_user, login_with_code as auth_login_with_code, get_current_user, reset_user_password, AuthError
from services.verification_service import send_code as send_verification_code, VerificationError
from utils.security import rate_limiter
from config import get_config

config = get_config()


def success_response(data=None, message='success', code=0):
    """统一成功响应"""
    return jsonify({'code': code, 'message': message, 'data': data})


def error_response(code, message, http_status=400, data=None):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': data}), http_status


def send_code():
    """
    发送验证码
    POST /api/v1/auth/send-code
    请求体: { "email": "...", "purpose": "login" | "register" }
    """
    # 频率限制（按 IP）
    client_ip = request.remote_addr
    if not rate_limiter.is_allowed(f'send_code:{client_ip}', 5, config.RATE_LIMIT_WINDOW):
        return error_response(3008, '操作过于频繁，请稍后再试', 429)

    # 获取请求参数
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    email = data.get('email', '').strip()
    purpose = data.get('purpose', 'register')

    if not email:
        return error_response(3002, '邮箱不能为空', 400)

    if purpose not in ('login', 'register', 'reset_password'):
        return error_response(3002, 'purpose 参数无效，必须为 login、register 或 reset_password', 400)

    try:
        result = send_verification_code(email, purpose)
        return success_response(result, '验证码已发送')
    except VerificationError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception:
        print(f'[ERROR] Send code failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)


def register():
    """
    用户注册
    POST /api/v1/auth/register
    请求体: { "email": "...", "password": "...", "code": "..." }
    """
    # 频率限制
    client_ip = request.remote_addr
    if not rate_limiter.is_allowed(f'register:{client_ip}', config.REGISTER_RATE_LIMIT, config.RATE_LIMIT_WINDOW):
        return error_response(3008, '注册请求过于频繁，请稍后再试', 429)

    # 获取请求参数
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    email = data.get('email', '').strip()
    password = data.get('password', '')
    code = data.get('code', '')

    if not email or not password:
        return error_response(3002, '邮箱和密码不能为空', 400)

    if not code:
        return error_response(3002, '验证码不能为空', 400)

    try:
        result = register_user(email, password, code)
        return success_response(result, '注册成功'), 201
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception:
        print(f'[ERROR] Register failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)


def login():
    """
    用户登录
    POST /api/v1/auth/login
    请求体: { "email": "...", "password": "..." }
    """
    # 频率限制
    client_ip = request.remote_addr
    if not rate_limiter.is_allowed(f'login:{client_ip}', config.LOGIN_RATE_LIMIT, config.RATE_LIMIT_WINDOW):
        return error_response(3008, '登录请求过于频繁，请稍后再试', 429)

    # 获取请求参数
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not email or not password:
        return error_response(3002, '邮箱和密码不能为空', 400)

    try:
        result = login_user(email, password)
        return success_response(result, '登录成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception:
        print(f'[ERROR] Login failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)


def login_with_code():
    """
    验证码登录
    POST /api/v1/auth/login/code
    请求体: { "email": "...", "code": "..." }
    """
    # 频率限制
    client_ip = request.remote_addr
    if not rate_limiter.is_allowed(f'login:{client_ip}', config.LOGIN_RATE_LIMIT, config.RATE_LIMIT_WINDOW):
        return error_response(3008, '登录请求过于频繁，请稍后再试', 429)

    # 获取请求参数
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    email = data.get('email', '').strip()
    code = data.get('code', '')

    if not email or not code:
        return error_response(3002, '邮箱和验证码不能为空', 400)

    try:
        result = auth_login_with_code(email, code)
        return success_response(result, '登录成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception:
        print(f'[ERROR] Login with code failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)


def reset_password():
    """
    重置密码
    POST /api/v1/auth/reset-password
    请求体: { "email": "...", "code": "...", "password": "..." }
    """
    # 频率限制
    client_ip = request.remote_addr
    if not rate_limiter.is_allowed(f'reset_password:{client_ip}', 3, config.RATE_LIMIT_WINDOW):
        return error_response(3008, '操作过于频繁，请稍后再试', 429)

    # 获取请求参数
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    email = data.get('email', '').strip()
    code = data.get('code', '')
    password = data.get('password', '')

    if not email or not code or not password:
        return error_response(3002, '邮箱、验证码和新密码不能为空', 400)

    try:
        result = reset_user_password(email, code, password)
        return success_response(result, '密码重置成功')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)
    except Exception:
        print(f'[ERROR] Reset password failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)


def get_me():
    """
    获取当前用户信息
    GET /api/v1/auth/me
    需要 Token 鉴权
    """
    try:
        user = get_current_user(g.current_user['user_id'])
    except Exception:
        print(f'[ERROR] Get me failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)
    
    if not user:
        return error_response(1001, '用户不存在', 401)
    return success_response({'user': user})


def admin_profile():
    """
    管理员信息接口（示例）
    GET /api/v1/admin/profile
    需要 admin 角色
    """
    return success_response({
        'message': '欢迎，管理员',
        'user': {
            'id': g.current_user['user_id'],
            'email': g.current_user['email'],
            'role': g.current_user['role'],
        }
    })


def user_profile():
    """
    普通用户信息接口（示例）
    GET /api/v1/user/profile
    需要登录
    """
    return success_response({
        'message': '欢迎',
        'user': {
            'id': g.current_user['user_id'],
            'email': g.current_user['email'],
            'role': g.current_user['role'],
        }
    })


def get_user_profile():
    """GET /api/v1/user/profile - 获取用户资料（含余额和团队）"""
    from models.user import UserModel
    from models.team import TeamModel
    try:
        user = UserModel().find_by_id(g.current_user['user_id'])
    except Exception:
        print(f'[ERROR] Get user profile failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)
    
    if not user:
        return error_response(1001, '用户不存在', 401)

    # 查询用户参与的团队列表（含 owner 和 member 身份）
    teams = []
    try:
        from models.team import TeamModel
        all_teams = TeamModel().find_by_user(user['id'])
        teams = [
            {
                'id': t['id'],
                'name': t['name'],
                'category': t['category'],
                'inviteCode': t['invite_code'],
                'ownerId': t['owner_id'],
                'memberCount': t['member_count'],
                'poolBalance': t['pool_balance'],
            }
            for t in all_teams
        ]
    except Exception:
        teams = []

    return success_response({
        'id': user['id'],
        'email': user['email'],
        'avatar': user.get('avatar'),
        'personalPoints': user.get('personal_points', 0),
        'role': user['role'],
        'teams': teams,
        'createdAt': user['created_at'].isoformat() if user.get('created_at') else None
    })


def get_balance():
    """GET /api/v1/user/balance - 获取余额"""
    wallet_type = request.args.get('wallet', 'personal')
    team_id = request.args.get('teamId')
    try:
        from services.points_record_service import get_balance as svc_get_balance
        result = svc_get_balance(g.current_user['user_id'], wallet_type, team_id)
    except Exception:
        print(f'[ERROR] Get balance failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)
    return success_response(result)


def get_points_records():
    """GET /api/v1/user/points-records - 获取灵感币流水"""
    wallet = request.args.get('wallet', 'personal')
    record_type = request.args.get('type')
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('pageSize', 20))
    try:
        from services.points_record_service import get_points_records as svc_get_records
        result = svc_get_records(g.current_user['user_id'], record_type, wallet, page, page_size)
    except Exception:
        print(f'[ERROR] Get points records failed: {traceback.format_exc()}', flush=True)
        return error_response(5001, '服务器内部错误，请稍后重试', 500)
    return success_response({
        'list': result['data'],
        'pagination': result['pagination']
    })