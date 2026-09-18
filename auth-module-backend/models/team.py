"""
团队数据模型
封装 teams 和 team_members 表的 CRUD 操作，用于团队创建、加入、查询和成员管理
"""
import pymysql
from config import get_config


class TeamModel:
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

    def find_all(self):
        """查询所有团队"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM teams ORDER BY id ASC')
                return cursor.fetchall()
        finally:
            conn.close()

    def find_by_id(self, team_id):
        """根据 ID 查询团队"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM teams WHERE id = %s', (team_id,))
                return cursor.fetchone()
        finally:
            conn.close()

    def find_by_name(self, name):
        """根据名称查询团队（用于重复检查）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT id FROM teams WHERE name = %s', (name,))
                return cursor.fetchone()
        finally:
            conn.close()

    def find_by_invite_code(self, invite_code):
        """根据邀请码查询团队"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM teams WHERE invite_code = %s', (invite_code,))
                return cursor.fetchone()
        finally:
            conn.close()

    def find_by_owner(self, owner_id):
        """查询用户拥有的团队"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM teams WHERE owner_id = %s ORDER BY id ASC', (owner_id,))
                return cursor.fetchall()
        finally:
            conn.close()

    def find_by_user(self, user_id):
        """查询用户参与的所有团队（含 owner 和 member 身份）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT t.*, tm.role AS member_role
                       FROM teams t
                       INNER JOIN team_members tm ON tm.team_id = t.id
                       WHERE tm.user_id = %s
                       ORDER BY t.id ASC''',
                    (user_id,)
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def create(self, name, category, owner_id, invite_code):
        """创建团队，返回 team_id"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO teams (name, category, owner_id, invite_code) VALUES (%s, %s, %s, %s)',
                    (name, category, owner_id, invite_code)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def update_member_count(self, team_id, delta):
        """原子更新成员计数"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE teams SET member_count = member_count + %s WHERE id = %s AND member_count + %s >= 0',
                    (delta, team_id, delta)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    # ==================== team_members 表操作 ====================

    def add_member(self, team_id, user_id, role='member'):
        """添加团队成员"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO team_members (team_id, user_id, role) VALUES (%s, %s, %s)',
                    (team_id, user_id, role)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def remove_member(self, team_id, user_id):
        """移除团队成员"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM team_members WHERE team_id = %s AND user_id = %s',
                    (team_id, user_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def find_member(self, team_id, user_id):
        """查询团队成员记录"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM team_members WHERE team_id = %s AND user_id = %s',
                    (team_id, user_id)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_members_by_team(self, team_id):
        """查询团队所有成员"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT tm.*, u.email
                       FROM team_members tm
                       INNER JOIN users u ON u.id = tm.user_id
                       WHERE tm.team_id = %s
                       ORDER BY tm.joined_at ASC''',
                    (team_id,)
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def delete_team(self, team_id):
        """
        删除团队（依赖外键级联删除 team_members、team_invitations 等关联数据）

        返回:
            bool: 是否删除成功
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM teams WHERE id = %s', (team_id,))
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def update_pool_balance(self, team_id, new_balance):
        """
        更新团队钱包余额

        返回:
            bool: 是否更新成功
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE teams SET pool_balance = %s WHERE id = %s',
                    (new_balance, team_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()