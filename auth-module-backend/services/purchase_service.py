"""
充值中心业务服务模块
定价方案查询 / 兑换码兑换
扩展：总使用次数限制、单账号使用次数限制
"""
import pymysql
from models.pricing_plan import PricingPlanModel
from models.redemption_code import RedemptionCodeModel
from models.points_record import PointsRecordModel
from services.auth_service import AuthError
from config import get_config

config = get_config()
pricing_plan_model = PricingPlanModel()
redemption_code_model = RedemptionCodeModel()
points_record_model = PointsRecordModel()


def get_pricing_plans(is_active_only=True):
    """获取定价方案列表"""
    return pricing_plan_model.find_all(is_active_only)


def redeem_code(user_id, code, wallet_type, team_id=None):
    """
    兑换码兑换（单连接 + 行级锁，防止并发重复使用）
    参数:
        user_id: 用户ID
        code: 兑换码
        wallet_type: 钱包类型 'personal' 或 'team'
        team_id: 团队ID（wallet_type='team' 时必填）
    返回:
        dict: { coinsAdded, newBalance, codeInfo }
    异常:
        AuthError: 兑换码不存在 / 已使用 / 已过期 / 达到次数上限
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
            # 1. 查询兑换码并加行级锁（防止并发）
            cursor.execute(
                'SELECT * FROM redemption_codes WHERE code = %s FOR UPDATE',
                (code,)
            )
            code_record = cursor.fetchone()
            if not code_record:
                raise AuthError('兑换码不存在', 4001, 404)

            # 2. 检查总使用次数上限
            if code_record['use_count'] >= code_record['max_uses']:
                raise AuthError('兑换码已达到总使用次数上限，无法继续使用', 4006, 409)

            # 3. 检查是否过期
            if code_record['expires_at'] is not None:
                from datetime import datetime
                if code_record['expires_at'] < datetime.now():
                    raise AuthError('兑换码已过期', 4003, 400)

            # 4. 检查单账号使用次数限制
            code_id = code_record['id']
            max_per_user = code_record['max_uses_per_user']
            # 在同一个事务中查询用户已使用次数（使用行级锁保护）
            cursor.execute(
                '''SELECT COUNT(*) AS cnt FROM redemption_code_usages
                   WHERE redemption_code_id = %s AND user_id = %s FOR UPDATE''',
                (code_id, user_id)
            )
            usage_row = cursor.fetchone()
            user_usage_count = usage_row['cnt'] if usage_row else 0
            if user_usage_count >= max_per_user:
                raise AuthError('该账号已达到此兑换码的使用次数限制', 4007, 409)

            coins = code_record['coins']

            # 5. 原子性递增 use_count + 插入使用记录 + 更新 is_used
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
                raise AuthError('兑换码已达到总使用次数上限，无法继续使用', 4006, 409)

            # 6. 插入使用记录明细
            cursor.execute(
                '''INSERT INTO redemption_code_usages
                   (redemption_code_id, user_id, wallet_type, team_id, coins_awarded)
                   VALUES (%s, %s, %s, %s, %s)''',
                (code_id, user_id, wallet_type, team_id, coins)
            )

            # 7. 更新余额
            if wallet_type == 'personal':
                cursor.execute(
                    'UPDATE users SET personal_points = COALESCE(personal_points, 0) + %s WHERE id = %s',
                    (coins, user_id)
                )
                cursor.execute(
                    'SELECT COALESCE(personal_points, 0) AS balance FROM users WHERE id = %s',
                    (user_id,)
                )
                balance_row = cursor.fetchone()
                new_balance = balance_row['balance'] if balance_row else coins
            elif wallet_type == 'team':
                if team_id is None:
                    raise AuthError('团队ID不能为空', 4004, 400)
                cursor.execute(
                    'UPDATE teams SET pool_balance = COALESCE(pool_balance, 0) + %s WHERE id = %s',
                    (coins, team_id)
                )
                cursor.execute(
                    'SELECT COALESCE(pool_balance, 0) AS balance FROM teams WHERE id = %s',
                    (team_id,)
                )
                balance_row = cursor.fetchone()
                new_balance = balance_row['balance'] if balance_row else coins
            else:
                raise AuthError('钱包类型无效', 4004, 400)

            # 8. 插入积分流水记录
            cursor.execute(
                'INSERT INTO points_records (user_id, amount, type, source_wallet, team_id, description) VALUES (%s, %s, %s, %s, %s, %s)',
                (user_id, coins, 'bonus', wallet_type, team_id, f'兑换码: {code}')
            )

            conn.commit()

            return {
                'coinsAdded': coins,
                'newBalance': new_balance,
                'codeInfo': {
                    'id': code_record['id'],
                    'code': code_record['code'],
                    'coins': code_record['coins'],
                }
            }
    except AuthError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print(f'[redeem_code] 兑换失败: user_id={user_id}, code={code}, error={e}')
        raise
    finally:
        conn.close()