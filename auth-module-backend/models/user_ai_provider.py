"""
用户自备模型服务商（BYOK）数据模型
封装 user_ai_settings（用户级开关）与 user_ai_providers（自备通道号池）两张表的读写操作

通道分类（category）：
    image_gen  生图
    multimodal 多模态视觉
    llm        文本
"""
import pymysql
from config import get_config

# update() 允许更新的字段白名单：入参字段名 -> 数据库列名
# 列名只从本映射取值，值统一用 %s 参数化，避免任何用户输入拼进 SQL
_UPDATABLE_COLUMNS = {
    'name': 'name',
    'api_base': 'api_base',
    'api_key_cipher': 'api_key_cipher',
    'model_name': 'model_name',
    'is_enabled': 'is_enabled',
}

# 失败原因类字段的最大长度（与表结构 VARCHAR(500) 保持一致）
_ERROR_MAX_LENGTH = 500


class UserAiSettingsModel:
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

    def get_or_create(self, user_id):
        """查询用户设置，不存在则插入默认行（use_own_provider=0）后返回，返回 dict"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM user_ai_settings WHERE user_id = %s',
                    (user_id,)
                )
                row = cursor.fetchone()
                if row:
                    return row

                # 无记录则插入默认行
                cursor.execute(
                    '''INSERT INTO user_ai_settings (user_id, use_own_provider)
                       VALUES (%s, 0)''',
                    (user_id,)
                )
                conn.commit()

                cursor.execute(
                    'SELECT * FROM user_ai_settings WHERE user_id = %s',
                    (user_id,)
                )
                return cursor.fetchone()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def set_use_own_provider(self, user_id, enabled):
        """设置「是否优先使用用户自备模型通道」开关，返回最新设置行 dict"""
        # 确保设置行存在
        self.get_or_create(user_id)
        use_own_provider = 1 if enabled else 0

        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE user_ai_settings
                       SET use_own_provider = %s
                       WHERE user_id = %s''',
                    (use_own_provider, user_id)
                )
                conn.commit()

                cursor.execute(
                    'SELECT * FROM user_ai_settings WHERE user_id = %s',
                    (user_id,)
                )
                return cursor.fetchone()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def is_own_provider_enabled(self, user_id):
        """便捷判断用户是否已开启自备模型通道（无记录视为未开启）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT use_own_provider FROM user_ai_settings WHERE user_id = %s',
                    (user_id,)
                )
                row = cursor.fetchone()
                return bool(row['use_own_provider']) if row else False
        finally:
            conn.close()


