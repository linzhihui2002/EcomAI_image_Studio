"""
转账审计日志数据模型
封装 transfer_audit_logs 表的 CRUD 操作
"""
import pymysql
from config import get_config


class TransferLogModel:
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

    def create(self, transfer_type, from_user_id, from_wallet, to_wallet,
               amount, team_id=None, to_user_id=None,
               status='success', error_msg=None, ip_address=None):
        """
        创建转账审计日志

        参数:
            transfer_type: 转账类型 (team_to_owner / personal_to_team)
            from_user_id: 转账发起人 ID
            from_wallet: 转出钱包类型 (personal / team)
            to_wallet: 转入钱包类型 (personal / team)
            amount: 转账金额
            team_id: 关联团队 ID
            to_user_id: 接收方用户 ID
            status: 转账状态 (success / failed)
            error_msg: 失败原因
            ip_address: 操作 IP
        返回:
            int: 新记录的 ID
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO transfer_audit_logs
                       (transfer_type, from_user_id, from_wallet, team_id,
                        to_user_id, to_wallet, amount, status, error_msg, ip_address)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    (transfer_type, from_user_id, from_wallet, team_id,
                     to_user_id, to_wallet, amount, status, error_msg, ip_address)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def create_in_transaction(self, cursor, transfer_type, from_user_id,
                               from_wallet, to_wallet, amount,
                               team_id=None, to_user_id=None,
                               status='success', error_msg=None, ip_address=None):
        """
        在已有事务中创建转账审计日志（使用外部传入的 cursor，不自行 commit）

        参数同 create()
        """
        cursor.execute(
            '''INSERT INTO transfer_audit_logs
               (transfer_type, from_user_id, from_wallet, team_id,
                to_user_id, to_wallet, amount, status, error_msg, ip_address)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (transfer_type, from_user_id, from_wallet, team_id,
             to_user_id, to_wallet, amount, status, error_msg, ip_address)
        )
        return cursor.lastrowid

    def find_by_team(self, team_id, page=1, page_size=20):
        """
        分页查询团队转账日志

        参数:
            team_id: 团队 ID
            page: 页码
            page_size: 每页条数
        返回:
            dict: { 'data': [...], 'pagination': { 'page', 'page_size', 'total', 'total_pages' } }
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 查询总数
                cursor.execute(
                    'SELECT COUNT(*) AS total FROM transfer_audit_logs WHERE team_id = %s',
                    (team_id,)
                )
                total = cursor.fetchone()['total']

                # 查询分页数据
                offset = (page - 1) * page_size
                cursor.execute(
                    '''SELECT tal.*, u.email AS from_user_email
                       FROM transfer_audit_logs tal
                       LEFT JOIN users u ON u.id = tal.from_user_id
                       WHERE tal.team_id = %s
                       ORDER BY tal.created_at DESC
                       LIMIT %s OFFSET %s''',
                    (team_id, page_size, offset)
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