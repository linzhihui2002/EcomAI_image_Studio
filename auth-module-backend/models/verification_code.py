"""
验证码数据模型
封装 verification_codes 表的 CRUD 操作
"""
import pymysql
from config import get_config


class VerificationCodeModel:
    def __init__(self):
        self.config = get_config()

    def _get_connection(self):
        return pymysql.connect(
            host=self.config.MYSQL_HOST,
            port=self.config.MYSQL_PORT,
            user=self.config.MYSQL_USER,
            password=self.config.MYSQL_PASSWORD,
            database=self.config.MYSQL_DATABASE,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

    def save(self, email, code, purpose):
        """保存验证码"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO verification_codes (email, code, purpose, expires_at) '
                    'VALUES (%s, %s, %s, DATE_ADD(NOW(), INTERVAL %s SECOND))',
                    (email, code, purpose, self.config.VERIFICATION_CODE_EXPIRE)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def verify(self, email, code, purpose):
        """
        校验验证码
        返回 True 表示验证通过（同时标记为已使用），False 表示无效
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 查找未使用、未过期的最新验证码
                cursor.execute(
                    'SELECT id, code, expires_at, used FROM verification_codes '
                    'WHERE email = %s AND purpose = %s AND used = 0 '
                    'AND expires_at > NOW() '
                    'ORDER BY created_at DESC LIMIT 1',
                    (email, purpose)
                )
                record = cursor.fetchone()
                if not record:
                    return False
                if record['code'] != code:
                    return False
                # 标记为已使用
                cursor.execute(
                    'UPDATE verification_codes SET used = 1 WHERE id = %s',
                    (record['id'],)
                )
                conn.commit()
                return True
        finally:
            conn.close()

    def count_today(self, email):
        """统计同一邮箱今天发送的验证码数量"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT COUNT(*) AS cnt FROM verification_codes '
                    'WHERE email = %s AND DATE(created_at) = CURDATE()',
                    (email,)
                )
                result = cursor.fetchone()
                return result['cnt'] if result else 0
        finally:
            conn.close()

    def latest_send_time(self, email):
        """获取同一邮箱最近一次发送验证码的时间（秒前）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT TIMESTAMPDIFF(SECOND, created_at, NOW()) AS seconds_ago '
                    'FROM verification_codes '
                    'WHERE email = %s ORDER BY created_at DESC LIMIT 1',
                    (email,)
                )
                result = cursor.fetchone()
                return result['seconds_ago'] if result else None
        finally:
            conn.close()

    def clean_expired(self):
        """清理过期验证码记录"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM verification_codes WHERE expires_at < NOW()'
                )
                conn.commit()
                return cursor.rowcount
        finally:
            conn.close()