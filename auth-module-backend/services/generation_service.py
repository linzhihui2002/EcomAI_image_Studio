"""商品图生成服务层 - 商品分析、生图模型调用"""
import json
import re
import time
import base64
from typing import Optional, Dict, Any
from config import AIConfig
from models.generation_task import ProductInfo
from services.user_ai_provider_service import (
    CATEGORY_IMAGE_GEN,
    CATEGORY_LLM,
    CATEGORY_MULTIMODAL,
    iter_channel_entries,
    report_entry_failure,
    report_entry_success,
)


class GenerationError(Exception):
    """生成服务异常"""
    def __init__(self, code: int, message: str, http_status: int = 500):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def _extract_json_from_text(text: str) -> dict:
    """从模型响应文本中提取 JSON（处理 markdown 代码块包裹等情况）"""
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # 尝试从 markdown 代码块中提取
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # 尝试匹配第一个完整的 JSON 对象
    brace_match = re.search(r'\{[\s\S]*\}', text)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    
    raise GenerationError(
        code=5002,
        message="AI模型返回格式异常，无法解析商品信息",
        http_status=502
    )


def _build_multimodal_request(
    image_base64: str,
    existing_info: Optional[str] = None,
    model_name: str = None,
) -> dict:
    """构建多模态模型请求体（model_name 由调用方按实际通道传入）"""
    system_prompt = (
        "You are a professional e-commerce product analyst. "
        "Analyze the product image and output a JSON object with the following fields:\n"
        "- product_name: 商品名称，使用简洁清晰的中文描述\n"
        "- target_audience: 目标消费人群，使用中文描述\n"
        "- selling_points: 核心卖点，使用中文，多个卖点用'/'分隔\n"
        "- selling_points_en: 核心卖点的英文双语结构化列表（3-5条），每条为 JSON 对象，"
        "格式 {\"title_en\": 简短英文标题, \"desc_en\": 英文描述, "
        "\"visual_keywords\": 纯英文视觉关键词（逗号分隔，用于AI生图，如 'wireless, sleek, matte finish'）}\n"
        "- usage_scenario: 使用场景，使用中文描述\n"
        "- product_category: 商品类目，如'电子产品/耳机/无线耳机'\n\n"
        "IMPORTANT: Output ONLY valid JSON, no markdown wrapping, no extra text. "
        "ALL field values MUST be in Chinese, EXCEPT selling_points_en "
        "which MUST be in English."
    )
    
    user_content = [{"type": "text", "text": "请分析这张商品图片，并以 JSON 格式返回结构化的商品信息。"}]
    
    if image_base64:
        # 确保不含 data:image 前缀
        if image_base64.startswith("data:"):
            # 提取 base64 部分和 mime type
            pass
        user_content.append({
            "type": "image_url",
            "image_url": {"url": image_base64 if image_base64.startswith("data:") else f"data:image/png;base64,{image_base64}"}
        })
    
    if existing_info:
        user_content.insert(0, {
            "type": "text",
            "text": f"用户提供了部分商品信息：\n{existing_info}\n\n请基于图片分析结果补充和优化以上信息，填写缺失字段。以 JSON 格式输出。"
        })
    
    return {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 1000,
    }


