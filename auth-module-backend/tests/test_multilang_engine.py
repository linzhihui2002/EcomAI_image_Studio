"""多语言/多站点提示词引擎单元测试（P0-1）"""
import os
import sys
from unittest.mock import patch

import pytest

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- mock 缺失的依赖（与 test_generation.py 惯例一致）----
from unittest.mock import MagicMock
_mock_langgraph = MagicMock()
sys.modules.setdefault('langgraph', _mock_langgraph)
sys.modules.setdefault('langgraph.graph', MagicMock())

from services import multilang_engine as engine


# ── 测试数据 ──

VALID_SP = {
    "zh_title": "无线快充",
    "zh_desc": "支持无线充电，摆脱线缆束缚",
    "en_title": "Wireless Fast Charging",
    "en_desc": "Charge without cables with fast wireless charging",
    "visual_keywords": "wireless, charging pad, sleek",
}


# ── 字典映射加载 ──

class TestDictionaries:
    def test_site_languages_loaded_at_least_12(self):
        """站点字典加载：≥12 站点"""
        assert len(engine.SUPPORTED_SITES) >= 12

    def test_supported_sites_contains_required(self):
        """必含站点码：US/GB/DE/FR/JP/SA/AE/BR/MX/MY/ID/TH"""
        for site in ["US", "GB", "DE", "FR", "JP", "SA", "AE", "BR", "MX",
                     "MY", "ID", "TH", "AU", "CA"]:
            assert site in engine.SUPPORTED_SITES

    def test_scene_map_at_least_15(self):
        """场景映射：≥15 条"""
        assert len(engine.list_scenes()) >= 15

    def test_map_scene_to_env_known(self):
        """已知场景映射为英文环境描述"""
        env = engine.map_scene_to_env("居家客厅")
        assert env == "in a cozy modern living room with soft natural light"
        assert not engine.contains_chinese(env)

    def test_map_scene_to_env_unknown_fallback(self):
        """未知场景回退默认英文环境"""
        env = engine.map_scene_to_env("不存在的场景xyz")
        assert "minimalist" in env


# ── 站点解析 ──

class TestResolveSite:
    def test_resolve_site_valid_arabic_rtl(self):
        """SA 站点：阿拉伯语 + RTL + 非拉丁"""
        info = engine.resolve_site("SA")
        assert info["site"] == "SA"
        assert info["language"] == "Arabic"
        assert info["rtl"] is True
        assert info["non_latin"] is True
        assert info["warnings"] == []

    def test_resolve_site_invalid_fallback_with_warning(self):
        """非法站点回退 US 且携带 warnings"""
        info = engine.resolve_site("XX")
        assert info["site"] == "US"
        assert info["language"] == "English"
        assert len(info["warnings"]) == 1

    def test_resolve_site_empty_fallback(self):
        """空站点回退 US"""
        info = engine.resolve_site("")
        assert info["site"] == "US"
        assert len(info["warnings"]) == 1

    def test_resolve_site_lowercase_normalized(self):
        """小写站点码归一为大写"""
        assert engine.resolve_site("jp")["site"] == "JP"


# ── 卖点校验 ──

class TestValidateSellingPoint:
    def test_valid_selling_point_passes(self):
        """合法卖点不抛异常"""
        engine.validate_selling_point(VALID_SP)

    def test_missing_field_error_contains_field_name(self):
        """缺失字段：ValueError 消息含字段名"""
        sp = dict(VALID_SP)
        sp.pop("zh_title")
        with pytest.raises(ValueError) as exc:
            engine.validate_selling_point(sp)
        assert "zh_title" in str(exc.value)

    def test_visual_keywords_chinese_rejected(self):
        """visual_keywords 防中文：含中文即拒绝且报字段名"""
        sp = dict(VALID_SP, visual_keywords="无线, 充电, sleek")
        with pytest.raises(ValueError) as exc:
            engine.validate_selling_point(sp)
        assert "visual_keywords" in str(exc.value)

    def test_en_title_chinese_rejected(self):
        """en_title 混入中文拒绝"""
        sp = dict(VALID_SP, en_title="Wireless 无线充电")
        with pytest.raises(ValueError) as exc:
            engine.validate_selling_point(sp)
        assert "en_title" in str(exc.value)

    def test_validate_selling_points_batch(self):
        """批量校验：合法/非法分流"""
        bad = dict(VALID_SP, visual_keywords="中文关键词")
        valid, errors = engine.validate_selling_points([VALID_SP, bad])
        assert len(valid) == 1
        assert len(errors) == 1
        assert "visual_keywords" in errors[0]


# ── 提示词组装 ──

