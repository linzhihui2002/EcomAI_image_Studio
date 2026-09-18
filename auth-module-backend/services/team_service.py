"""
团队业务服务模块
团队创建 / 加入 / 查询 / 邀请码管理
"""
import secrets
from datetime import datetime, timedelta
import traceback
import pymysql
from models.team import TeamModel
from models.invitation import InvitationModel
from services.auth_service import AuthError
from services.transfer_service import transfer_team_to_owner_in_transaction
from utils.crypto import hash_sha256, aes_encrypt, aes_decrypt
from config import get_config

config = get_config()

# 邀请码字符集（排除易混淆字符 O/0/I/1/l）
_INVITE_CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'

# 允许的团队类目
_ALLOWED_CATEGORIES = ['服装/鞋包', '3C电子', '家居园艺', '美妆个护', '运动户外', '其他']

team_model = TeamModel()
invitation_model = InvitationModel()


def _generate_invite_code():
    """生成唯一邀请码（10 位，含大小写字母+数字）"""
    length = config.INVITE_CODE_LENGTH
    for _ in range(10):
        code = ''.join(secrets.choice(_INVITE_CODE_CHARS) for _ in range(length))
        code_hash = hash_sha256(code)
        if not invitation_model.find_by_hash(code_hash):
            return code
    # 极端情况下回退为更长随机码
    return secrets.token_urlsafe(8)[:length]


def _serialize_team(t):
    """序列化团队信息"""
    return {
        'id': t['id'],
        'name': t['name'],
        'category': t['category'],
        'inviteCode': t.get('invite_code', ''),
        'ownerId': t['owner_id'],
        'memberCount': t['member_count'],
        'poolBalance': t['pool_balance'],
    }


# ==================== 邀请码管理 ====================

def create_invitation(team_id, created_by):
    """
    为团队创建新的邀请码

    返回:
        dict: { code, expiresAt, usageCount, maxUsage, createdAt, invitationId }
    """
    import traceback

    try:
        code = _generate_invite_code()
        code_hash = hash_sha256(code)
        code_encrypted = aes_encrypt(code, config.INVITE_CODE_ENCRYPTION_KEY)
        expires_at = datetime.now() + timedelta(days=config.INVITE_CODE_EXPIRE_DAYS)

        invitation_id = invitation_model.create(
            team_id=team_id,
            code_hash=code_hash,
            code_encrypted=code_encrypted,
            created_by=created_by,
            expires_at=expires_at.strftime('%Y-%m-%d %H:%M:%S'),
            max_usage=config.INVITE_CODE_MAX_USAGE,
        )
    except Exception as e:
        print(f'[TeamService] create_invitation: 操作异常 team_id={team_id}, created_by={created_by}: {e}')
        traceback.print_exc()
        raise

    return {
        'invitationId': invitation_id,
        'code': code,
        'expiresAt': expires_at.isoformat(),
        'usageCount': 0,
        'maxUsage': config.INVITE_CODE_MAX_USAGE,
        'createdAt': datetime.now().isoformat(),
    }


def get_active_invitation(team_id, user_id):
    """
    获取团队当前有效的邀请码

    权限：仅 owner 或 admin 可查看
    """
    # 校验权限
    member = team_model.find_member(team_id, user_id)
    if not member or member['role'] not in ('owner', 'admin'):
        raise AuthError('仅团队管理员可查看邀请码', 3011, 403)

    invitation = invitation_model.find_active_by_team(team_id)
    if not invitation:
        return None

    # 解密邀请码
    code = aes_decrypt(invitation['invite_code_encrypted'], config.INVITE_CODE_ENCRYPTION_KEY)

    return {
        'invitationId': invitation['id'],
        'code': code,
        'expiresAt': invitation['expires_at'].isoformat() if hasattr(invitation['expires_at'], 'isoformat') else str(invitation['expires_at']),
        'usageCount': invitation['usage_count'],
        'maxUsage': invitation['max_usage'],
        'createdAt': invitation['created_at'].isoformat() if hasattr(invitation['created_at'], 'isoformat') else str(invitation['created_at']),
    }


