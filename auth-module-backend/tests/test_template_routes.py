"""模板预览路由测试（P0-1）：鉴权 401 / 预览不计费不调模型 / options"""
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

from flask import Flask
from routes.template_routes import template_bp


VALID_SP = {
    "zh_title": "无线快充",
    "zh_desc": "支持无线充电，摆脱线缆束缚",
    "en_title": "Wireless Fast Charging",
    "en_desc": "Charge without cables",
    "visual_keywords": "wireless, charging pad, sleek",
}


def _fake_token_payload():
    return {"sub": "1", "email": "test@example.com", "role": "user"}


@pytest.fixture
def client():
    """最小 Flask 应用：仅注册 template 蓝图（不连 MySQL/Redis）"""
    app = Flask(__name__)
    app.register_blueprint(template_bp)
    app.config['TESTING'] = True
    return app.test_client()


@pytest.fixture
def auth_header(monkeypatch):
    """伪造 JWT 鉴权：patch middleware 内 verify_token"""
    monkeypatch.setattr(
        'middleware.auth_middleware.verify_token',
        lambda token: _fake_token_payload(),
    )
    return {'Authorization': 'Bearer fake-token'}


class TestPreviewAuth:
    def test_preview_requires_auth_401(self, client):
        """无 Token 访问预览端点 → 401"""
        resp = client.post('/api/v1/template/preview', json={})
        assert resp.status_code == 401
        assert resp.get_json()['code'] == 1001

    def test_options_requires_auth_401(self, client):
        """无 Token 访问 options 端点 → 401"""
        resp = client.get('/api/v1/template/options')
        assert resp.status_code == 401


class TestPreview:
    def test_preview_success_no_model_call_no_billing(self, client, auth_header):
        """预览成功：返回三图型提示词，不调模型不计费"""
        with patch('services.generation_service.analyze_product') as mock_analyze, \
             patch('services.generation_service.call_image_edit_model') as mock_call, \
             patch('services.feature_pricing_service.deduct_coins') as mock_deduct:
            resp = client.post(
                '/api/v1/template/preview',
                json={
                    "product_info": {"product_name": "保温杯", "title_en":
                                     "Insulated Water Bottle"},
                    "selling_points": [VALID_SP],
                    "scene": "居家客厅",
                    "site": "US",
                },
                headers=auth_header,
            )
            body = resp.get_json()
            assert resp.status_code == 200
            assert body['code'] == 0
            prompts = body['data']['prompts']
            assert set(prompts.keys()) == {'main', 'scene', 'detail'}
            assert 'RGB 255,255,255' in prompts['main']
            assert body['data']['warnings'] == []
            # 全程不触发模型调用、不扣费
            mock_analyze.assert_not_called()
            mock_call.assert_not_called()
            mock_deduct.assert_not_called()

    def test_preview_missing_product_info_400(self, client, auth_header):
        """缺 product_info → 400"""
        resp = client.post(
            '/api/v1/template/preview',
            json={"selling_points": [], "site": "US"},
            headers=auth_header,
        )
        assert resp.status_code == 400

    def test_preview_invalid_selling_point_400(self, client, auth_header):
        """卖点 visual_keywords 含中文 → 400 且消息含字段名"""
        bad = dict(VALID_SP, visual_keywords="无线, 中文")
        resp = client.post(
            '/api/v1/template/preview',
            json={
                "product_info": {"title_en": "Bottle"},
                "selling_points": [bad],
                "site": "US",
            },
            headers=auth_header,
        )
        body = resp.get_json()
        assert resp.status_code == 400
        assert 'visual_keywords' in body['message']

    def test_preview_invalid_image_type_400(self, client, auth_header):
        """未知图型 → 400"""
        resp = client.post(
            '/api/v1/template/preview',
            json={
                "product_info": {"title_en": "Bottle"},
                "selling_points": [],
                "site": "US",
                "image_types": ["poster"],
            },
            headers=auth_header,
        )
        assert resp.status_code == 400

    def test_preview_invalid_site_fallback_warning(self, client, auth_header):
        """非法站点回退默认站点并在 warnings 中提示"""
        resp = client.post(
            '/api/v1/template/preview',
            json={
                "product_info": {"title_en": "Bottle"},
                "selling_points": [],
                "site": "ZZ",
            },
            headers=auth_header,
        )
        body = resp.get_json()
        assert body['code'] == 0
        assert len(body['data']['warnings']) >= 1
        assert body['data']['site']['site'] == 'US'


class TestOptions:
    def test_options_success(self, client, auth_header):
        """options 返回站点/场景/图型"""
        resp = client.get('/api/v1/template/options', headers=auth_header)
        body = resp.get_json()
        assert resp.status_code == 200
        assert body['code'] == 0
        data = body['data']
        assert len(data['sites']) >= 12
        assert len(data['scenes']) >= 15
        assert data['image_types'] == ['main', 'scene', 'detail']
        # 站点条目包含语言与 RTL 标记
        us = next(s for s in data['sites'] if s['site'] == 'US')
        assert us['language'] == 'English'
        assert us['rtl'] is False
        sa = next(s for s in data['sites'] if s['site'] == 'SA')
        assert sa['rtl'] is True

    def test_options_frontend_contract_fields(self, client, auth_header):
        """回归 C1：站点条目须同时提供前端契约字段 code/name/isRtl

        前端站点选择器与批量提交依赖 {code, name, isRtl}，字段缺失会
        导致下拉空白与 siteCodeToMarket(undefined) TypeError。
        """
        resp = client.get('/api/v1/template/options', headers=auth_header)
        data = resp.get_json()['data']

        us = next(s for s in data['sites'] if s['site'] == 'US')
        assert us['code'] == 'us'                 # 契约：小写站点码
        assert us['name'] and '(' in us['name']   # 契约：中文展示名（如"美国站 (US)"）
        assert us['isRtl'] is False

        sa = next(s for s in data['sites'] if s['site'] == 'SA')
        assert sa['isRtl'] is True

        # 每个站点均须可被前端归一化（code/name 非空）
        for site in data['sites']:
            assert site['code'] and site['name']
