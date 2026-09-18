"""批量套图编排测试（P1-1）

覆盖：
- expand_tasks 展开去重 / item_key 幂等格式 / 非法图型
- estimate_cost 预扣口径（unit × n = ∑item.coins）
- 子任务状态机（合法跳转 / 非法跳转拒绝）
- run_batch_task 失败隔离 / 断点续跑跳过 completed / 进度发布次数 / 失败逐项退款
- 路由：预扣=∑item.coins / 幂等去重退差额 / manifest 鉴权与状态筛选 /
  retry 对 completed 批次返回 400 / retry 不重复扣费
- 模型集成（本机 MySQL 可用时执行）：INSERT IGNORE 幂等 / 状态机 / retry 取数
"""
import asyncio
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- mock 缺失的依赖（与 test_compliance_service.py 惯例一致）----
_mock_langgraph = MagicMock()
sys.modules.setdefault('langgraph', _mock_langgraph)
sys.modules.setdefault('langgraph.graph', MagicMock())

from models.batch_task import (
    BatchTask, BatchTaskItem, BatchTaskModel, InvalidItemTransition,
    validate_transition,
)
from services import batch_orchestrator as bo
from services.batch_orchestrator import expand_tasks, estimate_cost, run_batch_task
from services.feature_pricing_service import FeaturePricingError


# ============================================================
# 工具构造
# ============================================================

def _batch(total=10, succeeded=0, failed=0, user_id=7, task_id='batch-t1',
           status='pending', params=None):
    return BatchTask(
        id=99, task_id=task_id, user_id=user_id, status=status,
        total_items=total, succeeded_items=succeeded, failed_items=failed,
        feature_key='ai_product_image.batch', coins_locked=total * 5,
        platform='amazon', params=params or {},
    )


_IMAGE_CYCLE = ('main', 'scene', 'detail')


def _items(n, coins=5, statuses=None, start_id=1):
    """构造 n 个子任务（同属 payload 中的商品 p1，站点/图型轮转）"""
    items = []
    for i in range(n):
        status = statuses[i] if statuses else 'planned'
        items.append(BatchTaskItem(
            id=start_id + i,
            batch_task_id=99,
            item_key=f'p1_US_{_IMAGE_CYCLE[i % 3]}_{start_id + i}',
            product_id='p1',
            site='US',
            image_type=_IMAGE_CYCLE[i % 3],
            prompt=f'prompt {i}',
            status=status,
            coins=coins,
        ))
    return items


def _payload(batch_task_id='batch-t1', user_id=7):
    return {
        'batch_task_id': batch_task_id,
        'user_id': user_id,
        'platform': 'amazon',
        'size': '1024x1024',
        'feature_key': 'ai_product_image.batch',
        'products': [{'product_id': 'p1', 'product_image': 'b64img'}],
        'reference_image': None,
        'reference_text': None,
        'source_wallet': 'personal',
        'team_id': None,
    }


def _make_model_mock(items, batch, pre_completed=0):
    """带内存状态的 BatchTaskModel mock：update_item_status 真实驱动状态机与计数器"""
    state = {
        it.id: {'status': it.status, 'error': None, 'result_url': None,
                'coins': it.coins, 'item': it}
        for it in items
    }
    model = MagicMock()

    def fake_update_item_status(item_id, new_status, error=None,
                                result_url=None, review=None):
        current = state[item_id]['status']
        assert validate_transition(current, new_status), \
            f'mock 状态机拒绝: {current} → {new_status}'
        state[item_id]['status'] = new_status
        if error is not None:
            state[item_id]['error'] = error
        if result_url is not None:
            state[item_id]['result_url'] = result_url
        return state[item_id]['item']

    def fake_counters(batch_id):
        succeeded = pre_completed + sum(
            1 for v in state.values() if v['status'] == 'completed')
        failed = sum(1 for v in state.values() if v['status'] == 'failed')
        return {'total_items': pre_completed + len(state),
                'succeeded_items': succeeded, 'failed_items': failed}

    model.update_item_status.side_effect = fake_update_item_status
    model.update_batch_counters.side_effect = fake_counters
    model.state = state
    return model


