"""
SubTask 8.4：工作台 generation 批次/单任务进度 SSE 补齐 —— 事件发布测试

两部分：
1. 单元测试（fakeredis 打桩）：generation_store 写回代理写状态 → task-events:{id}
   收到统一形状事件 + task:{id} 镜像落库；终态发布断言；发布失败不影响主流程。
2. 可选集成测试（本机 Redis 可用时执行，否则跳过）：真实 worker 子进程（AI 调用打桩）
   + app.test_client 提交简单模式生成任务 → GET 形状不变 + Pub/Sub 订阅线程
   （模拟 SSE）收到 progress 与 completed 事件。
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.generation_store as gs
import services.task_queue as tq
from app import create_app


# ========== fixtures（fakeredis） ==========

@pytest.fixture()
def fake_server():
    import fakeredis
    return fakeredis.FakeServer()


@pytest.fixture()
def fake_sync_redis(fake_server, monkeypatch):
    """用 fakeredis 同时替换 generation_store 与 task_queue 的同步 Redis 连接
    （生产环境两者共用同一 Redis；镜像断言需经 task_queue.get_task 读取）"""
    import fakeredis
    r = fakeredis.FakeStrictRedis(server=fake_server, decode_responses=True)
    monkeypatch.setattr(gs, 'get_sync_redis', lambda: r)
    monkeypatch.setattr(tq, 'get_sync_redis', lambda: r)
    return r


def _subscribe(r, channel):
    """订阅频道并消费订阅确认消息"""
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=1)
    return pubsub


def _recv(pubsub, timeout=2):
    msg = pubsub.get_message(timeout=timeout)
    return json.loads(msg['data']) if msg else None


def _task_dict(task_id, batch_id, status='pending', image_url=None, error_msg=None):
    """构造 GenerationTask.to_dict() 形状的任务字典"""
    return {
        'task_id': task_id,
        'batch_id': batch_id,
        'image_type': 'white_bg',
        'slot_index': 0,
        'slot_name': '',
        'slot_desc': '',
        'status': status,
        'prompt_used': 'test prompt',
        'image_url': image_url,
        'error_msg': error_msg,
    }


# ========== 单任务事件发布 ==========

def test_task_write_publishes_unified_event(fake_sync_redis):
    """写回代理写入任务 → task-events:{task_id} 收到统一形状事件 + task:{id} 镜像"""
    pubsub = _subscribe(fake_sync_redis, tq.event_channel('task-e1'))

    gs.get_task_store()['task-e1'] = _task_dict('task-e1', 'batch-e1')

    msg = _recv(pubsub)
    pubsub.close()

    # 统一任务形状：pending → queued
    assert msg is not None
    assert msg['status'] == 'queued'
    assert msg['module'] == 'generation'
    for field in ('status', 'step', 'pct', 'result', 'error', 'module'):
        assert field in msg
    assert msg['result']['task_id'] == 'task-e1'
    assert msg['result']['batch_id'] == 'batch-e1'
    assert msg['result']['gen_status'] == 'pending'

    # 镜像 Hash：SSE 端点建连时读它作为初始状态（缺失会 404）
    mirror = tq.get_task('task-e1')
    assert mirror is not None
    assert mirror['status'] == 'queued'
    assert mirror['result'] == msg['result']


def test_writethrough_mutation_publishes_running(fake_sync_redis):
    """原地修改写回代理（工作流真实用法）→ 发布 running 事件"""
    store = gs.get_task_store()
    store['task-e2'] = _task_dict('task-e2', 'batch-e2')

    pubsub = _subscribe(fake_sync_redis, tq.event_channel('task-e2'))
    task = store['task-e2']          # _WriteThroughDict 写回代理
    task['status'] = 'processing'    # 原地修改 → 自动写回 + 发布
    msg = _recv(pubsub)
    pubsub.close()

    assert msg['status'] == 'running'
    assert msg['result']['gen_status'] == 'processing'
    assert tq.get_task('task-e2')['status'] == 'running'


def test_terminal_success_publishes_completed(fake_sync_redis):
    """终态 success → 发布 completed 事件（SSE 靠它关流），base64 剥离为 has_image"""
    pubsub = _subscribe(fake_sync_redis, tq.event_channel('task-e3'))

    gs.get_task_store()['task-e3'] = _task_dict(
        'task-e3', 'batch-e3', status='success', image_url='data:image/png;base64,AAAA')

    msg = _recv(pubsub)
    pubsub.close()

    assert msg['status'] == 'completed'
    assert msg['pct'] == 100
    # base64 数据 URI 剥离，与批次 GET 端点行为一致
    assert msg['result']['image_url'] == ''
    assert msg['result']['has_image'] is True


def test_terminal_failed_publishes_failed(fake_sync_redis):
    """终态 failed → 发布 failed 事件且 error 透传"""
    pubsub = _subscribe(fake_sync_redis, tq.event_channel('task-e4'))

    gs.get_task_store()['task-e4'] = _task_dict(
        'task-e4', 'batch-e4', status='failed', error_msg='模型调用超时')

    msg = _recv(pubsub)
    pubsub.close()

    assert msg['status'] == 'failed'
    assert msg['error'] == '模型调用超时'
    assert msg['result']['error_msg'] == '模型调用超时'


def test_publish_failure_does_not_break_persist(fake_sync_redis, monkeypatch):
    """发布失败（如 Redis Pub/Sub 异常）不影响 Hash 主流程写入"""
    def _boom(identifier, message):
        raise RuntimeError('pubsub down')

    monkeypatch.setattr(gs, '_publish_state', _boom)

    store = gs.get_task_store()
    store['task-e5'] = _task_dict('task-e5', 'batch-e5')

    # Hash 仍正常落库
    assert store['task-e5']['status'] == 'pending'


# ========== 批次聚合事件发布 ==========

def test_batch_registration_publishes_aggregate_and_mirror(fake_sync_redis):
    """批次注册 → task-events:{batch_id} 聚合事件 + task:{batch_id} 镜像（SSE 可订阅批次）"""
    store = gs.get_task_store()
    store['task-b1'] = _task_dict('task-b1', 'batch-b1')
    store['task-b2'] = _task_dict('task-b2', 'batch-b2')

    pubsub = _subscribe(fake_sync_redis, tq.event_channel('batch-b1'))
    gs.get_batch_store()['batch-b1'] = ['task-b1', 'task-b2']

    msg = _recv(pubsub)
    pubsub.close()

    assert msg is not None
    assert msg['status'] == 'running'      # 全部 pending，未到终态
    assert msg['step'] == '0/2 张完成'
    assert msg['pct'] == 0
    assert [t['task_id'] for t in msg['result']['tasks']] == ['task-b1', 'task-b2']

    mirror = tq.get_task('batch-b1')
    assert mirror is not None
    assert mirror['status'] == 'running'
    assert mirror['result']['batch_id'] == 'batch-b1'


def test_batch_aggregate_completes_when_all_terminal(fake_sync_redis):
    """全部任务到终态 → 批次聚合事件发布 completed（SSE 靠它关流）"""
    store = gs.get_task_store()
    store['task-c1'] = _task_dict('task-c1', 'batch-c1')
    store['task-c2'] = _task_dict('task-c2', 'batch-c2')
    gs.get_batch_store()['batch-c1'] = ['task-c1', 'task-c2']

    pubsub = _subscribe(fake_sync_redis, tq.event_channel('batch-c1'))

    # 第一张完成 → 仍 running
    store['task-c1'] = _task_dict('task-c1', 'batch-c1', status='success',
                                  image_url='https://example.com/1.png')
    msg1 = _recv(pubsub)
    assert msg1['status'] == 'running'
    assert msg1['step'] == '1/2 张完成'
    assert msg1['pct'] == 50

    # 第二张完成 → completed 终态
    store['task-c2'] = _task_dict('task-c2', 'batch-c1', status='failed', error_msg='x')
    msg2 = _recv(pubsub)
    pubsub.close()

    assert msg2['status'] == 'completed'
    assert msg2['pct'] == 100
    assert tq.get_task('batch-c1')['status'] == 'completed'


def test_task_write_publishes_batch_aggregate(fake_sync_redis):
    """单任务写回（含 batch_id）→ 同时发布单任务事件与批次聚合事件"""
    store = gs.get_task_store()
    gs.get_batch_store()['batch-d1'] = ['task-d1']

    store['task-d1'] = _task_dict('task-d1', 'batch-d1')

    task_pubsub = _subscribe(fake_sync_redis, tq.event_channel('task-d1'))
    batch_pubsub = _subscribe(fake_sync_redis, tq.event_channel('batch-d1'))

    task = store['task-d1']        # _WriteThroughDict 写回代理
    task['status'] = 'processing'  # 原地修改 → 写回 + 发布

    task_msg = _recv(task_pubsub)
    batch_msg = _recv(batch_pubsub)
    task_pubsub.close()
    batch_pubsub.close()

    assert task_msg['status'] == 'running'
    assert batch_msg['status'] == 'running'
    assert batch_msg['result']['tasks'][0]['gen_status'] == 'processing'


# ========== 集成测试（真实 Redis + 真实 worker 子进程 + test_client） ==========

def _real_redis_available() -> bool:
    try:
        import redis as _redis
        r = _redis.Redis.from_url(tq.REDIS_URL, socket_connect_timeout=1,
                                  socket_timeout=1, decode_responses=True)
        return bool(r.ping())
    except Exception:
        return False


@pytest.fixture
def app(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, '_run_migrations', lambda config, app: None)
    app = create_app(env='testing')
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    from utils.security import generate_token
    token = generate_token(user_id=9999, email="test_sse_events@example.com", role="user")
    return {"Authorization": f"Bearer {token}"}


from app import create_app  # noqa: E402  （置于 fixture 定义后，与既有集成测试一致）


def _start_stub_worker(unique: str, log_file):
    """启动真实 worker 子进程，仅打桩 AI 调用与历史落库（其余链路全部真实）"""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    worker_code = (
        "import sys\n"
        "import time\n"
        f"sys.path.insert(0, r'{backend_dir}')\n"
        "from services import generation_service as _gs\n"
        "def _fake_edit(**kwargs):\n"
        "    time.sleep(2.5)\n"
        f"    return {{'url': 'https://example.com/mock-{unique}.png'}}\n"
        "_gs.call_image_edit_model = _fake_edit\n"
        "import services.history_service as _hs\n"
        "_hs.save_history = lambda **kwargs: None\n"
        "import worker\n"
        "worker.run_worker(worker.WorkerSettings)\n"
    )
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    return subprocess.Popen(
        [sys.executable, '-c', worker_code],
        cwd=backend_dir, env=env,
        stdout=log_file, stderr=subprocess.STDOUT,
    )


@pytest.mark.skipif(not _real_redis_available(), reason='本机 Redis 不可用，跳过集成测试')
def test_smart_generation_batch_sse_events_end_to_end(client, auth_headers, monkeypatch):
    """
    真实 worker + test_client：提交简单模式生成任务 →
    1. GET /generation/batches/{batch_id} 响应形状不变（冻结表逐字段核对）
    2. Pub/Sub 订阅线程（模拟 SSE）收到 progress（running）与 completed 事件
    3. task:{batch_id} 镜像存在且终态为 completed（SSE 端点建连依赖）
    """
    # 扣费依赖定价配置，测试中置 0 走"费用为 0 跳过扣费"分支
    from routes import generation as gen_module
    monkeypatch.setattr(gen_module, 'calculate_image_cost', lambda *a, **k: 0)

    unique = uuid.uuid4().hex[:8]
    final_task = None
    with tempfile.TemporaryFile() as worker_log:
        proc = _start_stub_worker(unique, worker_log)
        try:
            # 1. 提交简单模式生成任务（商品信息完整 → 跳过 AI 分析，仅打桩生图调用）
            resp = client.post('/api/v1/generation/smart-generate', json={
                'product_images': ['test_base64_product_image_data_long_enough_1234567890'],
                'platform': 'Amazon',
                'region': '美国',
                'target_language': '英语',
                'size': '1024x1024',
                'product_info': {
                    'product_name': 'Test Product',
                    'target_audience': 'Everyone',
                    'selling_points': 'Great/Amazing',
                    'usage_scenario': 'Daily use',
                    'product_category': 'Test/General',
                },
                'image_groups': [
                    {'key': 'white', 'slots': [
                        {'id': 's1', 'name': '', 'desc': ''},
                        {'id': 's2', 'name': '', 'desc': ''},
                    ]},
                ],
            }, headers=auth_headers)
            data = resp.get_json()
            assert data['code'] == 0, f'提交失败: {data}'
            batch_id = data['data']['batch_id']
            gen_task_id = data['data']['tasks'][0]['task_id']

            # 提交即建立 task:{batch_id} 镜像 → SSE 端点建连不会 404
            assert tq.get_task(batch_id) is not None

            # 2. 另起线程订阅 task-events:{batch_id}（模拟 SSE 订阅）
            import redis as _redis
            r = _redis.Redis.from_url(tq.REDIS_URL, decode_responses=True)
            pubsub = r.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(tq.event_channel(batch_id))
            pubsub.get_message(timeout=1)  # 消费订阅确认

            received = []
            stop_event = threading.Event()

            def _consume():
                while not stop_event.is_set():
                    msg = pubsub.get_message(timeout=0.5)
                    if msg:
                        received.append(json.loads(msg['data']))

            consumer = threading.Thread(target=_consume, daemon=True)
            consumer.start()

            # 3. test_client 轮询 GET（与原前端轮询一致），断言响应形状不变
            frozen_task_keys = {
                'task_id', 'batch_id', 'image_type', 'slot_index', 'slot_name',
                'slot_desc', 'status', 'prompt_used', 'image_url', 'error_msg',
            }
            deadline = time.time() + 120
            final_tasks = None
            while time.time() < deadline:
                batch_resp = client.get(
                    f'/api/v1/generation/batches/{batch_id}', headers=auth_headers)
                batch_data = batch_resp.get_json()
                assert batch_data['code'] == 0
                # 冻结形状：{batch_id, tasks:[...]}
                assert set(batch_data['data'].keys()) == {'batch_id', 'tasks'}
                for task in batch_data['data']['tasks']:
                    assert frozen_task_keys <= set(task.keys()), f'缺少冻结字段: {task}'
                statuses_now = [t['status'] for t in batch_data['data']['tasks']]
                if all(s in ('success', 'failed') for s in statuses_now):
                    final_tasks = batch_data['data']['tasks']
                    break
                time.sleep(1)

            assert final_tasks is not None, '120s 内批次未到终态'
            assert all(t['status'] == 'success' for t in final_tasks), f"任务失败: {final_tasks}"
            assert all(t['image_url'] == f'https://example.com/mock-{unique}.png'
                       for t in final_tasks)

            # 单任务 GET 形状同样冻结
            task_resp = client.get(
                f'/api/v1/generation/tasks/{gen_task_id}', headers=auth_headers)
            task_data = task_resp.get_json()
            assert task_data['code'] == 0
            assert frozen_task_keys <= set(task_data['data'].keys())

            # 等订阅线程收齐终态事件
            event_deadline = time.time() + 10
            while time.time() < event_deadline:
                if any(m['status'] == 'completed' for m in received):
                    break
                time.sleep(0.2)
            stop_event.set()
            consumer.join(timeout=3)
            pubsub.close()

            # 4. 断言收到 progress（running）与 completed 事件，形状符合统一约定
            statuses = [m['status'] for m in received]
            assert 'running' in statuses, f'未收到 progress 事件: {received}'
            assert 'completed' in statuses, f'未收到 completed 事件: {received}'
            assert statuses[-1] == 'completed'
            completed = [m for m in received if m['status'] == 'completed'][-1]
            for field in ('status', 'step', 'pct', 'result', 'error', 'module'):
                assert field in completed
            assert completed['module'] == 'generation'
            assert completed['result']['batch_id'] == batch_id
            assert completed['result']['tasks'][0]['status'] == 'completed'

            # 5. 镜像终态：SSE 端点此时会直接下发 completed 并关流
            mirror = tq.get_task(batch_id)
            assert mirror is not None
            assert mirror['status'] == 'completed'
            assert all(t['status'] == 'completed' for t in mirror['result']['tasks'])

            # 6. 清理测试数据（Hash 为共享 key，按字段删除）
            r.hdel('generation:tasks', *[t['task_id'] for t in final_tasks])
            r.hdel('generation:batches', batch_id)
            r.hdel('generation:batchctx', batch_id)
            r.delete(tq._task_key(batch_id))
            r.delete(*(tq._task_key(t['task_id']) for t in final_tasks))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            worker_log.seek(0)
            log_content = worker_log.read().decode('utf-8', errors='replace')
            if final_tasks is None:
                print('\n===== worker 日志（失败诊断） =====\n', log_content[-4000:])
