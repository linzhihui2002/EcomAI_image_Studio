"""
编辑器任务数据模型
封装 editor_task 表的 CRUD（PyMySQL 直连，风格与 HistoryRecordModel 一致）
"""
import json
import pymysql
from config import get_config


class EditorTaskModel:
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

    @staticmethod
    def _deserialize_params(item):
        """将 params JSON 字符串反序列化为 Python 对象"""
        if item is None:
            return item
        params = item.get('params')
        if isinstance(params, str):
            try:
                item['params'] = json.loads(params)
            except (json.JSONDecodeError, TypeError):
                item['params'] = None
        return item

    def create(self, task_id, user_id, tool, params, status='queued'):
        """插入任务记录，返回新记录 ID"""
        conn = self._get_connection()
        try:
            params_json = json.dumps(params, ensure_ascii=False) if params is not None else None
            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO editor_task
                       (task_id, user_id, tool, params, status)
                       VALUES (%s, %s, %s, %s, %s)''',
                    (task_id, user_id, tool, params_json, status)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def find_by_task_id(self, task_id):
        """按 task_id 查询任务记录，返回 dict 或 None"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM editor_task WHERE task_id = %s', (task_id,))
                item = cursor.fetchone()
            return self._deserialize_params(item)
        finally:
            conn.close()

    def update_result(self, task_id, status, result_url=None, error=None):
        """回写任务执行结果（worker 完成时尽力调用），返回是否更新成功"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE editor_task
                       SET status = %s, result_url = %s, error = %s
                       WHERE task_id = %s''',
                    (status, result_url, error, task_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()
