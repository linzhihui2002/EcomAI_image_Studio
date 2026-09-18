"""多语言/多站点提示词引擎（P0-1）

纯函数模块：无 DB / 网络副作用。
站点→语言、中文场景→英文环境映射外置 JSON（config/dictionaries/，运营可维护），
带 mtime 缓存支持热更新。工程化自 prototype/research-2026-09-16/multilang_prompts/engine.py
（自研实现，无 license 风险）。
"""
import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from config import Config

# ── JSON 字典加载（mtime 缓存，热更新） ──

_JSON_CACHE: Dict[str, Tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

SITE_LANGUAGES_FILE = 'site_languages.json'
SCENE_ENV_FILE = 'scene_env_mappings.json'


def _load_json_dict(filename: str) -> dict:
    """按 mtime 缓存加载字典 JSON；文件变化自动重新加载"""
    path = os.path.join(Config.SITE_DICT_PATH, filename)
    mtime = os.stat(path).st_mtime
    with _CACHE_LOCK:
        cached = _JSON_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    with _CACHE_LOCK:
        _JSON_CACHE[path] = (mtime, data)
    return data


def _site_config() -> dict:
    return _load_json_dict(SITE_LANGUAGES_FILE)


def _scene_config() -> dict:
    return _load_json_dict(SCENE_ENV_FILE)


def _site_languages() -> Dict[str, dict]:
    return _site_config().get('sites', {})


def _scene_map() -> Dict[str, str]:
    return _scene_config().get('scenes', {})


def _non_latin_sites() -> set:
    return set(_site_config().get('non_latin_sites', []))


def _default_language() -> str:
    return _site_config().get('default_language', 'English')


def _default_scene_env() -> str:
    return _scene_config().get('_meta', {}).get(
        'default_env', 'in a clean minimalist lifestyle setting'
    )


# ── 站点枚举（惰性视图：随字典热更新） ──

class _SupportedSites:
    """SUPPORTED_SITES 枚举视图：成员与迭代实时反映 JSON 字典内容"""

    def __contains__(self, item) -> bool:
        return str(item).strip().upper() in _site_languages()

    def __iter__(self):
        return iter(sorted(_site_languages().keys()))

    def __len__(self) -> int:
        return len(_site_languages())

    def __repr__(self) -> str:
        return f"SUPPORTED_SITES({sorted(_site_languages().keys())})"


SUPPORTED_SITES = _SupportedSites()

DEFAULT_SITE = 'US'
# 预览支持的图型
IMAGE_TYPES = ('main', 'scene', 'detail')
# 图型别名归一（兼容 smart/pro 模式的 ImageType 值）
_IMAGE_TYPE_ALIASES = {
    'main': 'main',
    'main_image': 'main',
    'white_bg': 'main',
    'white': 'main',
    'scene': 'scene',
    'scene_image': 'scene',
    'sub_image': 'scene',
    'detail': 'detail',
    'detail_image': 'detail',
    'selling_point': 'detail',
    'checklist': 'detail',
    'material': 'detail',
    'size_chart': 'detail',
    'other': 'scene',
}


# ── 基础工具 ──

def contains_chinese(text: Any) -> bool:
    """判断文本是否包含中日韩统一表意文字"""
    return any('\u4e00' <= ch <= '\u9fff' for ch in str(text or ''))


def normalize_image_type(image_type: str) -> str:
    """图型归一为 main/scene/detail；未知图型抛 ValueError"""
    key = str(image_type or '').strip().lower()
    if key not in _IMAGE_TYPE_ALIASES:
        raise ValueError(f"未知图型: {image_type}（支持 main/scene/detail）")
    return _IMAGE_TYPE_ALIASES[key]


# ── 双语卖点校验 ──

def validate_selling_point(sp: Any) -> None:
    """校验双语卖点结构，失败抛 ValueError（消息含字段名）

    要求：zh_title/zh_desc/en_title/en_desc 非空；en_title/en_desc 不含中文；
    visual_keywords 非空且仅英文（不允许混入中文）。
    """
    if not isinstance(sp, dict):
        raise ValueError('selling_point 必须为对象')
    for field_name in ('zh_title', 'zh_desc', 'en_title', 'en_desc'):
        value = sp.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'selling_point.{field_name} 不能为空')
    for field_name in ('en_title', 'en_desc'):
        if contains_chinese(sp.get(field_name)):
            raise ValueError(f'selling_point.{field_name} 必须为英文，不能包含中文')
    visual_keywords = sp.get('visual_keywords')
    if not isinstance(visual_keywords, str) or not visual_keywords.strip():
        raise ValueError('selling_point.visual_keywords 不能为空')
    if contains_chinese(visual_keywords):
        raise ValueError('selling_point.visual_keywords 仅允许英文，不能包含中文')