class UserAiProviderModel:
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

    def list_by_user(self, user_id):
        """查询该用户全部自备通道（含停用），按优先级、ID 升序，返回 dict 列表"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT * FROM user_ai_providers
                       WHERE user_id = %s
                       ORDER BY priority ASC, id ASC''',
                    (user_id,)
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def list_enabled_by_user_category(self, user_id, category):
        """查询该用户某分类下已启用的自备通道（号池候选），按优先级、ID 升序，返回 dict 列表"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT * FROM user_ai_providers
                       WHERE user_id = %s AND category = %s AND is_enabled = 1
                       ORDER BY priority ASC, id ASC''',
                    (user_id, category)
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def list_enabled_by_user(self, user_id):
        """查询该用户全部已启用的自备通道（跨分类一次取回），按优先级、ID 升序，返回 dict 列表"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT * FROM user_ai_providers
                       WHERE user_id = %s AND is_enabled = 1
                       ORDER BY priority ASC, id ASC''',
                    (user_id,)
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def find_by_id(self, provider_id):
        """根据主键查询单条自备通道，不存在返回 None"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM user_ai_providers WHERE id = %s',
                    (provider_id,)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_by_id_and_user(self, provider_id, user_id):
        """根据主键 + 所属用户查询单条（越权防护），不存在返回 None"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT * FROM user_ai_providers WHERE id = %s AND user_id = %s',
                    (provider_id, user_id)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def create(self, user_id, category, name, api_base, api_key_cipher, model_name):
        """新增一条自备通道，priority 取该用户该分类当前 MAX(priority)+1（无记录为 0），返回新记录 dict"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 计算该用户该分类下的下一个优先级（无记录时 COALESCE 得 -1，+1 后为 0）
                cursor.execute(
                    '''SELECT COALESCE(MAX(priority), -1) + 1 AS next_priority
                       FROM user_ai_providers
                       WHERE user_id = %s AND category = %s''',
                    (user_id, category)
                )
                row = cursor.fetchone()
                next_priority = row['next_priority'] if row else 0

                cursor.execute(
                    '''INSERT INTO user_ai_providers
                       (user_id, category, name, api_base, api_key_cipher, model_name, priority, is_enabled)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 1)''',
                    (user_id, category, name, api_base, api_key_cipher, model_name, next_priority)
                )
                new_id = cursor.lastrowid
                conn.commit()

                cursor.execute(
                    'SELECT * FROM user_ai_providers WHERE id = %s AND user_id = %s',
                    (new_id, user_id)
                )
                return cursor.fetchone()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update(self, provider_id, user_id, fields):
        """按白名单更新传入字段（其余忽略），返回更新后的记录；无有效字段或记录不存在返回 None"""
        # 只保留白名单内的字段；列名取自映射，禁止直接使用用户输入的字段名
        payload = {k: v for k, v in (fields or {}).items() if k in _UPDATABLE_COLUMNS}
        if not payload:
            return None

        set_clause = ', '.join(f'{_UPDATABLE_COLUMNS[key]} = %s' for key in payload)
        params = list(payload.values()) + [provider_id, user_id]

        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'UPDATE user_ai_providers SET {set_clause} WHERE id = %s AND user_id = %s',
                    tuple(params)
                )
                conn.commit()

                cursor.execute(
                    'SELECT * FROM user_ai_providers WHERE id = %s AND user_id = %s',
                    (provider_id, user_id)
                )
                return cursor.fetchone()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete(self, provider_id, user_id):
        """删除一条自备通道（限定所属用户），返回是否删除成功"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM user_ai_providers WHERE id = %s AND user_id = %s',
                    (provider_id, user_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def move(self, provider_id, user_id, direction):
        """在同用户同分类内上移/下移：与相邻记录交换 priority；已是第一条/最后一条返回 False"""
        if direction not in ('up', 'down'):
            return False

        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 取出待移动记录（限定所属用户）
                cursor.execute(
                    '''SELECT id, category, priority FROM user_ai_providers
                       WHERE id = %s AND user_id = %s''',
                    (provider_id, user_id)
                )
                current = cursor.fetchone()
                if not current:
                    return False

                # 查找相邻记录：up 取更靠前的一条，down 取更靠后的一条
                if direction == 'up':
                    cursor.execute(
                        '''SELECT id, priority FROM user_ai_providers
                           WHERE user_id = %s AND category = %s AND id <> %s
                           AND (priority < %s OR (priority = %s AND id < %s))
                           ORDER BY priority DESC, id DESC
                           LIMIT 1''',
                        (user_id, current['category'], current['id'],
                         current['priority'], current['priority'], current['id'])
                    )
                else:
                    cursor.execute(
                        '''SELECT id, priority FROM user_ai_providers
                           WHERE user_id = %s AND category = %s AND id <> %s
                           AND (priority > %s OR (priority = %s AND id > %s))
                           ORDER BY priority ASC, id ASC
                           LIMIT 1''',
                        (user_id, current['category'], current['id'],
                         current['priority'], current['priority'], current['id'])
                    )
                neighbor = cursor.fetchone()
                if not neighbor:
                    # 已在边界，无需移动
                    return False

                # 交换两者的 priority
                cursor.execute(
                    'UPDATE user_ai_providers SET priority = %s WHERE id = %s',
                    (neighbor['priority'], current['id'])
                )
                cursor.execute(
                    'UPDATE user_ai_providers SET priority = %s WHERE id = %s',
                    (current['priority'], neighbor['id'])
                )
                conn.commit()
                return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_stats(self, provider_id, ok, error=None):
        """记录一次实际调用结果，无返回值

        失败（ok=False）：failure_count + 1、写入 last_error（截断 500 字符）、刷新 last_used_at
        成功（ok=True） ：刷新 last_used_at、清空 last_error
        """
        error_text = str(error)[:_ERROR_MAX_LENGTH] if error is not None else None

        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if ok:
                    cursor.execute(
                        '''UPDATE user_ai_providers
                           SET last_used_at = NOW(),
                               last_error = NULL
                           WHERE id = %s''',
                        (provider_id,)
                    )
                else:
                    cursor.execute(
                        '''UPDATE user_ai_providers
                           SET failure_count = failure_count + 1,
                               last_error = %s,
                               last_used_at = NOW()
                           WHERE id = %s''',
                        (error_text, provider_id)
                    )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_test_result(self, provider_id, ok, error=None):
        """写入连通性测试结果，返回更新后的记录；记录不存在返回 None"""
        error_text = str(error)[:_ERROR_MAX_LENGTH] if error is not None else None

        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE user_ai_providers
                       SET last_test_ok = %s,
                           last_test_at = NOW(),
                           last_test_error = %s
                       WHERE id = %s''',
                    (1 if ok else 0, error_text, provider_id)
                )
                conn.commit()

                cursor.execute(
                    'SELECT * FROM user_ai_providers WHERE id = %s',
                    (provider_id,)
                )
                return cursor.fetchone()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
