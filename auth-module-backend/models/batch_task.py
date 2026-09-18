"""批量套图编排任务数据模型（P1-1）

batch_task / batch_task_item 表 CRUD（pymysql 裸 SQL，风格与 models/compliance.py 一致）。

子任务状态机（非法跳转拒绝，抛 InvalidItemTransition，为 ValueError 子类）：
    planned → running → completed | failed
    failed  → running（断点续跑 / 重试）
    completed 为终态；planned 不允许直接跳 completed / failed。

item_key 幂等键（表级 UNIQUE，格式 product_site_imagetype）：
create_batch_task 批量插入使用 INSERT IGNORE —— 重复提交同商品/同站点/同图型时
第二次插入被静默忽略，并以实际落库行数回填 total_items，
保证"重复提交不重复计费"（预扣/退款对账口径见 services/batch_orchestrator.py 模块注释）。
"""
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pymysql

from config import get_config


# 子任务合法状态与状态机（current -> 允许的 next 集合）
ITEM_STATUSES = ('planned', 'running', 'completed', 'failed')
ITEM_TRANSITIONS: Dict[str, set] = {
    'planned': {'running'},
    'running': {'completed', 'failed'},
    'failed': {'running'},   # 断点续跑 / 重试
    'completed': set(),      # 终态
}

# 批次状态机（migration 注释：pending/running/completed/failed/partial）
BATCH_STATUSES = ('pending', 'running', 'completed', 'failed', 'partial')


class InvalidItemTransition(ValueError):
    """非法子任务状态跳转（ValueError 子类，便于上层按同一类异常处理）"""


def validate_transition(current: str, new_status: str) -> bool:
    """纯函数：判断子任务状态跳转是否合法（无 DB 副作用，供测试与校验复用）"""
    return new_status in ITEM_TRANSITIONS.get(current, set())


@dataclass
class BatchTask:
    """批量套图批次"""
    id: Optional[int]
    task_id: str
    user_id: int
    status: str = 'pending'
    total_items: int = 0
    succeeded_items: int = 0
    failed_items: int = 0
    feature_key: Optional[str] = None
    coins_locked: int = 0
    platform: Optional[str] = None
    params: Optional[dict] = None
    created_at: Any = None
    updated_at: Any = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "status": self.status,
            "total_items": self.total_items,
            "succeeded_items": self.succeeded_items,
            "failed_items": self.failed_items,
            "feature_key": self.feature_key,
            "coins_locked": self.coins_locked,
            "platform": self.platform,
            "params": self.params,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class BatchTaskItem:
    """批量套图子任务"""
    id: Optional[int]
    batch_task_id: int
    item_key: str
    product_id: Optional[str] = None
    site: Optional[str] = None
    image_type: Optional[str] = None
    size: Optional[str] = None
    prompt: Optional[str] = None
    status: str = 'planned'
    error: Optional[str] = None
    result_url: Optional[str] = None
    review: Optional[dict] = None
    coins: int = 0
    created_at: Any = None
    updated_at: Any = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "batch_task_id": self.batch_task_id,
            "item_key": self.item_key,
            "product_id": self.product_id,
            "site": self.site,
            "image_type": self.image_type,
            "size": self.size,
            "prompt": self.prompt,
            "status": self.status,
            "error": self.error,
            "result_url": self.result_url,
            "review": self.review,
            # coins=0 且 status=failed 表示该项费用已退款（对账口径见 orchestrator 注释）
            "coins": self.coins,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _parse_json(value) -> Optional[dict]:
    """pymysql 默认把 JSON 列作为字符串返回，统一解析"""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None
    return None