def validate_selling_points(selling_points: Any) -> Tuple[List[dict], List[str]]:
    """批量校验卖点：返回 (合法卖点列表, 错误消息列表)"""
    valid: List[dict] = []
    errors: List[str] = []
    if selling_points is None:
        return valid, errors
    if not isinstance(selling_points, list):
        return valid, ['selling_points 必须为列表']
    for idx, sp in enumerate(selling_points):
        try:
            validate_selling_point(sp)
            valid.append(sp)
        except ValueError as e:
            errors.append(f'第 {idx + 1} 条卖点校验失败: {e}')
    return valid, errors


# ── 站点 / 场景解析 ──

def resolve_site(site: Any) -> dict:
    """解析站点：非法/缺失回退默认站点 US，并携带 warnings

    Returns:
        {site, name, language, language_code, rtl, non_latin, warnings}
    """
    warnings: List[str] = []
    normalized = str(site or '').strip().upper()
    languages = _site_languages()
    if not normalized:
        normalized = DEFAULT_SITE
        warnings.append(f'未提供站点，已回退默认站点 {DEFAULT_SITE}')
    elif normalized not in languages:
        warnings.append(
            f'站点 {site} 不在支持列表，已回退默认站点 {DEFAULT_SITE}'
        )
        normalized = DEFAULT_SITE
    info = languages.get(normalized, {})
    return {
        'site': normalized,
        'name': info.get('name') or normalized,
        'language': info.get('language', _default_language()),
        'language_code': info.get('language_code', 'en'),
        'rtl': bool(info.get('rtl', False)),
        'non_latin': normalized in _non_latin_sites(),
        'warnings': warnings,
    }


def get_site_language(site: Any) -> str:
    """站点文案语言名（非法站点回退默认语言）"""
    return resolve_site(site)['language']


def is_non_latin_site(site: Any) -> bool:
    """是否非拉丁语系站点（需防乱码约束）"""
    return str(site or '').strip().upper() in _non_latin_sites()


def map_scene_to_env(scene_zh: Any) -> str:
    """中文场景 → 英文环境描述（未知场景回退默认环境）"""
    return _scene_map().get(str(scene_zh or '').strip(), _default_scene_env())


def list_scenes() -> List[str]:
    """支持的场景列表（保持字典顺序）"""
    return list(_scene_map().keys())


# ── 提示词组装 ──

def _product_title_en(product_info: Any) -> str:
    """提取英文商品名：优先 title_en / product_name_en；无英文时用参考图话术兜底"""
    if isinstance(product_info, dict):
        title = (product_info.get('title_en')
                 or product_info.get('product_name_en') or '')
    else:
        title = (getattr(product_info, 'title_en', '')
                 or getattr(product_info, 'product_name_en', '') or '')
    title = str(title).strip()
    if not title or contains_chinese(title):
        return 'the product shown in the reference image'
    return title


def _selling_points_fragment(selling_points: Any) -> str:
    """合法卖点 → 提示词片段（非法卖点静默跳过，warnings 由 build_preview 收集）"""
    valid, _errors = validate_selling_points(selling_points)
    if not valid:
        return ''
    pts = '; '.join(
        f"{sp['en_title']} ({sp['en_desc']}; visual cues: {sp['visual_keywords']})"
        for sp in valid
    )
    return f' Highlight key selling points: {pts}.'


def _text_language_constraint(site: str, language: str, image_type: str) -> str:
    """按图型生成文字语言约束片段"""
    if image_type == 'main':
        # 主图：禁止任何文字（白底约束在 prompt 模板中体现）
        return ''
    constraint = f' Any text overlay in the image must be written in {language}.'
    if site in _non_latin_sites():
        constraint += (
            f' All text must be written in {language} and rendered clearly in native '
            f'{language} script, with no garbled or broken characters.'
        )
    return constraint