def refresh_invitation(team_id, user_id):
    """
    刷新邀请码：失效旧码，生成新码

    权限：仅 owner 或 admin 可操作
    """
    import traceback

    # 校验权限
    try:
        member = team_model.find_member(team_id, user_id)
    except Exception as e:
        print(f'[TeamService] refresh_invitation: find_member 数据库异常 team_id={team_id}, user_id={user_id}: {e}')
        traceback.print_exc()
        raise

    if not member or member['role'] not in ('owner', 'admin'):
        raise AuthError('仅团队管理员可刷新邀请码', 3011, 403)

    # 失效旧邀请码
    try:
        invitation_model.deactivate(team_id)
    except Exception as e:
        print(f'[TeamService] refresh_invitation: deactivate 异常 team_id={team_id}: {e}')
        traceback.print_exc()
        raise

    # 生成新邀请码
    return create_invitation(team_id, user_id)


def verify_invitation(invite_code_str):
    """
    验证邀请码是否有效

    参数:
        invite_code_str: 用户输入的邀请码

    返回:
        dict: { valid, teamName, teamId, remainingUses, expiresAt }
    """
    invite_code_str = (invite_code_str or '').strip()

    code_hash = hash_sha256(invite_code_str)
    invitation = invitation_model.find_by_hash(code_hash)

    if not invitation:
        # 兼容旧系统：尝试通过 teams 表查找
        team = team_model.find_by_invite_code(invite_code_str.upper())
        if team:
            return {
                'valid': True,
                'teamId': team['id'],
                'teamName': team['name'],
                'remainingUses': None,
                'expiresAt': None,
            }
        return {'valid': False}

    remaining = invitation['max_usage'] - invitation['usage_count']
    expires_at = invitation['expires_at']
    if hasattr(expires_at, 'isoformat'):
        expires_at = expires_at.isoformat()
    else:
        expires_at = str(expires_at)

    return {
        'valid': True,
        'teamId': invitation['team_id'],
        'teamName': invitation['team_name'],
        'remainingUses': max(0, remaining),
        'expiresAt': expires_at,
    }


# ==================== 团队管理 ====================

def create_team(owner_id, name, category):
    """
    创建团队

    参数:
        owner_id: 创建者用户 ID
        name: 团队名称（2-20 字符）
        category: 主营类目

    返回:
        dict: 团队信息

    异常:
        AuthError: 参数无效 / 团队名已存在
    """
    name = (name or '').strip()
    category = (category or '').strip()

    # 参数校验
    if not name:
        raise AuthError('团队名称不能为空', 3002, 400)
    if len(name) < 2 or len(name) > 20:
        raise AuthError('团队名称需要 2-20 个字符', 3002, 400)
    if category not in _ALLOWED_CATEGORIES:
        raise AuthError('类目无效，请从列表中选择', 3002, 400)

    # 检查重名
    existing = team_model.find_by_name(name)
    if existing:
        raise AuthError('团队名称已存在，请更换名称', 3006, 409)

    # 生成邀请码
    invite_code = _generate_invite_code()

    # 创建团队
    team_id = team_model.create(name, category, owner_id, invite_code)

    # 创建者自动加入（role='owner'）
    team_model.add_member(team_id, owner_id, 'owner')

    # 创建邀请码记录（新系统）
    create_invitation(team_id, owner_id)

    # 返回团队信息
    team = team_model.find_by_id(team_id)
    return {
        'id': team['id'],
        'name': team['name'],
        'category': team['category'],
        'inviteCode': team['invite_code'],
        'ownerId': team['owner_id'],
        'memberCount': team['member_count'],
        'poolBalance': team['pool_balance'],
    }


def join_team(user_id, invite_code):
    """
    通过邀请码加入团队

    参数:
        user_id: 用户 ID
        invite_code: 邀请码

    返回:
        dict: 团队信息

    异常:
        AuthError: 邀请码无效 / 已过期 / 已达上限 / 已是成员
    """
    invite_code = (invite_code or '').strip()

    # 优先使用新系统验证
    code_hash = hash_sha256(invite_code)
    invitation = invitation_model.find_by_hash(code_hash)

    team = None
    if invitation:
        # 检查使用次数
        if invitation['usage_count'] >= invitation['max_usage']:
            raise AuthError('邀请码已达到最大使用次数', 3010, 400)
        team_id = invitation['team_id']
        team = team_model.find_by_id(team_id)
    else:
        # 兼容旧系统：通过 teams 表查找
        invite_code_upper = invite_code.upper()
        if len(invite_code_upper) == 6:
            team = team_model.find_by_invite_code(invite_code_upper)

    if not team:
        raise AuthError('邀请码无效或已过期', 3007, 404)

    team_id = team['id']

    # 检查是否已是成员
    existing_member = team_model.find_member(team_id, user_id)
    if existing_member:
        raise AuthError('您已经是该团队成员', 3008, 409)

    # 加入团队
    team_model.add_member(team_id, user_id, 'member')
    team_model.update_member_count(team_id, 1)

    # 记录使用日志（新系统）
    if invitation:
        invitation_model.increment_usage(invitation['id'])
        invitation_model.log_usage(invitation['id'], user_id)

    # 返回最新团队信息
    updated_team = team_model.find_by_id(team_id)
    return _serialize_team(updated_team)


