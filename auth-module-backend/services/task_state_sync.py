"""
同步任务状态写入辅助（供 ARQ 任务体内执行的同步业务代码调用）

背景：toolbox 系任务体是同步重 IO 代码（经 asyncio.to_thread 在 worker 线程池中
执行），原实现通过模块级字典记录 status/progress/result/error。迁移后这些"写字典"
位置改写同一个 Redis Hash（task:{task_id}）并向事件频道发布完整状态——语义与
services.task_queue 的异步侧 API 完全一致，只是改为同步阻塞实现，便于在同步
业务函数（如 replace_product / run_model_product_task）内部原位替换。

读取侧（Flask GET 端点）走 task_queue.get_task，与本模块写入互通。
"""
import json

from services.task_queue import (
    TASK_RESULT_TTL,
    _deserialize_state,
    _encode,
    _now,
    _task_key,
    event_channel,
    get_sync_redis,
)


def _install_arq_closed_compat():
    """
    arq/redis-py 版本兼容垫片（Task 0 遗留，不在 services/task_queue.py 内修改）：
    services.task_queue._get_arq_pool 会读取 _arq_pool.closed 以判断连接池是否关闭，
    但当前 arq 0.28 / redis-py 的 ArqRedis 并未提供 closed 属性，导致同一进程内
    第二次 submit_task 触发 AttributeError。这里给 ArqRedis 补一个只读属性：
    连接池在进程生命周期内不会关闭，默认返回 False（与原判空重建语义一致）。
    """
    try:
        from arq.connections import ArqRedis
    except Exception:  # pragma: no cover - 无 arq 环境下跳过
        return
    if hasattr(ArqRedis, 'closed'):
        return

    def _closed(self) -> bool:
        return getattr(self, '_task_queue_closed', False)

    ArqRedis.closed = property(_closed)


_install_arq_closed_compat()


def _apply_state(task_id: str, fields: dict) -> dict:
    """写 Hash 字段、刷新 TTL，并向事件频道发布完整状态（与异步版 _apply_state 等价）"""
    fields = {**fields, 'updated_at': _now()}
    r = get_sync_redis()
    pipe = r.pipeline()
    pipe.hset(_task_key(task_id), mapping=fields)
    pipe.expire(_task_key(task_id), TASK_RESULT_TTL)
    pipe.execute()
    raw = r.hgetall(_task_key(task_id))
    state = _deserialize_state(raw)
    r.publish(event_channel(task_id), json.dumps(state, ensure_ascii=False))
    return state


def set_progress_sync(task_id: str, step: str, pct=None, **extra):
    """同步版 set_progress：status=running + step/pct（+extra 扩展字段）"""
    fields = {'status': 'running', 'step': str(step)}
    if pct is not None:
        fields['pct'] = str(int(pct))
    fields.update({k: _encode(v) for k, v in extra.items()})
    return _apply_state(task_id, fields)


def complete_task_sync(task_id: str, result):
    """同步版 complete_task：status=completed + result"""
    return _apply_state(task_id, {'status': 'completed', 'result': _encode(result), 'error': ''})


def fail_task_sync(task_id: str, error):
    """同步版 fail_task：status=failed + error"""
    return _apply_state(task_id, {'status': 'failed', 'error': _encode(error)})
