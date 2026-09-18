"""提示词构建器 - 结构化提示词构建，支持品类自适应和平台感知"""
import os
from typing import Dict, Optional, Any, List
from models.generation_task import ImageType, PromptScheme
from prompts.pro.guidelines import (
    get_quality_booster,
    get_full_negative_prompt,
    get_platform_style_suffix,
    get_platform_bg_requirement,
    get_platform_prompt_suffix,
    PLATFORM_REQUIREMENTS,
)
from prompts.pro.templates.categories import detect_category, get_category_defaults


def _build_aspect_ratio_instruction(size: str) -> str:
    """根据尺寸字符串生成比例约束指令，确保生图模型遵循指定宽高比"""
    try:
        parts = size.split('x')
        w, h = int(parts[0]), int(parts[1])
        if w == h:
            return "square format, 1:1 aspect ratio, perfectly square composition"
        elif w > h:
            ratio = round(w / h, 1)
            return f"landscape format, {ratio}:1 aspect ratio, horizontal composition"
        else:
            ratio = round(h / w, 1)
            return f"portrait format, 1:{ratio}:1 aspect ratio, vertical composition"
    except Exception:
        return "square format, 1:1 aspect ratio"


class PromptBuilder:
    """根据图片类型加载对应模板，自动注入品类/平台/质量/负面提示词"""

    # 模板目录：prompts/（富模板，支持全部结构化变量注入）
    TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))
    ZH_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zh')

    TEMPLATE_MAP = {
        ImageType.MAIN_IMAGE: "main_image.txt",
        ImageType.SUB_IMAGE: "sub_image.txt",
        ImageType.WHITE_BG: "white_bg.txt",
        ImageType.SCENE: "scene.txt",
        ImageType.SELLING_POINT: "selling_point.txt",
        ImageType.CHECKLIST: "checklist.txt",
        ImageType.MATERIAL: "material.txt",
        ImageType.SIZE_CHART: "size_chart.txt",
        ImageType.OTHER: "other.txt",
    }

    # ── 图片类型 → 差异化默认值 ──

    MAIN_IMAGE_DEFAULTS = {
        "product_state": "hero shot, front-facing angle",
        "composition": "product centered, occupies 85%+ of frame, clean minimal composition",
        "background_description": "pure white seamless background",
    }

    SUB_IMAGE_DEFAULTS = {
        "product_state": "alternate angle view, showcasing product details and texture",
        "composition": "product centered, multi-angle presentation",
        "background_description": "pure white or light background",
    }

    # 白底图：固定纯白背景规范
    WHITE_BG_DEFAULTS = {
        "product_state": "front view, multi-angle presentation",
        "composition": "product centered, occupies 85%+ of frame, clean minimal composition",
        "background_description": "pure white seamless background",
    }

    # 场景图：生活化场景
    SCENE_DEFAULTS = {
        "product_state": "in natural use, lifestyle context, showing the product being used by the target audience in a real-world setting",
        "composition": "rule of thirds composition, product positioned naturally in the scene, balanced visual weight, depth of field with environment context",
        "background_description": "carefully styled authentic environment matching the product's intended use case, with complementary props and natural elements that enhance the product's appeal without distracting",
    }

    # 卖点图：营销展示
    SELLING_POINT_DEFAULTS = {
        "product_state": "hero shot, featured angle",
        "composition": "close-up detail layout, infographic style poster composition",
        "background_description": "clean marketing background, gradient or subtle texture",
    }

    # 清单图：网格布局
    CHECKLIST_DEFAULTS = {
        "product_state": "organized list layout showcasing package contents",
        "composition": "grid layout with icons and bullet points, each item with image and name",
        "background_description": "clean simple background",
    }

    # 材质图：微距特写
    MATERIAL_DEFAULTS = {
        "product_state": "close-up macro shots highlighting material texture",
        "composition": "split layout with product image and material callouts",
        "background_description": "neutral professional background",
    }

    # 尺寸图：尺寸标注
    SIZE_CHART_DEFAULTS = {
        "product_state": "product shown with scale reference",
        "composition": "clean measurement diagram with dimension annotations, dimension lines and arrows",
        "background_description": "clean simple background",
    }

    # 其他图：通用
    OTHER_DEFAULTS = {
        "product_state": "professional presentation",
        "composition": "clean commercial layout",
        "background_description": "neutral professional background",
    }

    def __init__(self):
        self._cache: Dict[str, str] = {}

    def _load_template(self, image_type: ImageType, language: str = "en") -> str:
        """加载模板文件（带缓存）"""
        cache_key = f"{language}:{image_type.value}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        filename = self.TEMPLATE_MAP.get(image_type)
        if not filename:
            raise ValueError(f"未知的图片类型: {image_type}")

        template_dir = self.ZH_TEMPLATE_DIR if language == "zh" else self.TEMPLATE_DIR
        filepath = os.path.join(template_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"模板文件不存在: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            template = f.read().strip()

        self._cache[cache_key] = template
        return template

    # ── 品类 + 平台 推断 ──

    def _resolve_category(self, variables: Dict[str, str]) -> str:
        """
        从 variables 中推断品类 key

        优先级：product_category > product_name 推导 > general
        """
        product_category = variables.get("product_category", "")
        product_name = variables.get("product_name", "")
        return detect_category(
            product_name=product_name,
            product_category=product_category,
        )

    def _enrich_variables(
        self,
        image_type: ImageType,
        variables: Dict[str, str],
    ) -> Dict[str, str]:
        """
        根据图片类型、品类、平台，补全所有结构化变量
        """
        category = self._resolve_category(variables)
        cat_defaults = get_category_defaults(category)
        platform = variables.get("platform", "")
        region = variables.get("region", "")

        # 图片类型差异化默认值
        type_defaults = self._get_type_defaults(image_type)

        # 平台信息
        platform_req = PLATFORM_REQUIREMENTS.get(platform, {})
        platform_style = get_platform_style_suffix(platform)
        platform_bg = get_platform_bg_requirement(platform)

        # 市场审美风格（从平台推断）
        market_style = platform_req.get("style_note", "professional e-commerce")

        # 视觉焦点（从卖点或品类推断）
        visual_focus = variables.get("visual_focus", "")
        if not visual_focus:
            selling_points = variables.get("selling_points", "")
            if selling_points and selling_points != "高品质":
                # 取第一个卖点作为视觉焦点
                first_point = selling_points.split("/")[0].strip()
                visual_focus = first_point
            else:
                visual_focus = variables.get("product_name", "product details")

        enriched = {
            # 已有变量直接传递
            "product_name": variables.get("product_name", "商品"),
            "target_audience": variables.get("target_audience", ""),
            "selling_points": variables.get("selling_points", "高品质"),
            "usage_scenario": variables.get("usage_scenario", "日常使用"),
            "product_category": variables.get("product_category", "通用"),
            "platform": platform,
            "region": region,
            "target_language": variables.get("target_language", "English"),
            "slot_name": variables.get("slot_name", ""),
            "slot_desc": variables.get("slot_desc", ""),

            # 品类自动推断
            "material_texture": cat_defaults.get("typical_materials", "various materials"),
            "category_attributes": self._build_category_attributes(cat_defaults),
            "lighting_setup": cat_defaults.get("lighting_default", "professional studio lighting"),
            "camera_spec": cat_defaults.get("camera_default", "50mm, f/8, product photography, sharp focus"),
            "style_keywords": cat_defaults.get("style_default", "professional, clean, commercial"),

            # 图片类型差异化（用户方案优先，否则使用默认值）
            "product_state": variables.get("product_state") or type_defaults.get("product_state", "professional presentation"),
            "composition": variables.get("composition") or type_defaults.get("composition", "clean commercial layout"),
            "background_description": variables.get("background_description") or type_defaults.get("background_description", "neutral professional background"),

            # 质量增强
            "quality_boosters": get_quality_booster("premium"),

            # 平台要求
            "platform_style": platform_style,
            "platform_bg_requirement": platform_bg,
            "market_style": market_style,

            # 视觉焦点
            "visual_focus": visual_focus,

            # 尺寸/比例约束
            "size": variables.get("size", "1024x1024"),
            "aspect_ratio_instruction": _build_aspect_ratio_instruction(
                variables.get("size", "1024x1024")
            ),

            # 负面提示词（品类 + 平台）
            "negative_prompt": get_full_negative_prompt(category, platform),
        }

        return enriched

    def _build_category_attributes(self, cat_defaults: dict) -> str:
        """构建品类属性描述"""
        style = cat_defaults.get("style_default", "")
        name_cn = cat_defaults.get("name_cn", "")

        if "tech" in style or "futuristic" in style:
            return "sleek modern design with premium finish"
        elif "elegant" in style or "luxurious" in style:
            return "elegant design with refined details"
        elif "cozy" in style or "natural" in style:
            return "natural aesthetic with organic textures"
        elif "dynamic" in style or "energetic" in style:
            return "dynamic design with sporty appeal"
        elif "appetizing" in style or "fresh" in style:
            return "fresh and appetizing presentation"
        else:
            return f"professional {name_cn} design" if name_cn else "professional product design"

    def _get_type_defaults(self, image_type: ImageType) -> dict:
        """获取图片类型差异化默认值"""
        if image_type == ImageType.MAIN_IMAGE:
            return self.MAIN_IMAGE_DEFAULTS
        elif image_type == ImageType.SUB_IMAGE:
            return self.SUB_IMAGE_DEFAULTS
        elif image_type == ImageType.WHITE_BG:
            return self.WHITE_BG_DEFAULTS
        elif image_type == ImageType.SCENE:
            return self.SCENE_DEFAULTS
        elif image_type == ImageType.SELLING_POINT:
            return self.SELLING_POINT_DEFAULTS
        elif image_type == ImageType.CHECKLIST:
            return self.CHECKLIST_DEFAULTS
        elif image_type == ImageType.MATERIAL:
            return self.MATERIAL_DEFAULTS
        elif image_type == ImageType.SIZE_CHART:
            return self.SIZE_CHART_DEFAULTS
        return self.OTHER_DEFAULTS

    # ── 公共 API ──

    def build_structured(
        self,
        image_type: ImageType,
        variables: Dict[str, str],
        extra_context: Optional[Dict[str, str]] = None,
        language: str = "en",
    ) -> str:
        """
        构建结构化提示词

        自动完成：
        1. 品类检测 → 材质/光影/相机/风格
        2. 平台感知 → 平台要求/市场审美
        3. 质量增强 → premium 级质量词
        4. 负面提示词 → 品类 + 平台双重负面
        5. 图片类型差异化
        """
        all_vars = {**variables}
        if extra_context:
            all_vars.update(extra_context)

        # 针对 other 类型的特殊处理：尺寸图/对比图注入专项指令
        if image_type == ImageType.OTHER:
            slot_name = (
                (extra_context or {}).get("slot_name", "")
                or variables.get("slot_name", "")
            )
            slot_desc = (
                (extra_context or {}).get("slot_desc", "")
                or variables.get("slot_desc", "")
            )
            target_language = variables.get("target_language", "English")

            if "尺寸图" in slot_name or "size chart" in slot_name.lower() or "尺寸" in slot_name:
                if extra_context is None:
                    extra_context = {}
                extra_context["slot_name"] = slot_name
                extra_context["slot_desc"] = (
                    f"Create a professional size chart / dimension diagram. "
                    f"ALL text, labels, numbers, and measurement units in the image MUST be in {target_language}. "
                    f"Include clear dimension lines, arrows, and annotated measurements. "
                    f"Additional requirements: {slot_desc}"
                )
                all_vars.update(extra_context)
            elif "对比图" in slot_name or "comparison" in slot_name.lower() or "对比" in slot_name:
                if extra_context is None:
                    extra_context = {}
                extra_context["slot_name"] = slot_name
                extra_context["slot_desc"] = (
                    f"Create a professional comparison chart. "
                    f"Place products side by side for visual comparison. "
                    f"ALL text, labels, comparison annotations, and feature callouts in the image MUST be in {target_language}. "
                    f"Include clear comparison labels, feature highlights, and visual markers (checkmarks, arrows, etc.) to emphasize differences. "
                    f"Additional requirements: {slot_desc}"
                )
                all_vars.update(extra_context)
            else:
                # 通用 other 类型也加入语言要求
                if extra_context is None:
                    extra_context = {}
                extra_context["slot_desc"] = (
                    f"ALL text and labels in the image MUST be in {target_language}. "
                    f"Additional requirements: {slot_desc}"
                )
                all_vars.update(extra_context)

        # 注入品类/平台/质量/负面等结构化变量
        enriched = self._enrich_variables(image_type, all_vars)

        # 加载模板
        template = self._load_template(image_type, language)

        # 变量替换（缺失变量保留占位符）
        class _Defaults(dict):
            def __missing__(self, key):
                return f'{{{key}}}'

        result = template.format_map(_Defaults(enriched))

        # 后处理：清理多余的空行和空格
        lines = [line.strip() for line in result.split('\n') if line.strip()]
        return "\n".join(lines)

    def build_from_scheme(
        self,
        image_type: ImageType,
        scheme: PromptScheme,
        base_variables: Dict[str, str],
        language: str = "en",
    ) -> str:
        """
        基于专业模式的 PromptScheme 构建生图提示词

        将方案中的排版字段、文案字段注入到基础变量中，
        再调用 build_structured 完成品类/平台/质量/负面等增强。

        Args:
            image_type: 图片类型
            scheme: 提示词方案（含排版/文案）
            base_variables: 基础变量（product_name, platform, region, target_language 等）

        Returns:
            完整的结构化生图提示词
        """
        variables = {**base_variables}
        layout = scheme.layout_prompt

        # 排版变量注入（用户方案优先）
        if layout.product_state:
            variables["product_state"] = layout.product_state
        if layout.composition:
            variables["composition"] = layout.composition
        if layout.background:
            variables["background_description"] = layout.background
        if layout.visual_focus:
            variables["visual_focus"] = layout.visual_focus

        # 文案变量注入（卖点图、清单图、尺寸图等文案密集型）
        copy = scheme.copy
        copy_parts: List[str] = []
        if copy.main_title:
            copy_parts.append(f"Main title: {copy.main_title}")
        if copy.sub_title:
            copy_parts.append(f"Subtitle: {copy.sub_title}")
        if copy.tags:
            copy_parts.append(f"Tags: {', '.join(copy.tags)}")

        target_language = base_variables.get("target_language", "English")

        # 尺寸图专项语言指令
        if image_type == ImageType.SIZE_CHART:
            copy_parts.append(
                f"ALL text, labels, numbers, and measurement units in the image MUST be in {target_language}. "
                f"Include clear dimension lines, arrows, and annotated measurements."
            )
        elif image_type == ImageType.CHECKLIST:
            copy_parts.append(
                f"ALL item names, quantities, and labels in the image MUST be in {target_language}."
            )
        elif image_type == ImageType.SELLING_POINT:
            copy_parts.append(
                f"ALL selling point text and annotations in the image MUST be in {target_language}."
            )
        elif image_type == ImageType.MATERIAL:
            copy_parts.append(
                f"ALL material property descriptions in the image MUST be in {target_language}."
            )

        # 角标
        if layout.corner_badge and layout.corner_badge.lower() not in ("none", "无", ""):
            copy_parts.append(f"Corner badge: {layout.corner_badge}")

        # 将文案部分追加为额外上下文
        extra_context: Dict[str, str] = {}
        if copy_parts:
            extra_context["slot_desc"] = " | ".join(copy_parts)

        # 图片名称作为 slot_name（用于 other 类型的分支判断）
        if scheme.image_name:
            extra_context["slot_name"] = scheme.image_name

        return self.build_structured(image_type, variables, extra_context, language)

    def build(
        self,
        image_type: ImageType,
        variables: Dict[str, str],
        extra_context: Optional[Dict[str, str]] = None,
        language: str = "en",
    ) -> str:
        """构建最终的生图提示词（向后兼容，内部调用 build_structured()）"""
        return self.build_structured(image_type, variables, extra_context, language)

    def reload(self):
        """清除模板缓存"""
        self._cache.clear()