def _run(payload=None, batch=None, items=None, pre_completed=0,
         gen_side_effect=None):
    """跑一次 run_batch_task，返回 (model mock, gen mock, 各 AsyncMock)"""
    payload = payload or _payload()
    batch = batch or _batch()
    items = items if items is not None else _items(10)

    model = _make_model_mock(items, batch, pre_completed=pre_completed)
    model.get_batch_by_task_id.return_value = batch
    model.list_retry_items.return_value = items

    gen = MagicMock(side_effect=gen_side_effect) if gen_side_effect else MagicMock(
        return_value={'url': 'http://cdn/img.png'})

    with patch('services.batch_orchestrator.BatchTaskModel', return_value=model), \
         patch('services.batch_orchestrator.call_image_edit_model', gen), \
         patch('services.batch_orchestrator.review_image') as review_mock, \
         patch('services.batch_orchestrator.apply_platform_constraints',
               side_effect=lambda p, t, pr: pr), \
         patch('services.batch_orchestrator.refund_coins') as refund_mock, \
         patch('services.batch_orchestrator.set_progress', new_callable=AsyncMock) as progress_mock, \
         patch('services.batch_orchestrator.complete_task', new_callable=AsyncMock) as complete_mock, \
         patch('services.batch_orchestrator.fail_task', new_callable=AsyncMock) as fail_mock:
        asyncio.run(run_batch_task({'redis': MagicMock()}, payload, 'arq-task-id'))

    return {
        'model': model, 'gen': gen, 'review': review_mock,
        'refund': refund_mock, 'progress': progress_mock,
        'complete': complete_mock, 'fail': fail_mock,
    }


# ============================================================
# 展开与估价
# ============================================================

class TestExpandTasks:
    def test_expand_cross_product_and_key_format(self):
        """笛卡尔积展开：2 商品 × 2 站点 × 2 图型 = 8 项，key = product_site_imagetype"""
        products = [{'product_id': 'p1'}, {'product_id': 'p2'}]
        items, warnings = expand_tasks(products, ['US', 'DE'],
                                       ['main', 'scene'], 'amazon')
        assert len(items) == 8
        assert len(warnings) == 0
        assert {'item_key': 'p1_US_main', 'product_id': 'p1',
                'site': 'US', 'image_type': 'main'} in items
        assert 'p2_DE_scene' in [it['item_key'] for it in items]

    def test_expand_dedup(self):
        """去重：同商品重复出现 / 同站点重复 / 同图型重复均只计一项"""
        products = [{'product_id': 'p1'}, {'product_id': 'p1'},
                    {'product_id': ' p1 '}]
        items, warnings = expand_tasks(products, ['US', 'us', 'US'],
                                       ['main', 'main_image', 'main'], 'amazon')
        assert len(items) == 1
        assert items[0]['item_key'] == 'p1_US_main'
        assert len(warnings) >= 1

    def test_expand_normalizes_alias(self):
        """图型别名归一：main_image → main；站点小写 → 大写"""
        items, _ = expand_tasks([{'product_id': 'p1'}], ['us'],
                                ['main_image'], 'amazon')
        assert items[0]['image_type'] == 'main'
        assert items[0]['site'] == 'US'

    def test_expand_unknown_image_type_raises(self):
        """非法图型：抛 ValueError（路由层转 400）"""
        with pytest.raises(ValueError):
            expand_tasks([{'product_id': 'p1'}], ['US'], ['banner'], 'amazon')

    def test_item_key_long_fallback_stable(self):
        """超长 product_id：key 兜底 ≤128 且确定可复现"""
        long_id = 'x' * 200
        k1 = bo.make_item_key(long_id, 'US', 'main')
        k2 = bo.make_item_key(long_id, 'US', 'main')
        assert k1 == k2 and len(k1) <= 128


