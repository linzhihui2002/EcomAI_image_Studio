"""
安全工具模块
密码加密 / JWT 令牌 / 请求频率限制
"""
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from config import get_config

config = get_config()

# ========== 密码加密 ==========
def hash_password(password: str) -> str:
    """使用 bcrypt 加密密码"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

# ========== JWT 令牌 ==========
def generate_token(user_id: int, email: str, role: str) -> str:
    """生成 JWT 令牌，有效期24小时"""
    payload = {
        'sub': str(user_id),  # 转为字符串
        'email': email,
        'role': role,
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + config.JWT_EXPIRATION,
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)

def verify_token(token: str) -> dict:
    """验证并解析 JWT 令牌，返回 payload 字典；验证失败返回 None"""
    try:
        payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# ========== 请求频率限制 ==========
class RateLimiter:
    """基于内存的简单频率限制器（线程安全）"""
    
    def __init__(self):
        self._requests = defaultdict(list)  # key -> [timestamp, ...]
        self._lock = threading.Lock()
    
    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """
        检查请求是否允许
        key: 标识（如 IP 地址）
        max_requests: 窗口内最大请求数
        window_seconds: 时间窗口（秒）
        """
        now = time.time()
        with self._lock:
            # 清理过期记录
            self._requests[key] = [
                t for t in self._requests[key]
                if now - t < window_seconds
            ]
            # 检查是否超限
            if len(self._requests[key]) >= max_requests:
                return False
            # 记录本次请求
            self._requests[key].append(now)
            return True

# 全局限流器实例
rate_limiter = RateLimiter()