class TestBuildPrompt:
    def test_main_white_bg_no_text(self):
        """main 图：纯白底 RGB(255,255,255) + 无文字水印约束"""
        prompt = engine.build_prompt({"title_en": "Insulated Water Bottle"},
                                     [VALID_SP], "居家客厅", "US", "main")
        assert "RGB 255,255,255" in prompt
        assert "No text" in prompt
        assert "Insulated Water Bottle" in prompt

    def test_main_no_language_constraint(self):
        """main 图不追加文字语言约束（本就禁文字）"""
        prompt = engine.build_prompt({"title_en": "Bottle"}, [], "", "JP", "main")
        assert "garbled" not in prompt

    def test_scene_contains_english_env(self):
        """scene 图：场景映射为英文环境"""
        prompt = engine.build_prompt({"title_en": "Bottle"}, [], "海边度假",
                                     "US", "scene")
        assert "tropical beach" in prompt

    def test_scene_non_latin_garble_constraint(self):
        """JP 站点 scene 图注入防乱码约束"""
        prompt = engine.build_prompt({"title_en": "Bottle"}, [], "居家客厅",
                                     "JP", "scene")
        assert "Japanese" in prompt
        assert "garbled" in prompt

    def test_scene_rtl_site_language(self):
        """SA 站点 scene 图约束为阿拉伯语"""
        prompt = engine.build_prompt({"title_en": "Bottle"}, [], "居家客厅",
                                     "SA", "scene")
        assert "Arabic" in prompt

    def test_detail_highlight_selling_points(self):
        """detail 图：合法卖点可视化"""
        prompt = engine.build_prompt({"title_en": "Bottle"}, [VALID_SP], "",
                                     "US", "detail")
        assert "Highlight key selling points" in prompt
        assert "Wireless Fast Charging" in prompt
        assert "wireless, charging pad, sleek" in prompt

    def test_invalid_selling_points_skipped(self):
        """非法卖点被跳过，不进入提示词"""
        bad = dict(VALID_SP, visual_keywords="中文")
        prompt = engine.build_prompt({"title_en": "Bottle"}, [bad], "",
                                     "US", "detail")
        assert "Highlight key selling points" not in prompt

    def test_invalid_site_fallback_in_prompt(self):
        """非法站点构建时回退 US/English 且不抛异常"""
        prompt = engine.build_prompt({"title_en": "Bottle"}, [], "居家客厅",
                                     "ZZ", "scene")
        assert "English" in prompt

    def test_chinese_title_fallback_to_reference(self):
        """无英文标题时用参考图话术兜底"""
        prompt = engine.build_prompt({"product_name": "保温杯"}, [], "",
                                     "US", "main")
        assert "the product shown in the reference image" in prompt

    def test_normalize_image_type_aliases(self):
        """图型别名归一"""
        assert engine.normalize_image_type("white_bg") == "main"
        assert engine.normalize_image_type("main_image") == "main"
        assert engine.normalize_image_type("selling_point") == "detail"
        with pytest.raises(ValueError):
            engine.normalize_image_type("unknown_type")


# ── 约束增强工具 ──

class TestConstraints:
    def test_site_constraints_strict_mode(self):
        """严格模式：非法/中文站点返回空串"""
        assert engine.site_constraints_if_supported("美国", "scene") == ""
        assert engine.site_constraints_if_supported("", "scene") == ""
        assert engine.site_constraints_if_supported("US", "scene") != ""

    def test_prompt_constraints_for_main_white_bg(self):
        """main 约束片段含白底无文字"""
        fragment = engine.prompt_constraints_for("US", "main")
        assert "RGB 255,255,255" in fragment
        assert "no text" in fragment

    def test_append_constraint_idempotent(self):
        """约束幂等追加：重复追加不重复"""
        prompt = "A professional product photo."
        constraint = "Any text overlay in the image must be written in Japanese."
        once = engine.append_constraint(prompt, constraint)
        twice = engine.append_constraint(once, constraint)
        assert once == twice
        assert once.count(constraint) == 1


# ── build_preview 汇总 ──

class TestBuildPreview:
    def test_preview_structure(self):
        """预览返回 prompts/warnings/site 三键"""
        result = engine.build_preview(
            {"title_en": "Bottle"}, [VALID_SP], "居家客厅", "US"
        )
        assert set(result["prompts"].keys()) == {"main", "scene", "detail"}
        assert result["warnings"] == []
        assert result["site"]["site"] == "US"

    def test_preview_invalid_site_warnings(self):
        """预览携带非法站点 warning"""
        result = engine.build_preview({"title_en": "Bottle"}, [], "", "XX")
        assert len(result["warnings"]) >= 1


# ── 模型调用隔离（引擎纯函数无副作用） ──

class TestNoModelCalls:
    def test_engine_never_calls_model(self):
        """引擎构建全程不触发 generation_service 模型调用"""
        with patch('services.generation_service.analyze_product') as mock_analyze, \
             patch('services.generation_service.call_image_edit_model') as mock_call:
            engine.build_prompt({"title_en": "Bottle"}, [VALID_SP],
                                "居家客厅", "JP", "scene")
            engine.build_preview({"title_en": "Bottle"}, [VALID_SP],
                                 "海边度假", "SA")
            mock_analyze.assert_not_called()
            mock_call.assert_not_called()
