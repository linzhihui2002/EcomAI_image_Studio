"""提示词结构规范与最佳实践指南"""

# ── 提示词结构顺序规范 ──
PROMPT_STRUCTURE_ORDER = [
    "subject",       # 商品主体描述
    "environment",   # 场景/背景
    "lighting",      # 光影方案
    "camera",        # 相机参数
    "style",         # 风格关键词
    "quality",       # 质量增强词
    "negative",      # 负面提示词
    "copy",          # 文案覆盖（可选，仅文案类图片类型）
]

# ── 质量增强词库（按级别）──
QUALITY_BOOSTERS = {
    "standard": "8K resolution, professional product photography",
    "premium": "8K, photorealistic, ray tracing, hyper-detailed, commercial grade",
    "luxury": "8K, photorealistic, ray tracing, hyper-detailed, V-ray render quality, magazine cover quality, award-winning commercial photography",
}

# ── 平台特定要求 ──
PLATFORM_REQUIREMENTS = {
    "Amazon": {
        "bg_requirement": "pure white background (RGB 255,255,255), product occupies 85%+ of frame",
        "no_props": True,
        "no_text": True,
        "style_note": "clean catalog style, front-facing preferred",
    },
    "AliExpress": {
        "bg_requirement": "white or light background, product occupies 70%+ of frame",
        "no_props": False,
        "no_text": False,
        "style_note": "colorful and engaging, can include infographics",
    },
    "Shopee": {
        "bg_requirement": "white background preferred, product occupies 70%+ of frame",
        "no_props": False,
        "no_text": False,
        "style_note": "clean with optional promotional text overlay",
    },
    "Lazada": {
        "bg_requirement": "pure white background, product occupies 70%+ of frame",
        "no_props": False,
        "no_text": False,
        "style_note": "professional e-commerce photography",
    },
    "TikTok Shop": {
        "bg_requirement": "lifestyle or creative background",
        "no_props": False,
        "no_text": False,
        "style_note": "vertical composition, vibrant colors, lifestyle context, engaging visual",
    },
    "Temu": {
        "bg_requirement": "white or clean background",
        "no_props": False,
        "no_text": False,
        "style_note": "clean, affordable look, simple presentation",
    },
    "Shein": {
        "bg_requirement": "white or neutral background",
        "no_props": False,
        "no_text": False,
        "style_note": "fashion-forward, trendy, model shots preferred",
    },
    "Walmart": {
        "bg_requirement": "white background, product occupies 75%+ of frame",
        "no_props": True,
        "no_text": True,
        "style_note": "clean, professional catalog style",
    },
    "eBay": {
        "bg_requirement": "white or light background",
        "no_props": False,
        "no_text": False,
        "style_note": "clear product presentation",
    },
    "Etsy": {
        "bg_requirement": "lifestyle or styled background",
        "no_props": False,
        "no_text": False,
        "style_note": "handcrafted, artisanal, warm and personal aesthetic",
    },
}

# ── 负面提示词库（按品类）──
NEGATIVE_PROMPTS = {
    "electronics": "blurry, distorted, screen glare, fingerprints, dust, messy cables, reflections on screen, perspective distortion, lens flare, chromatic aberration, low resolution, pixelated, watermark, text overlay",
    "fashion": "wrinkled, deformed, wrong proportions, missing limbs, floating garments, distorted fabric, mannequin visible, overexposed, harsh shadows on face, low quality, pixelated, watermark, text overlay",
    "home_garden": "cluttered, messy, distorted proportions, harsh shadows, cold sterile look, overexposed windows, reflection on glass surfaces, low quality, pixelated, watermark, text overlay",
    "beauty": "smudges, fingerprints on glass, dust, uneven lighting, color cast, distorted labels, reflections obscuring text, low quality, pixelated, watermark, text overlay",
    "food_beverage": "artificial colors, plastic-looking, melted, spoiled, unappetizing presentation, burnt, over-saturated, fake-looking, CGI artificial look, low quality, pixelated, watermark, text overlay",
    "sports_outdoor": "blurry motion, flat lighting, studio look, unnatural poses, artificial background, indoor setting, low quality, pixelated, watermark, text overlay",
    "general": "blurry, distorted, watermark, text overlay, low quality, pixelated, deformed, ugly, extra limbs, missing parts",
}


def get_platform_style_suffix(platform: str) -> str:
    """获取平台风格描述（不含白底要求），用于所有图片类型"""
    req = PLATFORM_REQUIREMENTS.get(platform)
    if not req:
        return ""
    return req["style_note"]


def get_platform_bg_requirement(platform: str) -> str:
    """获取平台白底要求，仅用于白底图模板"""
    req = PLATFORM_REQUIREMENTS.get(platform)
    if not req:
        return ""
    return req.get("bg_requirement", "")


def get_platform_prompt_suffix(platform: str) -> str:
    """获取平台特定的提示词后缀（兼容旧接口，合并风格+白底要求）"""
    req = PLATFORM_REQUIREMENTS.get(platform)
    if not req:
        return ""
    parts = [req["style_note"]]
    if req.get("bg_requirement"):
        parts.append(req["bg_requirement"])
    return ", ".join(parts)


def get_negative_prompt(category: str = "general") -> str:
    """获取品类特定的负面提示词"""
    return NEGATIVE_PROMPTS.get(category, NEGATIVE_PROMPTS["general"])


def get_quality_booster(level: str = "premium") -> str:
    """获取质量增强词"""
    return QUALITY_BOOSTERS.get(level, QUALITY_BOOSTERS["premium"])


def get_full_negative_prompt(category: str = "general", platform: str = "") -> str:
    """获取完整的负面提示词（品类 + 通用）"""
    parts = [get_negative_prompt(category)]
    if platform and platform in PLATFORM_REQUIREMENTS:
        req = PLATFORM_REQUIREMENTS[platform]
        if req.get("no_text"):
            parts.append("text, words, letters, typography, watermark, logo")
        if req.get("no_props"):
            parts.append("props, accessories, extra objects, additional items")
    return ", ".join(parts)