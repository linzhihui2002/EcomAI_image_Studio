"""Style Lock（P1-2）测试

覆盖：
- derive_style_lock 确定性（同输入恒同输出，无随机）
- 输出非空、以 "STYLE LOCK: " 开头、≤60 词
- run_batch_task 批次内所有 item prompt 均含同一锁定文本（mock 生图捕获 prompt）
- user_hint 生效
- 场景/品类影响派生结果（光线覆盖）
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_mock_langgraph = MagicMock()
sys.modules.setdefault('langgraph', _mock_langgraph)
sys.modules.setdefault('langgraph.graph', MagicMock())

from config import Config
from models.batch_task import BatchTask, BatchTaskItem, validate_transition
from services.batch_orchestrator import run_batch_task
from services.style_lock import (
    STYLE_LOCK_PREFIX, MAX_WORDS, derive_style_lock,
)


# ============================================================
# 纯函数：确定性 / 格式 / 词数
# ============================================================

PRODUCT = {
    'product_category': '家居',
    'product_name': '保温杯',
    'title_en': 'Stainless Steel Thermos Bottle',
}


class TestDeriveStyleLock:
    def test_deterministic_same_input_same_output(self):
        """确定性：同输入（含 dict 键序不同）多次派生输出完全一致"""
        kwargs = dict(platform='amazon', user_hint='高级感')
        a = derive_style_lock(PRODUCT, '厨房', **kwargs)
        b = derive_style_lock(PRODUCT, '厨房', **kwargs)
        c = derive_style_lock(dict(reversed(list(PRODUCT.items()))), '厨房', **kwargs)
        assert a == b == c

    def test_non_empty_prefix_and_word_budget(self):
        """非空 + "STYLE LOCK: " 前缀 + ≤60 词（覆盖多品类/场景/hint 组合）"""
        cases = [
            (PRODUCT, '厨房', 'amazon', None),
            ({'product_category': '电子产品'}, None, 'tiktok_shop', None),
            ({'title_en': 'Wireless Headphones'}, '户外露营', None, ' matte black finish'),
            ({}, None, None, 'a' * 200),          # 超长 hint 舍弃后仍 ≤60 词
            (None, '浴室', 'temu', '简约 白色'),   # 全空商品信息兜底
        ]
        for product, scene, platform, hint in cases:
            lock = derive_style_lock(product, scene, platform=platform, user_hint=hint)
            assert lock and lock.startswith(STYLE_LOCK_PREFIX)
            words = lock.split()
            assert len(words) <= MAX_WORDS, f'超词数上限: {lock}'
            # 覆盖四要素：色板 / 光线 / 构图 / 氛围
            lowered = lock.lower()
            assert 'palette' in lowered
            assert 'lighting' in lowered
            assert 'composition' in lowered
            assert 'atmosphere' in lowered

    def test_user_hint_takes_effect(self):
        """user_hint 生效：输出包含提示内容，且与无 hint 输出不同"""
        without = derive_style_lock(PRODUCT, '厨房', platform='amazon')
        with_hint = derive_style_lock(PRODUCT, '厨房', platform='amazon',
                                      user_hint='luxury gold tone 高级感')
        assert with_hint != without
        assert 'luxury gold tone' in with_hint

    def test_scene_overrides_lighting(self):
        """场景影响派生：户外场景覆盖为自然日光，且不同场景输出不同"""
        indoor = derive_style_lock(PRODUCT, '厨房')
        outdoor = derive_style_lock(PRODUCT, '户外野餐')
        assert indoor != outdoor
        assert 'bright natural daylight' in outdoor
        assert 'bright natural daylight' not in indoor


# ============================================================
# 批量编排接入：run_batch_task 派生一次并应用于每项 prompt
# ============================================================

def _batch(total=4, user_id=7, task_id='batch-t1'):
    return BatchTask(
        id=99, task_id=task_id, user_id=user_id, status='pending',
        total_items=total, feature_key='ai_product_image.batch',
        coins_locked=total * 5, platform='amazon', params={},
    )


def _items(n=4, coins=5):
    cycle = ('main', 'scene', 'detail', 'main')
    return [
        BatchTaskItem(
            id=i + 1, batch_task_id=99,
            item_key=f'p1_US_{cycle[i % 3]}_{i + 1}',
            product_id='p1', site='US', image_type=cycle[i % 3],
            prompt=f'engine prompt {i}', status='planned', coins=coins,
        )
        for i in range(n)
    ]


def _payload(batch_task_id='batch-t1', user_id=7, style_lock_hint=None):
    payload = {
        'batch_task_id': batch_task_id,
        'user_id': user_id,
        'platform': 'amazon',
        'size': '1024x1024',
        'feature_key': 'ai_product_image.batch',
        'products': [{'product_id': 'p1', 'product_name': '保温杯',
                      'product_image': 'b64img'}],
        'reference_image': None,
        'reference_text': None,
        'source_wallet': 'personal',
        'team_id': None,
    }
    if style_lock_hint is not None:
        payload['style_lock_hint'] = style_lock_hint
    return payload


def _run_batch(payload):
    """跑一次 run_batch_task（全 mock），捕获每项实际生图 prompt"""
    batch = _batch()
    items = _items()

    state = {it.id: {'status': it.status, 'item': it} for it in items}
    model = MagicMock()

    def fake_update_item_status(item_id, new_status, error=None,
                                result_url=None, review=None):
        current = state[item_id]['status']
        assert validate_transition(current, new_status)
        state[item_id]['status'] = new_status
        return state[item_id]['item']

    model.update_item_status.side_effect = fake_update_item_status
    model.update_batch_counters.return_value = {
        'total_items': len(items), 'succeeded_items': len(items),
        'failed_items': 0}
    model.get_batch_by_task_id.return_value = batch
    model.list_retry_items.return_value = items

    captured_prompts = []

    def fake_gen(product_image, prompt, size, reference_image=None,
                 reference_text=None, **kwargs):
        captured_prompts.append(prompt)
        return {'url': 'http://cdn/img.png'}

    with patch('services.batch_orchestrator.BatchTaskModel', return_value=model), \
         patch('services.batch_orchestrator.call_image_edit_model',
               side_effect=fake_gen), \
         patch('services.batch_orchestrator.review_image') as review_mock, \
         patch('services.batch_orchestrator.apply_platform_constraints',
               side_effect=lambda p, t, pr: pr), \
         patch('services.batch_orchestrator.refund_coins'), \
         patch('services.batch_orchestrator.set_progress', new_callable=AsyncMock), \
         patch('services.batch_orchestrator.complete_task', new_callable=AsyncMock), \
         patch('services.batch_orchestrator.fail_task', new_callable=AsyncMock), \
         patch.object(Config, 'COMPLIANCE_REVIEW_ENABLED', False):
        # 本文件聚焦 style lock：关闭合规审查开关，避免审查分支介入
        asyncio.run(run_batch_task({'redis': MagicMock()}, payload, 'arq-id'))

    review_mock.assert_not_called()
    return captured_prompts


class TestBatchStyleLockIntegration:
    def test_all_item_prompts_share_same_lock(self):
        """批次内所有 item prompt 均以同一锁定文本开头（mock 生图捕获）"""
        prompts = _run_batch(_payload())
        assert len(prompts) == 4
        expected_lock = derive_style_lock(
            {'product_id': 'p1', 'product_name': '保温杯'},  # 批次首个商品
            None, platform='amazon', user_hint=None,
        )
        assert expected_lock.startswith(STYLE_LOCK_PREFIX)
        for prompt in prompts:
            assert prompt.startswith(expected_lock + ' '), prompt
            assert 'engine prompt' in prompt  # 引擎主体描述保留在锁定文本之后

    def test_payload_style_lock_hint_flows_into_prompt(self):
        """payload.style_lock_hint 透传：hint 参与派生并出现在每图 prompt 中"""
        prompts = _run_batch(_payload(style_lock_hint='luxury gold tone'))
        expected_lock = derive_style_lock(
            {'product_id': 'p1', 'product_name': '保温杯'},
            None, platform='amazon', user_hint='luxury gold tone',
        )
        assert 'luxury gold tone' in expected_lock
        assert prompts and all(p.startswith(expected_lock) for p in prompts)

    def test_lock_deterministic_across_items(self):
        """同批次捕获到的锁定文本彼此一致且为合法 STYLE LOCK 输出"""
        prompts = _run_batch(_payload())
        # 锁定文本位于每图 prompt 开头（其后为引擎主体描述 "engine prompt ..."）
        locks = {p.split(' engine prompt')[0] for p in prompts}
        assert len(locks) == 1
        lock = locks.pop()
        assert lock.startswith(STYLE_LOCK_PREFIX)
        assert len(lock.split()) <= MAX_WORDS