def _analyze_product_by_channel(
    image_base64: str,
    existing_text: Optional[str],
    max_retries: int,
    api_base: str,
    api_key: str,
    model_name: str,
) -> ProductInfo:
    """在单一通道内完成「构建请求 + 重试循环」，全部重试失败时抛 GenerationError"""
    import requests

    request_body = _build_multimodal_request(image_base64, existing_text, model_name)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait = 2 ** attempt  # 指数退避: 2s, 4s, 8s...
                print(f"[商品分析] 第 {attempt} 次重试，等待 {wait}s...")
                time.sleep(wait)
            
            response = requests.post(
                f"{api_base}/chat/completions",
                json=request_body,
                headers=headers,
                timeout=60,
            )
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                if not content:
                    raise GenerationError(
                        code=5002,
                        message="商品分析服务返回空结果，请重试",
                        http_status=502
                    )
                
                result = _extract_json_from_text(content)

                # P0-1 双语卖点：解析 selling_points_en（缺失/格式异常时降级为 None）
                selling_points_en = result.get("selling_points_en")
                if not isinstance(selling_points_en, list):
                    selling_points_en = None
                else:
                    selling_points_en = [
                        sp for sp in selling_points_en if isinstance(sp, dict)
                    ] or None

                return ProductInfo(
                    product_name=result.get("product_name", ""),
                    target_audience=result.get("target_audience", ""),
                    selling_points=result.get("selling_points", ""),
                    usage_scenario=result.get("usage_scenario", ""),
                    product_category=result.get("product_category", ""),
                    selling_points_en=selling_points_en,
                )
            
            # 429 / 502 / 503 可重试
            if response.status_code in (429, 502, 503):
                err_detail = _safe_error_msg(response)
                print(f"[商品分析] API 返回 {response.status_code}，将重试: {err_detail}")
                last_error = GenerationError(
                    code=5002,
                    message="商品分析服务繁忙，正在重试...",
                    http_status=503
                )
                continue
            
            # 其他错误码不重试
            try:
                err_detail = response.json()
            except Exception:
                err_detail = response.text[:500]
            print(f"[商品分析] API 返回非 200: status={response.status_code}, detail={err_detail}")
            raise GenerationError(
                code=5002,
                message=f"商品分析失败: {_safe_error_msg(response)}",
                http_status=502
            )
            
        except requests.exceptions.Timeout:
            print(f"[商品分析] 超时 (第 {attempt + 1}/{max_retries + 1} 次)")
            last_error = GenerationError(
                code=5002,
                message="AI模型响应超时，请稍后重试",
                http_status=504
            )
        except requests.exceptions.ConnectionError:
            print(f"[商品分析] 连接错误 (第 {attempt + 1}/{max_retries + 1} 次)")
            last_error = GenerationError(
                code=5002,
                message="无法连接AI模型服务，请检查网络后重试",
                http_status=503
            )
        except GenerationError as e:
            if e.http_status == 503:
                last_error = e
                continue
            raise
        except Exception as e:
            last_error = GenerationError(
                code=5002,
                message=f"商品分析失败: {str(e)}",
                http_status=500
            )
    
    raise last_error or GenerationError(
        code=5002,
        message="商品分析失败，已达最大重试次数",
        http_status=502
    )


def analyze_product(
    image_base64: str,
    existing_text: Optional[str] = None,
    max_retries: int = None,
    user_id: int = None,
) -> ProductInfo:
    """
    调用多模态模型分析商品图片，返回结构化商品信息
    
    Args:
        image_base64: 商品图片的 Base64 编码
        existing_text: 用户已填写的部分商品信息文本
        max_retries: 最大重试次数（默认从 AIConfig 读取）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    
    Returns:
        ProductInfo 结构化商品信息
    
    Raises:
        GenerationError: 分析失败时抛出
    """
    if max_retries is None:
        max_retries = getattr(AIConfig, 'LLM_MAX_RETRIES', 2)

    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_MULTIMODAL):
        try:
            result = _analyze_product_by_channel(
                image_base64, existing_text, max_retries,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return result
        except GenerationError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, e.message)

    raise last_channel_error or GenerationError(
        code=5002,
        message="商品分析失败，已达最大重试次数",
        http_status=502
    )