class BatchTaskModel:
    """batch_task / batch_task_item 表 CRUD（pymysql 裸 SQL）"""

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
            cursorclass=pymysql.cursors.DictCursor,
        )

    @staticmethod
    def _to_batch(row: dict) -> BatchTask:
        return BatchTask(
            id=row.get('id'),
            task_id=row.get('task_id', ''),
            user_id=row.get('user_id'),
            status=row.get('status', 'pending'),
            total_items=int(row.get('total_items') or 0),
            succeeded_items=int(row.get('succeeded_items') or 0),
            failed_items=int(row.get('failed_items') or 0),
            feature_key=row.get('feature_key'),
            coins_locked=int(row.get('coins_locked') or 0),
            platform=row.get('platform'),
            params=_parse_json(row.get('params')),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at'),
        )

    @staticmethod
    def _to_item(row: dict) -> BatchTaskItem:
        return BatchTaskItem(
            id=row.get('id'),
            batch_task_id=row.get('batch_task_id'),
            item_key=row.get('item_key', ''),
            product_id=row.get('product_id'),
            site=row.get('site'),
            image_type=row.get('image_type'),
            size=row.get('size'),
            prompt=row.get('prompt'),
            status=row.get('status', 'planned'),
            error=row.get('error'),
            result_url=row.get('result_url'),
            review=_parse_json(row.get('review')),
            coins=int(row.get('coins') or 0),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at'),
        )

    # ── 批次 ──

    def create_batch_task(self, task_id: str, user_id: int, items: Optional[List[dict]] = None,
                          feature_key: Optional[str] = None, coins_locked: int = 0,
                          platform: Optional[str] = None, params: Optional[dict] = None,
                          status: str = 'pending') -> BatchTask:
        """创建批次头 + 批量插入子任务（INSERT IGNORE 幂等去重）

        items 元素字段：item_key / product_id / site / image_type / size / prompt / coins。
        item_key 全局唯一：已存在（如重复提交）的行被忽略，
        total_items 以实际落库行数回填（而非展开数量），供上层据此对账退差额。
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO batch_task
                       (task_id, user_id, status, feature_key, coins_locked, platform, params)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (
                        task_id, user_id, status, feature_key, int(coins_locked or 0),
                        platform,
                        json.dumps(params, ensure_ascii=False) if params is not None else None,
                    )
                )
                batch_pk = cursor.lastrowid
                if items:
                    cursor.executemany(
                        '''INSERT IGNORE INTO batch_task_item
                           (batch_task_id, item_key, product_id, site, image_type,
                            size, prompt, status, coins)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 'planned', %s)''',
                        [
                            (
                                batch_pk,
                                item['item_key'],
                                str(item.get('product_id') or '') or None,
                                item.get('site'),
                                item.get('image_type'),
                                item.get('size'),
                                item.get('prompt'),
                                int(item.get('coins') or 0),
                            )
                            for item in items
                        ]
                    )
                # 幂等去重：以实际落库子任务数为准回填 total_items
                cursor.execute(
                    'SELECT COUNT(*) AS cnt FROM batch_task_item WHERE batch_task_id = %s',
                    (batch_pk,)
                )
                total = int(cursor.fetchone()['cnt'])
                cursor.execute(
                    'UPDATE batch_task SET total_items = %s WHERE id = %s',
                    (total, batch_pk)
                )
            conn.commit()
        finally:
            conn.close()
        batch = self.get_batch_task(batch_pk)
        if batch is None:
            raise ValueError(f'批次创建后读取失败: task_id={task_id}')
        return batch

    def get_batch_task(self, batch_id: int) -> Optional[BatchTask]:
        """按主键查询批次"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM batch_task WHERE id = %s', (batch_id,))
                row = cursor.fetchone()
                return self._to_batch(row) if row else None
        finally:
            conn.close()

    def get_batch_by_task_id(self, task_id: str) -> Optional[BatchTask]:
        """按业务批次号（task_id，如 batch-xxxx）查询批次"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM batch_task WHERE task_id = %s', (task_id,))
                row = cursor.fetchone()
                return self._to_batch(row) if row else None
        finally:
            conn.close()

    def update_batch_status(self, batch_id: int, status: str) -> None:
        """更新批次状态（running/completed/failed/partial）"""
        if status not in BATCH_STATUSES:
            raise ValueError(f'非法批次状态: {status}')
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE batch_task SET status = %s WHERE id = %s',
                    (status, batch_id)
                )
            conn.commit()
        finally:
            conn.close()

    def update_coins_locked(self, batch_id: int, coins_locked: int) -> None:
        """回填批次预扣金额（幂等去重退差额后调用）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE batch_task SET coins_locked = %s WHERE id = %s',
                    (int(coins_locked), batch_id)
                )
            conn.commit()
        finally:
            conn.close()

    def update_batch_counters(self, batch_id: int) -> Dict[str, int]:
        """从子任务表重算并回填批次计数器（total/succeeded/failed），返回最新计数"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT COUNT(*) AS total_items,
                              COALESCE(SUM(status = 'completed'), 0) AS succeeded_items,
                              COALESCE(SUM(status = 'failed'), 0) AS failed_items
                       FROM batch_task_item WHERE batch_task_id = %s''',
                    (batch_id,)
                )
                row = cursor.fetchone()
                counters = {
                    'total_items': int(row['total_items'] or 0),
                    'succeeded_items': int(row['succeeded_items'] or 0),
                    'failed_items': int(row['failed_items'] or 0),
                }
                cursor.execute(
                    '''UPDATE batch_task
                       SET total_items = %s, succeeded_items = %s, failed_items = %s
                       WHERE id = %s''',
                    (
                        counters['total_items'], counters['succeeded_items'],
                        counters['failed_items'], batch_id,
                    )
                )
            conn.commit()
            return counters
        finally:
            conn.close()

    # ── 子任务 ──

    def get_item(self, item_id: int) -> Optional[BatchTaskItem]:
        """按主键查询子任务"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM batch_task_item WHERE id = %s', (item_id,))
                row = cursor.fetchone()
                return self._to_item(row) if row else None
        finally:
            conn.close()

    def list_items(self, batch_id: int, status: Optional[str] = None,
                   limit: int = 50, offset: int = 0) -> List[BatchTaskItem]:
        """分页列出子任务（可按状态筛选；limit/offset 由调用方保证合法范围）"""
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if status:
                    cursor.execute(
                        '''SELECT * FROM batch_task_item
                           WHERE batch_task_id = %s AND status = %s
                           ORDER BY id LIMIT %s OFFSET %s''',
                        (batch_id, status, limit, offset)
                    )
                else:
                    cursor.execute(
                        '''SELECT * FROM batch_task_item
                           WHERE batch_task_id = %s
                           ORDER BY id LIMIT %s OFFSET %s''',
                        (batch_id, limit, offset)
                    )
                rows = cursor.fetchall()
                return [self._to_item(r) for r in rows]
        finally:
            conn.close()

    def count_items(self, batch_id: int, status: Optional[str] = None) -> int:
        """统计子任务数（可按状态筛选），供分页 total"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                if status:
                    cursor.execute(
                        'SELECT COUNT(*) AS cnt FROM batch_task_item '
                        'WHERE batch_task_id = %s AND status = %s',
                        (batch_id, status)
                    )
                else:
                    cursor.execute(
                        'SELECT COUNT(*) AS cnt FROM batch_task_item WHERE batch_task_id = %s',
                        (batch_id,)
                    )
                return int(cursor.fetchone()['cnt'])
        finally:
            conn.close()

    def count_items_by_status(self, batch_id: int) -> Dict[str, int]:
        """按状态分组计数（缺省状态补 0），供 manifest 概览"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT status, COUNT(*) AS cnt FROM batch_task_item '
                    'WHERE batch_task_id = %s GROUP BY status',
                    (batch_id,)
                )
                counts = {s: 0 for s in ITEM_STATUSES}
                for row in cursor.fetchall():
                    if row['status'] in counts:
                        counts[row['status']] = int(row['cnt'])
                return counts
        finally:
            conn.close()

    def list_retry_items(self, batch_id: int) -> List[BatchTaskItem]:
        """断点续跑 / 重试：仅取 failed / planned 子任务（completed 项天然跳过）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT * FROM batch_task_item
                       WHERE batch_task_id = %s AND status IN ('failed', 'planned')
                       ORDER BY id''',
                    (batch_id,)
                )
                rows = cursor.fetchall()
                return [self._to_item(r) for r in rows]
        finally:
            conn.close()

    def update_item_status(self, item_id: int, new_status: str, error: Optional[str] = None,
                           result_url: Optional[str] = None,
                           review: Optional[dict] = None) -> BatchTaskItem:
        """子任务状态流转（状态机校验 + 条件更新防并发）

        非法跳转（如 planned→completed、completed→running）抛 InvalidItemTransition。
        error / result_url / review 仅在显式传入时更新。
        """
        if new_status not in ITEM_STATUSES:
            raise InvalidItemTransition(f'未知子任务状态: {new_status}')
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT status FROM batch_task_item WHERE id = %s', (item_id,)
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError(f'子任务不存在: {item_id}')
                current = row['status']
                if not validate_transition(current, new_status):
                    raise InvalidItemTransition(
                        f'非法状态跳转: {current} → {new_status}'
                    )
                sets, args = ['status = %s'], [new_status]
                if error is not None:
                    sets.append('error = %s')
                    args.append(error)
                if result_url is not None:
                    sets.append('result_url = %s')
                    args.append(result_url)
                if review is not None:
                    sets.append('review = %s')
                    args.append(json.dumps(review, ensure_ascii=False))
                # 条件更新：并发场景下状态已被他处变更时 rowcount=0，同样视为非法跳转
                args.extend([item_id, current])
                cursor.execute(
                    f'''UPDATE batch_task_item SET {", ".join(sets)}
                        WHERE id = %s AND status = %s''',
                    args
                )
                if cursor.rowcount == 0:
                    raise InvalidItemTransition(
                        f'非法状态跳转（并发变更）: {current} → {new_status}'
                    )
            conn.commit()
        finally:
            conn.close()
        item = self.get_item(item_id)
        if item is None:
            raise ValueError(f'子任务更新后读取失败: {item_id}')
        return item

    def reset_item_coins(self, item_id: int) -> None:
        """失败退款成功后把该项 coins 置 0（"费用已退"标记，防止重试再失败时重复退款）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE batch_task_item SET coins = 0 WHERE id = %s', (item_id,)
                )
            conn.commit()
        finally:
            conn.close()

    def set_item_review(self, item_id: int, review: dict) -> None:
        """写入 AI 视觉合规审查结果 JSON（Task 9，completed 后调用，不改状态机）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE batch_task_item SET review = %s WHERE id = %s',
                    (json.dumps(review, ensure_ascii=False), item_id)
                )
            conn.commit()
        finally:
            conn.close()

    def sum_items_coins(self, batch_id: int) -> int:
        """∑子任务 coins（图组逐项计价时，幂等去重后按落库行对账实际预扣）"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT COALESCE(SUM(coins), 0) AS total '
                    'FROM batch_task_item WHERE batch_task_id = %s',
                    (batch_id,)
                )
                return int(cursor.fetchone()['total'])
        finally:
            conn.close()
