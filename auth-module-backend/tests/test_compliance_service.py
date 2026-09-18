"""平台合规预校验服务测试（P0-2）：规则查询/缓存/分级/白底注入/去重/端点"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- mock 缺失的依赖（与 test_generation.py 惯例一致）----
_mock_langgraph = MagicMock()
sys.modules.setdefault('langgraph', _mock_langgraph)
sys.modules.setdefault('langgraph.graph', MagicMock())

from models.compliance import ComplianceRule
from services import compliance_service


GLOBAL_FORBIDDEN = {
    "items": [
        {"name": "二维码", "severity": "block", "keywords": ["qr code", "barcode"]},
        {"name": "水印", "severity": "block", "keywords": ["watermark"]},
        {"name": "物流/促销文字", "severity": "warning",
         "keywords": ["free shipping", "discount"]},
    ]
}

MAIN_RULES = {
    "background": "pure white RGB(255,255,255)",
    "background_rgb": [255, 255, 255],
    "product_min_ratio": 0.85,
    "severity": "block",
}

SCENE_RULES = {"background": "lifestyle scene allowed", "severity": "warning"}


def _mock_model(rules_rows):
    model = MagicMock()
    model.get_rules.return_value = rules_rows
    return model


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个用例前后清缓存，避免串扰"""
    compliance_service.invalidate_cache()
    yield
    compliance_service.invalidate_cache()


class TestGetPlatformRules:
    def test_rules_structure(self):
        """规则查询：图型规则 + globalForbidden 结构化返回"""
        model = _mock_model([
            ComplianceRule(platform='amazon', image_type='main_image',
                           rules=MAIN_RULES, global_forbidden=GLOBAL_FORBIDDEN),
            ComplianceRule(platform='amazon', image_type='scene',
                           rules=SCENE_RULES, global_forbidden=GLOBAL_FORBIDDEN),
        ])
        with patch('services.compliance_service.ComplianceRuleModel',
                   return_value=model):
            rules = compliance_service.get_platform_rules('amazon')
        assert rules["platform"] == 'amazon'
        assert rules["image_rules"]["main_image"]["product_min_ratio"] == 0.85
        assert len(rules["global_forbidden"]) == 3

    def test_cache_second_call_no_db(self):
        """进程内缓存：60s 内二次查询不触达 DB"""
        model = _mock_model([
            ComplianceRule(platform='amazon', image_type='main_image',
                           rules=MAIN_RULES, global_forbidden=GLOBAL_FORBIDDEN),
        ])
        with patch('services.compliance_service.ComplianceRuleModel',
                   return_value=model):
            compliance_service.get_platform_rules('amazon')
            compliance_service.get_platform_rules('amazon')
        assert model.get_rules.call_count == 1

    def test_normalize_platform(self):
        """平台名归一：Amazon → amazon，TikTok Shop → tiktok_shop"""
        assert compliance_service.normalize_platform('Amazon') == 'amazon'
        assert compliance_service.normalize_platform('TikTok Shop') == 'tiktok_shop'

    def test_unknown_platform_empty_rules(self):
        """未知平台：空规则不抛异常"""
        model = _mock_model([])
        with patch('services.compliance_service.ComplianceRuleModel',
                   return_value=model):
            rules = compliance_service.get_platform_rules('shopify')
        assert rules["image_rules"] == {}
        assert rules["global_forbidden"] == []


class TestPrecheckPrompt:
    def _patch_rules(self, rows=None):
        rows = rows if rows is not None else [
            ComplianceRule(platform='amazon', image_type='main_image',
                           rules=MAIN_RULES, global_forbidden=GLOBAL_FORBIDDEN),
        ]
        return patch('services.compliance_service.ComplianceRuleModel',
                     return_value=_mock_model(rows))

    def test_block_level_hit(self):
        """block 级禁元素命中：进入 blocks"""
        with self._patch_rules():
            result = compliance_service.precheck_prompt(
                'amazon', 'scene', 'add a qr code in the corner')
        assert len(result['blocks']) == 1
        assert result['blocks'][0]['name'] == '二维码'
        assert result['warnings'] == []

    def test_warning_level_hit(self):
        """warning 级禁元素命中：进入 warnings 不阻断"""
        with self._patch_rules():
            result = compliance_service.precheck_prompt(
                'amazon', 'scene', 'banner text: free shipping today')
        assert result['blocks'] == []
        assert len(result['warnings']) == 1
        assert result['warnings'][0]['severity'] == 'warning'

    def test_main_image_white_bg_injection(self):
        """主图提示词缺白底约束：注入约束文本"""
        with self._patch_rules():
            result = compliance_service.precheck_prompt(
                'amazon', 'main_image', 'a bottle on a wooden table')
        assert len(result['injected_constraints']) == 1
        assert 'RGB(255,255,255)' in result['injected_constraints'][0]
        assert '85%' in result['injected_constraints'][0]

    def test_white_bg_dedup_with_engine(self):
        """去重：prompt 已含白底约束（引擎注入）时不再注入"""
        prompt = ('Product photo. Pure white background (RGB 255,255,255) required; '
                  'no text, no watermark.')
        with self._patch_rules():
            result = compliance_service.precheck_prompt(
                'amazon', 'main_image', prompt)
        assert result['injected_constraints'] == []
        assert all(w.get('name') != '主图白底约束' for w in result['warnings'])

    def test_clean_prompt_no_hits(self):
        """干净提示词：无命中无注入"""
        with self._patch_rules():
            result = compliance_service.precheck_prompt(
                'amazon', 'scene', 'a bottle on a wooden table')
        assert result == {"warnings": [], "blocks": [], "injected_constraints": []}


