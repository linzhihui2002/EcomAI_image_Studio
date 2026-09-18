"""TikTok 三图组合（P1-3 tiktok_showcase）测试

覆盖：
- image_group='tiktok_showcase' 展开为固定 3 图型（main/scene/detail）且逐项尺寸正确
- estimate_cost 逐项按 size 计价（coins 写回每项，total=∑item.coins）
- 幂等去重在图组模式下仍生效（重复商品/站点/图型只计一项）
- 未知图组抛 ValueError
- 模型集成（本机 MySQL 可用时执行）：item.size 落库往返 + sum_items_coins 对账
"""
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_mock_langgraph = MagicMock()
sys.modules.setdefault('langgraph', _mock_langgraph)
sys.modules.setdefault('langgraph.graph', MagicMock())

from services import batch_orchestrator as bo
from services.batch_orchestrator import (
    IMAGE_GROUPS, expand_tasks, estimate_cost,
)


GROUP_SIZES = {'main': '1024x1024', 'scene': '1024x1024', 'detail': '1024x1820'}


class TestTiktokGroupExpand:
    def test_expands_three_types_with_correct_sizes(self):
        """tiktok_showcase 展开为固定 [main, scene, detail]，逐项尺寸按预设"""
        items, warnings = expand_tasks(
            [{'product_id': 'p1'}], ['US'], [], 'tiktok_shop',
            image_group='tiktok_showcase')
        assert len(items) == 3
        assert [it['image_type'] for it in items] == ['main', 'scene', 'detail']
        assert {it['image_type']: it['size'] for it in items} == GROUP_SIZES
        assert all(it['site'] == 'US' for it in items)
        assert warnings == []

    def test_group_overrides_user_image_types(self):
        """图组模式覆盖用户传入的 image_types（仍只展开 3 图型）"""
        items, _ = expand_tasks(
            [{'product_id': 'p1'}], ['US'], ['main', 'main'], 'tiktok_shop',
            image_group='tiktok_showcase')
        assert [it['image_type'] for it in items] == ['main', 'scene', 'detail']

    def test_unknown_group_raises(self):
        """未知图组预设：抛 ValueError（路由层转 400）"""
        with pytest.raises(ValueError):
            expand_tasks([{'product_id': 'p1'}], ['US'], [], 'amazon',
                         image_group='nope_group')

    def test_dedup_still_effective_in_group_mode(self):
        """幂等去重仍生效：重复商品/重复站点在图组模式下仍只计一项"""
        products = [{'product_id': 'p1'}, {'product_id': 'p1'}, {'product_id': ' p1 '}]
        items, warnings = expand_tasks(
            products, ['US', 'us'], [], 'tiktok_shop',
            image_group='tiktok_showcase')
        assert len(items) == 3
        assert len(warnings) >= 1
        assert {it['item_key'] for it in items} == {
            'p1_US_main', 'p1_US_scene', 'p1_US_detail'}


class TestTiktokGroupPricing:
    def test_estimate_cost_per_item_by_size(self):
        """逐项 coins 按 size 计价：5+5+8=18，coins 写回每项，unit=0（价格不唯一）"""
        items, _ = expand_tasks(
            [{'product_id': 'p1'}], ['US'], [], 'tiktok_shop',
            image_group='tiktok_showcase')

        def price_by_size(feature_key, size):
            return {'1024x1024': 5, '1024x1820': 8}[size]

        with patch('services.batch_orchestrator.calculate_image_cost',
                   side_effect=price_by_size):
            unit, total = estimate_cost(items, 'ai_product_image.batch',
                                        '1024x1024')
        assert total == 18  # 5 + 5 + 8
        assert [it['coins'] for it in items] == [5, 5, 8]
        assert total == sum(it['coins'] for it in items)  # 预扣 = ∑item.coins
        assert unit == 0  # 价格不唯一，调用方应以逐项 coins 为准

    def test_estimate_cost_uniform_when_prices_equal(self):
        """同尺寸同价：unit 为该单价（与原口径一致）"""

        def price_flat(feature_key, size):
            return 6

        items, _ = expand_tasks(
            [{'product_id': 'p1'}], ['US'], [], 'tiktok_shop',
            image_group='tiktok_showcase')
        with patch('services.batch_orchestrator.calculate_image_cost',
                   side_effect=price_flat):
            unit, total = estimate_cost(items, 'ai_product_image.batch',
                                        '1024x1024')
        assert unit == 6 and total == 18

    def test_group_preset_shape(self):
        """图组预设注册完整：IMAGE_GROUPS 含 tiktok_showcase 且尺寸齐全"""
        group = IMAGE_GROUPS['tiktok_showcase']
        assert group['image_types'] == ['main', 'scene', 'detail']
        assert group['sizes'] == GROUP_SIZES


# ============================================================
# 模型集成（本机 MySQL 可用时执行）：item.size 落库往返
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
class TestTiktokGroupDB:
    def setup_method(self):
        from models.batch_task import BatchTaskModel
        self.model = BatchTaskModel()
        self._created_task_ids = []

    def teardown_method(self):
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

    def test_item_size_roundtrip_and_sum_coins(self):
        """size 列落库往返：图组逐项尺寸持久化 + sum_items_coins 求和对账"""
        items, _ = expand_tasks(
            [{'product_id': 'grp1'}], ['US'], [], 'tiktok_shop',
            image_group='tiktok_showcase')
        priced = [dict(it, coins=c) for it, c in zip(items, [5, 5, 8])]
        tid = self._unique()
        batch = self.model.create_batch_task(
            task_id=tid, user_id=1, items=priced,
            feature_key='ai_product_image.batch', coins_locked=18)
        assert batch.total_items == 3

        rows = self.model.list_items(batch.id)
        assert {r.image_type: r.size for r in rows} == GROUP_SIZES
        assert sum(r.coins for r in rows) == 18
        assert self.model.sum_items_coins(batch.id) == 18
