"""AI 视觉合规审查服务（P1-4）

review_image(image_b64_or_url, platform, image_type) ->
    {riskLevel: high|medium|low|unknown, issues: [{rule, detail}], fixSuggestions: [str]}

- 规则来源：compliance_service.get_platform_rules(platform) 对应图型规则 +
  全局禁元素，把白底/占比/文字限制/禁元素转成审查要点构造多模态 system prompt
  （平台无规则时使用通用电商图审查要点兜底）。
- 多模态调用：与 services/generation_service._build_multimodal_request /
  services/toolbox_service._call_multimodal_api 同一封装方式
  （OpenAI 兼容 chat/completions + image_url），超时取 AIConfig.MULTIMODAL_TIMEOUT；
  输入为 http(s) url 时直传 url，base64（可含 data: 前缀）统一补 data URL 前缀，
  本地成图相对路径（/api/v1/images/...）读取磁盘文件转 base64 data URL。
- 解析容错：要求模型只输出 JSON；JSON 提取失败重试 1 次，
  仍失败（或调用异常）返回 {riskLevel: 'unknown', issues: [{rule: 'review_error', ...}], fixSuggestions: []}。
"""
import base64
import json
import os
import re
from typing import Any, Dict, List

import requests

from config import AIConfig
from services.compliance_service import (
    get_platform_rules, normalize_image_type, normalize_platform,
)
from services.user_ai_provider_service import (
    CATEGORY_MULTIMODAL,
    iter_channel_entries,
    report_entry_failure,
    report_entry_success,
)

# 合法风险等级（归一化目标）
RISK_LEVELS = ('high', 'medium', 'low')

# 重试次数：JSON 提取/调用失败后重试 1 次（共 2 次尝试）
_REVIEW_MAX_ATTEMPTS = 2

_DEFAULT_API_BASE = 'https://dashscope.aliyuncs.com/compatible-mode/v1'


def _unknown_result(err: Any) -> Dict[str, Any]:
    """审查失败/解析失败时的兜底结果（unknown，不阻断调用方主流程）"""
    return {
        'riskLevel': 'unknown',
        'issues': [{'rule': 'review_error', 'detail': str(err)[:300]}],
        'fixSuggestions': [],
    }


def _extract_json(text: str) -> dict:
    """从模型响应文本中提取 JSON（容错 markdown 代码块 / 前后缀噪声）"""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, TypeError):
        pass
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, TypeError):
            pass
    brace_match = re.search(r'\{[\s\S]*\}', text)
    if brace_match:
        try:
            parsed = json.loads(brace_match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, TypeError):
            pass
    raise ValueError(f'审查响应无法解析为 JSON: {str(text)[:120]}')


def _rule_lines(image_rules: dict) -> List[str]:
    """图型级规则 dict → 审查要点行（键值透传，兼容任意规则字段）"""
    lines = []
    for key, value in (image_rules or {}).items():
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f'- {key}: {value}')
    return lines


def _build_review_system_prompt(platform: Any, image_type: Any,
                                rules_data: Dict[str, Any]) -> str:
    """构造审查 system prompt：平台图型规则 + 全局禁元素 → 审查要点"""
    platform_key = normalize_platform(platform)
    canonical = normalize_image_type(image_type) or 'detail'
    image_rules = (rules_data.get('image_rules') or {}).get(canonical) or {}
    forbidden = rules_data.get('global_forbidden') or []

    lines = [
        f"You are a strict e-commerce image compliance reviewer for the "
        f"'{platform_key or 'general'}' marketplace.",
        f"Review the given '{canonical}' product image and check each rule below:",
    ]
    rule_lines = _rule_lines(image_rules)
    if rule_lines:
        lines.extend(rule_lines)
    else:
        # 平台未配置规则时的通用电商图审查要点兜底
        if canonical == 'main_image':
            lines.extend([
                '- background: pure white background (RGB 255,255,255)',
                '- product occupancy: product occupies at least 85% of the frame',
                '- text: no text, no watermark, no promo labels, no logos overlay',
            ])
        else:
            lines.extend([
                '- text overlays: minimal, accurate, no misleading claims',
                '- watermark: no watermark or third-party logos',
                '- content: no prohibited or offensive elements',
            ])
    if forbidden:
        names = [str(item.get('name') or '') for item in forbidden
                 if isinstance(item, dict)]
        names = [n for n in names if n]
        if names:
            lines.append('Forbidden elements to look for: ' + '、'.join(names))
    lines.append(
        'Compare the image against these points and judge overall risk level '
        '(high = clearly violates a rule, medium = borderline/unclear, '
        'low = compliant).'
    )
    lines.append(
        'Output ONLY a JSON object in this exact schema, no markdown, no extra text: '
        '{"riskLevel": "high|medium|low", '
        '"issues": [{"rule": "short rule name", "detail": "what is wrong"}], '
        '"fixSuggestions": ["actionable fix"]}'
    )
    return '\n'.join(lines)


