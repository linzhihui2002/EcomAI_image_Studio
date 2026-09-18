"""批次级风格锁定（Style Lock，P1-2）

纯函数模块：无 DB / 网络 / 随机副作用，同输入恒同输出（确定性）。
derive_style_lock 从商品品类 / 场景 / 用户风格提示派生批次级统一视觉风格
约束（英文），供批量套图（run_batch_task 开始时派生一次）与专业模式
（批次确认生图路径派生一次）前置到本批次所有生图 prompt，
保证同批次成图风格一致。

输出格式：以 "STYLE LOCK: " 开头的一段英文约束（≤ MAX_WORDS 词），
涵盖统一色板（主色调描述）、光线、构图风格与整体氛围；
user_hint 透传用户自定义风格提示（截断保序），超预算时优先舍弃 hint。
"""
from typing import Any

# 输出前缀与词数上限
STYLE_LOCK_PREFIX = 'STYLE LOCK: '
MAX_WORDS = 60
_HINT_MAX_CHARS = 40

# 品类 → 风格要素（关键词子串匹配，小写；中英双语）
# palette: 统一色板（主色调描述）；lighting: 默认光线；mood: 整体氛围
_CATEGORY_STYLES = {
    'electronics': {
        'keywords': ('electronic', 'headphone', 'earbud', 'phone', 'charger',
                     'keyboard', 'mouse', 'camera', 'speaker', 'laptop',
                     'cable', 'gadget', '电子', '耳机', '手机', '充电', '键盘',
                     '鼠标', '相机', '音箱', '电脑'),
        'palette': 'a cool neutral palette of clean greys, blacks and silver accents',
        'lighting': 'soft studio lighting with subtle specular highlights',
        'mood': 'sleek modern high-tech',
    },
    'beauty': {
        'keywords': ('beauty', 'skin', 'cosmetic', 'serum', 'cream', 'makeup',
                     'lipstick', 'perfume', 'shampoo', '美妆', '护肤',
                     '化妆品', '口红', '香水', '精华', '面膜'),
        'palette': 'a soft pastel palette with blush pink and cream tones',
        'lighting': 'bright airy lighting with a gentle glow',
        'mood': 'fresh elegant',
    },
    'home': {
        'keywords': ('home', 'kitchen', 'cook', 'pan', 'mug', 'cup', 'bottle',
                     'lamp', 'pillow', 'blanket', 'furniture', 'storage',
                     'towel', '家居', '厨房', '锅', '杯', '灯', '收纳', '枕头',
                     '毛巾'),
        'palette': 'a warm neutral palette with soft earth and beige tones',
        'lighting': 'soft warm lighting with natural shadows',
        'mood': 'cozy inviting',
    },
    'food': {
        'keywords': ('food', 'snack', 'tea', 'coffee', 'chocolate', 'candy',
                     'baking', '食品', '零食', '茶', '咖啡', '巧克力', '烘焙'),
        'palette': 'an appetizing warm palette with rich golden and brown tones',
        'lighting': 'bright appetizing lighting with soft highlights',
        'mood': 'fresh and tasty',
    },
    'outdoor': {
        'keywords': ('outdoor', 'sport', 'fitness', 'camping', 'hiking',
                     'yoga', 'bike', 'running', '户外', '运动', '健身', '露营',
                     '瑜伽', '骑行'),
        'palette': 'a vivid energetic palette with saturated accent colors',
        'lighting': 'bright natural daylight with crisp contrast',
        'mood': 'active and dynamic',
    },
    'apparel': {
        'keywords': ('shirt', 'dress', 'apparel', 'clothing', 'wear', 'sock',
                     'hat', 'scarf', '服装', '衣服', '袜', '帽', '围巾'),
        'palette': 'a clean neutral palette with soft fabric tones',
        'lighting': 'soft even lighting with gentle falloff',
        'mood': 'casual premium',
    },
    'toy': {
        'keywords': ('toy', 'kids', 'baby', 'children', 'puzzle',
                     '玩具', '儿童', '婴儿', '拼图'),
        'palette': 'a playful bright palette with cheerful primary colors',
        'lighting': 'bright soft lighting with lively color rendering',
        'mood': 'fun and cheerful',
    },
    'jewelry': {
        'keywords': ('jewelry', 'necklace', 'ring', 'bracelet', 'earring',
                     'watch', 'diamond', '首饰', '项链', '戒指', '手链', '手表',
                     '钻'),
        'palette': 'a luxurious palette with deep charcoal and champagne gold accents',
        'lighting': 'precise studio lighting with controlled sparkle highlights',
        'mood': 'luxurious refined',
    },
}