def _call_image_edit_by_channel(
    product_image: str,
    prompt: str,
    size: str,
    reference_image: Optional[str],
    reference_text: Optional[str],
    api_base: str,
    api_key: str,
    model_name: str,
) -> Dict[str, Any]:
    """在单一通道内完成「解码入参 + 构建表单 + 重试循环」，全部重试失败时抛 GenerationError"""
    import requests
    import sys

    max_retries = AIConfig.IMAGE_GEN_MAX_RETRIES
    timeout = AIConfig.IMAGE_GEN_TIMEOUT

    print(f"[生图-编辑] 开始调用 API: {api_base}/images/edits model={model_name}", flush=True)
    sys.stderr.write(f"[生图-编辑] 开始调用 API: {api_base}/images/edits model={model_name}\n")
    sys.stderr.flush()

    # 解码商品图
    try:
        product_bytes = _decode_base64_image(product_image, "商品图")
        print(f"[生图-编辑] 商品图解码成功 size={len(product_bytes)}", flush=True)
    except GenerationError as e:
        print(f"[生图-编辑] 商品图解码失败: {e.message}", flush=True)
        sys.stderr.write(f"[生图-编辑] 商品图解码失败: {e.message}\n")
        sys.stderr.flush()
        raise
    
    # 构建图片文件列表（商品图始终在第一位）
    image_files = [("image", ("product.png", product_bytes, "image/png"))]
    
    # 如果有参考图，追加到 image 列表（作为额外参考图）
    if reference_image:
        try:
            ref_bytes = _decode_base64_image(reference_image, "参考图")
            image_files.append(("image", ("reference.png", ref_bytes, "image/png")))
        except GenerationError:
            raise
    
    # 构建最终 prompt（追加参考描述）
    final_prompt = prompt
    if reference_image:
        if reference_text and reference_text.strip():
            final_prompt = f"{prompt}\n\n参考以下维度：{reference_text.strip()}"
        else:
            final_prompt = f"{prompt}\n\n参考提供的风格参考图的视觉风格，保持产品主体不变"
    
    form_data = {
        "model": model_name,
        "prompt": final_prompt,
        "size": size,
        "n": 1,
    }
    
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                print(f"[生图-编辑] 第 {attempt} 次重试...")
                time.sleep(2 * attempt)

            print(f"[生图-编辑] 发送 HTTP 请求 attempt={attempt}", flush=True)
            response = requests.post(
                f"{api_base}/images/edits",
                files=image_files,
                data=form_data,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
            print(f"[生图-编辑] HTTP 响应 status={response.status_code}", flush=True)

            if response.status_code == 200:
                return _parse_image_response(response)
            
            if response.status_code in (429, 502, 503):
                last_error = GenerationError(code=5002, message="生图服务繁忙，正在重试...", http_status=503)
                continue
            
            error_msg = _safe_error_msg(response)
            raise GenerationError(code=5002, message=f"图片编辑失败: {error_msg}", http_status=502)
            
        except requests.exceptions.Timeout:
            print(f"[生图-编辑] 超时 (第 {attempt + 1}/{max_retries + 1} 次)")
            last_error = GenerationError(code=5002, message="AI模型响应超时，请稍后重试", http_status=504)
        except requests.exceptions.ConnectionError:
            print(f"[生图-编辑] 连接错误 (第 {attempt + 1}/{max_retries + 1} 次)")
            last_error = GenerationError(code=5002, message="无法连接生图服务，请检查网络后重试", http_status=503)
        except GenerationError as e:
            if e.http_status == 503:
                last_error = e
                continue
            raise
    
    raise last_error or GenerationError(code=5002, message="图片编辑失败，已达最大重试次数", http_status=502)


def call_image_edit_model(
    product_image: str,
    prompt: str,
    size: str,
    reference_image: Optional[str] = None,
    reference_text: Optional[str] = None,
    user_id: int = None,
) -> Dict[str, Any]:
    """
    调用图像编辑模型生成图片
    始终使用 POST /v1/images/edits（multipart/form-data），保证产品一致性
    
    Args:
        product_image: 商品图 Base64（必传，编辑主图）
        prompt: 生图提示词
        size: 图片尺寸，格式如 "1024x1024"
        reference_image: 风格参考图 Base64（可选，作为额外 image[] 传入）
        reference_text: 参考维度描述（可选，追加到 prompt；留空则默认参考风格）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    
    Returns:
        {"url": "图片URL", ...} 或 {"b64_json": "base64数据", ...}
    
    Raises:
        GenerationError: 生图失败时抛出
    """
    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_IMAGE_GEN):
        try:
            result = _call_image_edit_by_channel(
                product_image, prompt, size, reference_image, reference_text,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return result
        except GenerationError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, e.message)

    raise last_channel_error or GenerationError(
        code=5002, message="图片编辑失败，已达最大重试次数", http_status=502
    )


def _decode_base64_image(image_data: str, label: str = "图片") -> bytes:
    """将 base64 图片解码为字节"""
    try:
        if image_data.startswith("data:"):
            b64 = image_data.split(",", 1)[1] if "," in image_data else image_data
        else:
            b64 = image_data
        return base64.b64decode(b64)
    except Exception as e:
        raise GenerationError(code=5002, message=f"{label}解码失败: {str(e)}", http_status=400)


