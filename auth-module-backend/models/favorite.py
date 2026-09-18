"""
收藏夹数据模型
封装 favorites 表的 CRUD 操作
支持两类收藏：image（单张图片）和 history（整条历史记录）
"""
import pymysql
import json
from config import get_config


class FavoriteModel:
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

    def find_by_user(self, user_id, page=1, page_size=20):
        """
        分页查询用户的收藏列表（同时包含 image 与 history 两种类型）
        返回 (items, total)，items 中每条已重塑为驼峰命名字段，便于前端使用。
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 查询总数（不分类型）
                cursor.execute(
                    'SELECT COUNT(*) AS total FROM favorites WHERE user_id = %s',
                    (user_id,)
                )
                result = cursor.fetchone()
                total = result['total'] if result else 0

                # 分页查询：LEFT JOIN history_records 与 users 取出 history 类型的展示字段
                offset = (page - 1) * page_size
                cursor.execute(
                    '''SELECT f.id, f.user_id, f.target_type, f.image_url, f.batch_id, f.config, f.created_at,
                              f.history_record_id, f.source_user_id,
                              h.title AS history_title, h.thumbnail_url AS history_thumbnail,
                              h.category AS history_category, h.sub_category AS history_sub_category,
                              u.email AS source_user_name
                       FROM favorites f
                       LEFT JOIN history_records h ON f.target_type = 'history' AND f.history_record_id = h.id
                       LEFT JOIN users u ON f.source_user_id = u.id
                       WHERE f.user_id = %s
                       ORDER BY f.created_at DESC
                       LIMIT %s OFFSET %s''',
                    (user_id, page_size, offset)
                )
                rows = cursor.fetchall()

            # 字段重塑为驼峰命名，并反序列化 config
            items = []
            for row in rows:
                # 反序列化 config
                config_value = row.get('config')
                if config_value is not None and isinstance(config_value, str):
                    try:
                        config_value = json.loads(config_value)
                    except (json.JSONDecodeError, TypeError):
                        config_value = None

                item = {
                    'id': row.get('id'),
                    'userId': row.get('user_id'),
                    'targetType': row.get('target_type'),
                    'imageUrl': row.get('image_url'),
                    'batchId': row.get('batch_id'),
                    'config': config_value,
                    'createdAt': row.get('created_at'),
                }

                # history 类型额外补充历史记录展示字段
                if row.get('target_type') == 'history':
                    item['historyRecordId'] = row.get('history_record_id')
                    item['sourceUserId'] = row.get('source_user_id')
                    item['title'] = row.get('history_title')
                    item['thumbnailUrl'] = row.get('history_thumbnail')
                    item['category'] = row.get('history_category')
                    item['subCategory'] = row.get('history_sub_category')
                    item['sourceUserName'] = row.get('source_user_name')

                items.append(item)

            return items, total
        finally:
            conn.close()

    def create(self, user_id, image_url, batch_id=None, config=None,
               target_type='image', history_record_id=None, source_user_id=None):
        """
        添加收藏
        参数:
            user_id: 用户ID
            image_url: 图片URL（image 类型必填；history 类型可传缩略图URL）
            batch_id: 批次ID（可选）
            config: 生成配置快照（可选）
            target_type: 收藏类型 'image' | 'history'（默认 'image'）
            history_record_id: 历史记录ID（仅 history 类型使用）
            source_user_id: 原始所有者用户ID（仅 history 类型，团队分享场景使用）
        返回:
            新创建的收藏记录ID；若已存在相同收藏则返回 None
        """
        conn = self._get_connection()
        try:
            # 去重检查：image 类型按 (user_id, image_url)，history 类型按 (user_id, history_record_id)
            with conn.cursor() as cursor:
                if target_type == 'history':
                    cursor.execute(
                        "SELECT id FROM favorites WHERE user_id = %s AND target_type = 'history' AND history_record_id = %s",
                        (user_id, history_record_id)
                    )
                else:
                    cursor.execute(
                        "SELECT id FROM favorites WHERE user_id = %s AND image_url = %s AND target_type = 'image'",
                        (user_id, image_url)
                    )
                if cursor.fetchone():
                    return None  # 已存在

            # 序列化 config
            config_json = None
            if config is not None:
                config_json = json.dumps(config, ensure_ascii=False)

            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO favorites
                       (user_id, target_type, image_url, batch_id, config, history_record_id, source_user_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (user_id, target_type, image_url, batch_id, config_json,
                     history_record_id, source_user_id)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    def delete_by_id(self, favorite_id, user_id):
        """
        删除收藏（校验所有权）
        返回是否删除成功
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM favorites WHERE id = %s AND user_id = %s',
                    (favorite_id, user_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()
