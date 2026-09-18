"""
编辑器文档数据模型
封装 editor_document 表的 CRUD（PyMySQL 直连，风格与 HistoryRecordModel 一致）
"""
import json
import pymysql
from pymysql.constants import CLIENT
from config import get_config


class EditorDocumentModel:
    def __init__(self):
        self.config = get_config()

    def _get_connection(self):
        """获取数据库连接（FOUND_ROWS：内容未变化的 UPDATE 也返回匹配行数，
        避免"重复自动保存"被 rowcount=0 误判为文档不存在）"""
        return pymysql.connect(
            host=self.config.MYSQL_HOST,
            port=self.config.MYSQL_PORT,
            user=self.config.MYSQL_USER,
            password=self.config.MYSQL_PASSWORD,
            database=self.config.MYSQL_DATABASE,
            charset='utf8mb4',
            client_flag=CLIENT.FOUND_ROWS,
            cursorclass=pymysql.cursors.DictCursor
        )

    @staticmethod
    def _deserialize_layers(item):
        """将 layers JSON 字符串反序列化为 Python 对象"""
        if item is None:
            return item
        layers = item.get('layers')
        if isinstance(layers, str):
            try:
                item['layers'] = json.loads(layers)
            except (json.JSONDecodeError, TypeError):
                item['layers'] = []
        return item

    def create(self, user_id, source_image_id, title, layers):
        """创建编辑文档，返回新文档 ID"""
        conn = self._get_connection()
        try:
            layers_json = json.dumps(layers, ensure_ascii=False)
            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO editor_document
                       (user_id, source_image_id, title, layers)
                       VALUES (%s, %s, %s, %s)''',
                    (user_id, source_image_id, title, layers_json)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def find_by_id(self, document_id, user_id):
        """按 ID 查询文档（校验归属），返回文档 dict 或 None"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM editor_document WHERE id = %s AND user_id = %s',
                    (document_id, user_id)
                )
                item = cursor.fetchone()
            return self._deserialize_layers(item)
        finally:
            conn.close()

    def update(self, document_id, user_id, title=None, layers=None):
        """更新文档（title / layers 至少提供一个），返回是否更新成功"""
        sets, params = [], []
        if title is not None:
            sets.append('title = %s')
            params.append(title)
        if layers is not None:
            sets.append('layers = %s')
            params.append(json.dumps(layers, ensure_ascii=False))
        if not sets:
            return False
        params.extend([document_id, user_id])
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE editor_document SET {', '.join(sets)} WHERE id = %s AND user_id = %s",
                    params
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def list_by_user(self, user_id):
        """当前用户的文档列表（不含 layers 大字段，按 updated_at 倒序）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT id, user_id, source_image_id, title, created_at, updated_at
                       FROM editor_document
                       WHERE user_id = %s
                       ORDER BY updated_at DESC, id DESC''',
                    (user_id,)
                )
                return cursor.fetchall()
        finally:
            conn.close()