class TestEstimateCost:
    def test_estimate_cost_unit_times_count(self):
        """估价：unit × n（预扣口径 = ∑item.coins 的依据）"""
        items = _items(8)
        with patch('services.batch_orchestrator.calculate_image_cost',
                   return_value=5):
            unit, total = estimate_cost(items, 'ai_product_image.batch',
                                        '1024x1024')
        assert unit == 5
        assert total == 40
        assert total == sum(it.coins for it in items)

    def test_resolve_feature_key_fallback(self):
        """计费键：batch 未配置定价（返回 0）时回退 smart_mode；显式传入优先"""
        with patch('services.batch_orchestrator.calculate_image_cost',
                   return_value=0):
            assert bo.resolve_batch_feature_key('1024x1024') == \
                bo.FALLBACK_FEATURE_KEY
        with patch('services.batch_orchestrator.calculate_image_cost',
                   return_value=5):
            assert bo.resolve_batch_feature_key('1024x1024') == \
                bo.BATCH_FEATURE_KEY
        assert bo.resolve_batch_feature_key(
            '1024x1024', 'custom.key') == 'custom.key'


# ============================================================
# 状态机
# ============================================================

class TestStateMachine:
    def test_legal_transitions(self):
        """合法跳转：planned→running→completed/failed；failed→running（重试）"""
        assert validate_transition('planned', 'running') is True
        assert validate_transition('running', 'completed') is True
        assert validate_transition('running', 'failed') is True
        assert validate_transition('failed', 'running') is True

    def test_illegal_transitions(self):
        """非法跳转：planned 直接完成/失败、completed 重跑、failed 直接完成等均拒绝"""
        assert validate_transition('planned', 'completed') is False
        assert validate_transition('planned', 'failed') is False
        assert validate_transition('completed', 'running') is False
        assert validate_transition('completed', 'failed') is False
        assert validate_transition('failed', 'completed') is False
        assert validate_transition('running', 'planned') is False
        assert validate_transition('unknown', 'running') is False

    def test_invalid_transition_is_value_error(self):
        """InvalidItemTransition 是 ValueError 子类（上层按同一类异常处理）"""
        assert issubclass(InvalidItemTransition, ValueError)


# ============================================================
# run_batch_task：失败隔离 / 续跑 / 进度 / 退款
# ============================================================

