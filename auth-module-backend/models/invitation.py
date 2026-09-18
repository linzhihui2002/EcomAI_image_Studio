"""
邀请码数据模型
封装 team_invitations 和 team_invitation_usage_logs 表的 CRUD 操作
"""
import pymysql
from config import get_config


class InvitationModel:
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

    def create(self, team_id, code_hash, code_encrypted, created_by, expires_at, max_usage):
        """创建邀请码记录，返回邀请码 id"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO team_invitations
                       (team_id, invite_code_hash, invite_code_encrypted, created_by, expires_at, max_usage)
                       VALUES (%s, %s, %s, %s, %s, %s)''',
                    (team_id, code_hash, code_encrypted, created_by, expires_at, max_usage)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def find_by_hash(self, code_hash):
        """
        根据哈希查找有效邀请码
        条件：is_active=TRUE 且未过期
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT ti.*, t.name AS team_name, t.category AS team_category
                       FROM team_invitations ti
                       INNER JOIN teams t ON t.id = ti.team_id
                       WHERE ti.invite_code_hash = %s
                         AND ti.is_active = TRUE
                         AND ti.expires_at > NOW()
                       LIMIT 1''',
                    (code_hash,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_active_by_team(self, team_id):
        """查找团队当前有效的邀请码"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT * FROM team_invitations
                       WHERE team_id = %s
                         AND is_active = TRUE
                         AND expires_at > NOW()
                       ORDER BY created_at DESC
                       LIMIT 1''',
                    (team_id,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def deactivate(self, team_id):
        """失效团队所有有效邀请码"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE team_invitations SET is_active = FALSE WHERE team_id = %s AND is_active = TRUE',
                    (team_id,)
                )
                conn.commit()
                return cursor.rowcount
        finally:
            conn.close()

    def increment_usage(self, invitation_id):
        """
        原子递增使用次数
        仅在 usage_count < max_usage 时执行，返回是否成功
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE team_invitations
                       SET usage_count = usage_count + 1
                       WHERE id = %s AND usage_count < max_usage AND is_active = TRUE''',
                    (invitation_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def log_usage(self, invitation_id, user_id):
        """记录邀请码使用日志"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO team_invitation_usage_logs (invitation_id, used_by) VALUES (%s, %s)',
                    (invitation_id, user_id)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()