def _parse_image_response(response) -> Dict[str, Any]:
    """解析生图/编辑 API 响应，提取图片数据"""
    content_type = response.headers.get('content-type', '')
    
    # 尝试解析 JSON（放宽 Content-Type 校验，兼容 text/plain 等非标准类型）
    try:
        data = response.json()
    except Exception:
        print(f"[生图] 错误：API 返回非 JSON 响应 (Content-Type: {content_type})")
        print(f"[生图] 响应内容预览: {response.text[:500]}")
        raise GenerationError(
            code=5002,
            message="生图服务返回了无效响应，请检查 API 配置",
            http_status=502
        )
    print(f"[生图] 成功响应 keys: {list(data.keys())}")
    
    image_data = data.get("data", [{}])
    
    # GPT Image 系列优先返回 b64_json
    if image_data and image_data[0].get("b64_json"):
        return {"b64_json": image_data[0]["b64_json"]}
    # 也支持 URL 返回
    if image_data and image_data[0].get("url"):
        return {"url": image_data[0]["url"]}
    # 兼容非标准 API：直接返回顶层字段
    if data.get("b64_json"):
        return {"b64_json": data["b64_json"]}
    if data.get("url"):
        return {"url": data["url"]}
    
    print(f"[生图] 警告：无法从响应中提取图片数据，响应结构: {json.dumps(data, ensure_ascii=False)[:500]}")
    raise GenerationError(
        code=5002,
        message="生图模型返回结果为空",
        http_status=502
    )


def _safe_error_msg(response) -> str:
    """安全地从响应中提取错误信息"""
    error_msg = f"HTTP {response.status_code}"
    if response.headers.get('content-type', '').startswith('application/json'):
        try:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", error_msg)
        except Exception:
            pass
    return error_msg


# ================================================================
# 专业模式：LLM 调用、AI 分析整合、对话优化
# ================================================================

def _call_llm_chat_by_channel(
    system_prompt: str,
    user_content,
    temperature: float,
    max_tokens: int,
    max_retries: int,
    api_base: str,
    api_key: str,
    model_name: str,
) -> str:
    """在单一通道内完成「构建请求 + 重试循环」，全部重试失败时抛 GenerationError"""
    import requests

    request_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait = 2 ** attempt  # 指数退避: 2s, 4s, 8s...
                print(f"[LLM对话] 第 {attempt} 次重试，等待 {wait}s...")
                time.sleep(wait)

            response = requests.post(
                f"{api_base}/chat/completions",
                json=request_body,
                headers=headers,
                timeout=120,
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                if not content:
                    raise GenerationError(
                        code=5002,
                        message="AI模型返回空结果，请重试",
                        http_status=502
                    )

                return content

            # 429 / 502 / 503 可重试
            if response.status_code in (429, 502, 503):
                err_detail = _safe_error_msg(response)
                print(f"[LLM对话] API 返回 {response.status_code}，将重试: {err_detail}")
                last_error = GenerationError(
                    code=5002,
                    message="AI模型服务繁忙，正在重试...",
                    http_status=503
                )
                continue

            # 其他错误码不重试
            try:
                err_detail = response.json()
            except Exception:
                err_detail = response.text[:500]
            print(f"[LLM对话] API 返回非 200: status={response.status_code}, detail={err_detail}")
            raise GenerationError(
                code=5002,
                message=f"AI模型调用失败: {_safe_error_msg(response)}",
                http_status=502
            )

        except requests.exceptions.Timeout:
            print(f"[LLM对话] 超时 (第 {attempt + 1}/{max_retries + 1} 次)")
            last_error = GenerationError(
                code=5002,
                message="AI模型响应超时，请稍后重试",
                http_status=504
            )
        except requests.exceptions.ConnectionError:
            print(f"[LLM对话] 连接错误 (第 {attempt + 1}/{max_retries + 1} 次)")
            last_error = GenerationError(
                code=5002,
                message="无法连接AI模型服务，请检查网络后重试",
                http_status=503
            )
        except GenerationError as e:
            if e.http_status == 503:
                last_error = e
                continue
            raise
        except Exception as e:
            last_error = GenerationError(
                code=5002,
                message=f"AI模型调用失败: {str(e)}",
                http_status=500
            )

    raise last_error or GenerationError(
        code=5002,
        message="AI模型调用失败，已达最大重试次数",
        http_status=502
    )


def call_llm_chat(
    system_prompt: str,
    user_content,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    max_retries: int = None,
    user_id: int = None,
) -> str:
    """
    调用 LLM 文本模型（qwen3.6-plus）进行对话，返回文本内容

    Args:
        system_prompt: 系统提示词
        user_content: 用户消息内容（字符串或多模态消息列表）
        temperature: 温度参数
        max_tokens: 最大输出 token 数
        max_retries: 最大重试次数（默认从 AIConfig 读取）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        模型输出的文本内容

    Raises:
        GenerationError: 调用失败时抛出
    """
    if max_retries is None:
        max_retries = getattr(AIConfig, 'LLM_MAX_RETRIES', 2)

    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_LLM):
        try:
            result = _call_llm_chat_by_channel(
                system_prompt, user_content, temperature, max_tokens, max_retries,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return result
        except GenerationError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, e.message)

    raise last_channel_error or GenerationError(
        code=5002,
        message="AI模型调用失败，已达最大重试次数",
        http_status=502
    )