class TestRunBatchTask:
    def test_failure_isolation(self):
        """失败隔离：10 项中第 2、7 次生图抛异常 → 批次不中断，counters 正确"""
        calls = {'n': 0}

        def gen_side_effect(product_image, prompt, size,
                            reference_image=None, reference_text=None,
                            **kwargs):
            calls['n'] += 1
            if calls['n'] in (2, 7):
                raise RuntimeError('模型超时')
            return {'url': f'http://cdn/img_{calls["n"]}.png'}

        items = _items(10)
        r = _run(items=items, gen_side_effect=gen_side_effect)

        # 全部到达终态：8 成功 / 2 失败
        statuses = [v['status'] for v in r['model'].state.values()]
        assert statuses.count('completed') == 8
        assert statuses.count('failed') == 2
        assert len(statuses) == 10
        # 失败项记录了 error，成功项记录了 result_url
        failed = [v for v in r['model'].state.values() if v['status'] == 'failed']
        assert all('模型超时' in (v['error'] or '') for v in failed)
        succeeded = [v for v in r['model'].state.values()
                     if v['status'] == 'completed']
        assert all((v['result_url'] or '').startswith('http://cdn/')
                   for v in succeeded)
        # 生图调用未中断（10 次全发）
        assert r['gen'].call_count == 10
        # 部分失败 → 编排任务本身正常完成（partial），不是 fail_task
        assert r['complete'].await_count == 1
        r['fail'].assert_not_awaited()

    def test_failed_items_refunded_one_by_one(self):
        """失败即时退款：逐项调用 refund_coins（amount=item.coins）并置 coins=0"""
        calls = {'n': 0}

        def gen_side_effect(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] in (2, 7):
                raise RuntimeError('boom')
            return {'url': 'http://cdn/x.png'}

        items = _items(10, coins=5)
        r = _run(items=items, gen_side_effect=gen_side_effect)

        assert r['refund'].call_count == 2
        for call in r['refund'].call_args_list:
            assert call.args[0] == 7                 # user_id
            assert call.args[1] == 5                 # item.coins
            assert call.kwargs['related_batch_id'] == 'batch-t1'
            assert call.kwargs['source_wallet'] == 'personal'
        assert r['model'].reset_item_coins.call_count == 2

    def test_refund_skipped_when_coins_zero(self):
        """coins=0（此前失败已退款）的项再失败 → 不重复退款"""
        def gen_side_effect(*args, **kwargs):
            raise RuntimeError('again')

        items = _items(3, coins=0)  # 已退款项
        r = _run(items=items, gen_side_effect=gen_side_effect)
        r['refund'].assert_not_called()
        r['model'].reset_item_coins.assert_not_called()
        assert r['fail'].await_count == 1  # 全部失败 → fail_task

    def test_resume_skips_completed(self):
        """断点续跑：list_retry_items 只返回 failed/planned（5 项），completed 5 项不重生图"""
        retry_items = _items(5, statuses=['failed', 'planned', 'failed',
                                          'planned', 'failed'], start_id=6)
        batch = _batch(total=10, succeeded=5, failed=5)
        r = _run(batch=batch, items=retry_items, pre_completed=5)

        assert r['gen'].call_count == 5
        touched_ids = {call.args[0]
                       for call in r['model'].update_item_status.call_args_list}
        assert touched_ids == {6, 7, 8, 9, 10}  # completed 的 1-5 未被触碰

    def test_progress_published_per_item(self):
        """进度发布：初始 1 次 + 每项 1 次 = N+1 次；末次 pct=100 且带 succeeded/failed"""
        items = _items(10)
        r = _run(items=items)

        assert r['progress'].await_count == 11
        first_call = r['progress'].await_args_list[0]
        assert first_call.args[1] == 'batch-t1'  # 发布到 task:{batch_task_id}
        last_call = r['progress'].await_args_list[-1]
        assert last_call.kwargs['pct'] == 100
        assert last_call.kwargs['succeeded'] == 10
        assert last_call.kwargs['failed'] == 0

    def test_no_retry_items_completes_immediately(self):
        """无可执行子任务（retry 空跑）：直接 complete_task，不调生图"""
        r = _run(items=[])
        assert r['gen'].call_count == 0
        assert r['complete'].await_count == 1
        result = r['complete'].await_args.args[2]
        assert '无可执行子任务' in result['message']

    def test_batch_not_found_fails(self):
        """批次不存在：fail_task 且不执行任何子任务"""
        model = MagicMock()
        model.get_batch_by_task_id.return_value = None
        with patch('services.batch_orchestrator.BatchTaskModel',
                   return_value=model), \
             patch('services.batch_orchestrator.fail_task',
                   new_callable=AsyncMock) as fail_mock, \
             patch('services.batch_orchestrator.call_image_edit_model') as gen:
            asyncio.run(run_batch_task({'redis': MagicMock()},
                                       _payload(), 'arq-task-id'))
        fail_mock.assert_awaited_once()
        assert gen.call_count == 0


# ============================================================
# 路由
# ============================================================

from flask import Flask
from routes.batch_routes import batch_bp


VALID_BODY = {
    'products': [{'product_id': 'p1', 'product_name': '保温杯',
                  'product_image': 'b64data'}],
    'sites': ['US', 'DE'],
    'image_types': ['main', 'scene'],
    'platform': 'amazon',
    'size': '1024x1024',
}


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(batch_bp)
    app.config['TESTING'] = True
    return app.test_client()


@pytest.fixture
def auth_header(monkeypatch):
    monkeypatch.setattr(
        'middleware.auth_middleware.verify_token',
        lambda token: {'sub': '1', 'email': 't@t.com', 'role': 'user'},
    )
    return {'Authorization': 'Bearer fake-token'}


@pytest.fixture
def route_patches():
    """路由层公共 mock：模型 / 扣费 / 退款 / 入队 / SSE 种子 / 平台约束 / 单价 / BYOK 判定"""
    model = MagicMock()
    with patch('routes.batch_routes.BatchTaskModel', return_value=model), \
         patch('routes.batch_routes.deduct_coins') as deduct, \
         patch('routes.batch_routes.refund_coins') as refund, \
         patch('routes.batch_routes.submit_task', return_value='arq123') as submit, \
         patch('routes.batch_routes.seed_task_state') as seed, \
         patch('routes.batch_routes.apply_platform_constraints',
               side_effect=lambda p, t, pr: pr), \
         patch('routes.batch_routes.is_feature_byok', return_value=False), \
         patch('services.batch_orchestrator.calculate_image_cost',
               return_value=5):
        yield {'model': model, 'deduct': deduct, 'refund': refund,
               'submit': submit, 'seed': seed}