class TestApplyPlatformConstraints:
    def _patch_rules(self):
        return patch(
            'services.compliance_service.ComplianceRuleModel',
            return_value=_mock_model([
                ComplianceRule(platform='amazon', image_type='main_image',
                               rules=MAIN_RULES, global_forbidden=GLOBAL_FORBIDDEN),
            ]),
        )

    def test_apply_main_image_constraint(self):
        """主图最终 prompt 注入平台约束"""
        with self._patch_rules():
            enhanced = compliance_service.apply_platform_constraints(
                'amazon', 'white_bg', 'a bottle, centered composition')
        assert 'Platform compliance' in enhanced
        assert 'RGB(255,255,255)' in enhanced

    def test_apply_idempotent(self):
        """幂等：二次应用不重复注入"""
        with self._patch_rules():
            once = compliance_service.apply_platform_constraints(
                'amazon', 'main_image', 'a bottle on wood')
            twice = compliance_service.apply_platform_constraints(
                'amazon', 'main_image', once)
        assert once == twice

    def test_apply_non_main_unchanged(self):
        """非主图：不注入，原样返回"""
        with self._patch_rules():
            prompt = 'lifestyle scene photo'
            result = compliance_service.apply_platform_constraints(
                'amazon', 'scene', prompt)
        assert result == prompt


# ── 路由测试 ──

from flask import Flask
from routes.compliance_routes import compliance_bp


@pytest.fixture
def client():
    """最小 Flask 应用：仅注册 compliance 蓝图"""
    app = Flask(__name__)
    app.register_blueprint(compliance_bp)
    app.config['TESTING'] = True
    return app.test_client()


@pytest.fixture
def auth_header(monkeypatch):
    """伪造 JWT 鉴权"""
    monkeypatch.setattr(
        'middleware.auth_middleware.verify_token',
        lambda token: {'sub': '1', 'email': 't@t.com', 'role': 'user'},
    )
    return {'Authorization': 'Bearer fake-token'}


class TestComplianceRoutes:
    def test_rules_requires_auth_401(self, client):
        """无 Token 访问 rules → 401"""
        resp = client.get('/api/v1/compliance/rules?platform=amazon')
        assert resp.status_code == 401
        assert resp.get_json()['code'] == 1001

    def test_rules_missing_platform_param_400(self, client, auth_header):
        """platform 参数缺失 → 400"""
        resp = client.get('/api/v1/compliance/rules', headers=auth_header)
        assert resp.status_code == 400
        assert 'platform' in resp.get_json()['message']

    def test_rules_success(self, client, auth_header):
        """查询成功：返回图型规则 + globalForbidden"""
        with patch(
            'routes.compliance_routes.get_platform_rules',
            return_value={
                'platform': 'amazon',
                'image_rules': {'main_image': MAIN_RULES, 'scene': SCENE_RULES},
                'global_forbidden': GLOBAL_FORBIDDEN['items'],
            },
        ):
            resp = client.get('/api/v1/compliance/rules?platform=amazon',
                              headers=auth_header)
        body = resp.get_json()
        assert resp.status_code == 200
        assert body['code'] == 0
        assert body['data']['platform'] == 'amazon'
        assert body['data']['image_rules']['main_image']['product_min_ratio'] == 0.85
        assert len(body['data']['globalForbidden']) == 3

    def test_rules_frontend_contract_fields(self, client, auth_header):
        """回归 C2：须提供前端契约字段 imageTypes 与禁元素 term

        前端读 imageTypes[*].productRatioMin 与 globalForbidden[*].term，
        缺失会导致合规摘要显示"禁用词：、、"且主图摘要不显示。
        """
        with patch(
            'routes.compliance_routes.get_platform_rules',
            return_value={
                'platform': 'amazon',
                'image_rules': {'main_image': MAIN_RULES, 'scene': SCENE_RULES},
                'global_forbidden': GLOBAL_FORBIDDEN['items'],
            },
        ):
            resp = client.get('/api/v1/compliance/rules?platform=amazon',
                              headers=auth_header)
        data = resp.get_json()['data']

        # imageTypes 与兼容字段 image_rules 同值
        assert data['imageTypes'] == data['image_rules']
        assert data['imageTypes']['main_image']['product_min_ratio'] == 0.85

        # 每个禁元素均带非空 term（由 name 派生），且保留原始字段
        assert len(data['globalForbidden']) == 3
        for item in data['globalForbidden']:
            assert item['term'] and item['term'] == item['name']
            assert 'keywords' in item

    def test_rules_unknown_platform_404(self, client, auth_header):
        """未知平台 → 404"""
        with patch(
            'routes.compliance_routes.get_platform_rules',
            return_value={'platform': 'shopify', 'image_rules': {},
                          'global_forbidden': []},
        ):
            resp = client.get('/api/v1/compliance/rules?platform=shopify',
                              headers=auth_header)
        assert resp.status_code == 404