# 图片类型 → 中文定位说明（用于 LLM 提示）
_IMAGE_TYPE_ROLE_DESC = {
    "main_image": "商品主视觉图，平台首图，决定点击率",
    "sub_image": "多角度细节展示图，补充主图",
    "white_bg": "平台规范要求的纯白背景图",
    "scene": "生活化场景图，增强代入感",
    "selling_point": "突出核心卖点的营销信息图",
    "checklist": "套装/组合商品的内容清单图",
    "material": "材质细节放大图，体现品质",
    "size_chart": "尺寸标注图，辅助购买决策",
    "other": "用户自定义图片",
}


def _build_analyze_integrate_system_prompt(
    image_type_value: str,
    platform: str,
    region: str,
    target_language: str,
    requirement: str,
) -> str:
    """构建 AI 分析整合的系统提示词（英文版）"""
    role_desc = _IMAGE_TYPE_ROLE_DESC.get(image_type_value, "商品展示图")
    copy_required = {
        "selling_point": "必须包含文案",
        "checklist": "必须包含文案",
        "size_chart": "必须包含文案",
        "main_image": "通常无文案（平台规范）",
        "white_bg": "无文案",
        "sub_image": "无文案",
        "scene": "无文案",
        "material": "可选文案",
        "other": "按需文案",
    }.get(image_type_value, "按需文案")

    return (
        "You are a professional e-commerce product image prompt engineer. "
        "Your task is to generate a structured prompt scheme (提示词方案) for a product image.\n\n"
        f"图片类型: {image_type_value}\n"
        f"图片定位: {role_desc}\n"
        f"文案需求: {copy_required}\n"
        f"目标平台: {platform}\n"
        f"目标市场: {region}\n"
        f"图片文案语言: {target_language}\n"
        f"整体要求: {requirement or '无特殊要求'}\n\n"
        "输出要求：\n"
        "1. 输出 ONLY 一个合法 JSON 对象，不要 markdown 代码块包裹，不要任何额外文字解释\n"
        "2. JSON 结构必须严格符合以下 schema：\n"
        "{\n"
        '  "image_name": "图片名称（中文，简洁）",\n'
        '  "image_role": "图片定位说明（中文）",\n'
        '  "layout_prompt": {\n'
        '    "product_state": "商品状态/角度（英文描述）",\n'
        '    "composition": "构图方式（英文描述）",\n'
        '    "background": "背景描述（英文描述）",\n'
        '    "corner_badge": "角标内容，无则填 none",\n'
        '    "visual_focus": "视觉重心（英文描述）"\n'
        '  },\n'
        '  "copy": {\n'
        '    "main_title": "主标题（使用目标语言，无文案则留空）",\n'
        '    "sub_title": "副标题（使用目标语言，无文案则留空）",\n'
        '    "tags": ["标签1", "标签2"]\n'
        '  }\n'
        "}\n\n"
        "注意事项：\n"
        f"- 文案字段（main_title/sub_title/tags）的文字必须使用 {target_language}\n"
        "- layout_prompt 中的字段使用英文描述，要具体、专业\n"
        "- 若图片类型无文案需求，copy 字段全部留空\n"
        "- 背景描述要结合平台规范（如 Amazon 要求纯白背景）"
    )


