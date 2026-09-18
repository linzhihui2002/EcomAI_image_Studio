"""
商品图/专业模式生成任务的 Redis 存储适配层

把原进程内字典迁移到 Redis Hash（JSON 编码值）：
- generation:tasks      task_id     -> GenerationTask.to_dict()（原 routes/generation._task_store）
- generation:batches    batch_id    -> [task_id, ...]（原 _batch_store）
- generation:batchctx   batch_id    -> 批次生成上下文（原 _batch_context）
- generation:pro_batches batch_id   -> 专业模式批次上下文（原 workflows/pro_generation._pro_batch_store）

对外保持 dict（MutableMapping）语义：
- 取出的 dict 值是 _WriteThroughDict 写回代理：原地修改（task["status"] = ...）会
  自动序列化写回 Redis，保证 smart/pro 工作流里大量"原地改字典"业务代码零改动；
- 其余读写（赋值、删除、包含判断、keys、clear）直接映射 Redis 命令。

SubTask 8.4 补齐事件发布：generation:tasks / generation:batches 每次写回时，同步
PUBLISH task-events:{id} 一条完整状态 JSON（与 task_queue.get_task 返回形状一致的
统一任务形状 {status, step, pct, result, error, module, ...}），并同时镜像写
task:{id} Hash——SSE 端点（routes/sse_routes.py）连接建立时读该镜像作为初始状态，
没有镜像会直接 404。批次 id 与单图 task id 都会发事件，前端可任选其一订阅。
"""
import json
import os
from collections.abc import MutableMapping
from typing import Any

from services.task_queue import (
    TASK_RESULT_TTL,
    _now,
    _task_key,
    event_channel,
    get_sync_redis,
)

# 默认 TTL：原内存字典随进程存活（重启即清空），现给 7 天可配置过期
DEFAULT_STORE_TTL = int(os.environ.get('GENERATION_STORE_TTL', 7 * 86400))

# generation 原始任务状态 → 统一任务状态语义（对齐 services.task_queue）
_STATUS_TO_UNIFIED = {
    'pending': 'queued',
    'processing': 'running',
    'success': 'completed',
    'failed': 'failed',
}


def _unified_status(raw_status) -> str:
    """原始状态值 → queued|running|completed|failed（未知值按运行中处理，避免误判终态）"""
    return _STATUS_TO_UNIFIED.get(str(raw_status or ''), 'running')


def _generation_task_payload(task_id: str, task: dict) -> dict:
    """单任务事件载荷：统一状态 + generation 扩展字段（base64 数据 URI 剥离，与批次 GET 一致）"""
    status = _unified_status(task.get('status'))
    image_url = task.get('image_url') or ''
    has_image = bool(image_url)
    if image_url.startswith('data:'):
        image_url = ''
    return {
        'task_id': task_id,
        'batch_id': task.get('batch_id') or '',
        'image_type': task.get('image_type', ''),
        'slot_index': task.get('slot_index', 0),
        'slot_name': task.get('slot_name', ''),
        'slot_desc': task.get('slot_desc', ''),
        'status': status,
        'gen_status': str(task.get('status') or ''),
        'prompt_used': task.get('prompt_used') or '',
        'image_url': image_url,
        'has_image': has_image,
        'error_msg': task.get('error_msg') or None,
    }


def _task_event(task_id: str, task: dict) -> dict:
    """单任务事件（统一任务形状；result 内嵌完整任务载荷）"""
    payload = _generation_task_payload(task_id, task)
    terminal = payload['status'] in ('completed', 'failed')
    return {
        'module': 'generation',
        'status': payload['status'],
        'step': '',
        'pct': 100 if terminal else 0,
        'result': payload,
        'error': payload['error_msg'],
    }


def _batch_event(batch_id: str):
    """批次聚合事件：result.tasks 为批次内各任务统一载荷；全部到终态时 status=completed"""
    task_ids = _batch_store.get(batch_id)
    if not isinstance(task_ids, list) or not task_ids:
        return None
    tasks = []
    for tid in task_ids:
        task = _task_store.get(tid)
        if task is None:
            continue
        tasks.append(_generation_task_payload(tid, dict(task)))
    if not tasks:
        return None
    done = sum(1 for t in tasks if t['status'] in ('completed', 'failed'))
    return {
        'module': 'generation',
        'status': 'completed' if done == len(tasks) else 'running',
        'step': f'{done}/{len(tasks)} 张完成',
        'pct': int(done * 100 / len(tasks)),
        'result': {'batch_id': batch_id, 'tasks': tasks},
        'error': None,
    }


