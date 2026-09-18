"""品类定义与元数据 - 为各品类提供专业默认参数"""

PRODUCT_CATEGORIES = {
    "electronics": {
        "name_cn": "3C 电子",
        "aliases": ["electronics", "electronic", "gadget", "phone", "laptop", "headphone", "speaker", "camera", "watch", "digital",
                     "电子", "手机", "电脑", "耳机", "音箱", "相机", "手表", "数码", "平板", "充电", "数据线", "键盘", "鼠标"],
        "typical_materials": "metal, glass, matte plastic, LED indicators, brushed aluminum, anodized finish",
        "lighting_default": "cool-toned studio lighting with rim highlights, softbox key light at 45 degrees, accent light for edge definition",
        "camera_default": "85mm macro lens, f/11 aperture, sharp focus, product photography, no depth of field",
        "style_default": "futuristic, clean, professional, minimalist, tech",
        "quality_default": "ray tracing, photorealistic, 8K, hyper-detailed, product surface texture visible",
        "negative_default": "blurry, distorted, screen glare, fingerprints, dust, messy cables, reflections on screen, perspective distortion, lens flare, chromatic aberration",
    },
    "fashion": {
        "name_cn": "服饰鞋包",
        "aliases": ["fashion", "clothing", "apparel", "shoes", "bag", "dress", "t-shirt", "jacket", "sneaker", "accessory", "jewelry",
                     "服装", "服饰", "衣服", "鞋", "包", "裙子", "夹克", "运动鞋", "首饰", "珠宝", "配饰", "帽子", "围巾", "皮带", "袜子"],
        "typical_materials": "fabric, leather, suede, cotton, silk, denim, wool, knit, canvas, synthetic textile",
        "lighting_default": "soft diffused natural light, warm tone, large softbox overhead, fill light from front for shadow reduction",
        "camera_default": "50mm, f/2.8-f/4, shallow depth of field for background blur, fashion editorial photography",
        "style_default": "elegant, lifestyle, editorial, warm, sophisticated, modern",
        "quality_default": "photorealistic, fabric texture visible, stitching detail, 8K, commercial fashion grade",
        "negative_default": "wrinkled, deformed, wrong proportions, missing limbs, floating garments, distorted fabric, mannequin visible, overexposed, harsh shadows on face",
    },
    "home_garden": {
        "name_cn": "家居园艺",
        "aliases": ["home", "garden", "furniture", "decor", "lamp", "rug", "vase", "plant", "cushion", "shelf", "kitchen", "bathroom",
                     "家居", "家具", "园艺", "装饰", "灯", "地毯", "花瓶", "植物", "抱枕", "架子", "厨房", "浴室", "窗帘", "床上用品", "餐具"],
        "typical_materials": "wood, ceramic, glass, cotton, linen, metal, rattan, bamboo, marble, porcelain",
        "lighting_default": "warm natural window light, soft ambient fill, gentle golden hour tone, cozy atmosphere",
        "camera_default": "35mm, f/4-f/5.6, medium depth of field, interior design photography, wide angle for room context",
        "style_default": "cozy, Scandinavian, modern, warm, natural, inviting, minimalist",
        "quality_default": "photorealistic, natural material texture, 8K, interior design grade, soft shadows",
        "negative_default": "cluttered, messy, distorted proportions, harsh shadows, cold sterile look, overexposed windows, reflection on glass surfaces",
    },
    "beauty": {
        "name_cn": "美妆个护",
        "aliases": ["beauty", "cosmetics", "skincare", "makeup", "perfume", "lipstick", "cream", "serum", "fragrance", "personal care",
                     "美妆", "化妆品", "护肤", "化妆", "香水", "口红", "面霜", "精华", "个护", "洗面奶", "面膜", "粉底", "眼影"],
        "typical_materials": "glass bottle, acrylic, cream texture, metallic cap, frosted glass, liquid, gel, powder",
        "lighting_default": "soft beauty dish lighting, ring light for catchlight, diffused overhead, clean white light with slight warmth",
        "camera_default": "100mm macro, f/8-f/11, sharp focus on product labeling, beauty product photography",
        "style_default": "luxurious, clean, elegant, fresh, premium, minimalist",
        "quality_default": "photorealistic, glass transparency, liquid texture, 8K, cosmetic commercial grade, label text crisp",
        "negative_default": "smudges, fingerprints on glass, dust, uneven lighting, color cast, distorted labels, reflections obscuring text",
    },
    "food_beverage": {
        "name_cn": "食品饮料",
        "aliases": ["food", "beverage", "drink", "snack", "coffee", "tea", "chocolate", "candy", "supplement", "nutrition", "wine", "beer",
                     "食品", "饮料", "零食", "咖啡", "茶", "巧克力", "糖果", "保健品", "营养", "酒", "啤酒", "饼干", "面包", "牛奶", "果汁"],
        "typical_materials": "food texture, liquid, glass, ceramic, paper packaging, metal can, plastic wrap, fresh ingredients",
        "lighting_default": "warm natural light, side-backlight for rim glow, soft fill from front, food photography style",
        "camera_default": "100mm macro, f/2.8-f/5.6, selective focus on hero element, food photography, slight bokeh background",
        "style_default": "appetizing, fresh, vibrant, warm, artisanal, mouth-watering",
        "quality_default": "photorealistic, food texture visible, fresh ingredients, 8K, commercial food photography, steam and gloss effects",
        "negative_default": "artificial colors, plastic-looking, melted, spoiled, unappetizing presentation, burnt, over-saturated, fake-looking, CGI artificial look",
    },
    "sports_outdoor": {
        "name_cn": "运动户外",
        "aliases": ["sports", "outdoor", "fitness", "camping", "hiking", "bike", "yoga", "tent", "backpack", "running", "swimming", "exercise",
                     "运动", "户外", "健身", "露营", "登山", "自行车", "瑜伽", "帐篷", "背包", "跑步", "游泳", "锻炼", "球类", "钓具", "滑雪"],
        "typical_materials": "nylon, rubber, mesh, carbon fiber, silicone, waterproof fabric, aluminum, EVA foam, neoprene",
        "lighting_default": "dynamic natural daylight, strong directional light, outdoor atmosphere, high contrast for texture emphasis",
        "camera_default": "24-70mm, f/5.6-f/8, action photography, outdoor sports style, dynamic composition",
        "style_default": "dynamic, energetic, rugged, outdoor, adventure, athletic",
        "quality_default": "photorealistic, material texture visible, 8K, outdoor product photography, dynamic motion feel",
        "negative_default": "blurry motion, flat lighting, studio look, unnatural poses, artificial background, indoor setting",
    },
    "general": {
        "name_cn": "通用",
        "aliases": [],
        "typical_materials": "various materials",
        "lighting_default": "professional studio lighting, softbox key light, fill light for shadow reduction",
        "camera_default": "50mm, f/8, product photography, sharp focus",
        "style_default": "professional, clean, commercial",
        "quality_default": "8K, photorealistic, commercial grade",
        "negative_default": "blurry, distorted, watermark, text overlay, low quality, pixelated",
    },
}


def detect_category(product_name: str = "", product_category: str = "", task_name: str = "") -> str:
    """
    从商品名称/类目/任务名称中检测品类

    返回品类 key（如 "electronics"），未匹配返回 "general"
    """
    search_text = f"{product_name} {product_category} {task_name}".lower()

    for cat_key, cat_info in PRODUCT_CATEGORIES.items():
        if cat_key == "general":
            continue
        for alias in cat_info.get("aliases", []):
            if alias in search_text:
                return cat_key

    return "general"


def get_category_defaults(category: str) -> dict:
    """获取品类默认值，品类不存在时返回 general 默认值"""
    return PRODUCT_CATEGORIES.get(category, PRODUCT_CATEGORIES["general"])