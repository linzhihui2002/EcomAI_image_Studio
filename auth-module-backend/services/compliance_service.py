"""平台合规预校验服务（P0-2）

- get_platform_rules：平台规则查询（进程内缓存 60s）
- precheck_prompt：生图前提示词预校验 → {warnings, blocks, injected_constraints}
  禁元素词表命中分级（warning/block），block 级由调用方阻断；
  主图白底/占比约束缺失时注入（与引擎已有约束去重）
- apply_platform_constraints：对最终 prompt 注入平台约束（幂等），供 workflow 挂点
"""
import threading
import time
from typing import Any, Dict, List, Optional

from models.compliance import ComplianceRuleModel

# 规则缓存：platform -> (expires_at, data)
_RULES_CACHE: Dict[str, tuple] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL_SECONDS = 60

# 合法平台集合（用于种子/预校验提示，实际以 DB 为准）
KNOWN_PLATFORMS = ('amazon', 'temu', 'shopee', 'tiktok_shop', 'aliexpress', 'ozon')

# 图型归一：DB 规则键为 main_image/scene/detail；兼容 smart/pro 模式 ImageType 值
_IMAGE_TYPE_ALIASES = {
    'main_image': 'main_image',
    'main': 'main_image',
    'white_bg': 'main_image',
    'white': 'main_image',
    'scene': 'scene',
    'scene_image': 'scene',
    'sub_image': 'scene',
    'detail': 'detail',
    'detail_image': 'detail',
    'selling_point': 'detail',
    'checklist': 'detail',
    'material': 'detail',
    'size_chart': 'detail',
}


def normalize_platform(platform: Any) -> str:
    """平台名归一：'Amazon'/'amazon' → 'amazon'，'TikTok Shop' → 'tiktok_shop'"""
    return str(platform or '').strip().lower().replace(' ', '_')


def normalize_image_type(image_type: Any) -> Optional[str]:
    """图型归一为规则键 main_image/scene/detail；未知返回 None"""
    return _IMAGE_TYPE_ALIASES.get(str(image_type or '').strip().lower())


def get_platform_rules(platform: Any) -> Dict[str, Any]:
    """查询平台规则（进程内缓存 60s）

    Returns:
        {"platform": "amazon", "image_rules": {image_type: rules_dict},
         "global_forbidden": [{name, severity, keywords}]}
        平台无规则时 image_rules/global_forbidden 为空（负结果同样缓存）。
    """
    key = normalize_platform(platform)
    if not key:
        return {"platform": "", "image_rules": {}, "global_forbidden": []}

    now = time.time()
    with _CACHE_LOCK:
        cached = _RULES_CACHE.get(key)
        if cached and cached[0] > now:
            data = cached[1]
            return {
                "platform": key,
                "image_rules": dict(data["image_rules"]),
                "global_forbidden": list(data["global_forbidden"]),
            }

    model = ComplianceRuleModel()
    image_rules: Dict[str, dict] = {}
    global_forbidden: List[dict] = []
    try:
        rules = model.get_rules(key)
        for rule in rules:
            if rule.rules:
                image_rules[rule.image_type] = rule.rules
            items = rule.global_forbidden.get('items')
            if isinstance(items, list) and not global_forbidden:
                global_forbidden = items
    except Exception:
        # DB 异常时降级为无规则，不阻断生图主流程
        image_rules, global_forbidden = {}, []

    with _CACHE_LOCK:
        _RULES_CACHE[key] = (
            now + CACHE_TTL_SECONDS,
            {"image_rules": image_rules, "global_forbidden": global_forbidden},
        )

    return {
        "platform": key,
        "image_rules": dict(image_rules),
        "global_forbidden": list(global_forbidden),
    }


def invalidate_cache(platform: Any = None) -> None:
    """清除规则缓存（管理端更新规则后调用；缺省清全部）"""
    with _CACHE_LOCK:
        if platform is None:
            _RULES_CACHE.clear()
        else:
            _RULES_CACHE.pop(normalize_platform(platform), None)


