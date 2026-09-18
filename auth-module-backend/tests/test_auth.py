"""
认证模块单元测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from app import create_app
from utils.security import rate_limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """每个测试前重置限流器"""
    rate_limiter._requests.clear()


@pytest.fixture
def app():
    """创建测试应用"""
    app = create_app('testing')
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return app.test_client()


# 开发测试账号（对应 init_db.sql 中写入的种子数据）
# 注意：这两个账号仅供本地开发与自动化测试使用，对外部署前必须修改密码或删除，
# 详见 docs/SECURITY.md 的「开发测试默认凭据」章节。
TEST_ADMIN_EMAIL = 'admin@ecomai.local'
TEST_ADMIN_PASSWORD = 'tao666666'
TEST_USER_EMAIL = 'user@ecomai.local'
TEST_USER_PASSWORD = '1234567890'


@pytest.fixture
def admin_token(client):
    """获取管理员 Token"""
    response = client.post('/api/v1/auth/login', json={
        'email': TEST_ADMIN_EMAIL,
        'password': TEST_ADMIN_PASSWORD
    })
    data = response.get_json()
    return data['data']['token']


@pytest.fixture
def user_token(client):
    """获取普通用户 Token"""
    response = client.post('/api/v1/auth/login', json={
        'email': TEST_USER_EMAIL,
        'password': TEST_USER_PASSWORD
    })
    data = response.get_json()
    return data['data']['token']


class TestRegister:
    """注册功能测试"""

    def test_register_success(self, client):
        """注册成功"""
        response = client.post('/api/v1/auth/register', json={
            'email': f'test_{os.urandom(4).hex()}@example.com',
            'password': 'Test1234!',
            'code': '000000'
        })
        # 由于验证码无效，应该返回 400 (3009)
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3009

    def test_register_duplicate_email(self, client):
        """重复邮箱注册"""
        response = client.post('/api/v1/auth/register', json={
            'email': 'admin@ecomai.local',
            'password': 'Test1234!',
            'code': '000000'
        })
        # 验证码无效，先被验证码检查拦截
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3009

    def test_register_weak_password_no_upper(self, client):
        """密码强度不足 — 无大写字母"""
        response = client.post('/api/v1/auth/register', json={
            'email': 'test@example.com',
            'password': 'test1234!',
            'code': '000000'
        })
        assert response.status_code == 400
        data = response.get_json()
        # 密码强度检查在验证码检查之前，所以返回密码错误
        assert data['code'] == 3002
        assert '大写字母' in data['message']

    def test_register_weak_password_no_digit(self, client):
        """密码强度不足 — 无数字"""
        response = client.post('/api/v1/auth/register', json={
            'email': 'test@example.com',
            'password': 'TestTest!',
            'code': '000000'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002
        assert '数字' in data['message']

    def test_register_weak_password_short(self, client):
        """密码强度不足 — 长度不够"""
        response = client.post('/api/v1/auth/register', json={
            'email': 'test@example.com',
            'password': 'Ab1!',
            'code': '000000'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002
        assert '长度' in data['message']

    def test_register_invalid_email(self, client):
        """邮箱格式无效"""
        response = client.post('/api/v1/auth/register', json={
            'email': 'not-an-email',
            'password': 'Test1234!',
            'code': '000000'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002

    def test_register_missing_fields(self, client):
        """缺少必填字段"""
        response = client.post('/api/v1/auth/register', json={
            'email': 'test@example.com'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002


class TestLogin:
    """登录功能测试"""

    def test_login_admin_success(self, client):
        """管理员登录成功"""
        response = client.post('/api/v1/auth/login', json={
            'email': TEST_ADMIN_EMAIL,
            'password': TEST_ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0
        assert 'token' in data['data']
        assert data['data']['user']['role'] == 'admin'

    def test_login_user_success(self, client):
        """普通用户登录成功"""
        response = client.post('/api/v1/auth/login', json={
            'email': TEST_USER_EMAIL,
            'password': TEST_USER_PASSWORD
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0
        assert data['data']['user']['role'] == 'user'

    def test_login_wrong_password(self, client):
        """密码错误"""
        response = client.post('/api/v1/auth/login', json={
            'email': 'admin@ecomai.local',
            'password': 'wrongpassword'
        })
        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 1001

    def test_login_nonexistent_email(self, client):
        """邮箱不存在"""
        response = client.post('/api/v1/auth/login', json={
            'email': 'nonexistent@qq.com',
            'password': 'Test1234!'
        })
        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 1001

    def test_login_missing_fields(self, client):
        """缺少必填字段"""
        response = client.post('/api/v1/auth/login', json={
            'email': 'admin@ecomai.local'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002


class TestAuthMe:
    """获取当前用户信息测试"""

    def test_get_me_with_valid_token(self, client, user_token):
        """有效 Token 获取用户信息"""
        response = client.get('/api/v1/auth/me', headers={
            'Authorization': f'Bearer {user_token}'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0
        assert 'user' in data['data']

    def test_get_me_without_token(self, client):
        """无 Token 访问"""
        response = client.get('/api/v1/auth/me')
        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 1001

    def test_get_me_with_invalid_token(self, client):
        """无效 Token"""
        response = client.get('/api/v1/auth/me', headers={
            'Authorization': 'Bearer invalid_token_here'
        })
        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 1002


class TestRoleAccess:
    """角色权限测试"""

    def test_admin_access_admin_profile(self, client, admin_token):
        """管理员访问管理接口"""
        response = client.get('/api/v1/admin/profile', headers={
            'Authorization': f'Bearer {admin_token}'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0

    def test_user_access_admin_profile(self, client, user_token):
        """普通用户访问管理接口"""
        response = client.get('/api/v1/admin/profile', headers={
            'Authorization': f'Bearer {user_token}'
        })
        assert response.status_code == 403
        data = response.get_json()
        assert data['code'] == 1003

    def test_user_access_user_profile(self, client, user_token):
        """普通用户访问用户接口"""
        response = client.get('/api/v1/user/profile', headers={
            'Authorization': f'Bearer {user_token}'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0

    def test_no_token_access_protected(self, client):
        """未登录访问受保护接口"""
        response = client.get('/api/v1/user/profile')
        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 1001


class TestSendCode:
    """验证码发送测试"""

    def test_send_code_register(self, client):
        """发送注册验证码成功"""
        response = client.post('/api/v1/auth/send-code', json={
            'email': 'test_send@example.com',
            'purpose': 'register'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0
        assert 'expires_in' in data['data']

    def test_send_code_login(self, client):
        """发送登录验证码成功"""
        response = client.post('/api/v1/auth/send-code', json={
            'email': 'admin@ecomai.local',
            'purpose': 'login'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0

    def test_send_code_duplicate_quickly(self, client):
        """60秒内重复发送被限流"""
        client.post('/api/v1/auth/send-code', json={
            'email': 'test_dup@example.com',
            'purpose': 'register'
        })
        response = client.post('/api/v1/auth/send-code', json={
            'email': 'test_dup@example.com',
            'purpose': 'register'
        })
        assert response.status_code == 429
        data = response.get_json()
        assert data['code'] == 3008

    def test_send_code_missing_email(self, client):
        """缺少邮箱"""
        response = client.post('/api/v1/auth/send-code', json={
            'purpose': 'register'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002

    def test_send_code_invalid_purpose(self, client):
        """无效的 purpose 参数"""
        response = client.post('/api/v1/auth/send-code', json={
            'email': 'test@example.com',
            'purpose': 'invalid'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002


class TestLoginWithCode:
    """验证码登录测试"""

    def test_login_with_code_invalid(self, client):
        """无效验证码登录"""
        response = client.post('/api/v1/auth/login/code', json={
            'email': 'admin@ecomai.local',
            'code': '000000'
        })
        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 1001

    def test_login_with_code_missing_code(self, client):
        """缺少验证码"""
        response = client.post('/api/v1/auth/login/code', json={
            'email': 'admin@ecomai.local'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002


class TestRegisterWithCode:
    """注册（带验证码）测试"""

    def test_register_without_code(self, client):
        """注册时缺少验证码"""
        response = client.post('/api/v1/auth/register', json={
            'email': 'test@example.com',
            'password': 'Test1234!'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3002

    def test_register_with_invalid_code(self, client):
        """注册时验证码无效"""
        response = client.post('/api/v1/auth/register', json={
            'email': f'test_{os.urandom(4).hex()}@example.com',
            'password': 'Test1234!',
            'code': '000000'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3009

    def test_register_with_expired_code(self, client):
        """注册时验证码过期"""
        # 此测试需要手动插入过期验证码到数据库
        import pymysql
        from config import get_config as _get_config
        cfg = _get_config()
        conn = pymysql.connect(
            host=cfg.MYSQL_HOST, port=cfg.MYSQL_PORT,
            user=cfg.MYSQL_USER, password=cfg.MYSQL_PASSWORD,
            database=cfg.MYSQL_DATABASE, charset='utf8mb4'
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO verification_codes (email, code, purpose, expires_at) '
                    'VALUES (%s, %s, %s, DATE_SUB(NOW(), INTERVAL 1 SECOND))',
                    ('test_expired@example.com', '123456', 'register')
                )
                conn.commit()
        finally:
            conn.close()

        response = client.post('/api/v1/auth/register', json={
            'email': 'test_expired@example.com',
            'password': 'Test1234!',
            'code': '123456'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['code'] == 3009


class TestPasswordLoginStillWorks:
    """确认密码登录功能不受影响"""

    def test_admin_password_login(self, client):
        """管理员密码登录仍然正常"""
        response = client.post('/api/v1/auth/login', json={
            'email': TEST_ADMIN_EMAIL,
            'password': TEST_ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0
        assert 'token' in data['data']

    def test_user_password_login(self, client):
        """普通用户密码登录仍然正常"""
        response = client.post('/api/v1/auth/login', json={
            'email': TEST_USER_EMAIL,
            'password': TEST_USER_PASSWORD
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0
        assert 'token' in data['data']


class TestHealthCheck:
    """健康检查测试"""

    def test_health_check(self, client):
        """健康检查接口"""
        response = client.get('/api/v1/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['code'] == 0
        assert data['data']['status'] == 'healthy'