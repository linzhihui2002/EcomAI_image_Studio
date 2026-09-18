"""
公告数据模型
封装 announcements 表的 CRUD 操作
"""
import pymysql
from config import get_config


class AnnouncementModel:
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
        """查询所有公告（管理员视图），按创建时间倒序"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM announcements ORDER BY created_at DESC'
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def find_public(self):
        """查询公开公告（is_active=1 且未过期或无过期时间），置顶优先，按时间倒序"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT * FROM announcements
                       WHERE is_active = 1
                       AND (expires_at IS NULL OR expires_at > NOW())
                       ORDER BY is_pinned DESC, created_at DESC'''
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def find_by_id(self, ann_id):
        """根据 ID 查询单条公告"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM announcements WHERE id = %s',
                    (ann_id,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def create(self, title, content, ann_type, is_pinned, created_by, expires_at):
        """创建公告"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO announcements (title, content, type, is_pinned, is_active, created_by, expires_at)
                       VALUES (%s, %s, %s, %s, 1, %s, %s)''',
                    (title, content, ann_type, is_pinned, created_by, expires_at)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def update(self, ann_id, title, content, ann_type, is_pinned, expires_at):
        """更新公告"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE announcements
                       SET title = %s, content = %s, type = %s, is_pinned = %s, expires_at = %s
                       WHERE id = %s''',
                    (title, content, ann_type, is_pinned, expires_at, ann_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def delete(self, ann_id):
        """删除公告"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM announcements WHERE id = %s',
                    (ann_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def toggle_active(self, ann_id):
        """切换公告启用/停用状态"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE announcements SET is_active = NOT is_active WHERE id = %s',
                    (ann_id,)
                )
                conn.commit()
                # 获取更新后的状态
                cursor.execute(
                    'SELECT is_active FROM announcements WHERE id = %s',
                    (ann_id,)
                )
                result = cursor.fetchone()
                return result['is_active'] if result else None
        finally:
            conn.close()