def _hit_forbidden_items(prompt: str, global_forbidden: List[dict]) -> tuple:
    """禁元素词表命中分级：返回 (warnings, blocks)"""
    warnings: List[dict] = []
    blocks: List[dict] = []
    if not prompt:
        return warnings, blocks
    lowered = str(prompt).lower()
    for item in global_forbidden:
        if not isinstance(item, dict):
            continue
        keywords = [str(k).lower() for k in item.get('keywords', []) if k]
        hits = [k for k in keywords if k in lowered]
        if not hits:
            continue
        entry = {
            "name": item.get('name', ''),
            "severity": item.get('severity', 'warning'),
            "keywords_hit": hits,
        }
        if entry["severity"] == 'block':
            blocks.append(entry)
        else:
            warnings.append(entry)
    return warnings, blocks


def _main_image_constraint(rules: dict) -> str:
    """主图约束片段（白底/占比/无文字），规则缺失时用平台常识兜底"""
    rgb = rules.get('background_rgb')
    if isinstance(rgb, list) and len(rgb) == 3:
        bg = f"pure white background RGB({rgb[0]},{rgb[1]},{rgb[2]})"
    else:
        bg = "pure white background RGB(255,255,255)"
    ratio = rules.get('product_min_ratio', 0.85)
    try:
        ratio_pct = f"{float(ratio):.0%}"
    except (TypeError, ValueError):
        ratio_pct = "85%"
    return (
        f"Platform compliance: {bg}; product occupies at least {ratio_pct} of the "
        "frame; no text, no watermark, no promo labels."
    )


def _already_has_white_bg(prompt: str) -> bool:
    """与引擎约束去重：prompt 已含白底/无文字约束时不再注入"""
    lowered = str(prompt).lower()
    return (
        'rgb 255,255,255' in lowered
        or 'rgb (255,255,255)' in lowered
        or 'pure white background' in lowered
    )


def precheck_prompt(platform: Any, image_type: Any, prompt: Any) -> Dict[str, Any]:
    """生图前预校验

    Returns:
        {"warnings": [{name, severity, keywords_hit}],
         "blocks": [{name, severity, keywords_hit}],
         "injected_constraints": [str]}
        blocks 非空时调用方应返回 400 阻断。
    """
    warnings: List[dict] = []
    blocks: List[dict] = []
    injected: List[str] = []

    rules_data = get_platform_rules(platform)
    canonical = normalize_image_type(image_type)

    # 1. 禁元素词表命中分级
    warnings, blocks = _hit_forbidden_items(prompt, rules_data["global_forbidden"])

    # 2. 主图白底/占比约束注入（缺失时提醒并给出约束文本；与引擎约束去重）
    if canonical == 'main_image' and prompt:
        image_rules = rules_data["image_rules"].get('main_image')
        if image_rules and not _already_has_white_bg(prompt):
            constraint = _main_image_constraint(image_rules)
            injected.append(constraint)
            warnings.append({
                "name": "主图白底约束",
                "severity": "warning",
                "message": "提示词未包含主图白底/占比约束，已生成注入文本",
            })

    return {"warnings": warnings, "blocks": blocks, "injected_constraints": injected}


def apply_platform_constraints(platform: Any, image_type: Any, prompt: str) -> str:
    """对最终 prompt 注入平台约束（幂等），供 workflow 内挂点

    当前注入范围：主图白底/占比/无文字约束（与引擎约束去重合并）。
    """
    if not prompt:
        return prompt
    rules_data = get_platform_rules(platform)
    if not rules_data["image_rules"]:
        return prompt
    canonical = normalize_image_type(image_type)
    if canonical != 'main_image':
        return prompt
    image_rules = rules_data["image_rules"].get('main_image')
    if not image_rules or _already_has_white_bg(prompt):
        return prompt
    return f"{prompt.rstrip()} {_main_image_constraint(image_rules)}"
