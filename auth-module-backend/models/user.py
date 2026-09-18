"""
用户数据模型
封装 users 表的 CRUD 操作
"""
import pymysql
from config import get_config

class UserModel:
    def __init__(self):
        self.config = get_config()

    def _get_connection(self):
        """获取数据库连接"""
        return pymysql.connect(
            host=self.config.MYSQL_HOST,
            port=self.config.MYSQL_PORT,
            user=self.config.MYSQL_USER,
            password=self.config.MYSQL_PASSWORD,
            database=self.config.MYSQL_DATABASE,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

    def find_by_email(self, email):
        """根据邮箱查找用户"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM users WHERE email = %s',
                    (email,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_by_id(self, user_id):
        """根据ID查找用户（不返回密码哈希）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT id, email, role, is_active, personal_points, created_at, updated_at FROM users WHERE id = %s',
                    (user_id,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def create(self, email, password_hash):
        """创建新用户，返回用户ID"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO users (email, password_hash) VALUES (%s, %s)',
                    (email, password_hash)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def update_password(self, email, password_hash):
        """更新用户密码，返回是否更新成功"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE users SET password_hash = %s WHERE email = %s',
                    (password_hash, email)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()