class TestBatchRoutesCreate:
    def test_create_requires_auth_401(self, client):
        resp = client.post('/api/v1/batch/tasks', json=VALID_BODY)
        assert resp.status_code == 401
        assert resp.get_json()['code'] == 1001

    def test_create_missing_product_image_400(self, client, auth_header,
                                              route_patches):
        """dry-run 预检：商品图非空核对"""
        body = {**VALID_BODY, 'products': [{'product_id': 'p1'}]}
        resp = client.post('/api/v1/batch/tasks', json=body, headers=auth_header)
        assert resp.status_code == 400
        assert 'product_image' in resp.get_json()['message']

    def test_create_unsupported_site_400(self, client, auth_header,
                                         route_patches):
        resp = client.post('/api/v1/batch/tasks',
                           json={**VALID_BODY, 'sites': ['XX']},
                           headers=auth_header)
        assert resp.status_code == 400
        assert 'XX' in resp.get_json()['message']

    def test_create_success_deduct_equals_sum_item_coins(self, client,
                                                         auth_header,
                                                         route_patches):
        """提交成功：预扣 = unit × n = ∑item.coins；建批 items 每项 coins=unit"""
        p = route_patches
        p['model'].create_batch_task.return_value = _batch(total=4, user_id=1)
        resp = client.post('/api/v1/batch/tasks', json=VALID_BODY,
                           headers=auth_header)
        body = resp.get_json()
        assert resp.status_code == 200
        assert body['code'] == 0
        data = body['data']
        assert data['total_items'] == 4
        assert data['coins_locked'] == 20
        assert data['unit_cost'] == 5
        assert data['feature_key'] == 'ai_product_image.batch'
        # 预扣 = ∑item.coins（4 项 × 5）
        p['deduct'].assert_called_once()
        assert p['deduct'].call_args.kwargs['amount'] == 20
        assert p['deduct'].call_args.kwargs['related_batch_id'].startswith('batch-')
        # 建批：每项 coins=unit_cost
        item_rows = p['model'].create_batch_task.call_args.kwargs['items']
        assert len(item_rows) == 4
        assert sum(row['coins'] for row in item_rows) == 20
        assert all(row['prompt'] for row in item_rows)
        # 入队 batch_generation + SSE 种子
        p['submit'].assert_called_once()
        assert p['submit'].call_args.args[0] == 'batch_generation'
        submit_payload = p['submit'].call_args.args[1]
        assert submit_payload['batch_task_id'] == data['batch_task_id']
        p['seed'].assert_called_once_with(data['batch_task_id'], module='batch')

    def test_create_dedup_refunds_difference(self, client, auth_header,
                                             route_patches):
        """幂等去重：实际落库 2 < 展开 4 → 差额 10 立即退款，coins_locked 回填"""
        p = route_patches
        p['model'].create_batch_task.return_value = _batch(total=2, user_id=1)
        resp = client.post('/api/v1/batch/tasks', json=VALID_BODY,
                           headers=auth_header)
        data = resp.get_json()['data']
        assert resp.status_code == 200
        assert data['total_items'] == 2
        assert data['coins_locked'] == 10
        p['refund'].assert_called_once()
        assert p['refund'].call_args.args[1] == 10

    def test_create_all_duplicates_refunds_full_400(self, client,
                                                     auth_header,
                                                     route_patches):
        """全部子任务已存在：全额退款 + 400，不入队"""
        p = route_patches
        p['model'].create_batch_task.return_value = _batch(total=0, user_id=1)
        resp = client.post('/api/v1/batch/tasks', json=VALID_BODY,
                           headers=auth_header)
        assert resp.status_code == 400
        p['refund'].assert_called_once()
        assert p['refund'].call_args.args[1] == 20
        p['submit'].assert_not_called()

    def test_create_insufficient_balance_400(self, client, auth_header,
                                             route_patches):
        """余额不足：透传 FeaturePricingError，不入队不建批"""
        p = route_patches
        p['deduct'].side_effect = FeaturePricingError('灵感币余额不足',
                                                      code=3001, http_status=400)
        resp = client.post('/api/v1/batch/tasks', json=VALID_BODY,
                           headers=auth_header)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 3001
        p['submit'].assert_not_called()
        p['model'].create_batch_task.assert_not_called()