# 未命中品类时的兜底风格
_DEFAULT_STYLE = {
    'palette': 'a clean neutral palette with muted tones',
    'lighting': 'soft studio lighting',
    'mood': 'premium minimal',
}

# 场景关键词 → 光线覆盖（命中则覆盖品类默认光线）
_SCENE_LIGHTING_OVERRIDES = (
    (('outdoor', 'beach', 'garden', 'street', 'park', 'picnic',
      '户外', '海滩', '庭院', '公园', '野餐'),
     'bright natural daylight'),
    (('kitchen', 'living room', 'bedroom', 'cozy', 'home',
      '厨房', '客厅', '卧室', '居家'),
     'warm cozy home lighting'),
    (('office', 'desk', 'workspace', 'studio',
      '办公', '书桌', '工作室'),
     'clean bright workspace lighting'),
    (('bathroom', 'spa', 'shower',
      '浴室', '沐浴', '水疗'),
     'soft diffused bright lighting'),
)


def _text_of(product_info: Any) -> str:
    """拼接商品信息中的品类线索文本（dict / 对象均支持，全部小写）"""
    def _get(name: str) -> Any:
        if isinstance(product_info, dict):
            return product_info.get(name)
        return getattr(product_info, name, None)

    parts = [str(_get(name) or '') for name in
             ('product_category', 'category', 'title_en', 'product_name_en',
              'product_name', 'title')]
    return ' '.join(parts).lower()


def _match_category(product_info: Any) -> dict:
    """按品类关键词命中风格要素；未命中返回默认风格"""
    text = _text_of(product_info)
    if text:
        for style in _CATEGORY_STYLES.values():
            if any(k in text for k in style['keywords']):
                return style
    return _DEFAULT_STYLE


def _scene_lighting(scene_zh: Any) -> str:
    """场景关键词 → 光线覆盖片段；未命中返回空串"""
    text = str(scene_zh or '').lower()
    if not text:
        return ''
    for keywords, lighting in _SCENE_LIGHTING_OVERRIDES:
        if any(k in text for k in keywords):
            return lighting
    return ''


def _clean_hint(user_hint: Any) -> str:
    """清洗用户风格提示：压平空白并截断（保序，确定性）"""
    hint = ' '.join(str(user_hint or '').split())
    return hint[:_HINT_MAX_CHARS].strip()


def derive_style_lock(product_info: Any, scene_zh: Any, platform: Any = None,
                      user_hint: Any = None) -> str:
    """派生批次级风格锁定文本（确定性：同输入恒同输出，无随机）

    Args:
        product_info: 商品信息（dict/对象，读取品类/标题线索）
        scene_zh: 中文场景名（影响光线选择）
        platform: 平台（可选，追加 marketplace 风格要求）
        user_hint: 用户风格提示（可选，透传截断；超词数预算时优先舍弃）

    Returns:
        以 "STYLE LOCK: " 开头的英文约束段（≤ MAX_WORDS 词），
        涵盖统一色板 / 光线 / 构图 / 整体氛围。
    """
    style = _match_category(product_info)
    lighting = _scene_lighting(scene_zh) or style['lighting']

    parts = [
        f"unified color palette: {style['palette']}",
        f'lighting: {lighting}',
        'composition: centered product framing with consistent negative space',
        f"overall atmosphere: {style['mood']}",
    ]
    plat = str(platform or '').strip().lower().replace(' ', '_')
    if plat:
        parts.append(f'clean marketplace-ready look for {plat}')
    hint = _clean_hint(user_hint)
    if hint:
        parts.append(f'style hint: {hint}')

    lock = STYLE_LOCK_PREFIX + 'Apply consistently across this batch: ' \
        + '; '.join(parts) + '.'
    if len(lock.split()) > MAX_WORDS and hint:
        # 词数超预算：舍弃 hint 后重建（保持 ≤ MAX_WORDS）
        parts.pop()
        lock = STYLE_LOCK_PREFIX + 'Apply consistently across this batch: ' \
            + '; '.join(parts) + '.'
    return lock
