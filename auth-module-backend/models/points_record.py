"""
灵感币流水数据模型
封装 points_records 表的 CRUD 操作
"""
import pymysql
from config import get_config


class PointsRecordModel:
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

    def find_by_user(self, user_id, record_type=None, source_wallet=None, page=1, page_size=20):
        """
        分页查询用户灵感币流水
        参数:
            user_id: 用户ID
            record_type: 流水类型过滤 (consume/refund/bonus/topup)，可选
            source_wallet: 钱包类型过滤 (personal/team)，可选
            page: 页码
            page_size: 每页条数
        返回:
            dict: { 'data': [...], 'pagination': { 'page', 'page_size', 'total', 'total_pages' } }
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 构建 WHERE 条件
                conditions = ['user_id = %s']
                params = [user_id]

                if record_type:
                    conditions.append('type = %s')
                    params.append(record_type)

                if source_wallet:
                    conditions.append('source_wallet = %s')
                    params.append(source_wallet)

                where_clause = ' AND '.join(conditions)

                # 查询总数
                cursor.execute(
                    f'SELECT COUNT(*) AS total FROM points_records WHERE {where_clause}',
                    params
                )
                total = cursor.fetchone()['total']

                # 查询分页数据
                offset = (page - 1) * page_size
                cursor.execute(
                    f'SELECT * FROM points_records WHERE {where_clause} ORDER BY created_at DESC LIMIT %s OFFSET %s',
                    params + [page_size, offset]
                )
                records = cursor.fetchall()

                # 格式化日期字段
                for record in records:
                    if record.get('created_at'):
                        record['created_at'] = record['created_at'].isoformat()

                total_pages = (total + page_size - 1) // page_size if total > 0 else 0

                return {
                    'data': records,
                    'pagination': {
                        'page': page,
                        'pageSize': page_size,
                        'total': total,
                        'totalPages': total_pages,
                    }
                }
        finally:
            conn.close()

    def create(self, user_id, amount, record_type, source_wallet, description,
               team_id=None, related_batch_id=None):
        """
        创建灵感币流水记录
        参数:
            user_id: 用户ID
            amount: 金额（正数=收入，负数=支出）
            record_type: 流水类型 (consume/refund/bonus/topup)
            source_wallet: 钱包类型 (personal/team)
            description: 描述
            team_id: 关联团队ID，可选
            related_batch_id: 关联批次ID，可选
        返回:
            int: 新记录的ID
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO points_records
                       (user_id, amount, type, source_wallet, team_id, related_batch_id, description)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (user_id, amount, record_type, source_wallet, team_id, related_batch_id, description)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def get_balance(self, user_id, source_wallet):
        """
        获取用户指定钱包的余额
        参数:
            user_id: 用户ID
            source_wallet: 钱包类型 (personal/team)
        返回:
            int: 余额
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT COALESCE(SUM(amount), 0) AS balance FROM points_records WHERE user_id = %s AND source_wallet = %s',
                    (user_id, source_wallet)
                )
                result = cursor.fetchone()
                return int(result['balance'])
        finally:
            conn.close()