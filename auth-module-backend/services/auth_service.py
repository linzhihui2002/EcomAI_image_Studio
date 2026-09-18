"""
认证业务服务模块
注册 / 登录 / 用户信息查询
"""
import re
from models.user import UserModel
from utils.security import hash_password, verify_password, generate_token
from services.email_service import send_welcome_email
from services.verification_service import verify_code
from config import get_config

config = get_config()
user_model = UserModel()


class AuthError(Exception):
    """认证业务异常"""
    def __init__(self, message: str, code: int, http_status: int = 400):
        self.message = message
        self.code = code
        self.http_status = http_status
        super().__init__(self.message)


def _validate_email(email: str) -> bool:
    """验证邮箱格式"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def _validate_password_strength(password: str) -> list:
    """
    验证密码强度
    返回不满足的规则列表，空列表表示通过
    """
    errors = []
    if len(password) < config.PASSWORD_MIN_LENGTH:
        errors.append(f'密码长度至少{config.PASSWORD_MIN_LENGTH}位')
    if config.PASSWORD_REQUIRE_UPPER and not re.search(r'[A-Z]', password):
        errors.append('密码必须包含大写字母')
    if config.PASSWORD_REQUIRE_DIGIT and not re.search(r'\d', password):
        errors.append('密码必须包含数字')
    if config.PASSWORD_REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append('密码必须包含特殊字符')
    return errors


def register_user(email: str, password: str, code: str = None) -> dict:
    """
    用户注册
    参数:
        email: 邮箱
        password: 明文密码
        code: 验证码（可选，但建议强制）
    返回:
        dict: 包含 token 和 user 信息
    异常:
        AuthError: 邮箱格式无效 / 邮箱已存在 / 密码强度不足 / 验证码无效
    """
    # 1. 校验邮箱格式
    if not _validate_email(email):
        raise AuthError('邮箱格式无效', 3002, 400)
    
    # 2. 校验密码强度
    pwd_errors = _validate_password_strength(password)
    if pwd_errors:
        raise AuthError('; '.join(pwd_errors), 3002, 400)
    
    # 3. 校验验证码（如果提供）
    if code is not None:
        if not verify_code(email, code, 'register'):
            raise AuthError('验证码无效或已过期', 3009, 400)
    
    # 4. 检查邮箱唯一性（包裹数据库异常）
    try:
        existing = user_model.find_by_email(email)
    except Exception:
        raise AuthError('服务暂时不可用，请稍后重试', 5001, 500)
    
    if existing:
        raise AuthError('该邮箱已被注册', 2006, 409)
    
    # 5. 创建用户（密码加密，默认 role='user'）
    password_hash = hash_password(password)
    try:
        user_id = user_model.create(email, password_hash)
    except Exception:
        raise AuthError('服务暂时不可用，请稍后重试', 5001, 500)
    
    # 6. 生成 JWT Token
    token = generate_token(user_id, email, 'user')
    
    # 7. 发送欢迎邮件（异步，失败不影响注册）
    try:
        send_welcome_email(email)
    except Exception:
        pass  # 邮件发送失败不影响注册流程
    
    return {
        'token': token,
        'user': {
            'id': user_id,
            'email': email,
            'role': 'user',
        }
    }


def login_user(email: str, password: str) -> dict:
    """
    用户登录
    参数:
        email: 邮箱
        password: 明文密码
    返回:
        dict: 包含 token 和 user 信息
    异常:
        AuthError: 邮箱或密码错误 / 服务不可用
    """
    # 1. 查找用户（包裹数据库异常，转换为业务异常）
    try:
        user = user_model.find_by_email(email)
    except Exception as db_err:
        raise AuthError('服务暂时不可用，请稍后重试', 5001, 500)
    
    if not user:
        raise AuthError('邮箱或密码错误', 1001, 401)
    
    # 2. 验证密码
    if not verify_password(password, user['password_hash']):
        raise AuthError('邮箱或密码错误', 1001, 401)
    
    # 3. 生成 JWT Token
    token = generate_token(user['id'], user['email'], user['role'])
    
    return {
        'token': token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'role': user['role'],
        }
    }


def login_with_code(email: str, code: str) -> dict:
    """
    验证码登录
    参数:
        email: 邮箱
        code: 验证码
    返回:
        dict: 包含 token 和 user 信息
    异常:
        AuthError: 验证码无效 / 用户不存在 / 服务不可用
    """
    # 1. 校验验证码
    if not verify_code(email, code, 'login'):
        raise AuthError('验证码无效或已过期', 1001, 401)
    
    # 2. 查找用户（包裹数据库异常）
    try:
        user = user_model.find_by_email(email)
    except Exception:
        raise AuthError('服务暂时不可用，请稍后重试', 5001, 500)
    
    if not user:
        # 用户不存在，但验证码已验证通过，返回统一错误
        raise AuthError('验证码无效或已过期', 1001, 401)
    
    # 3. 生成 JWT Token
    token = generate_token(user['id'], user['email'], user['role'])
    
    return {
        'token': token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'role': user['role'],
        }
    }


def get_current_user(user_id: int) -> dict:
    """
    获取当前用户信息
    参数:
        user_id: 用户ID
    返回:
        dict: 用户信息（不含密码），不存在返回 None
    """
    return user_model.find_by_id(user_id)


def reset_user_password(email: str, code: str, new_password: str) -> dict:
    """
    重置密码
    参数:
        email: 邮箱
        code: 验证码
        new_password: 新密码
    返回:
        dict: 成功信息
    异常:
        AuthError: 邮箱格式无效 / 密码强度不足 / 验证码无效 / 用户不存在
    """
    # 1. 校验邮箱格式
    if not _validate_email(email):
        raise AuthError('邮箱格式无效', 3002, 400)

    # 2. 校验密码强度
    pwd_errors = _validate_password_strength(new_password)
    if pwd_errors:
        raise AuthError('; '.join(pwd_errors), 3002, 400)

    # 3. 校验验证码
    if not verify_code(email, code, 'reset_password'):
        raise AuthError('验证码无效或已过期', 3009, 400)

    # 4. 查找用户（必须存在）
    user = user_model.find_by_email(email)
    if not user:
        raise AuthError('该邮箱未注册', 1001, 404)

    # 5. 更新密码
    password_hash = hash_password(new_password)
    user_model.update_password(email, password_hash)

    return {'message': '密码重置成功'}