def _build_analyze_integrate_system_prompt_zh(
    image_type_value: str,
    platform: str,
    region: str,
    target_language: str,
    requirement: str,
) -> str:
    """构建 AI 分析整合的系统提示词（中文版）"""
    role_desc = _IMAGE_TYPE_ROLE_DESC.get(image_type_value, "商品展示图")
    copy_required = {
        "selling_point": "必须包含文案",
        "checklist": "必须包含文案",
        "size_chart": "必须包含文案",
        "main_image": "通常无文案（平台规范）",
        "white_bg": "无文案",
        "sub_image": "无文案",
        "scene": "无文案",
        "material": "可选文案",
        "other": "按需文案",
    }.get(image_type_value, "按需文案")

    return (
        "你是一位专业的电商商品图提示词工程师。"
        "你的任务是为商品图片生成结构化的提示词方案（PromptScheme）。\n\n"
        f"图片类型：{image_type_value}\n"
        f"图片定位：{role_desc}\n"
        f"文案需求：{copy_required}\n"
        f"目标平台：{platform}\n"
        f"目标市场：{region}\n"
        f"图片文案语言：{target_language}\n"
        f"整体要求：{requirement or '无特殊要求'}\n\n"
        "输出要求：\n"
        "1. 仅输出一个合法的 JSON 对象，不要用 markdown 代码块包裹，不要添加任何额外文字解释\n"
        "2. JSON 结构必须严格符合以下 schema：\n"
        "{\n"
        '  "image_name": "图片名称（中文，简洁）",\n'
        '  "image_role": "图片定位说明（中文）",\n'
        '  "layout_prompt": {\n'
        '    "product_state": "商品状态/角度（英文描述）",\n'
        '    "composition": "构图方式（英文描述）",\n'
        '    "background": "背景描述（英文描述）",\n'
        '    "corner_badge": "角标内容，无则填 none",\n'
        '    "visual_focus": "视觉重心（英文描述）"\n'
        '  },\n'
        '  "copy": {\n'
        '    "main_title": "主标题（使用目标语言，无文案则留空）",\n'
        '    "sub_title": "副标题（使用目标语言，无文案则留空）",\n'
        '    "tags": ["标签1", "标签2"]\n'
        '  }\n'
        "}\n\n"
        "注意事项：\n"
        f"- 文案字段（main_title/sub_title/tags）的文字必须使用 {target_language}\n"
        "- layout_prompt 中的字段使用英文描述，要具体、专业\n"
        "- 若图片类型无文案需求，copy 字段全部留空\n"
        "- 背景描述要结合平台规范（如 Amazon 要求纯白背景）"
    )


def analyze_integrate_scheme(
    image_type_value: str,
    product_info_dict: dict,
    platform: str,
    region: str,
    target_language: str,
    requirement: str = "",
    max_retries: int = 1,
    prompt_language: str = "en",
    user_id: int = None,
) -> dict:
    """
    AI 分析整合：为单个图片任务生成结构化提示词方案

    Args:
        image_type_value: 图片类型值（如 "main_image"）
        product_info_dict: 商品信息字典
        platform: 平台
        region: 国家/地区
        target_language: 目标语言
        requirement: 整体生成要求
        max_retries: 失败重试次数

    Returns:
        提示词方案 JSON 字典

    Raises:
        GenerationError: 生成失败
    """
    system_prompt = _build_analyze_integrate_system_prompt(
        image_type_value, platform, region, target_language, requirement
    ) if prompt_language != "zh" else _build_analyze_integrate_system_prompt_zh(
        image_type_value, platform, region, target_language, requirement
    )

    user_content = (
        f"商品信息：\n{json.dumps(product_info_dict, ensure_ascii=False, indent=2)}\n\n"
        f"请为该商品的「{image_type_value}」类型生成提示词方案。"
    )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            content = call_llm_chat(
                system_prompt=system_prompt,
                user_content=user_content,
                temperature=0.3,
                max_tokens=1500,
                user_id=user_id,
            )
            scheme = _extract_json_from_text(content)
            # 字段校验与兜底
            scheme.setdefault("image_name", "")
            scheme.setdefault("image_role", "")
            scheme.setdefault("layout_prompt", {})
            scheme.setdefault("copy", {})
            lp = scheme["layout_prompt"]
            lp.setdefault("product_state", "")
            lp.setdefault("composition", "")
            lp.setdefault("background", "")
            lp.setdefault("corner_badge", "none")
            lp.setdefault("visual_focus", "")
            cp = scheme["copy"]
            cp.setdefault("main_title", "")
            cp.setdefault("sub_title", "")
            cp.setdefault("tags", [])
            return scheme
        except GenerationError as e:
            last_error = e
            if attempt < max_retries:
                print(f"[分析整合] 第 {attempt + 1} 次失败，重试中: {e.message}")
                continue
            raise
        except Exception as e:
            last_error = GenerationError(
                code=5002,
                message=f"提示词方案生成失败: {str(e)}",
                http_status=500,
            )
            if attempt < max_retries:
                print(f"[分析整合] 第 {attempt + 1} 次异常，重试中: {e}")
                continue
            raise last_error

    raise last_error or GenerationError(
        code=5002,
        message="提示词方案生成失败，已达最大重试次数",
        http_status=502,
    )


