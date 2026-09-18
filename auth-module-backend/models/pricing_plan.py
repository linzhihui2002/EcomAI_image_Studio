"""
定价方案数据模型
封装 pricing_plans 表的 CRUD 操作
"""
import pymysql
from config import get_config


class PricingPlanModel:
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

    def find_all(self, is_active_only=True):
        """查询所有定价方案，按 sort_order 升序排列"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if is_active_only:
                    cursor.execute(
                        'SELECT * FROM pricing_plans WHERE is_active = 1 ORDER BY sort_order ASC'
                    )
                else:
                    cursor.execute(
                        'SELECT * FROM pricing_plans ORDER BY sort_order ASC'
                    )
                return cursor.fetchall()
        finally:
            conn.close()

    def find_by_id(self, plan_id):
        """根据 ID 查询单条定价方案"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM pricing_plans WHERE id = %s',
                    (plan_id,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def create(self, name, price, coins, bonus_coins):
        """创建定价方案"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 获取最大 sort_order
                cursor.execute('SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM pricing_plans')
                next_order = cursor.fetchone()['next_order']
                cursor.execute(
                    '''INSERT INTO pricing_plans (name, price, coins, bonus_coins, sort_order)
                       VALUES (%s, %s, %s, %s, %s)''',
                    (name, price, coins, bonus_coins, next_order)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def update(self, plan_id, name, price, coins, bonus_coins):
        """更新定价方案"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE pricing_plans
                       SET name = %s, price = %s, coins = %s, bonus_coins = %s
                       WHERE id = %s''',
                    (name, price, coins, bonus_coins, plan_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def delete(self, plan_id):
        """删除定价方案"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM pricing_plans WHERE id = %s',
                    (plan_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def toggle_active(self, plan_id):
        """切换定价方案上架/下架状态"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE pricing_plans SET is_active = NOT is_active WHERE id = %s',
                    (plan_id,)
                )
                conn.commit()
                cursor.execute(
                    'SELECT is_active FROM pricing_plans WHERE id = %s',
                    (plan_id,)
                )
                result = cursor.fetchone()
                return result['is_active'] if result else None
        finally:
            conn.close()