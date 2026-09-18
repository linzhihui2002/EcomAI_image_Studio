"""
历史记录数据模型
封装 history_records 表的 CRUD 操作
"""
import pymysql
import json
from config import get_config


class HistoryRecordModel:
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

    def _deserialize_json_fields(self, item):
        """将 JSON 字符串字段反序列化为 Python 对象"""
        json_fields = ['input_data', 'output_data', 'config_snapshot']
        for field in json_fields:
            if item.get(field) and isinstance(item[field], str):
                try:
                    item[field] = json.loads(item[field])
                except (json.JSONDecodeError, TypeError):
                    item[field] = None
        return item

    def create(self, user_id, category, sub_category, title, thumbnail_url,
               input_data, output_data, config_snapshot=None):
        """
        创建历史记录
        返回新创建的记录ID
        """
        conn = self._get_connection()
        try:
            input_json = json.dumps(input_data, ensure_ascii=False)
            output_json = json.dumps(output_data, ensure_ascii=False)
            config_json = None
            if config_snapshot is not None:
                config_json = json.dumps(config_snapshot, ensure_ascii=False)

            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO history_records
                       (user_id, category, sub_category, title, thumbnail_url,
                        input_data, output_data, config_snapshot)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                    (user_id, category, sub_category, title, thumbnail_url,
                     input_json, output_json, config_json)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def find_by_user(self, user_id, category=None, sub_category=None,
                     page=1, page_size=20):
        """
        分页查询用户的历史记录
        支持按 category 和 sub_category 过滤
        返回 (items, total)
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 构建动态 WHERE 条件
                conditions = ['user_id = %s']
                params = [user_id]

                if category is not None:
                    conditions.append('category = %s')
                    params.append(category)

                if sub_category is not None:
                    conditions.append('sub_category = %s')
                    params.append(sub_category)

                where_clause = ' AND '.join(conditions)

                # 查询总数
                cursor.execute(
                    f'SELECT COUNT(*) AS total FROM history_records WHERE {where_clause}',
                    params
                )
                result = cursor.fetchone()
                total = result['total'] if result else 0

                # 分页查询（列表不取 input_data/output_data/config_snapshot 大字段，
                # 避免 ORDER BY 时 sort buffer 溢出；详情用 find_by_id 获取完整数据）
                offset = (page - 1) * page_size
                cursor.execute(
                    f'''SELECT id, user_id, category, sub_category, title, thumbnail_url,
                               shared_to_team, shared_team_id, shared_at, created_at
                        FROM history_records
                        WHERE {where_clause}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s''',
                    params + [page_size, offset]
                )
                items = cursor.fetchall()

            # 将 JSON 字符串字段反序列化
            for item in items:
                self._deserialize_json_fields(item)

            return items, total
        finally:
            conn.close()

    def find_by_id(self, record_id, user_id):
        """
        根据ID查询单条历史记录（校验所有权）
        返回记录 dict 或 None
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT id, user_id, category, sub_category, title, thumbnail_url,
                               input_data, output_data, config_snapshot,
                               shared_to_team, shared_team_id, shared_at, created_at
                       FROM history_records
                       WHERE id = %s AND user_id = %s''',
                    (record_id, user_id)
                )
                item = cursor.fetchone()

            if item:
                self._deserialize_json_fields(item)

            return item
        finally:
            conn.close()

    def find_by_id_accessible(self, record_id, user_id, user_team_ids=None):
        """
        根据 ID 查询历史记录，校验访问权限（所有者 或 团队分享可见）
        参数:
            record_id: 记录ID
            user_id: 当前用户ID
            user_team_ids: 当前用户所属团队ID列表（可选，若为 None 则仅校验所有权）
        返回:
            记录 dict 或 None
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT id, user_id, category, sub_category, title, thumbnail_url,
                               input_data, output_data, config_snapshot,
                               shared_to_team, shared_team_id, shared_at, created_at
                       FROM history_records
                       WHERE id = %s''',
                    (record_id,)
                )
                item = cursor.fetchone()

            if not item:
                return None

            # 所有者直接返回
            if item['user_id'] == user_id:
                return self._deserialize_json_fields(item)

            # 团队分享可见
            if (item.get('shared_to_team') == 1
                    and item.get('shared_team_id') is not None
                    and user_team_ids is not None
                    and item['shared_team_id'] in user_team_ids):
                return self._deserialize_json_fields(item)

            return None
        finally:
            conn.close()

    def find_latest_by_batch_id(self, user_id, batch_id):
        """
        根据批次ID查询用户最新的历史记录（用于重试成功后回写结果）
        返回记录 dict（含 output_data）或 None
        """
        if not batch_id:
            return None
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT id, user_id, sub_category, thumbnail_url, output_data
                       FROM history_records
                       WHERE user_id = %s
                         AND JSON_UNQUOTE(JSON_EXTRACT(output_data, '$.batch_id')) = %s
                       ORDER BY created_at DESC
                       LIMIT 1''',
                    (user_id, batch_id)
                )
                item = cursor.fetchone()

            if item:
                self._deserialize_json_fields(item)

            return item
        finally:
            conn.close()

    def update_output_data(self, record_id, output_data, thumbnail_url=None):
        """
        更新历史记录的 output_data（可选同时更新缩略图）
        返回是否更新成功
        """
        conn = self._get_connection()
        try:
            output_json = json.dumps(output_data, ensure_ascii=False)
            with conn.cursor() as cursor:
                if thumbnail_url is None:
                    cursor.execute(
                        'UPDATE history_records SET output_data = %s WHERE id = %s',
                        (output_json, record_id)
                    )
                else:
                    cursor.execute(
                        '''UPDATE history_records
                           SET output_data = %s, thumbnail_url = %s
                           WHERE id = %s''',
                        (output_json, thumbnail_url, record_id)
                    )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_by_id(self, record_id, user_id):
        """
        删除历史记录（校验所有权）
        返回是否删除成功
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM history_records WHERE id = %s AND user_id = %s',
                    (record_id, user_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def share_to_team(self, record_id, user_id, team_id):
        """
        将历史记录分享到团队
        返回是否更新成功
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE history_records
                       SET shared_to_team = 1, shared_team_id = %s, shared_at = NOW()
                       WHERE id = %s AND user_id = %s''',
                    (team_id, record_id, user_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def unshare(self, record_id, user_id):
        """
        取消团队分享
        返回是否更新成功
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE history_records
                       SET shared_to_team = 0, shared_team_id = NULL, shared_at = NULL
                       WHERE id = %s AND user_id = %s''',
                    (record_id, user_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def find_by_team(self, team_id, page=1, page_size=20):
        """
        分页查询团队分享的历史记录
        返回 (items, total)
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 查询总数
                cursor.execute(
                    '''SELECT COUNT(*) AS total FROM history_records
                       WHERE shared_to_team = 1 AND shared_team_id = %s''',
                    (team_id,)
                )
                result = cursor.fetchone()
                total = result['total'] if result else 0

                # 分页查询（列表不取大字段，避免 sort buffer 溢出）
                offset = (page - 1) * page_size
                cursor.execute(
                    '''SELECT id, user_id, category, sub_category, title, thumbnail_url,
                               shared_to_team, shared_team_id, shared_at, created_at
                       FROM history_records
                       WHERE shared_to_team = 1 AND shared_team_id = %s
                       ORDER BY created_at DESC
                       LIMIT %s OFFSET %s''',
                    (team_id, page_size, offset)
                )
                items = cursor.fetchall()

            # 将 JSON 字符串字段反序列化
            for item in items:
                self._deserialize_json_fields(item)

            return items, total
        finally:
            conn.close()