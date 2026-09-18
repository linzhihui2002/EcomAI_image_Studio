"""
用户资产查询服务模块
灵感币流水查询 / 余额查询
"""
import pymysql
from models.points_record import PointsRecordModel
from config import get_config

config = get_config()
points_record_model = PointsRecordModel()


def get_points_records(user_id, record_type=None, source_wallet=None, page=1, page_size=20):
    """
    获取用户灵感币流水（分页）
    参数:
        user_id: 用户ID
        record_type: 流水类型过滤，可选
        source_wallet: 钱包类型过滤 (personal/team)，可选
        page: 页码
        page_size: 每页条数
    返回:
        dict: { 'data': [...], 'pagination': {...} }
    """
    return points_record_model.find_by_user(
        user_id=user_id,
        record_type=record_type,
        source_wallet=source_wallet,
        page=page,
        page_size=page_size
    )


def get_balance(user_id, wallet_type='personal', team_id=None):
    """
    获取用户余额信息（直接从 users/teams 表读取，确保与兑换交易数据源一致）
    参数:
        user_id: 用户ID
        wallet_type: 钱包类型 (personal/team)
        team_id: 团队ID（team 钱包时需要），可选
    返回:
        dict: 余额信息
    """
    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cursor:
            if wallet_type == 'team' and team_id:
                cursor.execute(
                    'SELECT COALESCE(pool_balance, 0) AS balance FROM teams WHERE id = %s',
                    (team_id,)
                )
                row = cursor.fetchone()
                balance = int(row['balance']) if row else 0
            else:
                cursor.execute(
                    'SELECT COALESCE(personal_points, 0) AS balance FROM users WHERE id = %s',
                    (user_id,)
                )
                row = cursor.fetchone()
                balance = int(row['balance']) if row else 0

            result = {
                'wallet': wallet_type,
                'balance': balance,
            }

            if wallet_type == 'team' and team_id:
                result['teamId'] = int(team_id)

            return result
    finally:
        conn.close()