def get_user_teams(user_id):
    """
    获取用户参与的所有团队

    参数:
        user_id: 用户 ID

    返回:
        list: 团队信息列表
    """
    teams = team_model.find_by_user(user_id)
    return [_serialize_team(t) for t in teams]


# ==================== 团队成员管理 ====================

def get_team_members(team_id, user_id):
    """
    获取团队成员列表

    参数:
        team_id: 团队 ID
        user_id: 当前用户 ID（需为团队 member 及以上）

    返回:
        list: 成员信息列表
    """
    # 校验是否为团队 member
    current_member = team_model.find_member(team_id, user_id)
    if not current_member:
        raise AuthError('团队不存在或您不是该团队成员', 3007, 404)

    members = team_model.find_members_by_team(team_id)
    return [
        {
            'id': m['user_id'],
            'email': m.get('email', ''),
            'role': m['role'],
            'joinedAt': m['joined_at'].isoformat() if hasattr(m['joined_at'], 'isoformat') else str(m['joined_at']),
        }
        for m in members
    ]


# ==================== 解散团队 ====================

def dissolve_team(team_id, user_id, ip_address=None):
    """
    解散团队（仅 Owner 可操作）

    流程：
    1. 校验 user 是否为团队 owner
    2. 获取团队信息
    3. 开启事务（单连接）
    4. 如果 pool_balance > 0，将余额转移至 owner 个人钱包
    5. 删除团队（级联删除成员、邀请码等）
    6. 提交事务

    返回:
        dict: { transferredAmount, message }

    异常:
        AuthError(3013): 仅团队创建者可解散团队
        AuthError(3014): 余额转移失败，团队解散已中止
    """
    # 1. 校验权限
    member = team_model.find_member(team_id, user_id)
    if not member or member['role'] != 'owner':
        raise AuthError('仅团队创建者可解散团队', 3013, 403)

    # 2. 获取团队信息
    team = team_model.find_by_id(team_id)
    if not team:
        raise AuthError('团队不存在或已解散', 3007, 404)

    pool_balance = int(team['pool_balance']) if team['pool_balance'] else 0
    owner_id = team['owner_id']
    team_name = team['name']

    # 3. 开启事务
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
            # 锁定团队行，防止并发修改余额
            cursor.execute(
                'SELECT pool_balance FROM teams WHERE id = %s FOR UPDATE',
                (team_id,)
            )

            # 4. 如果有余额，转移到 owner 个人钱包
            transferred = 0
            if pool_balance > 0:
                try:
                    # 清空团队余额
                    cursor.execute(
                        'UPDATE teams SET pool_balance = 0 WHERE id = %s',
                        (team_id,)
                    )
                    # 转移余额到 owner
                    transfer_team_to_owner_in_transaction(
                        cursor, team_id, owner_id, pool_balance, ip_address
                    )
                    transferred = pool_balance
                except Exception as e:
                    conn.rollback()
                    print(f'[dissolve_team] 余额转移失败: team_id={team_id}, '
                          f'amount={pool_balance}, error={e}')
                    traceback.print_exc()
                    raise AuthError('余额转移失败，团队解散已中止', 3014, 500)

            # 5. 删除团队（级联删除关联数据）
            cursor.execute('DELETE FROM teams WHERE id = %s', (team_id,))

            conn.commit()

            if transferred > 0:
                message = f'团队「{team_name}」已解散，{transferred} 灵感币已转入您的个人钱包'
            else:
                message = f'团队「{team_name}」已解散'

            return {
                'transferredAmount': transferred,
                'message': message,
            }

    except AuthError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print(f'[dissolve_team] 解散失败: team_id={team_id}, user_id={user_id}, error={e}')
        traceback.print_exc()
        raise AuthError('团队解散失败，请稍后重试', 3017, 500)
    finally:
        conn.close()