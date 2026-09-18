"""
功能定价数据模型
封装 feature_pricing 表的 CRUD 操作
"""
import json
import pymysql
from config import get_config


class FeaturePricingModel:
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

    def _format_row(self, row):
        """格式化单行数据：解析 config JSON 字符串为 dict、格式化时间字段为 isoformat"""
        if not row:
            return row
        # 解析 config（pymysql 默认把 JSON 列作为字符串返回）
        config_val = row.get('config')
        if isinstance(config_val, str):
            try:
                row['config'] = json.loads(config_val)
            except (ValueError, TypeError):
                # 解析失败保留原值
                pass
        # 格式化时间字段
        for field in ('created_at', 'updated_at'):
            val = row.get(field)
            if val is not None and hasattr(val, 'isoformat'):
                row[field] = val.isoformat()
        return row

    def _format_rows(self, rows):
        """格式化多行数据"""
        if not rows:
            return rows
        return [self._format_row(r) for r in rows]

    def find_all(self, active_only=False):
        """查询所有功能定价，按 category、sort_order 升序排列"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if active_only:
                    cursor.execute(
                        'SELECT * FROM feature_pricing WHERE is_active = 1 '
                        'ORDER BY category ASC, sort_order ASC'
                    )
                else:
                    cursor.execute(
                        'SELECT * FROM feature_pricing '
                        'ORDER BY category ASC, sort_order ASC'
                    )
                return self._format_rows(cursor.fetchall())
        finally:
            conn.close()

    def find_active(self, category=None):
        """查询启用的功能定价，可选 category 过滤"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if category:
                    cursor.execute(
                        'SELECT * FROM feature_pricing '
                        'WHERE is_active = 1 AND category = %s '
                        'ORDER BY sort_order ASC',
                        (category,)
                    )
                else:
                    cursor.execute(
                        'SELECT * FROM feature_pricing WHERE is_active = 1 '
                        'ORDER BY category ASC, sort_order ASC'
                    )
                return self._format_rows(cursor.fetchall())
        finally:
            conn.close()

    def find_by_id(self, pricing_id):
        """根据 ID 查询单条功能定价"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM feature_pricing WHERE id = %s',
                    (pricing_id,)
                )
                return self._format_row(cursor.fetchone())
        finally:
            conn.close()

    def find_by_key(self, feature_key, active_only=False):
        """根据 feature_key 查询单条功能定价"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if active_only:
                    cursor.execute(
                        'SELECT * FROM feature_pricing '
                        'WHERE feature_key = %s AND is_active = 1',
                        (feature_key,)
                    )
                else:
                    cursor.execute(
                        'SELECT * FROM feature_pricing WHERE feature_key = %s',
                        (feature_key,)
                    )
                return self._format_row(cursor.fetchone())
        finally:
            conn.close()

    def create(self, feature_key, display_name, category, pricing_type, config, description=None):
        """
        创建功能定价
        config 可为 dict（自动 json.dumps）或 JSON 字符串
        返回新记录 id
        """
        if isinstance(config, dict):
            config = json.dumps(config, ensure_ascii=False)
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 获取下一个 sort_order
                cursor.execute(
                    'SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM feature_pricing'
                )
                next_order = cursor.fetchone()['next_order']
                cursor.execute(
                    '''INSERT INTO feature_pricing
                       (feature_key, display_name, category, pricing_type, config, description, sort_order)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (feature_key, display_name, category, pricing_type, config, description, next_order)
                )
                conn.commit()
                return cursor.lastrowid
        except pymysql.err.IntegrityError:
            raise ValueError(f'feature_key "{feature_key}" 已存在，请勿重复创建')
        finally:
            conn.close()

    def update(self, pricing_id, display_name, category, pricing_type, config, description=None):
        """
        更新功能定价
        config 可为 dict（自动 json.dumps）或 JSON 字符串
        返回是否更新成功
        """
        if isinstance(config, dict):
            config = json.dumps(config, ensure_ascii=False)
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE feature_pricing
                       SET display_name = %s, category = %s, pricing_type = %s,
                           config = %s, description = %s
                       WHERE id = %s''',
                    (display_name, category, pricing_type, config, description, pricing_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def delete(self, pricing_id):
        """删除功能定价"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM feature_pricing WHERE id = %s',
                    (pricing_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def toggle_active(self, pricing_id):
        """切换功能定价启用/禁用状态，返回新的 is_active（bool）或 None（记录不存在）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE feature_pricing SET is_active = NOT is_active WHERE id = %s',
                    (pricing_id,)
                )
                conn.commit()
                cursor.execute(
                    'SELECT is_active FROM feature_pricing WHERE id = %s',
                    (pricing_id,)
                )
                result = cursor.fetchone()
                return bool(result['is_active']) if result else None
        finally:
            conn.close()