def _local_image_data_url(image: str) -> str:
    """本地成图相对 URL（/api/v1/images/...）→ data URL；非本地路径或文件缺失返回空串"""
    from services import image_storage_service as storage

    url = image.split('?', 1)[0]
    for prefix, directory in ((storage.THUMB_URL_PREFIX, storage.THUMB_DIR),
                              (storage.URL_PREFIX, storage.STORAGE_DIR)):
        if not url.startswith(prefix + '/'):
            continue
        # 只取文件名，避免路径穿越；文件不存在时返回空串
        filename = os.path.basename(url[len(prefix) + 1:])
        path = os.path.join(directory, filename)
        if not filename or not os.path.isfile(path):
            return ''
        with open(path, 'rb') as f:
            raw = f.read()
        if not raw:
            return ''
        mime = storage.get_content_type(filename)
        return f'data:{mime};base64,{base64.b64encode(raw).decode()}'
    return ''


def _normalize_image_input(image_b64_or_url: Any) -> str:
    """图片输入归一：http(s) url 直传；本地成图相对路径读盘转 base64；
    base64（含/不含 data: 前缀）统一补 data URL"""
    image = str(image_b64_or_url or '').strip()
    if image.startswith('http://') or image.startswith('https://'):
        return image
    if image.startswith('data:'):
        return image
    if image.startswith('/'):
        # 本地成图路径（如 /api/v1/images/batch_1_xxx.png）：必须读盘成功，否则明确报错
        data_url = _local_image_data_url(image)
        if not data_url:
            raise FileNotFoundError(f'本地图片不存在或不可读: {image}')
        return data_url
    return f'data:image/png;base64,{image}'


def _call_review_model_by_channel(image_b64_or_url: Any, system_prompt: str,
                                  api_base: str, api_key: str, model_name: str) -> str:
    """在单一通道内调用多模态模型审查图片，返回原始文本响应"""
    request_body = {
        'model': model_name,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': [
                {'type': 'text',
                 'text': 'Review this product image for marketplace compliance '
                         'and output only the JSON verdict.'},
                {'type': 'image_url',
                 'image_url': {'url': _normalize_image_input(image_b64_or_url)}},
            ]},
        ],
        'temperature': 0.1,
        'max_tokens': 800,
    }
    response = requests.post(
        f'{api_base}/chat/completions',
        json=request_body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        timeout=AIConfig.MULTIMODAL_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f'多模态审查 API 返回 {response.status_code}: '
                           f'{response.text[:200]}')
    content = (response.json().get('choices') or [{}])[0] \
        .get('message', {}).get('content', '')
    if not content:
        raise RuntimeError('多模态审查 API 返回空结果')
    return content


def _call_review_model(image_b64_or_url: Any, system_prompt: str,
                       user_id: int = None) -> str:
    """调用多模态模型审查图片，返回原始文本响应（封装方式与现有 multimodal 通道一致）

    按用户自备通道号池依次尝试；全部通道失败时抛最后一条通道的错误。
    """
    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_MULTIMODAL):
        try:
            content = _call_review_model_by_channel(
                image_b64_or_url, system_prompt,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return content
        except Exception as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, str(e))

    raise last_channel_error or RuntimeError('多模态审查 API 调用失败')


def _normalize_result(parsed: dict) -> Dict[str, Any]:
    """模型输出归一：riskLevel 小写且限定枚举；issues/fixSuggestions 结构化"""
    risk = str(parsed.get('riskLevel') or '').strip().lower()
    if risk not in RISK_LEVELS:
        risk = 'unknown'
    issues: List[dict] = []
    for item in parsed.get('issues') or []:
        if isinstance(item, dict):
            issues.append({
                'rule': str(item.get('rule') or 'unknown'),
                'detail': str(item.get('detail') or ''),
            })
        elif isinstance(item, str) and item.strip():
            issues.append({'rule': 'issue', 'detail': item.strip()})
    fixes = [str(s).strip() for s in (parsed.get('fixSuggestions') or [])
             if str(s).strip()]
    return {'riskLevel': risk, 'issues': issues, 'fixSuggestions': fixes}


def review_image(image_b64_or_url: Any, platform: Any, image_type: Any,
                 user_id: int = None) -> Dict[str, Any]:
    """AI 视觉合规审查：审查一张成图是否满足平台图型规则

    Args:
        image_b64_or_url: 图片 base64（可含 data: 前缀）或 http(s) url
        platform: 平台标识（amazon/temu/...，决定规则来源）
        image_type: 图型（main/scene/detail 及其别名，归一为规则键）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        {riskLevel: 'high'|'medium'|'low'|'unknown',
         issues: [{rule, detail}], fixSuggestions: [str]}
        调用异常或 JSON 解析失败（重试 1 次后仍失败）时返回 riskLevel='unknown'。
    """
    rules_data = get_platform_rules(platform)
    system_prompt = _build_review_system_prompt(platform, image_type, rules_data)

    last_err: Exception = None  # type: ignore[assignment]
    for attempt in range(_REVIEW_MAX_ATTEMPTS):
        try:
            content = _call_review_model(image_b64_or_url, system_prompt, user_id=user_id)
            return _normalize_result(_extract_json(content))
        except Exception as e:  # API 异常与解析失败同样重试 1 次
            last_err = e
            print(f'[合规审查] 第 {attempt + 1}/{_REVIEW_MAX_ATTEMPTS} 次审查失败: {e}',
                  flush=True)
    return _unknown_result(last_err)