def build_prompt(
    product_info: Any,
    selling_points: Any,
    scene_zh: Any,
    site: Any,
    image_type: str,
) -> str:
    """组装英文生图提示词

    Args:
        product_info: dict（title_en/product_name_en，可含 include_model）或对象
        selling_points: 双语卖点列表 [{zh_title, zh_desc, en_title, en_desc, visual_keywords}]
        scene_zh: 中文场景名
        site: 站点码（US/DE/JP...，非法回退 US）
        image_type: main（纯白底主图）/ scene（场景图）/ detail（卖点可视化细节图）

    Returns:
        英文提示词字符串
    """
    img_type = normalize_image_type(image_type)
    site_info = resolve_site(site)
    site = site_info['site']
    language = site_info['language']
    title_en = _product_title_en(product_info)

    if img_type == 'main':
        prompt = (
            f'Professional e-commerce product photography of {title_en}. '
            'Pure white background (RGB 255,255,255), even studio lighting, '
            'centered composition, product fills about 85 percent of the frame, '
            'ultra sharp focus. No text, no watermark, no logo, no props.'
        )
    elif img_type == 'scene':
        env_desc = map_scene_to_env(scene_zh)
        prompt = (
            f'Professional e-commerce lifestyle photography of {title_en} {env_desc}. '
            'Soft natural lighting, shallow depth of field, product as the clear '
            'focal point, clean uncluttered composition.'
        )
        if isinstance(product_info, dict) and product_info.get('include_model'):
            prompt += (
                ' A lifestyle model naturally using the product may appear, '
                'hands and pose realistic.'
            )
    else:  # detail
        prompt = (
            f'Extreme close-up macro detail shot of {title_en}. '
            'Crisp texture rendering, soft diffused lighting, shallow depth of field, '
            'material quality clearly visible.'
        )

    prompt += _selling_points_fragment(selling_points)
    prompt += _text_language_constraint(site, language, img_type)
    return prompt


def prompt_constraints_for(site: Any, image_type: str = 'scene') -> str:
    """站点约束片段（供已有 builder 产出的 prompt 幂等追加）

    main 图追加白底无文字强化约束；scene/detail 追加文字语言约束。
    已包含对应约束时不重复追加（返回空串）。
    """
    img_type = normalize_image_type(image_type)
    site_info = resolve_site(site)
    if img_type == 'main':
        fragment = (
            'Pure white background (RGB 255,255,255) required; '
            'no text, no watermark, no promo labels.'
        )
    else:
        fragment = _text_language_constraint(
            site_info['site'], site_info['language'], img_type
        ).lstrip()
    return fragment


def append_constraint(prompt: str, constraint: str) -> str:
    """向 prompt 追加约束片段（已存在则原样返回，保证幂等）"""
    if not constraint or not prompt:
        return prompt
    if constraint in prompt:
        return prompt
    return f'{prompt.rstrip()} {constraint}'


def site_constraints_if_supported(site: Any, image_type: str = 'scene') -> str:
    """站点受支持时返回约束片段；缺失/非法返回空串（严格模式，不回退默认站点）

    供 pro/smart 模式对已构建 prompt 做幂等增强：region 传入中文
    （如"美国"）时不误判为 US。
    """
    normalized = str(site or '').strip().upper()
    if not normalized or normalized not in _site_languages():
        return ''
    try:
        return prompt_constraints_for(normalized, image_type)
    except ValueError:
        return ''


def build_preview(
    product_info: Any,
    selling_points: Any,
    scene_zh: Any,
    site: Any,
    image_types: Tuple[str, ...] = IMAGE_TYPES,
) -> dict:
    """组装预览结果：{prompts, warnings, site}

    - 逐条校验卖点，非法项跳过并记入 warnings
    - 非法站点回退默认站点，warnings 携带提示
    - 全程不调模型不计费
    """
    site_info = resolve_site(site)
    valid_sps, sp_errors = validate_selling_points(selling_points)
    prompts: Dict[str, str] = {}
    for raw_type in image_types:
        img_type = normalize_image_type(raw_type)
        prompts[img_type] = build_prompt(
            product_info, valid_sps, scene_zh, site_info['site'], img_type
        )
    return {
        'prompts': prompts,
        'warnings': site_info['warnings'] + sp_errors,
        'site': {
            'site': site_info['site'],
            'language': site_info['language'],
            'language_code': site_info['language_code'],
            'rtl': site_info['rtl'],
            'non_latin': site_info['non_latin'],
        },
    }
