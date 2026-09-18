"""
异步任务队列辅助模块
Redis 状态存储 + Pub/Sub 进度推送 + ARQ 任务入队

- Flask 同步侧：submit_task（提交任务）/ get_task（读取状态）
- Worker 异步侧：set_progress / complete_task / fail_task（更新状态并发布事件）
- SSE 路由：get_sync_redis / event_channel（订阅 task-events:{task_id} 频道）

任务状态统一存 Redis Hash：key = task:{task_id}，字段：
status(queued|running|completed|failed) / step(中文步骤文案) / pct(0-100) /
result(JSON 字符串) / error / module / created_at / updated_at
"""
import os
import json
import uuid
import threading
import asyncio
from datetime import datetime, timezone

import redis
from arq import create_pool
from arq.connections import RedisSettings

# ========== 配置 ==========
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
TASK_RESULT_TTL = int(os.environ.get('TASK_RESULT_TTL', 86400))

# 任务状态 Hash key 前缀
TASK_KEY_PREFIX = 'task:'
# 进度事件 Pub/Sub 频道前缀
EVENT_CHANNEL_PREFIX = 'task-events:'


# ========== 任务注册表 ==========
# 任务名 -> async 函数 (ctx, payload: dict, task_id: str)
# worker.py 启动时把注册表收集为 ARQ functions；业务模块通过装饰器注册
TASK_REGISTRY = {}


def register_task(name: str):
    """任务注册装饰器：将 async 任务函数注册到全局注册表（worker.py 收集）"""
    def decorator(func):
        TASK_REGISTRY[name] = func
        return func
    return decorator


# ========== 同步 Redis 连接（Flask 侧 / SSE 侧） ==========
_sync_redis = None
_sync_redis_lock = threading.Lock()


def get_sync_redis() -> 'redis.Redis':
    """获取同步 Redis 连接（进程内单例，懒加载；decode_responses=True）"""
    global _sync_redis
    if _sync_redis is None:
        with _sync_redis_lock:
            if _sync_redis is None:
                _sync_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _sync_redis


# ========== key / 频道 / 状态序列化工具 ==========
def _task_key(task_id: str) -> str:
    return f'{TASK_KEY_PREFIX}{task_id}'


