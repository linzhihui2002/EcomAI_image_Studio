"""
生图计划分析数据模型
封装 plan_analysis_tasks 和 plan_analysis_files 表的 CRUD 操作
"""
import pymysql
from config import get_config


class PlanAnalysisTaskModel:
    def __init__(self):
        self.config = get_config()

    def _get_connection(self):
        return pymysql.connect(
            host=self.config.MYSQL_HOST,
            port=self.config.MYSQL_PORT,
            user=self.config.MYSQL_USER,
            password=self.config.MYSQL_PASSWORD,
            database=self.config.MYSQL_DATABASE,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

    def create(self, user_id, input_hash, status='pending'):
        """创建分析任务，返回 task_id"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                sql = (
                    "INSERT INTO plan_analysis_tasks "
                    "(user_id, status, input_hash, result_json, error_message, created_at, updated_at) "
                    "VALUES (%s, %s, %s, NULL, NULL, NOW(), NOW())"
                )
                cursor.execute(sql, (user_id, status, input_hash))
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def update_status(self, task_id, status, result_json=None, error_message=None):
        """更新任务状态和结果"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if result_json is not None:
                    sql = (
                        "UPDATE plan_analysis_tasks SET status=%s, result_json=%s, "
                        "error_message=%s, updated_at=NOW() WHERE id=%s"
                    )
                    cursor.execute(sql, (status, result_json, error_message, task_id))
                else:
                    sql = (
                        "UPDATE plan_analysis_tasks SET status=%s, error_message=%s, "
                        "updated_at=NOW() WHERE id=%s"
                    )
                    cursor.execute(sql, (status, error_message, task_id))
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def find_by_id(self, task_id):
        """根据 ID 查询任务"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM plan_analysis_tasks WHERE id=%s",
                    (task_id,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_by_hash(self, input_hash, ttl_seconds=3600):
        """
        根据输入哈希查询缓存任务（completed 且未过期）
        返回最近一条匹配的任务
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                sql = (
                    "SELECT * FROM plan_analysis_tasks "
                    "WHERE input_hash=%s AND status='completed' "
                    "AND updated_at > DATE_SUB(NOW(), INTERVAL %s SECOND) "
                    "ORDER BY updated_at DESC LIMIT 1"
                )
                cursor.execute(sql, (input_hash, ttl_seconds))
                return cursor.fetchone()
        finally:
            conn.close()

    def find_pending(self):
        """获取最早的 pending 任务（FIFO）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM plan_analysis_tasks WHERE status='pending' "
                    "ORDER BY created_at ASC LIMIT 1"
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_by_user(self, user_id, page=1, page_size=10):
        """分页查询用户的任务列表，返回 (list, total)"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                count_sql = (
                    "SELECT COUNT(*) AS total FROM plan_analysis_tasks WHERE user_id=%s"
                )
                cursor.execute(count_sql, (user_id,))
                total = cursor.fetchone()['total']

                offset = (page - 1) * page_size
                sql = (
                    "SELECT id, status, input_hash, result_json, error_message, "
                    "created_at, updated_at FROM plan_analysis_tasks "
                    "WHERE user_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s"
                )
                cursor.execute(sql, (user_id, page_size, offset))
                return cursor.fetchall(), total
        finally:
            conn.close()

    def delete_by_id(self, task_id, user_id):
        """删除指定任务（用户只能删除自己的）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM plan_analysis_tasks WHERE id=%s AND user_id=%s",
                    (task_id, user_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()


class PlanAnalysisFileModel:
    def __init__(self):
        self.config = get_config()

    def _get_connection(self):
        return pymysql.connect(
            host=self.config.MYSQL_HOST,
            port=self.config.MYSQL_PORT,
            user=self.config.MYSQL_USER,
            password=self.config.MYSQL_PASSWORD,
            database=self.config.MYSQL_DATABASE,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

    def create(self, task_id, file_name, file_size, file_type, storage_path):
        """创建文件记录"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                sql = (
                    "INSERT INTO plan_analysis_files "
                    "(task_id, file_name, file_size, file_type, storage_path, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, NOW())"
                )
                cursor.execute(sql, (task_id, file_name, file_size, file_type, storage_path))
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def find_by_task(self, task_id):
        """查询任务关联的文件"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM plan_analysis_files WHERE task_id=%s ORDER BY created_at ASC",
                    (task_id,)
                )
                return cursor.fetchall()
        finally:
            conn.close()