def _build_dialog_optimize_system_prompt(
    image_type_value: str,
    platform: str,
    region: str,
    target_language: str,
) -> str:
    """构建对话优化的系统提示词"""
    role_desc = _IMAGE_TYPE_ROLE_DESC.get(image_type_value, "商品展示图")
    return (
        "你是一位专业的电商商品图提示词优化专家。用户正在通过对话优化「"
        f"{image_type_value}」（{role_desc}）的提示词方案。\n\n"
        f"目标平台: {platform}\n"
        f"目标市场: {region}\n"
        f"图片文案语言: {target_language}\n\n"
        "你的任务：\n"
        "1. 理解用户的优化指令（如“把背景改成浅灰色”、“添加促销角标”等）\n"
        "2. 基于当前方案，返回修改后的完整方案（不是 diff，是完整 JSON）\n\n"
        "输出要求：\n"
        "1. 输出 ONLY 一个合法 JSON 对象，不要 markdown 代码块包裹，不要额外解释\n"
        "2. JSON 结构必须符合：\n"
        "{\n"
        '  "image_name": "图片名称",\n'
        '  "image_role": "图片定位",\n'
        '  "layout_prompt": {\n'
        '    "product_state": "...",\n'
        '    "composition": "...",\n'
        '    "background": "...",\n'
        '    "corner_badge": "...",\n'
        '    "visual_focus": "..."\n'
        '  },\n'
        '  "copy": {\n'
        '    "main_title": "...",\n'
        '    "sub_title": "...",\n'
        '    "tags": ["..."]\n'
        '  }\n'
        "}\n\n"
        f"- 文案字段的文字使用 {target_language}\n"
        "- layout_prompt 字段使用英文描述\n"
        "- 仅修改用户指令涉及的字段，其他字段保持不变"
    )


def dialog_optimize_scheme(
    image_type_value: str,
    current_scheme: dict,
    dialog_history: list,
    user_input: str,
    platform: str,
    region: str,
    target_language: str,
    user_id: int = None,
) -> dict:
    """
    AI 对话优化：基于用户指令优化提示词方案

    Args:
        image_type_value: 图片类型值
        current_scheme: 当前提示词方案
        dialog_history: 对话历史 [{role, content}, ...]
        user_input: 用户本轮输入
        platform: 平台
        region: 国家/地区
        target_language: 目标语言

    Returns:
        优化后的提示词方案 JSON 字典

    Raises:
        GenerationError: 优化失败
    """
    system_prompt = _build_dialog_optimize_system_prompt(
        image_type_value, platform, region, target_language
    )

    # 构建用户消息：当前方案 + 历史 + 本轮指令
    user_content = (
        f"当前提示词方案：\n{json.dumps(current_scheme, ensure_ascii=False, indent=2)}\n\n"
    )

    # 追加对话历史摘要
    if dialog_history:
        history_text = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '助手'}: {m.get('content', '')}"
            for m in dialog_history[-10:]  # 仅保留最近10轮
        )
        user_content += f"对话历史：\n{history_text}\n\n"

    user_content += f"用户本轮指令：{user_input}\n\n请返回优化后的完整提示词方案 JSON。"

    content = call_llm_chat(
        system_prompt=system_prompt,
        user_content=user_content,
        temperature=0.4,
        max_tokens=1500,
        user_id=user_id,
    )

    scheme = _extract_json_from_text(content)
    # 字段兜底
    scheme.setdefault("image_name", current_scheme.get("image_name", ""))
    scheme.setdefault("image_role", current_scheme.get("image_role", ""))
    scheme.setdefault("layout_prompt", {})
    scheme.setdefault("copy", {})
    return scheme