def _publish_state(identifier: str, message: dict):
    """镜像写 task:{id} Hash（SSE 端点建连时读它作初始状态）并发布事件到 task-events:{id}"""
    r = get_sync_redis()
    key = _task_key(identifier)
    result = message.get('result')
    error = message.get('error')
    fields = {
        'status': message.get('status') or 'running',
        'step': message.get('step') or '',
        'pct': str(message.get('pct') or 0),
        'result': json.dumps(result, ensure_ascii=False) if result is not None else '',
        'error': json.dumps(error, ensure_ascii=False) if error is not None else '',
        'module': message.get('module') or 'generation',
        'updated_at': _now(),
    }
    pipe = r.pipeline()
    pipe.hset(key, mapping=fields)
    pipe.expire(key, TASK_RESULT_TTL)
    pipe.execute()
    r.publish(event_channel(identifier), json.dumps(message, ensure_ascii=False))


def _notify_writes(store_key: str, field: str, value: Any):
    """Hash 写入后的事件发布分发（发布失败仅记日志，不影响主流程）"""
    try:
        if store_key == 'generation:tasks':
            if isinstance(value, dict):
                _publish_state(field, _task_event(field, dict(value)))
                batch_id = value.get('batch_id')
                if batch_id:
                    message = _batch_event(batch_id)
                    if message:
                        _publish_state(batch_id, message)
        elif store_key == 'generation:batches':
            # 批次注册/变更：发布聚合事件并建立 task:{batch_id} 镜像（SSE 初始状态依赖）
            message = _batch_event(field)
            if message:
                _publish_state(field, message)
        # generation:batchctx / generation:pro_batches：上下文存储，无统一进度语义，不发布
    except Exception as e:  # pragma: no cover - 防御性兜底
        print(f"[generation_store] 任务事件发布失败（不影响主流程）: field={field} err={e}", flush=True)


class _WriteThroughDict(dict):
    """dict 子类：任何原地修改后自动把整个字典写回所属 Redis Hash"""

    def __init__(self, store: 'RedisJSONHash', key: str, data: dict):
        super().__init__(data)
        self._store = store
        self._key = key

    def __reduce__(self):
        # pickle 安全（ARQ 任务载荷默认用 pickle 序列化）：退化为普通 dict，
        # 避免反序列化时未经过 __init__ 导致缺少 _store 属性而崩溃
        return (dict, (dict(self),))

    def _persist(self):
        self._store[self._key] = dict(self)

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self._persist()

    def __delitem__(self, k):
        super().__delitem__(k)
        self._persist()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._persist()

    def setdefault(self, k, default=None):
        result = super().setdefault(k, default)
        self._persist()
        return result

    def pop(self, k, *args):
        result = super().pop(k, *args)
        self._persist()
        return result

    def clear(self):
        super().clear()
        self._persist()


class RedisJSONHash(MutableMapping):
    """Redis Hash 到 dict 的适配器：field -> JSON 值；dict 值返回写回代理"""

    def __init__(self, key: str, ttl: int = DEFAULT_STORE_TTL):
        self.key = key
        self.ttl = ttl

    # ── 读 ──
    def __getitem__(self, k: str) -> Any:
        raw = get_sync_redis().hget(self.key, k)
        if raw is None:
            raise KeyError(k)
        value = json.loads(raw)
        if isinstance(value, dict):
            return _WriteThroughDict(self, k, value)
        return value

    def __contains__(self, k) -> bool:
        return bool(get_sync_redis().hexists(self.key, k))

    def __iter__(self):
        return iter(get_sync_redis().hkeys(self.key))

    def __len__(self) -> int:
        return int(get_sync_redis().hlen(self.key))

    # ── 写 ──
    def __setitem__(self, k: str, v: Any):
        pipe = get_sync_redis().pipeline()
        pipe.hset(self.key, k, json.dumps(v, ensure_ascii=False))
        pipe.expire(self.key, self.ttl)
        pipe.execute()
        # SubTask 8.4：写回后同步发布任务/批次事件（失败不影响主流程）
        _notify_writes(self.key, k, v)

    def __delitem__(self, k: str):
        get_sync_redis().hdel(self.key, k)

    def clear(self):
        """清空整个 Hash（测试辅助；业务上按字段删除）"""
        get_sync_redis().delete(self.key)


# ── 进程内单例（Flask 与 worker 各自导入后共享同一批 Redis key） ──
_task_store = RedisJSONHash('generation:tasks')
_batch_store = RedisJSONHash('generation:batches')
_batch_context = RedisJSONHash('generation:batchctx')
_pro_batch_store = RedisJSONHash('generation:pro_batches')


def get_task_store() -> RedisJSONHash:
    """原 routes/generation._task_store 的 Redis 适配器"""
    return _task_store


def get_batch_store() -> RedisJSONHash:
    """原 _batch_store 的 Redis 适配器"""
    return _batch_store


def get_batch_context_store() -> RedisJSONHash:
    """原 _batch_context 的 Redis 适配器"""
    return _batch_context


def get_pro_batch_store() -> RedisJSONHash:
    """原 workflows/pro_generation._pro_batch_store 的 Redis 适配器"""
    return _pro_batch_store
