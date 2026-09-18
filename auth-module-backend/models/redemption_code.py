"""
兑换码数据模型
封装 redemption_codes 表的 CRUD 操作
扩展：总使用次数限制、单账号使用次数限制、使用记录明细
"""
import pymysql
from config import get_config


class RedemptionCodeModel:
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

    def find_by_code(self, code):
        """根据兑换码查询单条记录（含次数限制字段）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM redemption_codes WHERE code = %s',
                    (code,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_usable_code(self, code):
        """
        查询仍可用的兑换码（use_count < max_uses 且未过期）
        - 已过期或已达到总使用次数上限的兑换码不返回
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                from datetime import datetime
                cursor.execute(
                    '''SELECT * FROM redemption_codes
                       WHERE code = %s
                         AND use_count < max_uses
                         AND (expires_at IS NULL OR expires_at > %s)''',
                    (code, datetime.now())
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def mark_as_used(self, code_id, user_id):
        """将兑换码标记为已使用（兼容旧版单次使用逻辑）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE redemption_codes SET is_used = 1, used_by = %s, used_at = NOW() WHERE id = %s',
                    (user_id, code_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def find_all_by_status(self, status='all'):
        """按状态查询兑换码列表"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if status == 'unused':
                    cursor.execute(
                        'SELECT * FROM redemption_codes WHERE is_used = 0 ORDER BY created_at DESC'
                    )
                elif status == 'used':
                    cursor.execute(
                        'SELECT * FROM redemption_codes WHERE is_used = 1 ORDER BY created_at DESC'
                    )
                else:
                    cursor.execute(
                        'SELECT * FROM redemption_codes ORDER BY created_at DESC'
                    )
                return cursor.fetchall()
        finally:
            conn.close()

    def create(self, code, coins, expires_at, remark, max_uses=1, max_uses_per_user=1):
        """创建兑换码（含次数限制参数）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO redemption_codes (code, coins, expires_at, remark, max_uses, max_uses_per_user, use_count)
                       VALUES (%s, %s, %s, %s, %s, %s, 0)''',
                    (code, coins, expires_at, remark, max_uses, max_uses_per_user)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def delete(self, code_id):
        """删除兑换码"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM redemption_codes WHERE id = %s',
                    (code_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def find_by_id(self, code_id):
        """根据 ID 查询兑换码"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM redemption_codes WHERE id = %s',
                    (code_id,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    # ==================== 新增：使用次数追踪 ====================

    def count_user_usages(self, code_id, user_id):
        """
        查询指定用户对某兑换码的使用次数
        用于校验单账号使用次数限制
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT COUNT(*) AS cnt FROM redemption_code_usages
                       WHERE redemption_code_id = %s AND user_id = %s''',
                    (code_id, user_id)
                )
                row = cursor.fetchone()
                return row['cnt'] if row else 0
        finally:
            conn.close()

    def find_usages_by_code_id(self, code_id):
        """查询兑换码的所有使用记录"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT rcu.*, u.email AS user_email
                       FROM redemption_code_usages rcu
                       LEFT JOIN users u ON rcu.user_id = u.id
                       WHERE rcu.redemption_code_id = %s
                       ORDER BY rcu.used_at DESC''',
                    (code_id,)
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def increment_usage(self, code_id, user_id, coins_awarded, wallet_type, team_id=None):
        """
        原子性递增 use_count + 插入使用记录 + 同步更新 is_used
        在同一连接中由调用方管理事务
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 1. 原子递增 use_count，并根据递增后的值判断是否达到上限
                cursor.execute(
                    '''UPDATE redemption_codes
                       SET use_count = use_count + 1,
                           is_used = (use_count + 1 >= max_uses),
                           used_by = %s,
                           used_at = NOW()
                       WHERE id = %s AND use_count < max_uses''',
                    (user_id, code_id)
                )
                if cursor.rowcount == 0:
                    conn.rollback()
                    return False

                # 2. 插入使用记录明细
                cursor.execute(
                    '''INSERT INTO redemption_code_usages
                       (redemption_code_id, user_id, wallet_type, team_id, coins_awarded)
                       VALUES (%s, %s, %s, %s, %s)''',
                    (code_id, user_id, wallet_type, team_id, coins_awarded)
                )

                conn.commit()
                return True
        finally:
            conn.close()