class TestBatchRoutesManifest:
    def test_manifest_requires_auth_401(self, client):
        resp = client.get('/api/v1/batch/tasks/batch-x/manifest')
        assert resp.status_code == 401

    def test_manifest_not_found_or_not_owner_404(self, client, auth_header,
                                                 route_patches):
        """归属校验：他人批次 / 不存在批次均 404（不泄露存在性）"""
        route_patches['model'].get_batch_by_task_id.return_value = _batch(user_id=2)
        resp = client.get('/api/v1/batch/tasks/batch-x/manifest',
                          headers=auth_header)
        assert resp.status_code == 404
        route_patches['model'].get_batch_by_task_id.return_value = None
        resp = client.get('/api/v1/batch/tasks/batch-x/manifest',
                          headers=auth_header)
        assert resp.status_code == 404

    def test_manifest_status_filter_and_pagination(self, client, auth_header,
                                                   route_patches):
        """状态筛选 + 分页参数透传；返回批次头 + items + 计数"""
        p = route_patches
        p['model'].get_batch_by_task_id.return_value = _batch(user_id=1)
        p['model'].list_items.return_value = _items(2)
        p['model'].count_items.return_value = 2
        p['model'].count_items_by_status.return_value = {
            'planned': 0, 'running': 0, 'completed': 8, 'failed': 2}
        resp = client.get(
            '/api/v1/batch/tasks/batch-x/manifest?status=failed&page=2&page_size=2',
            headers=auth_header)
        body = resp.get_json()
        assert resp.status_code == 200
        assert body['code'] == 0
        assert body['data']['counts']['failed'] == 2
        assert body['data']['page'] == 2
        p['model'].list_items.assert_called_once_with(
            99, status='failed', limit=2, offset=2)

    def test_manifest_invalid_status_400(self, client, auth_header,
                                         route_patches):
        route_patches['model'].get_batch_by_task_id.return_value = _batch(user_id=1)
        resp = client.get(
            '/api/v1/batch/tasks/batch-x/manifest?status=oops',
            headers=auth_header)
        assert resp.status_code == 400


class TestBatchRoutesRetry:
    def test_retry_completed_without_failed_400(self, client, auth_header,
                                                route_patches):
        """completed 批次且无失败/待执行项 → 400"""
        p = route_patches
        p['model'].get_batch_by_task_id.return_value = _batch(
            user_id=1, status='completed', total=10, succeeded=10)
        p['model'].list_retry_items.return_value = []
        resp = client.post('/api/v1/batch/tasks/batch-t1/retry',
                           headers=auth_header)
        assert resp.status_code == 400
        p['submit'].assert_not_called()

    def test_retry_running_400(self, client, auth_header, route_patches):
        p = route_patches
        p['model'].get_batch_by_task_id.return_value = _batch(
            user_id=1, status='running')
        resp = client.post('/api/v1/batch/tasks/batch-t1/retry',
                           headers=auth_header)
        assert resp.status_code == 400

    def test_retry_success_no_rededuct(self, client, auth_header,
                                       route_patches):
        """重试成功：复用参数快照入队，只跑 failed/planned，不重复扣费"""
        p = route_patches
        params = {**_payload(batch_task_id='batch-t1', user_id=1)}
        p['model'].get_batch_by_task_id.return_value = _batch(
            user_id=1, status='partial', total=10, succeeded=8, failed=2,
            params=params)
        p['model'].list_retry_items.return_value = _items(2, statuses=['failed',
                                                                       'failed'])
        resp = client.post('/api/v1/batch/tasks/batch-t1/retry',
                           headers=auth_header)
        body = resp.get_json()
        assert resp.status_code == 200
        assert body['code'] == 0
        assert body['data']['retry_items'] == 2
        assert body['data']['batch_task_id'] == 'batch-t1'
        # 不重复扣费
        p['deduct'].assert_not_called()
        p['refund'].assert_not_called()
        # 复用原参数快照（含商品图）
        p['submit'].assert_called_once()
        assert p['submit'].call_args.args[0] == 'batch_generation'
        submitted = p['submit'].call_args.args[1]
        assert submitted['batch_task_id'] == 'batch-t1'
        assert submitted['products'] == params['products']

    def test_retry_other_user_404(self, client, auth_header, route_patches):
        route_patches['model'].get_batch_by_task_id.return_value = _batch(user_id=2)
        resp = client.post('/api/v1/batch/tasks/batch-t1/retry',
                           headers=auth_header)
        assert resp.status_code == 404


