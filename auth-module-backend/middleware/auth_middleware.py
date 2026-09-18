"""
鉴权中间件模块
JWT 鉴权 + 基于角色的访问控制
"""
from functools import wraps
from flask import request, g, jsonify
from utils.security import verify_token


def token_required(f):
    """
    JWT Token 鉴权装饰器
    从 Authorization Header 解析 Token，验证后将用户信息注入 g.current_user
    验证失败返回相应的错误响应
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # 从 Authorization Header 获取 Token
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        
        # 无 Token
        if not token:
            return jsonify({
                'code': 1001,
                'message': '未登录，请先登录',
                'data': None
            }), 401
        
        # 验证 Token
        payload = verify_token(token)
        if payload is None:
            return jsonify({
                'code': 1002,
                'message': 'Token无效或已过期，请重新登录',
                'data': None
            }), 401
        
        # 注入当前用户信息
        g.current_user = {
            'user_id': int(payload['sub']),
            'email': payload['email'],
            'role': payload['role'],
        }
        
        return f(*args, **kwargs)
    
    return decorated


def require_role(role):
    """
    角色权限校验装饰器工厂
    role: 要求的角色（如 'admin'）
    必须在 token_required 之后使用
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # 确保 g.current_user 存在（由 token_required 注入）
            if not hasattr(g, 'current_user'):
                return jsonify({
                    'code': 1001,
                    'message': '未登录，请先登录',
                    'data': None
                }), 401
            
            # 校验角色
            if g.current_user.get('role') != role:
                return jsonify({
                    'code': 1003,
                    'message': '权限不足，需要管理员权限',
                    'data': None
                }), 403
            
            return f(*args, **kwargs)
        return decorated
    return decorator