def event_channel(task_id: str) -> str:
    """任务进度事件 Pub/Sub 频道名"""
    return f'{EVENT_CHANNEL_PREFIX}{task_id}'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(value) -> str:
    """将字段值转为可存入 Hash 的字符串（非字符串序列化为 JSON）"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _decode(value):
    """尝试 JSON 反序列化，失败时保留原始字符串"""
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _deserialize_state(raw: dict) -> dict:
    """将 Hash 原始字段转为对外状态对象（pct 转 int，result/error 反序列化）"""
    state = dict(raw)
    try:
        state['pct'] = int(state.get('pct') or 0)
    except (TypeError, ValueError):
        state['pct'] = 0
    for field in ('result', 'error'):
        value = state.get(field)
        if value:
            state[field] = _decode(value)
        else:
            state[field] = None
    return state


# ========== ARQ 入队（模块级常驻 event loop，避免每请求新建 loop） ==========
_loop = None
_loop_lock = threading.Lock()
_arq_pool = None


def _get_loop() -> asyncio.AbstractEventLoop:
    """获取后台常驻 event loop（首次调用时创建并启动守护线程）"""
    global _loop
    if _loop is None or _loop.is_closed():
        with _loop_lock:
            if _loop is None or _loop.is_closed():
                _loop = asyncio.new_event_loop()
                threading.Thread(
                    target=_loop.run_forever,
                    daemon=True,
                    name='arq-enqueue-loop',
                ).start()
    return _loop


async def _get_arq_pool():
    """获取（或创建）ARQ Redis 连接池"""
    global _arq_pool
    if _arq_pool is None or _arq_pool.closed:
        _arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    return _arq_pool


async def _enqueue_job(name: str, task_id: str, payload: dict):
    """将任务入队 ARQ（payload 与 task_id 作为函数参数传入，job_id 固定为 task_id）"""
    pool = await _get_arq_pool()
    await pool.enqueue_job(name, payload, task_id, _job_id=task_id)


# ========== Flask 同步侧 API ==========
def seed_task_state(task_id: str, module: str = '', step: str = '任务已提交，等待执行') -> None:
    """仅写入 queued 初始状态（不入队 ARQ）

    供以业务自定义 ID（如批量套图的 batch_task_id）暴露进度的任务使用：
    worker 领取任务前，SSE 端点即可按该 ID 订阅到 queued 状态（get_task 不返回 None）。
    """
    task_id = str(task_id)
    now = _now()
    fields = {
        'status': 'queued',
        'step': step,
        'pct': '0',
        'result': '',
        'error': '',
        'module': module or '',
        'created_at': now,
        'updated_at': now,
    }
    r = get_sync_redis()
    pipe = r.pipeline()
    pipe.hset(_task_key(task_id), mapping=fields)
    pipe.expire(_task_key(task_id), TASK_RESULT_TTL)
    pipe.execute()


def submit_task(name: str, payload: dict, module: str = '') -> str:
    """
    提交异步任务（Flask 同步侧调用）
    1. 写入 queued 初始状态到 Redis Hash（带 TTL）
    2. 通过常驻 event loop 将任务入队 ARQ（job_id = task_id）
    返回 task_id（uuid4 hex）；入队失败时向上抛出异常，由调用方处理
    """
    task_id = uuid.uuid4().hex
    seed_task_state(task_id, module=module)

    future = asyncio.run_coroutine_threadsafe(
        _enqueue_job(name, task_id, payload), _get_loop()
    )
    future.result(timeout=10)
    return task_id


def get_task(task_id: str):
    """读取任务状态（同步；任务不存在或已过期返回 None）"""
    raw = get_sync_redis().hgetall(_task_key(task_id))
    if not raw:
        return None
    return _deserialize_state(raw)


# ========== Worker 异步侧 API（ctx['redis'] 由 worker on_startup 注入） ==========
async def _apply_state(ctx, task_id: str, fields: dict) -> dict:
    """写入 Hash 字段、刷新 TTL，并向事件频道发布完整状态（返回发布的状态对象）"""
    fields = {**fields, 'updated_at': _now()}
    r = ctx['redis']
    await r.hset(_task_key(task_id), mapping=fields)
    await r.expire(_task_key(task_id), TASK_RESULT_TTL)
    raw = await r.hgetall(_task_key(task_id))
    raw = {
        (k.decode() if isinstance(k, bytes) else k):
        (v.decode() if isinstance(v, bytes) else v)
        for k, v in raw.items()
    }
    state = _deserialize_state(raw)
    await r.publish(event_channel(task_id), json.dumps(state, ensure_ascii=False))
    return state


async def set_progress(ctx, task_id: str, step: str, pct=None, **extra):
    """
    更新任务进度（worker 内调用）：status=running + step/pct
    extra 可覆盖任意字段（如自定义扩展信息）
    """
    fields = {'status': 'running', 'step': str(step)}
    if pct is not None:
        fields['pct'] = str(int(pct))
    fields.update({k: _encode(v) for k, v in extra.items()})
    return await _apply_state(ctx, task_id, fields)


async def complete_task(ctx, task_id: str, result):
    """标记任务完成：status=completed + result（JSON 序列化存储）"""
    fields = {'status': 'completed', 'result': _encode(result), 'error': ''}
    return await _apply_state(ctx, task_id, fields)


async def fail_task(ctx, task_id: str, error):
    """标记任务失败：status=failed + error 信息"""
    fields = {'status': 'failed', 'error': _encode(error)}
    return await _apply_state(ctx, task_id, fields)
