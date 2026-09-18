"""
任务队列模块单元测试（fakeredis 打桩）
可选集成测试：本机 Redis 可连时测真实读写与 Pub/Sub 往返，否则自动跳过
"""
import asyncio
import json

import pytest

import services.task_queue as tq


# ========== fixtures ==========
@pytest.fixture()
def fake_server():
    """fakeredis 服务实例（同步/异步客户端共享，保证数据互通）"""
    import fakeredis
    return fakeredis.FakeServer()


@pytest.fixture()
def fake_sync_redis(fake_server, monkeypatch):
    """用 fakeredis 替换 task_queue 的同步 Redis 连接"""
    import fakeredis
    r = fakeredis.FakeStrictRedis(server=fake_server, decode_responses=True)
    monkeypatch.setattr(tq, 'get_sync_redis', lambda: r)
    return r


def _make_ctx(fake_server):
    """构造带 fakeredis 异步连接的 worker ctx（fakeredis 异步客户端绑定单一事件循环，
    多次 asyncio.run 需各自新建连接）"""
    from fakeredis import aioredis as fake_aioredis
    r = fake_aioredis.FakeRedis(server=fake_server, decode_responses=True)
    return {'redis': r}


@pytest.fixture()
def fake_ctx(fake_server):
    """构造带 fakeredis 异步连接的 worker ctx（模拟 on_startup 注入）"""
    return _make_ctx(fake_server)


# ========== submit_task ==========
def test_submit_task_creates_queued_state(fake_sync_redis, monkeypatch):
    """提交任务：返回 uuid hex task_id、写入 queued 状态、按 task_id 入队"""
    enqueued = {}

    async def fake_enqueue(name, task_id, payload):
        enqueued['args'] = (name, task_id, payload)

    monkeypatch.setattr(tq, '_enqueue_job', fake_enqueue)

    task_id = tq.submit_task('demo_progress', {'steps': 3}, module='demo')

    assert isinstance(task_id, str) and len(task_id) == 32
    assert enqueued['args'] == ('demo_progress', task_id, {'steps': 3})

    state = tq.get_task(task_id)
    assert state is not None
    assert state['status'] == 'queued'
    assert state['module'] == 'demo'
    assert state['pct'] == 0
    assert state['result'] is None
    assert 'created_at' in state and 'updated_at' in state


def test_register_task_decorator():
    """register_task 装饰器：注册进全局注册表且不影响原函数"""
    async def dummy(ctx, payload, task_id):
        return None

    tq.register_task('test_unit_dummy')(dummy)
    assert tq.TASK_REGISTRY['test_unit_dummy'] is dummy


# ========== worker 侧状态更新 ==========
def _seed_task(r, task_id):
    """预置一个 queued 状态任务"""
    r.hset(tq._task_key(task_id), mapping={
        'status': 'queued', 'step': '', 'pct': '0',
        'created_at': '2026-01-01T00:00:00+00:00', 'updated_at': '2026-01-01T00:00:00+00:00',
    })


def test_set_progress_updates_and_publishes(fake_sync_redis, fake_ctx):
    """set_progress：更新 Hash（running/step/pct）并向事件频道发布完整状态"""
    task_id = 'a' * 32
    _seed_task(fake_sync_redis, task_id)

    pubsub = fake_sync_redis.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(tq.event_channel(task_id))
    pubsub.get_message(timeout=1)  # 消费订阅确认消息

    state = asyncio.run(tq.set_progress(fake_ctx, task_id, '正在处理第 2 步', pct=40))
    pubsub.close()

    assert state['status'] == 'running'
    assert state['step'] == '正在处理第 2 步'
    assert state['pct'] == 40

    # Hash 落库一致
    stored = tq.get_task(task_id)
    assert stored['status'] == 'running' and stored['pct'] == 40


def test_complete_task(fake_sync_redis, fake_ctx):
    """complete_task：status=completed，result JSON 可读回为对象"""
    task_id = 'b' * 32
    _seed_task(fake_sync_redis, task_id)

    state = asyncio.run(tq.complete_task(fake_ctx, task_id, {'echo': {'steps': 2}}))

    assert state['status'] == 'completed'
    stored = tq.get_task(task_id)
    assert stored['status'] == 'completed'
    assert stored['result'] == {'echo': {'steps': 2}}


def test_fail_task(fake_sync_redis, fake_ctx):
    """fail_task：status=failed，error 信息可读回"""
    task_id = 'c' * 32
    _seed_task(fake_sync_redis, task_id)

    state = asyncio.run(tq.fail_task(fake_ctx, task_id, '模型调用超时'))

    assert state['status'] == 'failed'
    stored = tq.get_task(task_id)
    assert stored['status'] == 'failed'
    assert stored['error'] == '模型调用超时'


# ========== get_task ==========
def test_get_task_returns_none_when_missing(fake_sync_redis):
    """任务不存在 / 已过期：返回 None"""
    assert tq.get_task('nonexistent') is None


def test_get_task_deserializes_result_and_pct(fake_sync_redis, fake_server):
    """get_task：pct 转 int、result 反序列化为对象"""
    task_id = 'd' * 32
    _seed_task(fake_sync_redis, task_id)
    asyncio.run(tq.set_progress(_make_ctx(fake_server), task_id, '生成中', pct=66))
    asyncio.run(tq.complete_task(_make_ctx(fake_server), task_id, {'ok': True, 'n': 1}))

    state = tq.get_task(task_id)
    assert state['pct'] == 66
    assert isinstance(state['result'], dict)
    assert state['result'] == {'ok': True, 'n': 1}


# ========== 集成测试（可选） ==========
def _real_redis_available() -> bool:
    """探测本机 Redis 是否可连（不可连则跳过集成测试）"""
    try:
        import redis as _redis
        r = _redis.Redis.from_url(tq.REDIS_URL, socket_connect_timeout=1,
                                  socket_timeout=1, decode_responses=True)
        return bool(r.ping())
    except Exception:
        return False


@pytest.mark.skipif(not _real_redis_available(), reason='本机 Redis 不可用，跳过集成测试')
def test_redis_integration_pubsub_roundtrip():
    """集成测试：真实 Redis Hash 读写 + Pub/Sub 往返（不依赖 worker 进程）"""
    r = tq.get_sync_redis()
    assert r.ping() is True

    # Hash 读写
    key = tq._task_key('integration-test')
    r.hset(key, mapping={'status': 'running', 'step': '集成测试', 'pct': '50'})
    r.expire(key, 60)
    assert r.hget(key, 'status') == 'running'
    assert r.hget(key, 'pct') == '50'
    r.delete(key)
    assert r.hgetall(key) == {}

    # Pub/Sub 往返
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(tq.event_channel('integration-test'))
    pubsub.get_message(timeout=1)  # 消费订阅确认
    payload = json.dumps({'status': 'running', 'step': '发布测试'}, ensure_ascii=False)
    r.publish(tq.event_channel('integration-test'), payload)
    msg = pubsub.get_message(timeout=2)
    pubsub.close()
    assert msg is not None
    assert json.loads(msg['data'])['step'] == '发布测试'
