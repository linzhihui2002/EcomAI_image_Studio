"""AI 视觉合规审查（P1-4）测试

覆盖（mock 多模态调用，不发起真实 HTTP）：
- review_image 正常 JSON 解析（含请求体校验：图 base64/data URL、模型名）
- riskLevel 归一（大小写/空白/非法值 → unknown）
- 坏 JSON：重试 1 次后仍失败 → riskLevel=unknown + issues[review_error]，共调用 2 次
- 批量链路：开关开启 + 平台非空 → 每项 completed 后 review_image 触发并 set_item_review 落库
- 批量链路：COMPLIANCE_REVIEW_ENABLED=False（monkeypatch）→ 不触发审查
- 批量链路：review_image 抛异常 → review 记 unknown，批次不中断
- 手动端点 POST /api/v1/compliance/review：JWT 鉴权（无 token 401）/ 入参校验 / 成功返回
"""
import asyncio
import base64
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
from services import compliance_review_service as crs
from services.batch_orchestrator import run_batch_task


GOOD_JSON = ('{"riskLevel": "HIGH", '
             '"issues": [{"rule": "white_background", "detail": "bg is grey"}], '
             '"fixSuggestions": ["retake on pure white background"]}')


def _resp(content, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = content
    resp.json.return_value = {
        'choices': [{'message': {'content': content}}]}
    return resp


# ============================================================
# review_image 服务层（mock 多模态 HTTP）
# ============================================================

@pytest.fixture
def rules_mock():
    """屏蔽 DB：get_platform_rules 返回固定规则"""
    data = {
        'platform': 'amazon',
        'image_rules': {
            'main_image': {'background_rgb': [255, 255, 255],
                           'product_min_ratio': 0.85},
        },
        'global_forbidden': [{'name': '促销水印', 'severity': 'block',
                              'keywords': ['discount']}],
    }
    with patch('services.compliance_review_service.get_platform_rules',
               return_value=data):
        yield data


class TestReviewImage:
    def test_parses_json_and_checks_request(self, rules_mock):
        """正常 JSON 解析 + 请求体校验（模型名 / data URL 图像 / system prompt）"""
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured['url'] = url
            captured['body'] = json
            captured['timeout'] = timeout
            return _resp(GOOD_JSON)

        with patch('services.compliance_review_service.requests.post',
                   side_effect=fake_post):
            result = crs.review_image('b64abc', 'amazon', 'main')

        assert result['riskLevel'] == 'high'          # HIGH → 归一为 high
        assert result['issues'] == [
            {'rule': 'white_background', 'detail': 'bg is grey'}]
        assert result['fixSuggestions'] == ['retake on pure white background']
        # 请求体：多模态 chat/completions + base64 补 data URL 前缀 + 规则要点
        body = captured['body']
        assert body['model'] == crs.AIConfig.MULTIMODAL_MODEL_NAME
        user_content = body['messages'][1]['content']
        assert user_content[1]['image_url']['url'] == 'data:image/png;base64,b64abc'
        system_prompt = body['messages'][0]['content']
        assert 'background_rgb' in system_prompt
        assert 'product_min_ratio' in system_prompt
        assert '促销水印' in system_prompt
        assert captured['timeout'] == crs.AIConfig.MULTIMODAL_TIMEOUT

    def test_http_url_passed_through(self, rules_mock):
        """http url 输入直传（不转 base64）"""
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured['body'] = json
            return _resp(GOOD_JSON)

        with patch('services.compliance_review_service.requests.post',
                   side_effect=fake_post):
            crs.review_image('https://cdn.example.com/img.png', 'amazon', 'scene')
        url = captured['body']['messages'][1]['content'][1]['image_url']['url']
        assert url == 'https://cdn.example.com/img.png'

    def test_risk_level_normalization(self, rules_mock):
        """riskLevel 归一：大小写/空白归一；非法值 → unknown"""
        cases = [
            ('{"riskLevel": " Medium ", "issues": [], "fixSuggestions": []}',
             'medium'),
            ('{"riskLevel": "Low", "issues": [], "fixSuggestions": []}', 'low'),
            ('{"riskLevel": "catastrophic", "issues": [], "fixSuggestions": []}',
             'unknown'),
            ('{"issues": [], "fixSuggestions": []}', 'unknown'),  # 缺失字段
        ]
        for content, expected in cases:
            with patch('services.compliance_review_service.requests.post',
                       return_value=_resp(content)):
                result = crs.review_image('b64', 'amazon', 'main')
            assert result['riskLevel'] == expected, content

    def test_bad_json_retried_once_then_unknown(self, rules_mock):
        """坏 JSON：解析失败重试 1 次，仍失败 → unknown + review_error，共 2 次调用"""
        with patch('services.compliance_review_service.requests.post',
                   return_value=_resp('not a json {{{')) as post_mock:
            result = crs.review_image('b64', 'amazon', 'main')
        assert post_mock.call_count == 2
        assert result['riskLevel'] == 'unknown'
        assert len(result['issues']) == 1
        assert result['issues'][0]['rule'] == 'review_error'
        assert result['issues'][0]['detail']
        assert result['fixSuggestions'] == []

    def test_api_error_then_unknown(self, rules_mock):
        """API 异常（非 200）同样重试 1 次后返回 unknown，不向调用方抛异常"""
        resp = MagicMock()
        resp.status_code = 500
        resp.text = 'boom'
        with patch('services.compliance_review_service.requests.post',
                   return_value=resp) as post_mock:
            result = crs.review_image('b64', 'amazon', 'main')
        assert post_mock.call_count == 2
        assert result['riskLevel'] == 'unknown'
        assert result['issues'][0]['rule'] == 'review_error'


class TestNormalizeImageInput:
    """回归 C3：本地成图相对路径 /api/v1/images/... 须读盘转 data URL

    修复前该路径被误补 `data:image/png;base64,` 前缀 → 审查 500 / 全部 unknown。
    """

    def _patch_storage(self, monkeypatch, tmp_path):
        from services import image_storage_service as storage
        monkeypatch.setattr(storage, 'STORAGE_DIR', str(tmp_path))
        monkeypatch.setattr(storage, 'URL_PREFIX', '/api/v1/images')

    def test_local_storage_path_read_as_data_url(self, monkeypatch, tmp_path):
        raw = b'\x89PNG\r\n\x1a\nFAKE'
        (tmp_path / 'batch_1_x.png').write_bytes(raw)
        self._patch_storage(monkeypatch, tmp_path)

        expected = 'data:image/png;base64,' + base64.b64encode(raw).decode()
        assert crs._normalize_image_input('/api/v1/images/batch_1_x.png') == expected
        # 带查询串仍可解析
        assert crs._normalize_image_input(
            '/api/v1/images/batch_1_x.png?v=2') == expected

    def test_missing_local_file_raises(self, monkeypatch, tmp_path):
        self._patch_storage(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            crs._normalize_image_input('/api/v1/images/not_found.png')

    def test_path_traversal_blocked(self, monkeypatch, tmp_path):
        """路径穿越：只取 basename，越界文件读不到 → FileNotFoundError"""
        self._patch_storage(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            crs._normalize_image_input('/api/v1/images/../../etc/passwd')


# ============================================================
# 批量链路触发（run_batch_task 内 completed 后审查）
# ============================================================

def _batch(total=2, user_id=7, task_id='batch-t1'):
    return BatchTask(
        id=99, task_id=task_id, user_id=user_id, status='pending',
        total_items=total, feature_key='ai_product_image.batch',
        coins_locked=total * 5, platform='amazon', params={},
    )


def _items(n=2, coins=5):
    cycle = ('main', 'scene')
    return [
        BatchTaskItem(
            id=i + 1, batch_task_id=99,
            item_key=f'p1_US_{cycle[i % 2]}_{i + 1}',
            product_id='p1', site='US', image_type=cycle[i % 2],
            prompt=f'engine prompt {i}', status='planned', coins=coins,
        )
        for i in range(n)
    ]


def _payload(batch_task_id='batch-t1', user_id=7, platform='amazon'):
    return {
        'batch_task_id': batch_task_id,
        'user_id': user_id,
        'platform': platform,
        'size': '1024x1024',
        'feature_key': 'ai_product_image.batch',
        'products': [{'product_id': 'p1', 'product_image': 'b64img'}],
        'reference_image': None,
        'reference_text': None,
        'source_wallet': 'personal',
        'team_id': None,
    }


def _run_batch(payload=None, review_side_effect=None, review_returns=None):
    """跑一次 run_batch_task（全 mock），返回 (model mock, review mock)"""
    payload = payload or _payload()
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

    gen = MagicMock(return_value={'url': 'http://cdn/img.png'})
    review_mock = (MagicMock(side_effect=review_side_effect)
                   if review_side_effect else MagicMock(
                       return_value=review_returns or {
                           'riskLevel': 'low', 'issues': [],
                           'fixSuggestions': []}))

    with patch('services.batch_orchestrator.BatchTaskModel', return_value=model), \
         patch('services.batch_orchestrator.call_image_edit_model', gen), \
         patch('services.batch_orchestrator.review_image', review_mock), \
         patch('services.batch_orchestrator.apply_platform_constraints',
               side_effect=lambda p, t, pr: pr), \
         patch('services.batch_orchestrator.refund_coins'), \
         patch('services.batch_orchestrator.set_progress', new_callable=AsyncMock), \
         patch('services.batch_orchestrator.complete_task', new_callable=AsyncMock), \
         patch('services.batch_orchestrator.fail_task', new_callable=AsyncMock):
        asyncio.run(run_batch_task({'redis': MagicMock()}, payload, 'arq-id'))

    return model, review_mock


class TestBatchReviewTrigger:
    def test_review_triggered_and_persisted_per_completed_item(self):
        """每项 completed 后触发 review_image，结果经 set_item_review 落库"""
        review = {'riskLevel': 'medium',
                  'issues': [{'rule': 'text_overlay', 'detail': 'too much text'}],
                  'fixSuggestions': ['remove text']}
        model, review_mock = _run_batch(review_returns=review)

        assert review_mock.call_count == 2
        # 审查入参：成图 url + 平台 + 图型
        assert review_mock.call_args_list[0].args == \
            ('http://cdn/img.png', 'amazon', 'main')
        assert review_mock.call_args_list[1].args == \
            ('http://cdn/img.png', 'amazon', 'scene')
        # 落库：set_item_review(item_id, review)
        assert model.set_item_review.call_count == 2
        assert model.set_item_review.call_args_list[0].args == (1, review)
        assert model.set_item_review.call_args_list[1].args == (2, review)

    def test_review_disabled_skips(self, monkeypatch):
        """COMPLIANCE_REVIEW_ENABLED=False（monkeypatch）→ 批量不触发审查"""
        monkeypatch.setattr(Config, 'COMPLIANCE_REVIEW_ENABLED', False)
        model, review_mock = _run_batch()
        review_mock.assert_not_called()
        model.set_item_review.assert_not_called()

    def test_review_exception_records_unknown_without_breaking_batch(self):
        """审查异常不阻断批次：review 记 unknown 并照常落库"""
        model, review_mock = _run_batch(
            review_side_effect=RuntimeError('multimodal down'))
        assert review_mock.call_count == 2
        assert model.set_item_review.call_count == 2
        for call in model.set_item_review.call_args_list:
            stored = call.args[1]
            assert stored['riskLevel'] == 'unknown'
            assert stored['issues'][0]['rule'] == 'review_error'

    def test_no_platform_skips_review(self, monkeypatch):
        """批次无平台（platform 为空）→ 不触发审查"""
        monkeypatch.setattr(Config, 'COMPLIANCE_REVIEW_ENABLED', True)
        model, review_mock = _run_batch(payload=_payload(platform=''))
        review_mock.assert_not_called()
        model.set_item_review.assert_not_called()


# ============================================================
# 手动审查端点 POST /api/v1/compliance/review
# ============================================================

from flask import Flask
from routes.compliance_routes import compliance_bp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(compliance_bp)
    app.config['TESTING'] = True
    return app.test_client()


@pytest.fixture
def auth_header(monkeypatch):
    monkeypatch.setattr(
        'middleware.auth_middleware.verify_token',
        lambda token: {'sub': '1', 'email': 't@t.com', 'role': 'user'},
    )
    return {'Authorization': 'Bearer fake-token'}


class TestReviewEndpoint:
    def test_requires_auth_401(self, client):
        """手动审查端点鉴权：无 token 401"""
        resp = client.post('/api/v1/compliance/review',
                           json={'image': 'b64', 'platform': 'amazon',
                                 'image_type': 'main'})
        assert resp.status_code == 401
        assert resp.get_json()['code'] == 1001

    def test_missing_image_400(self, client, auth_header):
        resp = client.post('/api/v1/compliance/review',
                           json={'platform': 'amazon'}, headers=auth_header)
        assert resp.status_code == 400
        assert 'image' in resp.get_json()['message']

    def test_oversized_base64_400(self, client, auth_header):
        """大小限制校验：base64 > 8MB → 400（不触发审查）"""
        big = 'A' * (8 * 1024 * 1024 + 1)
        with patch('routes.compliance_routes.review_image') as review_mock:
            resp = client.post('/api/v1/compliance/review',
                               json={'image': big, 'platform': 'amazon',
                                     'image_type': 'main'},
                               headers=auth_header)
        assert resp.status_code == 400
        review_mock.assert_not_called()

    def test_review_success(self, client, auth_header):
        """成功：调 review_image 并返回结构化结果"""
        result = {'riskLevel': 'low', 'issues': [], 'fixSuggestions': []}
        with patch('routes.compliance_routes.review_image',
                   return_value=result) as review_mock:
            resp = client.post('/api/v1/compliance/review',
                               json={'image': 'https://cdn/x.png',
                                     'platform': 'amazon',
                                     'image_type': 'main'},
                               headers=auth_header)
        body = resp.get_json()
        assert resp.status_code == 200
        assert body['code'] == 0
        assert body['data'] == result
        review_mock.assert_called_once_with('https://cdn/x.png', 'amazon', 'main')