# ============================================================
# 模型集成测试（本机 MySQL 可用时执行）
# ============================================================

def _mysql_available():
    try:
        import pymysql
        from config import get_config
        cfg = get_config()
        conn = pymysql.connect(
            host=cfg.MYSQL_HOST, port=cfg.MYSQL_PORT, user=cfg.MYSQL_USER,
            password=cfg.MYSQL_PASSWORD, database=cfg.MYSQL_DATABASE,
            connect_timeout=2, charset='utf8mb4',
        )
        conn.close()
        return True
    except Exception:
        return False


MYSQL_UP = _mysql_available()


@pytest.mark.skipif(not MYSQL_UP, reason='本机 MySQL 不可用，跳过模型集成测试')
class TestBatchModelDB:
    """真实 DB 验证：INSERT IGNORE 幂等 / 状态机 / retry 取数 / 计数器"""

    def setup_method(self):
        self.model = BatchTaskModel()
        self._created_task_ids = []

    def teardown_method(self):
        self._cleanup()

    def _cleanup(self):
        import pymysql
        conn = self.model._get_connection()
        try:
            with conn.cursor() as c:
                for tid in self._created_task_ids:
                    c.execute(
                        'DELETE bi FROM batch_task_item bi '
                        'JOIN batch_task bt ON bi.batch_task_id = bt.id '
                        'WHERE bt.task_id = %s', (tid,))
                    c.execute('DELETE FROM batch_task WHERE task_id = %s', (tid,))
            conn.commit()
        finally:
            conn.close()

    def _unique(self):
        tid = f'batch-test-{uuid.uuid4().hex[:12]}'
        self._created_task_ids.append(tid)
        return tid

    def _item_row(self, product_id, site='US', image_type='main', coins=5):
        return {
            'item_key': bo.make_item_key(product_id, site, image_type),
            'product_id': product_id, 'site': site,
            'image_type': image_type, 'prompt': 'prompt text', 'coins': coins,
        }

    def test_create_and_get_roundtrip(self):
        """建批 + 读回：total_items 回填、params JSON 往返、子任务初始 planned"""
        tid = self._unique()
        items = [self._item_row('p1'), self._item_row('p1', image_type='scene'),
                 self._item_row('p1', image_type='detail')]
        batch = self.model.create_batch_task(
            task_id=tid, user_id=1, items=items,
            feature_key='ai_product_image.batch', coins_locked=15,
            platform='amazon', params={'k': 'v'},
        )
        assert batch.total_items == 3
        assert batch.coins_locked == 15
        assert batch.status == 'pending'
        assert batch.params == {'k': 'v'}

        read = self.model.get_batch_by_task_id(tid)
        assert read is not None and read.id == batch.id

        rows = self.model.list_items(batch.id)
        assert len(rows) == 3
        assert all(r.status == 'planned' for r in rows)
        assert all(r.coins == 5 for r in rows)
        assert sum(r.coins for r in rows) == 15  # 预扣 = ∑item.coins

    def test_insert_ignore_idempotent(self):
        """item_key 幂等：二次提交含相同 item_key 的子任务被忽略，不重复计费"""
        tid1 = self._unique()
        tid2 = self._unique()
        items1 = [self._item_row('dup1'), self._item_row('dup1',
                                                         image_type='scene')]
        batch1 = self.model.create_batch_task(
            task_id=tid1, user_id=1, items=items1, coins_locked=10)

        # 第二次提交：dup1_US_main 已全局存在（被忽略），仅新 key 落库
        items2 = [self._item_row('dup1'),
                  self._item_row('dup1', site='DE')]
        batch2 = self.model.create_batch_task(
            task_id=tid2, user_id=1, items=items2, coins_locked=10)

        assert batch1.total_items == 2
        assert batch2.total_items == 1  # 重复项被 INSERT IGNORE 忽略
        keys2 = {r.item_key for r in self.model.list_items(batch2.id)}
        assert keys2 == {bo.make_item_key('dup1', 'DE', 'main')}

    def test_update_item_status_state_machine(self):
        """状态机：合法流转生效 + counters 重算；非法跳转抛 InvalidItemTransition"""
        tid = self._unique()
        batch = self.model.create_batch_task(
            task_id=tid, user_id=1,
            items=[self._item_row('sm1'), self._item_row('sm1',
                                                         image_type='scene')],
            coins_locked=10)

        rows = {r.item_key: r for r in self.model.list_items(batch.id)}
        target = rows[bo.make_item_key('sm1', 'US', 'main')]
        other = rows[bo.make_item_key('sm1', 'US', 'scene')]

        # planned → running → completed
        self.model.update_item_status(target.id, 'running')
        done = self.model.update_item_status(target.id, 'completed',
                                             result_url='http://cdn/a.png')
        assert done.status == 'completed'
        assert done.result_url == 'http://cdn/a.png'

        counters = self.model.update_batch_counters(batch.id)
        assert counters == {'total_items': 2, 'succeeded_items': 1,
                            'failed_items': 0}
        head = self.model.get_batch_task(batch.id)
        assert head.succeeded_items == 1

        # 非法跳转：completed → running 拒绝
        with pytest.raises(InvalidItemTransition):
            self.model.update_item_status(target.id, 'running')

        # planned → completed 直接跳转拒绝
        with pytest.raises(InvalidItemTransition):
            self.model.update_item_status(other.id, 'completed')

        # failed → running（重试）允许
        self.model.update_item_status(other.id, 'running')
        self.model.update_item_status(other.id, 'failed', error='超时')
        again = self.model.update_item_status(other.id, 'running')
        assert again.status == 'running'
        assert again.error == '超时'

    def test_list_retry_items_and_filters(self):
        """retry 取数只含 failed/planned；list_items 状态筛选与分页生效"""
        tid = self._unique()
        batch = self.model.create_batch_task(
            task_id=tid, user_id=1,
            items=[self._item_row(f'f{i}', image_type=_IMAGE_CYCLE[i % 3])
                   for i in range(4)],
            coins_locked=20)
        rows = self.model.list_items(batch.id)

        self.model.update_item_status(rows[0].id, 'running')
        self.model.update_item_status(rows[0].id, 'completed',
                                      result_url='http://cdn/0.png')
        self.model.update_item_status(rows[1].id, 'running')
        self.model.update_item_status(rows[1].id, 'failed', error='e')

        retry = self.model.list_retry_items(batch.id)
        # failed(1) + planned(2,3) 均被拾起；completed(0) 跳过
        assert {r.id for r in retry} == {rows[1].id, rows[2].id, rows[3].id}

        failed_page = self.model.list_items(batch.id, status='failed',
                                            limit=10, offset=0)
        assert [r.id for r in failed_page] == [rows[1].id]
        assert self.model.count_items(batch.id, status='failed') == 1
        assert self.model.count_items(batch.id) == 4
        counts = self.model.count_items_by_status(batch.id)
        assert counts['completed'] == 1 and counts['failed'] == 1
        assert counts['planned'] == 2 and counts['running'] == 0

    def test_reset_item_coins(self):
        """退款标记：coins 置 0（重试再失败不重复退款）"""
        tid = self._unique()
        batch = self.model.create_batch_task(
            task_id=tid, user_id=1, items=[self._item_row('rc1')],
            coins_locked=5)
        row = self.model.list_items(batch.id)[0]
        self.model.reset_item_coins(row.id)
        assert self.model.get_item(row.id).coins == 0


# ============================================================
# worker 注册确认
# ============================================================

def test_worker_discovers_batch_generation():
    """worker 能发现 batch_generation：TASK_REGISTRY 注册 + worker.py 静态导入"""
    import services.batch_orchestrator  # noqa: F401 触发注册
    from services.task_queue import TASK_REGISTRY
    assert 'batch_generation' in TASK_REGISTRY
    assert TASK_REGISTRY['batch_generation'] is bo.run_batch_task

    worker_src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'worker.py')
    with open(worker_src_path, 'r', encoding='utf-8') as f:
        worker_src = f.read()
    assert 'import services.batch_orchestrator' in worker_src
