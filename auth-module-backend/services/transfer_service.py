"""
转账业务服务模块
个人 ↔ 团队钱包转账（含事务管理、审计日志）
"""
import traceback
import pymysql
from models.team import TeamModel
from models.transfer_log import TransferLogModel
from services.auth_service import AuthError
from config import get_config

config = get_config()
team_model = TeamModel()
transfer_log_model = TransferLogModel()


def transfer_personal_to_team(user_id, team_id, amount, ip_address=None):
    """
    个人钱包 → 团队钱包 转账

    参数:
        user_id: 转账发起人 ID
        team_id: 目标团队 ID
        amount: 转账金额（> 0）
        ip_address: 操作 IP

    返回:
        dict: { amount, newTeamBalance, newPersonalBalance }

    异常:
        AuthError(3012): 个人余额不足
        AuthError(3015): 转账金额必须大于 0
        AuthError(3017): 转账失败
    """
    # 参数校验
    if not amount or int(amount) <= 0:
        raise AuthError('转账金额必须大于 0', 3015, 400)

    amount = int(amount)

    # 校验是否为团队成员
    member = team_model.find_member(team_id, user_id)
    if not member:
        raise AuthError('团队不存在或您不是该团队成员', 3007, 404)

    # 仅 Owner 可向团队钱包转账
    if member['role'] != 'owner':
        raise AuthError('仅团队创建者可向团队钱包转账', 3018, 403)

    # 单连接事务
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
            # 1. 锁定用户行（防止并发）
            cursor.execute(
                'SELECT personal_points FROM users WHERE id = %s FOR UPDATE',
                (user_id,)
            )
            user_row = cursor.fetchone()
            if not user_row:
                raise AuthError('用户不存在', 1008, 404)

            personal_balance = int(user_row['personal_points'])

            # 2. 余额校验
            if personal_balance < amount:
                raise AuthError('个人余额不足，无法完成转账', 3012, 400)

            # 3. 扣减个人余额
            cursor.execute(
                'UPDATE users SET personal_points = personal_points - %s WHERE id = %s',
                (amount, user_id)
            )

            # 4. 增加团队余额
            cursor.execute(
                'UPDATE teams SET pool_balance = pool_balance + %s WHERE id = %s',
                (amount, team_id)
            )

            # 5. 获取新余额
            cursor.execute(
                'SELECT COALESCE(personal_points, 0) AS balance FROM users WHERE id = %s',
                (user_id,)
            )
            new_personal = int(cursor.fetchone()['balance'])

            cursor.execute(
                'SELECT COALESCE(pool_balance, 0) AS balance FROM teams WHERE id = %s',
                (team_id,)
            )
            new_team = int(cursor.fetchone()['balance'])

            # 6. 插入积分流水记录（转出方 - consume）
            cursor.execute(
                '''INSERT INTO points_records
                   (user_id, amount, type, source_wallet, team_id, description)
                   VALUES (%s, %s, %s, %s, %s, %s)''',
                (user_id, -amount, 'consume', 'personal', team_id,
                 f'向团队转账 {amount} 灵感币')
            )

            # 7. 插入积分流水记录（转入方 - topup）
            cursor.execute(
                '''INSERT INTO points_records
                   (user_id, amount, type, source_wallet, team_id, description)
                   VALUES (%s, %s, %s, %s, %s, %s)''',
                (user_id, amount, 'topup', 'team', team_id,
                 f'收到成员转账 {amount} 灵感币')
            )

            # 8. 插入审计日志（非致命：即使日志写入失败也不影响核心转账）
            try:
                transfer_log_model.create_in_transaction(
                    cursor,
                    transfer_type='personal_to_team',
                    from_user_id=user_id,
                    from_wallet='personal',
                    to_wallet='team',
                    amount=amount,
                    team_id=team_id,
                    ip_address=ip_address
                )
            except Exception as e:
                print(f'[transfer_personal_to_team] 审计日志写入失败（非致命）: '
                      f'user_id={user_id}, team_id={team_id}, amount={amount}, error={e}')
                traceback.print_exc()

            conn.commit()

            return {
                'amount': amount,
                'newTeamBalance': new_team,
                'newPersonalBalance': new_personal,
            }

    except AuthError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print(f'[transfer_personal_to_team] 转账失败: user_id={user_id}, '
              f'team_id={team_id}, amount={amount}, error={e}')
        raise AuthError('转账失败，请稍后重试', 3017, 500)
    finally:
        conn.close()


def transfer_team_to_owner_in_transaction(cursor, team_id, owner_id, amount, ip_address=None):
    """
    团队钱包 → Owner 个人钱包 转账（在已有事务中执行）

    仅供 dissolve_team 内部调用，不自行管理连接和事务

    参数:
        cursor: 外部事务 cursor
        team_id: 团队 ID
        owner_id: Owner 用户 ID
        amount: 转账金额
        ip_address: 操作 IP
    """
    if amount <= 0:
        return

    # 增加 owner 个人余额
    cursor.execute(
        'UPDATE users SET personal_points = personal_points + %s WHERE id = %s',
        (amount, owner_id)
    )

    # 插入积分流水记录（转入方 - topup）
    cursor.execute(
        '''INSERT INTO points_records
           (user_id, amount, type, source_wallet, team_id, description)
           VALUES (%s, %s, %s, %s, %s, %s)''',
        (owner_id, amount, 'topup', 'personal', team_id,
         f'团队解散余额转入 {amount} 灵感币')
    )

    # 插入积分流水记录（转出方 - consume）
    cursor.execute(
        '''INSERT INTO points_records
           (user_id, amount, type, source_wallet, team_id, description)
           VALUES (%s, %s, %s, %s, %s, %s)''',
        (owner_id, -amount, 'consume', 'team', team_id,
         f'团队解散余额转出 {amount} 灵感币')
    )

    # 插入审计日志（非致命：即使日志写入失败也不影响核心转账）
    try:
        transfer_log_model.create_in_transaction(
            cursor,
            transfer_type='team_to_owner',
            from_user_id=owner_id,
            from_wallet='team',
            to_wallet='personal',
            amount=amount,
            team_id=team_id,
            to_user_id=owner_id,
            ip_address=ip_address
        )
    except Exception as e:
        print(f'[transfer_team_to_owner] 审计日志写入失败（非致命）: '
              f'team_id={team_id}, owner_id={owner_id}, amount={amount}, error={e}')
        traceback.print_exc()