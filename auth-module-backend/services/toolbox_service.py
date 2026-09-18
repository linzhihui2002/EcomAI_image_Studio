"""AI 工具箱服务层 - 抠图、文生图、图片合并、生图计划分析、对话式生图"""
import asyncio
import base64
import io
import json
import re
import threading
import time as _time_module
import traceback
import uuid
from typing import Any, Dict, List, Optional

import requests
from config import AIConfig

# ARQ 任务队列基础设施（Task 7 迁移：图片合并 / 产品替换改为注册任务）
from services.task_queue import (
    register_task,
    submit_task,
    set_progress,
    complete_task,
    fail_task,
)
from services.task_state_sync import set_progress_sync, complete_task_sync, fail_task_sync
from services.user_ai_provider_service import (
    CATEGORY_IMAGE_GEN,
    CATEGORY_MULTIMODAL,
    iter_channel_entries,
    report_entry_failure,
    report_entry_success,
)


class ToolboxError(Exception):
    """工具箱服务异常"""
    def __init__(self, code: int, message: str, http_status: int = 500):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# ── 通用工具函数 ──

def _decode_base64_image(image_data: str, label: str = "图片") -> bytes:
    """将 base64 图片（可能含 data:image/...;base64, 前缀）解码为字节"""
    try:
        if image_data.startswith("data:"):
            b64 = image_data.split(",", 1)[1] if "," in image_data else image_data
        else:
            b64 = image_data
        return base64.b64decode(b64)
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"{label}解码失败: {str(e)}",
            http_status=400
        )


def _get_image_dimensions(image_data: str, label: str = "图片") -> tuple:
    """从 base64 图片获取宽高 (width, height)"""
    try:
        from PIL import Image as PILImage
        image_bytes = _decode_base64_image(image_data, label)
        img = PILImage.open(io.BytesIO(image_bytes))
        return img.size
    except ImportError:
        raise ToolboxError(
            code=5002,
            message="图片处理库未安装，无法获取参考图尺寸",
            http_status=500
        )
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"无法读取{label}尺寸: {str(e)}",
            http_status=400
        )


def _encode_bytes_to_data_url(image_bytes: bytes, mime: str = "image/png") -> str:
    """将图片字节编码为 data URL"""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _extract_json_from_text(text: str) -> dict:
    """从模型响应文本中提取 JSON（处理 markdown 代码块包裹等情况）"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    brace_match = re.search(r'\{[\s\S]*\}', text)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ToolboxError(
        code=5002,
        message="AI模型返回格式异常，无法解析为 JSON",
        http_status=502
    )


def _call_multimodal_by_channel(
    request_body: dict,
    operation_name: str,
    timeout: int,
    max_retries: int,
    api_base: str,
    api_key: str,
    model_name: str,
) -> dict:
    """在单一通道内完成「构建请求 + 重试循环」，全部重试失败时抛 ToolboxError"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait_sec = 2 ** attempt  # 指数退避：2s, 4s, 8s...
                print(f"[{operation_name}] 第 {attempt} 次重试（等待 {wait_sec}s）...", flush=True)
                import time as _time
                _time.sleep(wait_sec)

            response = requests.post(
                f"{api_base}/chat/completions",
                json=dict(request_body, model=model_name),
                headers=headers,
                timeout=timeout,
            )

            if response.status_code == 200:
                return response.json()

            # 5xx 错误（含 524 Cloudflare 超时）→ 可重试
            if 500 <= response.status_code < 600:
                try:
                    err_detail = response.json()
                except Exception:
                    err_detail = response.text[:500]
                print(f"[{operation_name}] API 返回 {response.status_code}（第 {attempt+1}/{max_retries+1} 次），detail={err_detail}", flush=True)
                last_error = ToolboxError(
                    code=5002,
                    message=f"{operation_name}服务暂时不可用，请稍后重试",
                    http_status=503 if response.status_code != 524 else 504,
                )
                continue  # 可重试

            # 4xx 错误 → 不可重试
            try:
                err_detail = response.json()
            except Exception:
                err_detail = response.text[:500]
            print(f"[{operation_name}] API 返回非 200: status={response.status_code}, detail={err_detail}", flush=True)
            raise ToolboxError(
                code=5002,
                message=f"{operation_name}服务暂时不可用，请稍后重试",
                http_status=503,
            )

        except requests.exceptions.Timeout:
            print(f"[{operation_name}] 请求超时（第 {attempt+1}/{max_retries+1} 次）", flush=True)
            last_error = ToolboxError(
                code=5002,
                message="AI分析服务响应超时，请稍后重试",
                http_status=504,
            )
            continue  # 可重试

        except requests.exceptions.ConnectionError:
            print(f"[{operation_name}] 连接错误（第 {attempt+1}/{max_retries+1} 次）", flush=True)
            last_error = ToolboxError(
                code=5002,
                message="无法连接AI分析服务，请检查网络后重试",
                http_status=503,
            )
            continue  # 可重试

    # 所有重试均失败
    raise last_error or ToolboxError(
        code=5002,
        message=f"{operation_name}失败，已达最大重试次数",
        http_status=502,
    )


def _call_multimodal_api(
    request_body: dict,
    operation_name: str = "多模态API",
    timeout: int = None,
    max_retries: int = None,
    user_id: int = None,
) -> dict:
    """
    通用多模态 API 调用方法，含重试逻辑

    可重试条件（同时满足以下两点）：
    1. HTTP 状态码为 5xx（含 524 Cloudflare 超时）
    2. 未超过最大重试次数

    不可重试条件：
    - HTTP 4xx（客户端错误）
    - 已达到最大重试次数

    Args:
        request_body: API 请求体
        operation_name: 操作名称（用于日志）
        timeout: 单次请求超时秒数，默认读取 AIConfig.MULTIMODAL_TIMEOUT
        max_retries: 最大重试次数，默认读取 AIConfig.MULTIMODAL_MAX_RETRIES
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        dict: API 响应的 JSON 数据

    Raises:
        ToolboxError: 所有重试均失败时抛出
    """
    if timeout is None:
        timeout = AIConfig.MULTIMODAL_TIMEOUT
    if max_retries is None:
        max_retries = AIConfig.MULTIMODAL_MAX_RETRIES

    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_MULTIMODAL):
        try:
            data = _call_multimodal_by_channel(
                request_body, operation_name, timeout, max_retries,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return data
        except ToolboxError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, e.message)

    raise last_channel_error or ToolboxError(
        code=5002,
        message=f"{operation_name}失败，已达最大重试次数",
        http_status=502,
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


def _parse_image_response(response) -> Dict[str, Any]:
    """解析生图 API 响应，提取图片数据"""
    try:
        data = response.json()
    except Exception:
        print(f"[工具箱-生图] 错误：API 返回非 JSON 响应")
        print(f"[工具箱-生图] 响应内容预览: {response.text[:500]}")
        raise ToolboxError(
            code=5002,
            message="生图服务返回了无效响应，请检查 API 配置",
            http_status=502
        )

    image_data = data.get("data", [{}])

    if image_data and image_data[0].get("b64_json"):
        return {"b64_json": image_data[0]["b64_json"]}
    if image_data and image_data[0].get("url"):
        return {"url": image_data[0]["url"]}
    if data.get("b64_json"):
        return {"b64_json": data["b64_json"]}
    if data.get("url"):
        return {"url": data["url"]}

    print(f"[工具箱-生图] 警告：无法从响应中提取图片数据，响应结构: {json.dumps(data, ensure_ascii=False)[:500]}")
    raise ToolboxError(
        code=5002,
        message="生图模型返回结果为空",
        http_status=502
    )


# ── Task 4: 智能抠图 ──

def remove_background(image_base64: str) -> str:
    """
    智能抠图：通过遮罩生成方式去除背景，严格保证产品零形变

    优先使用 rembg（基于 U2Net 模型生成前景遮罩，原始产品像素完全保留）。
    若 rembg 不可用，回退到调用多模态 LLM 生成遮罩；若都不可用则抛出明确错误。

    Args:
        image_base64: base64 编码的图片（可能含 data:image/...;base64, 前缀）

    Returns:
        透明背景的 PNG base64 字符串（含 data:image/png;base64, 前缀）

    Raises:
        ToolboxError: 抠图失败时抛出
    """
    # 解码输入图片
    image_bytes = _decode_base64_image(image_base64, "抠图输入图片")

    # 优先尝试 rembg
    try:
        from rembg import remove as rembg_remove  # type: ignore
    except ImportError:
        rembg_remove = None

    if rembg_remove is not None:
        try:
            print(f"[工具箱-抠图] 使用 rembg 处理图片，输入大小: {len(image_bytes)} bytes", flush=True)
            # rembg 直接基于 U2Net 生成前景遮罩，原始产品像素完全保留，仅将背景置为透明
            output_bytes = rembg_remove(image_bytes)
            if not output_bytes:
                raise ToolboxError(
                    code=5002,
                    message="抠图服务返回空结果，请重试",
                    http_status=502
                )
            print(f"[工具箱-抠图] rembg 处理完成，输出大小: {len(output_bytes)} bytes", flush=True)
            return _encode_bytes_to_data_url(output_bytes, "image/png")
        except ToolboxError:
            raise
        except Exception as e:
            print(f"[工具箱-抠图] rembg 处理失败: {e}", flush=True)
            raise ToolboxError(
                code=5002,
                message=f"抠图处理失败: {str(e)}",
                http_status=500
            )

    # 回退：尝试用 PIL 进行简单的纯色背景移除（仅对接近白色的背景有效）
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        Image = None  # type: ignore

    if Image is not None:
        try:
            print(f"[工具箱-抠图] rembg 不可用，回退到 PIL 纯色背景移除", flush=True)
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            width, height = img.size
            pixels = img.load()

            # 采样四角像素作为背景色参考
            corner_colors = []
            for x, y in [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]:
                corner_colors.append(pixels[x, y])

            # 计算平均背景色（仅取 RGB）
            bg_r = sum(c[0] for c in corner_colors) // len(corner_colors)
            bg_g = sum(c[1] for c in corner_colors) // len(corner_colors)
            bg_b = sum(c[2] for c in corner_colors) // len(corner_colors)

            # 阈值：与背景色差异小于此值的像素视为背景
            threshold = 30

            for x in range(width):
                for y in range(height):
                    r, g, b, a = pixels[x, y]
                    if (abs(r - bg_r) < threshold and
                            abs(g - bg_g) < threshold and
                            abs(b - bg_b) < threshold):
                        pixels[x, y] = (r, g, b, 0)

            output_buf = io.BytesIO()
            img.save(output_buf, format="PNG")
            output_bytes = output_buf.getvalue()
            print(f"[工具箱-抠图] PIL 回退处理完成，输出大小: {len(output_bytes)} bytes", flush=True)
            return _encode_bytes_to_data_url(output_bytes, "image/png")
        except Exception as e:
            print(f"[工具箱-抠图] PIL 回退处理失败: {e}", flush=True)
            raise ToolboxError(
                code=5002,
                message=f"抠图处理失败: {str(e)}",
                http_status=500
            )

    # 两者都不可用
    raise ToolboxError(
        code=5002,
        message="抠图服务未配置",
        http_status=503
    )


# ── Task 5: 文生图 ──

def _validate_image_size(size_str: str):
    """
    按 gpt-image-2 约束规则校验尺寸字符串
    规则：最大边长 ≤ 3840、宽高为 16 倍数、长边/短边 ≤ 3:1、总像素 655,360~8,294,400
    校验通过返回 (width, height)，失败抛出 ToolboxError
    """
    match = re.match(r'^(\d+)[xX×](\d+)$', size_str.strip())
    if not match:
        raise ToolboxError(code=2001, message="尺寸格式无效，请使用 宽x高 格式，如 1024x1024", http_status=400)
    w = int(match.group(1))
    h = int(match.group(2))

    max_side = max(w, h)
    if max_side > 3840:
        raise ToolboxError(code=2001, message="尺寸边长不能超过 3840px", http_status=400)
    if w % 16 != 0 or h % 16 != 0:
        raise ToolboxError(code=2001, message="尺寸宽高必须为 16 的倍数", http_status=400)
    long_side = max(w, h)
    short_side = min(w, h)
    if short_side > 0 and long_side / short_side > 3:
        raise ToolboxError(code=2001, message="尺寸长边与短边比例不能超过 3:1", http_status=400)
    total = w * h
    if total < 655360:
        raise ToolboxError(code=2001, message="尺寸总像素数不能少于 655,360", http_status=400)
    if total > 8294400:
        raise ToolboxError(code=2001, message="尺寸总像素数不能超过 8,294,400", http_status=400)

    return w, h


def _calc_size_from_aspect(ref_width: int, ref_height: int) -> str:
    """根据参考图宽高计算符合 gpt-image-2 约束的尺寸，短边基准 1024"""
    if ref_width <= 0 or ref_height <= 0:
        return "1024x1024"

    if ref_width <= ref_height:
        short, long = ref_width, ref_height
    else:
        short, long = ref_height, ref_width

    ratio = long / short
    target_short = 1024
    target_long = int(target_short * ratio)

    # 对齐到 16 倍数
    target_long = ((target_long + 8) // 16) * 16

    # 总像素数超限则等比缩小
    if target_short * target_long > 8294400:
        scale = (8294400 / (target_short * target_long)) ** 0.5
        target_short = max(16, ((int(target_short * scale) + 8) // 16) * 16)
        target_long = max(16, ((int(target_long * scale) + 8) // 16) * 16)

    # 总像素数不足则等比放大
    if target_short * target_long < 655360:
        scale = (655360 / (target_short * target_long)) ** 0.5
        target_short = ((int(target_short * scale) + 8) // 16) * 16
        target_long = ((int(target_long * scale) + 8) // 16) * 16

    # 长边超限则等比缩小
    if target_long > 3840:
        scale = 3840 / target_long
        target_long = 3840
        target_short = ((int(target_short * scale) + 8) // 16) * 16

    if ref_width <= ref_height:
        size = f"{target_short}x{target_long}"
    else:
        size = f"{target_long}x{target_short}"

    _validate_image_size(size)
    return size


def _text_to_image_by_channel(
    prompt: str,
    size: str,
    quality: Optional[str],
    api_base: str,
    api_key: str,
    model_name: str,
) -> str:
    """在单一通道内完成「构建请求 + 重试循环」，全部重试失败时抛 ToolboxError"""
    max_retries = AIConfig.IMAGE_GEN_MAX_RETRIES
    timeout = AIConfig.IMAGE_GEN_TIMEOUT

    payload = {
        "model": model_name,
        "prompt": prompt,
        "size": size,
        "n": int(1),
    }
    if quality:
        payload["quality"] = quality

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                print(f"[工具箱-文生图] 第 {attempt} 次重试...", flush=True)
                import time as _time
                _time.sleep(2 * attempt)

            print(f"[工具箱-文生图] 请求 payload: model={model_name}, size={size}, n={payload['n']} (type={type(payload['n']).__name__})", flush=True)
            response = requests.post(
                f"{api_base}/images/generations",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )

            if response.status_code == 200:
                result = _parse_image_response(response)
                url = result.get("url")
                b64 = result.get("b64_json")
                if b64:
                    return f"data:image/png;base64,{b64}"
                if url:
                    try:
                        img_resp = requests.get(url, timeout=timeout)
                        if img_resp.status_code == 200:
                            return _encode_bytes_to_data_url(img_resp.content, "image/png")
                    except Exception as e:
                        print(f"[工具箱-文生图] 下载图片 URL 失败: {e}", flush=True)
                    return url
                raise ToolboxError(
                    code=5002,
                    message="生图模型返回结果为空",
                    http_status=502
                )

            if response.status_code == 429:
                last_error = ToolboxError(
                    code=5002,
                    message="生图服务繁忙，正在重试...",
                    http_status=503
                )
                continue

            error_msg = _safe_error_msg(response)
            raise ToolboxError(
                code=5002,
                message=f"文生图失败: {error_msg}",
                http_status=502
            )

        except requests.exceptions.Timeout:
            print(f"[工具箱-文生图] 超时 (第 {attempt + 1}/{max_retries + 1} 次)", flush=True)
            last_error = ToolboxError(
                code=5002,
                message="AI模型响应超时，请稍后重试",
                http_status=504
            )
        except requests.exceptions.ConnectionError:
            print(f"[工具箱-文生图] 连接错误 (第 {attempt + 1}/{max_retries + 1} 次)", flush=True)
            last_error = ToolboxError(
                code=5002,
                message="无法连接生图服务，请检查网络后重试",
                http_status=503
            )
        except ToolboxError as e:
            if e.http_status == 503:
                last_error = e
                continue
            raise

    raise last_error or ToolboxError(
        code=5002,
        message="文生图失败，已达最大重试次数",
        http_status=502
    )


def text_to_image(prompt: str, size: Optional[str] = None, quality: Optional[str] = None, user_id: int = None) -> str:
    """
    文生图：调用 gpt-image-2 模型生成图片

    Args:
        prompt: 生图提示词
        size: 图片尺寸，如 "1024x1024"，默认 1024x1024
        quality: 画质，"low" | "medium" | "high" | "auto"，默认不传
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        base64 编码图片（含 data:image/png;base64, 前缀）

    Raises:
        ToolboxError: 生图失败时抛出
    """
    if not size:
        size = "1024x1024"

    # 校验尺寸
    _validate_image_size(size)

    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_IMAGE_GEN):
        try:
            image_data_url = _text_to_image_by_channel(
                prompt, size, quality,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return image_data_url
        except ToolboxError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, e.message)

    raise last_channel_error or ToolboxError(
        code=5002,
        message="文生图失败，已达最大重试次数",
        http_status=502
    )


# ── 图片合并任务状态管理（Task 7 迁移：原 _merge_tasks 内存字典 → Redis task:{id}） ──

# Redis 状态 → 前端轮询状态的映射（原字典只有 processing/completed/failed 三态）
_TASK_STATUS_MAP = {
    'queued': 'processing',
    'running': 'processing',
    'completed': 'completed',
    'failed': 'failed',
}


def _map_task_state_to_legacy(state: Optional[dict]) -> Optional[Dict[str, Any]]:
    """将 task_queue.get_task 的 Redis 状态映射回原字典时代的响应结构"""
    if not state:
        return None
    return {
        "status": _TASK_STATUS_MAP.get(state.get('status'), 'processing'),
        "progress": state.get('step', ''),
        "result": state.get('result'),
        "error": state.get('error'),
    }


def get_merge_task_status(task_id: str) -> Dict[str, Any]:
    """
    获取合并任务状态（数据源：Redis task:{task_id}）

    Args:
        task_id: 任务 ID

    Returns:
        dict: {task_id, status, progress, result, error}

    Raises:
        ToolboxError: 任务不存在时抛出
    """
    from services.task_queue import get_task
    legacy = _map_task_state_to_legacy(get_task(task_id))
    if not legacy:
        raise ToolboxError(
            code=4004,
            message="合并任务不存在或已过期，请重新提交",
            http_status=404
        )
    return {
        "task_id": task_id,
        "status": legacy["status"],
        "progress": legacy.get("progress", ""),
        "result": legacy.get("result"),
        "error": legacy.get("error"),
    }


# ── 图片合并 ARQ 任务体（原 routes/toolbox.py 后台线程 _run_merge 平移） ──

@register_task('toolbox_image_merge')
async def toolbox_image_merge_task(ctx, payload: dict, task_id: str):
    """
    图片合并任务（ARQ）：执行体与原后台线程 _run_merge 完全一致
    payload: {images, user_id, deducted, cost, feature_key, tool_name}
    """
    from services.history_service import save_history
    from services.feature_pricing_service import refund_coins

    images = payload['images']
    user_id = payload.get('user_id')
    deducted = payload.get('deducted', False)
    cost = payload.get('cost', 0)
    feature_key = payload.get('feature_key', 'toolbox.image_merge')
    tool_name = payload.get('tool_name', '图片合并')

    try:
        # 步骤1: 产品特征分析（沿用原前端展示文案）
        await set_progress(ctx, task_id, "正在分析产品特征...")

        result = await asyncio.to_thread(merge_images, images, user_id=user_id)

        await set_progress(ctx, task_id, "处理完成", pct=100)
        await complete_task(ctx, task_id, result)

        # 保存历史记录
        try:
            save_history(
                user_id=user_id,
                category='ai_toolbox',
                sub_category='image_merge',
                input_data={'images': images},
                output_data=result,
            )
        except Exception:
            pass  # 历史记录保存失败不影响主流程

    except ToolboxError as e:
        await set_progress(ctx, task_id, "处理失败")
        await fail_task(ctx, task_id, e.message)
        if deducted:
            try:
                refund_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款',
                             related_batch_id=task_id)
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
    except Exception as e:
        print(f"[工具箱-图片合并] 后台任务异常: {e}", flush=True)
        print(f"[工具箱-图片合并] 异常堆栈: {traceback.format_exc()}", flush=True)
        await set_progress(ctx, task_id, "处理失败")
        await fail_task(ctx, task_id, f"图片合并失败: {str(e)}")
        if deducted:
            try:
                refund_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款',
                             related_batch_id=task_id)
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)


# ── 产品替换任务状态管理（Task 7 迁移：原 _product_replace_tasks 内存字典 → Redis task:{id}） ──

def get_product_replace_task_status(task_id: str) -> Dict[str, Any]:
    """
    获取产品替换任务状态（数据源：Redis task:{task_id}）

    Args:
        task_id: 任务 ID

    Returns:
        dict: {task_id, status, progress, result, error}

    Raises:
        ToolboxError: 任务不存在时抛出
    """
    from services.task_queue import get_task
    legacy = _map_task_state_to_legacy(get_task(task_id))
    if not legacy:
        raise ToolboxError(
            code=4004,
            message="替换任务不存在或已过期",
            http_status=404
        )
    return {
        "task_id": task_id,
        "status": legacy["status"],
        "progress": legacy.get("progress", ""),
        "result": legacy.get("result"),
        "error": legacy.get("error"),
    }


# ── 产品替换 ARQ 任务体（原 routes/toolbox.py 后台线程 _run_replace 平移） ──

@register_task('toolbox_product_replace')
async def toolbox_product_replace_task(ctx, payload: dict, task_id: str):
    """
    产品替换任务（ARQ）：执行体与原后台线程 _run_replace 完全一致
    （replace_product 内部负责进度/完成/失败状态写入与返回结果）
    payload: {product_image, reference_image, prompt, user_id, deducted, cost,
              feature_key, tool_name, history_input}
    """
    from services.history_service import save_history
    from services.feature_pricing_service import refund_coins

    product_image = payload['product_image']
    reference_image = payload['reference_image']
    prompt = payload.get('prompt')
    user_id = payload.get('user_id')
    deducted = payload.get('deducted', False)
    cost = payload.get('cost', 0)
    feature_key = payload.get('feature_key', 'toolbox.product_replace')
    tool_name = payload.get('tool_name', '产品替换')
    history_input = payload.get('history_input', {})

    try:
        await set_progress(ctx, task_id, "正在提交替换任务...")
        result_image = await asyncio.to_thread(
            replace_product, task_id, product_image, reference_image, prompt=prompt, user_id=user_id
        )
        # 保存历史记录
        try:
            save_history(
                user_id=user_id,
                category='ai_toolbox',
                sub_category='product_replace',
                input_data=history_input,
                output_data={'result_image': result_image},
            )
        except Exception:
            pass  # 历史记录保存失败不影响主流程
    except ToolboxError as e:
        if deducted:
            try:
                refund_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款',
                             related_batch_id=task_id)
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
    except Exception as e:
        print(f"[工具箱-产品替换] 后台任务异常: {e}", flush=True)
        print(f"[工具箱-产品替换] 异常堆栈: {traceback.format_exc()}", flush=True)
        await set_progress(ctx, task_id, "处理失败")
        await fail_task(ctx, task_id, f"产品替换失败: {str(e)}")
        if deducted:
            try:
                refund_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款',
                             related_batch_id=task_id)
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)


def _analyze_product_features(images_base64_list: List[str], user_id: int = None) -> Dict[str, Any]:
    """
    调用多模态 LLM 分析产品图片，提取产品特征并生成一致性保护提示词

    Args:
        images_base64_list: 商品图 base64 列表
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        dict: {
            feature_checklist: {category, shape, color, material, texture, brand_logo, size, details},
            consistency_prompt: "detailed English prompt for product consistency protection"
        }

    Raises:
        ToolboxError: 分析失败时抛出
    """
    model_name = AIConfig.MULTIMODAL_MODEL_NAME

    system_prompt = (
        "你是一位专业的电商产品摄影师，擅长分析产品视觉特征。\n"
        "请仔细分析用户提供的产品图片，提取以下产品特征信息：\n\n"
        "1. category（品类）：产品所属的具体品类，如 \"运动鞋\"、\"蓝牙耳机\"、\"不锈钢水杯\"\n"
        "2. shape（形状）：产品的外形描述，如 \"圆筒形\"、\"长方形\"、\"L形\"\n"
        "3. color（颜色）：产品的主色调和配色方案，如 \"黑色主体+红色logo\"\n"
        "4. material（材质）：产品的主要材质，如 \"ABS塑料\"、\"不锈钢\"、\"硅胶\"\n"
        "5. texture（纹理）：产品表面的纹理特征，如 \"磨砂\"、\"光滑镜面\"、\"碳纤维纹理\"\n"
        "6. brand_logo（品牌标识）：产品上的品牌logo或文字信息，位置和颜色\n"
        "7. size（尺寸比例）：产品的大致尺寸比例，如 \"长宽比约 3:1\"、\"紧凑型\"\n"
        "8. details（细节特征）：其他值得注意的视觉细节，如接口位置、按键布局、特殊结构等\n\n"
        "此外，请生成一段详细的英文提示词片段（consistency_prompt），"
        "用于在 AI 图像生成时强制保持产品外观一致性。\n"
        "该提示词应包含所有上述特征，确保生成的图片中产品外观与原始产品完全一致。\n\n"
        "必须以 JSON 格式返回，结构如下：\n"
        '{"feature_checklist": {"category": "", "shape": "", "color": "", "material": "", "texture": "", "brand_logo": "", "size": "", "details": ""}, "consistency_prompt": "..."}\n\n'
        "重要规则：\n"
        "- 仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本\n"
        "- feature_checklist 中所有字段都必须填写，未知信息填 \"未识别\"\n"
        "- consistency_prompt 必须是英文，详细且具体，可直接用于 Stable Diffusion / Midjourney 等生图工具\n"
        "- consistency_prompt 应聚焦于产品外观保护，不要包含场景、背景、光线等非产品特征"
    )

    user_content: List[Dict[str, Any]] = []

    user_content.append({
        "type": "text",
        "text": f"请分析这 {len(images_base64_list)} 张产品图片，提取产品特征并生成一致性保护提示词。"
    })

    for img_b64 in images_base64_list:
        if not img_b64.startswith("data:"):
            img_b64 = f"data:image/png;base64,{img_b64}"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": img_b64}
        })

    request_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    try:
        print(f"[工具箱-合并] 开始分析 {len(images_base64_list)} 张产品图特征...", flush=True)
        data = _call_multimodal_api(request_body, operation_name="工具箱-合并-特征分析", user_id=user_id)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"[工具箱-合并] AI 返回内容长度: {len(content)} 字符", flush=True)

        if not content:
            raise ToolboxError(
                code=5002,
                message="产品特征分析服务返回空结果，请重试",
                http_status=502
            )

        result = _extract_json_from_text(content)

        # 补全缺失字段
        checklist = result.get("feature_checklist", {})
        for field in ["category", "shape", "color", "material", "texture", "brand_logo", "size", "details"]:
            checklist.setdefault(field, "未识别")

        consistency_prompt = result.get("consistency_prompt", "")
        if not consistency_prompt:
            print(f"[工具箱-合并] 警告：consistency_prompt 为空，AI 原始返回前500字: {content[:500]}", flush=True)

        print(f"[工具箱-合并] 产品特征分析完成: category={checklist.get('category', '')}", flush=True)
        return {
            "feature_checklist": checklist,
            "consistency_prompt": consistency_prompt,
        }

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"产品特征分析失败: {str(e)}",
            http_status=500
        )


def _image_to_image_merge_by_channel(
    images_base64_list: List[str],
    prompt: str,
    size: str,
    api_base: str,
    api_key: str,
    model_name: str,
) -> str:
    """在单一通道内完成「解码入参 + 构建表单 + 重试循环」，全部重试失败时抛 ToolboxError"""
    max_retries = AIConfig.IMAGE_GEN_MAX_RETRIES
    timeout = AIConfig.IMAGE_GEN_TIMEOUT

    # 解码所有产品图为 bytes，作为 image 文件上传
    image_files = []
    for idx, img_b64 in enumerate(images_base64_list):
        try:
            img_bytes = _decode_base64_image(img_b64, f"第{idx + 1}张产品图")
            image_files.append(("image", (f"product_{idx + 1}.png", img_bytes, "image/png")))
        except ToolboxError:
            raise

    form_data = {
        "model": model_name,
        "prompt": prompt,
        "size": size,
        "n": int(1),
    }

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                print(f"[工具箱-合并-图生图] 第 {attempt} 次重试...", flush=True)
                import time as _time
                _time.sleep(2 * attempt)

            response = requests.post(
                f"{api_base}/images/edits",
                files=image_files,
                data=form_data,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )

            if response.status_code == 200:
                result = _parse_image_response(response)
                url = result.get("url")
                b64 = result.get("b64_json")
                if b64:
                    return f"data:image/png;base64,{b64}"
                if url:
                    try:
                        img_resp = requests.get(url, timeout=timeout)
                        if img_resp.status_code == 200:
                            return _encode_bytes_to_data_url(img_resp.content, "image/png")
                    except Exception as e:
                        print(f"[工具箱-合并-图生图] 下载图片 URL 失败: {e}", flush=True)
                    return url
                raise ToolboxError(
                    code=5002,
                    message="图生图模型返回结果为空",
                    http_status=502
                )

            if response.status_code == 429:
                last_error = ToolboxError(
                    code=5002,
                    message="生图服务繁忙，正在重试...",
                    http_status=503
                )
                continue

            error_msg = _safe_error_msg(response)
            raise ToolboxError(
                code=5002,
                message=f"图生图合并失败: {error_msg}",
                http_status=502
            )

        except requests.exceptions.Timeout:
            print(f"[工具箱-合并-图生图] 超时 (第 {attempt + 1}/{max_retries + 1} 次)", flush=True)
            last_error = ToolboxError(
                code=5002,
                message="AI模型响应超时，请稍后重试",
                http_status=504
            )
        except requests.exceptions.ConnectionError:
            print(f"[工具箱-合并-图生图] 连接错误 (第 {attempt + 1}/{max_retries + 1} 次)", flush=True)
            last_error = ToolboxError(
                code=5002,
                message="无法连接生图服务，请检查网络后重试",
                http_status=503
            )
        except ToolboxError as e:
            if e.http_status == 503:
                last_error = e
                continue
            raise

    raise last_error or ToolboxError(
        code=5002,
        message="图生图合并失败，已达最大重试次数",
        http_status=502
    )


def _image_to_image_merge(
    images_base64_list: List[str],
    prompt: str,
    size: str = "1024x1024",
    user_id: int = None,
) -> str:
    """
    图生图合并：调用 /v1/images/edits 端点，以产品图为输入生成白底综合展示图

    Args:
        images_base64_list: 产品图 base64 列表
        prompt: 生图提示词（布局、白底等要求）
        size: 输出尺寸，默认 1024x1024
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        data URL 格式的合并图片

    Raises:
        ToolboxError: 生图失败时抛出
    """
    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_IMAGE_GEN):
        try:
            merged = _image_to_image_merge_by_channel(
                images_base64_list, prompt, size,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return merged
        except ToolboxError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, e.message)

    raise last_channel_error or ToolboxError(
        code=5002,
        message="图生图合并失败，已达最大重试次数",
        http_status=502
    )


def _ai_smart_merge(
    images_base64_list: List[str],
    feature_checklist: Dict[str, str],
    consistency_prompt: str,
    retry_hints: Optional[str] = None,
    user_id: int = None,
) -> str:
    """
    AI 智能合并：使用图生图模型将多张产品图合并为一张白底综合展示图

    将产品图作为输入传入 /v1/images/edits，模型基于产品图生成白底综合展示图。

    Args:
        images_base64_list: 原始输入图片 base64 列表
        feature_checklist: 产品特征清单（来自 _analyze_product_features）
        consistency_prompt: 产品一致性保护提示词
        retry_hints: 可选的重试修正提示（来自一致性校验失败后的修正建议）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        data URL 格式的合并图片

    Raises:
        ToolboxError: 合并失败时抛出
    """
    # 构建图生图提示词：聚焦白底 + 布局 + 电商展示风格
    prompt_parts = []

    # 1. 白底要求
    prompt_parts.append(
        "Background: Pure white background (#FFFFFF), no shadows, no gradients, no textures, "
        "clean and minimal e-commerce style."
    )

    # 2. 产品布局要求
    prompt_parts.append(
        "Layout: Arrange all product images in a clean grid or gallery layout. "
        "Each product should be clearly visible, well-spaced, and properly scaled. "
        "Professional e-commerce product display composition."
    )

    # 3. 产品一致性保护
    if consistency_prompt:
        prompt_parts.append(
            "Product Consistency: " + consistency_prompt
        )

    # 4. 重试修正提示（如有）
    if retry_hints:
        prompt_parts.append(
            "CORRECTION INSTRUCTIONS: " + retry_hints
        )

    full_prompt = "\n\n".join(prompt_parts)

    print(f"[工具箱-合并] 开始 AI 智能合并（图生图），产品图 {len(images_base64_list)} 张，提示词长度: {len(full_prompt)} 字符", flush=True)

    try:
        result = _image_to_image_merge(images_base64_list, full_prompt, user_id=user_id)
        print(f"[工具箱-合并] AI 智能合并完成", flush=True)
        return result
    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"AI 智能合并失败: {str(e)}",
            http_status=500
        )


def _verify_product_consistency(
    merged_image: str,
    original_images_base64_list: List[str],
    feature_checklist: Dict[str, str],
    user_id: int = None,
) -> Dict[str, Any]:
    """
    一致性校验：将合并结果与原始图片比对，检测产品特征偏差

    调用多模态 LLM 将合并结果与原始输入图片逐一比对，检测形状变形、
    颜色偏移、纹理丢失、标识错误等偏差。

    Args:
        merged_image: AI 合并后的图片 data URL
        original_images_base64_list: 原始输入图片 base64 列表
        feature_checklist: 产品特征清单

    Returns:
        {passed: bool, issues: [str, ...], correction_hints: str}

    Raises:
        ToolboxError: 校验服务异常时抛出
    """
    model_name = AIConfig.MULTIMODAL_MODEL_NAME

    system_prompt = (
        "你是一位严格的产品质量控制专家。请仔细比对以下两张图片：\n"
        "第一张是 AI 生成的合并图片，后续几张是原始输入图片。\n"
        "请检查合并图片中的产品是否与原图完全一致，重点检查：\n"
        "1. 形状：产品轮廓、比例是否变形\n"
        "2. 颜色：主色调、配色是否偏移\n"
        "3. 材质：表面质感是否发生变化\n"
        "4. 纹理：细节纹理是否丢失或改变\n"
        "5. 品牌标识：Logo、文字是否清晰准确\n"
        "6. 其他细节：包装、配件、标签等是否完整\n\n"
        "必须以 JSON 格式返回：\n"
        '{{"passed": true/false, "issues": ["偏差描述1", "偏差描述2"], "correction_hints": "修正建议（英文，用于生图提示词修正）"}}\n'
        "重要：仅输出合法 JSON，不要使用 markdown 代码块包裹。issues 和 correction_hints 使用中文。"
    )

    # 构建用户消息：特征清单 + 合并图 + 原始图
    feature_text = "产品特征清单：\n" + "\n".join(
        f"- {key}: {value}" for key, value in feature_checklist.items() if value
    )

    user_content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"{feature_text}\n\n请比对合并图片与原始图片，检测产品特征偏差。"},
    ]

    # 添加合并图片
    merged_b64 = merged_image
    if not merged_b64.startswith("data:"):
        merged_b64 = f"data:image/png;base64,{merged_b64}"
    user_content.append({
        "type": "image_url",
        "image_url": {"url": merged_b64}
    })

    # 添加原始图片（最多 3 张，避免 token 超限）
    for img_b64 in original_images_base64_list[:3]:
        if not img_b64.startswith("data:"):
            img_b64 = f"data:image/png;base64,{img_b64}"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": img_b64}
        })

    request_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
    }

    try:
        print(f"[工具箱-合并] 开始一致性校验，比对 {len(original_images_base64_list)} 张原始图片...", flush=True)
        data = _call_multimodal_api(request_body, operation_name="工具箱-合并-一致性校验", user_id=user_id)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            raise ToolboxError(
                code=5002,
                message="产品一致性校验服务返回空结果，请重试",
                http_status=502
            )

        try:
            result = _extract_json_from_text(content)
        except ToolboxError:
            print(f"[工具箱-合并] 校验 JSON 解析失败，使用原始文本", flush=True)
            return {
                "passed": False,
                "issues": [content[:500]],
                "correction_hints": content[:500],
            }

        passed = bool(result.get("passed", False))
        issues = result.get("issues", []) or []
        correction_hints = result.get("correction_hints", "") or ""

        if passed:
            print(f"[工具箱-合并] 一致性校验通过", flush=True)
        else:
            print(f"[工具箱-合并] 一致性校验未通过: {len(issues)} 个问题", flush=True)
            for issue in issues:
                print(f"[工具箱-合并]   - {issue}", flush=True)

        return {
            "passed": passed,
            "issues": issues,
            "correction_hints": correction_hints,
        }

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"产品一致性校验失败: {str(e)}",
            http_status=500
        )


# ── Task 6: 图片合并（AI 智能合并）──

def merge_images(images_base64_list: List[str], user_id: int = None) -> Dict[str, Any]:
    """
    AI 智能合并：将多张产品图合并为一张综合图片

    流程：
    1. 图片质量校验（分辨率、文件大小）
    2. 产品特征分析（调用多模态 LLM 提取特征）
    3. AI 生图合并（调用 text_to_image 生成综合图片）
    4. 一致性校验（比对合并结果与原始图片）
    5. 修正重试（校验不通过时最多重试 1 次）

    Args:
        images_base64_list: base64 编码图片列表（2-10 张）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        {
            "image": "data:image/png;base64,...",
            "verification": {"passed": bool, "issues": [...]}
        }

    Raises:
        ToolboxError: 合并失败时抛出
    """
    import time as _time

    if not images_base64_list:
        raise ToolboxError(
            code=4001,
            message="请上传 2-10 张图片进行合并",
            http_status=400
        )

    n = len(images_base64_list)
    if n < 2 or n > 10:
        raise ToolboxError(
            code=4001,
            message="请上传 2-10 张图片进行合并",
            http_status=400
        )

    # ── 步骤0: 图片质量校验 ──
    print(f"[工具箱-合并] 步骤0: 图片质量校验，共 {n} 张图片", flush=True)
    for idx, img_b64 in enumerate(images_base64_list):
        try:
            img_bytes = _decode_base64_image(img_b64, f"第{idx + 1}张图片")
            # 检查文件大小（base64 解码后）
            img_size_mb = len(img_bytes) / (1024 * 1024)
            if img_size_mb > 20:
                raise ToolboxError(
                    code=4001,
                    message=f"第{idx + 1}张图片文件过大（{img_size_mb:.1f}MB），单张图片不超过 20MB",
                    http_status=400
                )
            # 检查分辨率
            try:
                from PIL import Image as PILImage
                img = PILImage.open(io.BytesIO(img_bytes))
                width, height = img.size
                if width < 200 or height < 200:
                    raise ToolboxError(
                        code=4001,
                        message=f"第{idx + 1}张图片尺寸过小（{width}x{height}），请上传至少 200x200 像素的图片",
                        http_status=400
                    )
            except ImportError:
                pass  # PIL 不可用时跳过分辨率检查
        except ToolboxError:
            raise
        except Exception as e:
            raise ToolboxError(
                code=5002,
                message=f"第{idx + 1}张图片质量校验失败: {str(e)}",
                http_status=400
            )
    print(f"[工具箱-合并] 图片质量校验通过", flush=True)

    # ── 步骤1: 产品特征分析 ──
    t1 = _time.time()
    print(f"[工具箱-合并] 步骤1: 产品特征分析...", flush=True)
    analysis_result = _analyze_product_features(images_base64_list, user_id=user_id)
    feature_checklist = analysis_result.get("feature_checklist", {})
    consistency_prompt = analysis_result.get("consistency_prompt", "")
    print(f"[工具箱-合并] 步骤1 完成，耗时 {_time.time() - t1:.1f}s", flush=True)

    # 检查特征分析是否有效
    has_features = any(v for v in feature_checklist.values() if v)
    if not has_features:
        print(f"[工具箱-合并] 警告: 产品特征分析未提取到有效特征，将使用通用提示词", flush=True)

    # ── 步骤2: AI 生图合并 ──
    t2 = _time.time()
    print(f"[工具箱-合并] 步骤2: AI 生图合并...", flush=True)
    merged_image = _ai_smart_merge(
        images_base64_list,
        feature_checklist,
        consistency_prompt,
        user_id=user_id,
    )
    print(f"[工具箱-合并] 步骤2 完成，耗时 {_time.time() - t2:.1f}s", flush=True)

    # ── 步骤3: 一致性校验 ──
    t3 = _time.time()
    print(f"[工具箱-合并] 步骤3: 一致性校验...", flush=True)
    verification = _verify_product_consistency(
        merged_image,
        images_base64_list,
        feature_checklist,
        user_id=user_id,
    )
    print(f"[工具箱-合并] 步骤3 完成，耗时 {_time.time() - t3:.1f}s", flush=True)

    # ── 步骤4: 修正重试（最多 1 次）──
    if not verification.get("passed", False):
        issues = verification.get("issues", [])
        correction_hints = verification.get("correction_hints", "")
        print(f"[工具箱-合并] 一致性校验未通过，触发修正重试", flush=True)
        for issue in issues:
            print(f"[工具箱-合并]   偏差: {issue}", flush=True)

        if correction_hints:
            print(f"[工具箱-合并] 步骤4: 修正重试...", flush=True)
            t4 = _time.time()
            merged_image = _ai_smart_merge(
                images_base64_list,
                feature_checklist,
                consistency_prompt,
                retry_hints=correction_hints,
                user_id=user_id,
            )
            print(f"[工具箱-合并] 修正重试完成，耗时 {_time.time() - t4:.1f}s", flush=True)

            # 二次校验
            print(f"[工具箱-合并] 步骤4b: 二次校验...", flush=True)
            verification = _verify_product_consistency(
                merged_image,
                images_base64_list,
                feature_checklist,
                user_id=user_id,
            )

    total_time = _time.time() - t1
    print(f"[工具箱-合并] 全部完成，总耗时 {total_time:.1f}s，校验{'通过' if verification.get('passed') else '未通过'}", flush=True)

    return {
        "image": merged_image,
        "verification": {
            "passed": verification.get("passed", False),
            "issues": verification.get("issues", []),
        }
    }


# ── MinerU 文档解析 ──

def _download_markdown_with_fallback(url: str) -> str:
    """
    下载 MinerU Markdown 结果，含多层降级策略：
    1. 正常请求 + 重试（指数退避，最多 3 次）
    2. 自定义 SSL Context（兼容更多 TLS 版本）
    3. 跳过 SSL 验证（兜底）

    Args:
        url: CDN 上的 markdown 文件 URL

    Returns:
        str: Markdown 文本内容

    Raises:
        ToolboxError: 所有尝试均失败时抛出
    """
    import ssl
    import time
    import urllib3

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/markdown,text/plain,*/*",
    }

    last_error = None

    # 策略 1: 正常请求 + 重试（最多 3 次，指数退避）
    for attempt in range(3):
        try:
            print(f"[工具箱-MinerU] CDN 下载尝试 {attempt + 1}/3（正常模式）...", flush=True)
            resp = requests.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            content = resp.text
            if content.strip():
                return content
        except requests.exceptions.SSLError as e:
            last_error = e
            print(f"[工具箱-MinerU] SSL 错误（尝试 {attempt + 1}）: {e}", flush=True)
        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"[工具箱-MinerU] 网络错误（尝试 {attempt + 1}）: {e}", flush=True)
        if attempt < 2:
            wait = 2 ** attempt  # 1s, 2s
            time.sleep(wait)

    # 策略 2: 自定义 SSL Context（兼容更多 TLS 版本）
    try:
        print(f"[工具箱-MinerU] CDN 下载尝试（自定义 SSL Context）...", flush=True)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.set_ciphers('DEFAULT:@SECLEVEL=1')
        resp = requests.get(url, headers=headers, timeout=60, verify=ssl_context)
        resp.raise_for_status()
        content = resp.text
        if content.strip():
            return content
    except Exception as e:
        last_error = e
        print(f"[工具箱-MinerU] 自定义 SSL Context 也失败: {e}", flush=True)

    # 策略 3: 跳过 SSL 验证（最终兜底）
    try:
        print(f"[工具箱-MinerU] CDN 下载尝试（跳过 SSL 验证）...", flush=True)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(url, headers=headers, timeout=60, verify=False)
        resp.raise_for_status()
        content = resp.text
        if content.strip():
            return content
    except Exception as e:
        last_error = e
        print(f"[工具箱-MinerU] 跳过 SSL 验证也失败: {e}", flush=True)

    raise ToolboxError(
        code=5003,
        message=f"MinerU 结果下载失败（已尝试 3 种方式均失败）: {last_error}",
        http_status=502
    )


def _extract_file_content_via_mineru(file_bytes: bytes, filename: str) -> str:
    """
    通过 MinerU Agent Lightweight Extract API 解析文档，提取 Markdown 文本内容

    流程：
    1. POST /api/v1/agent/parse/file 获取 task_id 和上传地址
    2. PUT 文件到上传地址
    3. 轮询 GET /api/v1/agent/parse/{task_id}
    4. 下载 Markdown 内容 → 返回文本

    说明：Agent API 无需 Token，直接支持文件上传，适合 AI Agent 工作流。

    Args:
        file_bytes: 文件的原始字节数据
        filename: 文件名（用于判断类型）

    Returns:
        str: 提取的 Markdown 文本内容

    Raises:
        ToolboxError: 解析失败时抛出
    """
    # ── 步骤1: 创建 Agent 解析任务，获取 task_id 和上传地址 ──
    agent_url = "https://mineru.net/api/v1/agent/parse/file"
    agent_headers = {"Content-Type": "application/json"}
    agent_payload = {
        "file_name": filename,
        "language": "ch",
        "enable_table": True,
        "is_ocr": False,
        "enable_formula": True,
    }

    try:
        print(f"[工具箱-MinerU] 步骤1: 创建 Agent 解析任务，文件: {filename} ({len(file_bytes)} bytes)", flush=True)
        agent_res = requests.post(agent_url, headers=agent_headers, json=agent_payload, timeout=30)
        if agent_res.status_code != 200:
            raise ToolboxError(
                code=5003,
                message=f"MinerU Agent API 请求失败 (HTTP {agent_res.status_code})",
                http_status=502
            )
        agent_data = agent_res.json()
        if agent_data.get("code") != 0:
            raise ToolboxError(
                code=5003,
                message=f"MinerU Agent API 返回错误: {agent_data.get('msg', '未知错误')}",
                http_status=502
            )

        task_id = agent_data.get("data", {}).get("task_id", "")
        upload_url = agent_data.get("data", {}).get("file_url", "")
        if not task_id or not upload_url:
            raise ToolboxError(
                code=5003,
                message="MinerU Agent API 未返回 task_id 或上传地址",
                http_status=502
            )
        print(f"[工具箱-MinerU] Agent 任务创建成功, task_id: {task_id}", flush=True)

    except requests.exceptions.RequestException as e:
        raise ToolboxError(
            code=5003,
            message=f"MinerU Agent API 网络异常: {str(e)}",
            http_status=502
        )
    except ToolboxError:
        raise

    # ── 步骤2: 上传文件到预签名 URL ──
    try:
        print(f"[工具箱-MinerU] 步骤2: 上传文件到 MinerU ({len(file_bytes)} bytes)...", flush=True)
        upload_res = requests.put(upload_url, data=file_bytes, timeout=120)
        if upload_res.status_code not in (200, 201):
            raise ToolboxError(
                code=5003,
                message=f"MinerU 文件上传失败 (HTTP {upload_res.status_code})",
                http_status=502
            )
        print(f"[工具箱-MinerU] 文件上传成功", flush=True)
    except requests.exceptions.RequestException as e:
        raise ToolboxError(
            code=5003,
            message=f"MinerU 文件上传网络异常: {str(e)}",
            http_status=502
        )
    except ToolboxError:
        raise

    # ── 步骤3: 轮询任务状态 ──
    query_url = f"https://mineru.net/api/v1/agent/parse/{task_id}"
    max_poll_times = 60       # 最多轮询 60 次
    poll_interval_sec = 5     # 每 5 秒轮询一次
    markdown_url = None

    for i in range(max_poll_times):
        try:
            query_res = requests.get(query_url, timeout=15)

            if query_res.status_code == 404:
                raise ToolboxError(
                    code=5003,
                    message="MinerU 解析任务不存在，task_id 可能无效或已过期",
                    http_status=502
                )
            if query_res.status_code != 200:
                print(f"[工具箱-MinerU] 轮询返回 HTTP {query_res.status_code}，第 {i+1}/{max_poll_times} 次", flush=True)
                import time
                time.sleep(poll_interval_sec)
                continue

            qdata = query_res.json()
            if qdata.get("code") != 0:
                if i == 0:
                    print(f"[工具箱-MinerU] 首次轮询完整响应: {json.dumps(qdata, ensure_ascii=False)[:800]}", flush=True)
                import time
                time.sleep(poll_interval_sec)
                continue

            data_block = qdata.get("data", {})
            if not isinstance(data_block, dict):
                import time
                time.sleep(poll_interval_sec)
                continue

            state = data_block.get("state", "")
            err_msg = data_block.get("err_msg", "")

            if state == "done":
                markdown_url = data_block.get("markdown_url", "")
                # 打印 data_block 所有字段，便于排查可用的内容字段
                print(f"[工具箱-MinerU] 文档解析完成（第 {i+1} 次轮询），data_block keys: {list(data_block.keys())}", flush=True)
                # 尝试从轮询响应直接获取内容（降级方案，避免 CDN 下载失败）
                direct_content = data_block.get("content") or data_block.get("text") or data_block.get("full_text") or ""
                if direct_content.strip():
                    print(f"[工具箱-MinerU] 从轮询响应直接获取内容，共 {len(direct_content)} 字符", flush=True)
                    return direct_content
                break
            elif state == "failed":
                raise ToolboxError(
                    code=5003,
                    message=f"MinerU 文档解析失败: {err_msg or '未知错误'}",
                    http_status=502
                )
            else:
                if (i + 1) % 6 == 0:  # 每 ~30 秒打印一次进度
                    print(f"[工具箱-MinerU] 解析中... 状态: {state}，第 {i+1}/{max_poll_times} 次", flush=True)

        except requests.exceptions.RequestException as e:
            print(f"[工具箱-MinerU] 轮询网络异常: {e}，第 {i+1}/{max_poll_times} 次", flush=True)
        except ToolboxError:
            raise

        import time
        time.sleep(poll_interval_sec)

    if not markdown_url:
        raise ToolboxError(
            code=5003,
            message=f"MinerU 文档解析超时（已等待 {max_poll_times * poll_interval_sec} 秒），请稍后重试",
            http_status=504
        )

    # ── 步骤4: 下载 Markdown 内容（含多层降级策略）──
    try:
        print(f"[工具箱-MinerU] 步骤4: 下载 Markdown 结果...", flush=True)
        print(f"[工具箱-MinerU] CDN URL: {markdown_url}", flush=True)
        md_content = _download_markdown_with_fallback(markdown_url)
        print(f"[工具箱-MinerU] 文本提取成功，共 {len(md_content)} 字符", flush=True)
        return md_content
    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5003,
            message=f"MinerU 结果处理失败: {str(e)}",
            http_status=500
        )


# ── Task 7: 生图计划分析 ──

def analyze_generation_plan(
    images_base64_list: List[str],
    file_content: Optional[str] = None,
    prompt: Optional[str] = None,
    file_data: Optional[str] = None,
    file_name: Optional[str] = None,
    user_id: int = None,
) -> Dict[str, Any]:
    """
    生图计划分析：调用多模态 LLM 分析商品图，返回结构化生图计划

    Args:
        images_base64_list: 商品图 base64 列表
        file_content: 可选的说明文件文本（直接文本内容，txt/md/json 等纯文本文件）
        prompt: 可选的用户自定义提示词
        file_data: 可选的二进制文件 base64 数据（PDF/DOC/PPT/XLS/图片等需 MinerU 解析的文件）
        file_name: 可选的二进制文件名（与 file_data 配合使用）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        dict: {scenes: [], angles: [], styles: [], prompts: [], platform_tips: {}}

    Raises:
        ToolboxError: 分析失败时抛出
    """
    model_name = AIConfig.MULTIMODAL_MODEL_NAME

    # 若提供了二进制文件数据，通过 MinerU 解析提取文本
    if file_data and file_name:
        try:
            raw_bytes = _decode_base64_image(file_data, label="文档文件")
            file_content = _extract_file_content_via_mineru(raw_bytes, file_name)
        except ToolboxError:
            raise
        except Exception as e:
            raise ToolboxError(
                code=5003,
                message=f"文档解析失败: {str(e)}",
                http_status=500
            )

    system_prompt = (
        "你是一位资深的跨境电商商品摄影总监，拥有 15 年以上的商品图拍摄与策划经验。\n"
        "请根据用户提供的商品图片和可选的说明文件，输出一份简洁、可直接执行的生图方案。\n\n"
        "必须以 JSON 格式返回，包含以下字段：\n\n"
        "1. summary（字符串）：分析数据摘要，说明从图片和文件中识别到的关键信息，包括商品品类、核心卖点、规格件数、材质颜色、目标市场等\n"
        "2. images（数组）：逐图方案，建议 6-8 张图，每项包含：\n"
        "   - index: 图片序号（整数，从 1 开始）\n"
        "   - title: 图片标题（中文，如 \"主图：整套识别图\"）\n"
        "   - plan: 这张图的方案（中文，说明拍什么、怎么构图、突出什么）\n"
        "   - reason: 选择这个方案的原因（中文，说明为什么这张图需要这样拍）\n"
        "   - prompt_cn: 中文 AI 出图提示词（详细描述画面内容，可直接复制使用）\n"
        "   - prompt_en: 英文 AI 出图提示词（详细描述画面内容，可用于 Midjourney/SDXL，可直接复制）\n"
        "   - backup_prompt_cn: 备用中文提示词（不同风格或角度的替代方案，可直接复制）\n"
        "   - backup_prompt_en: 备用英文提示词（不同风格或角度的替代方案，可直接复制）\n\n"
        "重要规则：\n"
        "- 仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本\n"
        "- summary 和 images 中的非提示词字段必须使用中文\n"
        "- 所有提示词必须足够详细，可直接用于 AI 生图工具\n"
        "- 每张图的提示词应独立完整，可直接复制使用\n"
        "- 方案和原因要简洁明了，聚焦跨境电商转化需求\n"
        "- 备用提示词应提供不同视角或风格的替代方案，而非简单重复\n"
        "- 必须注意风险控制：不要承诺商品不具备的特性，不要使用夸大宣传用语"
    )

    user_content: List[Dict[str, Any]] = []

    if file_content:
        user_content.append({
            "type": "text",
            "text": f"用户提供的说明文件内容：\n{file_content}\n\n请结合图片和说明文件综合分析。"
        })

    if prompt and prompt.strip():
        user_content.append({
            "type": "text",
            "text": f"用户的自定义提示词：\n{prompt.strip()}\n\n请在生成生图计划时充分考虑上述提示词的偏好与要求。"
        })

    user_content.append({
        "type": "text",
        "text": f"请分析这 {len(images_base64_list)} 张商品图片，并返回结构化的生图计划 JSON。"
    })

    for img_b64 in images_base64_list:
        if not img_b64.startswith("data:"):
            img_b64 = f"data:image/png;base64,{img_b64}"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": img_b64}
        })

    request_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 8192,
    }

    try:
        print(f"[工具箱-计划分析] 开始分析 {len(images_base64_list)} 张商品图...", flush=True)
        data = _call_multimodal_api(request_body, operation_name="工具箱-计划分析", user_id=user_id)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"[工具箱-计划分析] AI 返回内容长度: {len(content)} 字符", flush=True)
        finish_reason = data.get("choices", [{}])[0].get("finish_reason", "")
        if finish_reason == "length":
            print(f"[工具箱-计划分析] 警告：输出被截断（finish_reason=length），请增大 max_tokens", flush=True)

        if not content:
            raise ToolboxError(
                code=5002,
                message="生图计划分析服务返回空结果，请重试",
                http_status=502
            )

        # 尝试解析 JSON
        try:
            result = _extract_json_from_text(content)
        except ToolboxError:
            print(f"[工具箱-计划分析] JSON 解析失败，返回原始文本", flush=True)
            return {
                "summary": "",
                "images": [],
                "raw_text": content,
            }

        # 结果有效性检查：summary 和 images 均为空时，视为解析失败
        images = result.get("images", []) or []
        summary = result.get("summary", "") or ""
        if not summary and not images:
            print(f"[工具箱-计划分析] JSON 解析成功但结果为空，AI 原始返回前500字: {content[:500]}", flush=True)
            return {
                "summary": "",
                "images": [],
                "raw_text": content,
            }

        # 补全缺失字段，确保所有字段都有默认值
        for img in images:
            img.setdefault("index", 0)
            img.setdefault("title", "")
            img.setdefault("plan", "")
            img.setdefault("reason", "")
            img.setdefault("prompt_cn", "")
            img.setdefault("prompt_en", "")
            img.setdefault("backup_prompt_cn", "")
            img.setdefault("backup_prompt_en", "")

        print(f"[工具箱-计划分析] 分析完成: summary={len(summary)}字, images={len(images)}张", flush=True)
        return {
            "summary": summary,
            "images": images,
        }

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"生图计划分析失败: {str(e)}",
            http_status=500
        )


# ── Task 8: 对话式生图 ──

def chat_generate(
    messages: List[Dict[str, Any]],
    reference_images: Optional[List[str]] = None,
    user_id: int = None,
) -> Dict[str, Any]:
    """
    对话式生图：AI 判断用户需求是否明确，明确则调用文生图，不明确则返回澄清问题

    Args:
        messages: 对话历史 [{role, content}, ...]
        reference_images: 可选参考图 base64 列表
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        {reply: '...', images: ['data:image/...']}

    Raises:
        ToolboxError: 调用失败时抛出
    """
    model_name = AIConfig.MULTIMODAL_MODEL_NAME

    system_prompt = (
        "你是一位专业的电商商品图生图助手。请根据用户对话判断需求：\n"
        "1. 如果用户需求已经明确（包含具体的商品、场景、风格、视角等关键信息），"
        "请返回 JSON：{\"reply\": \"简要回复说明正在生成图片\", \"need_image\": true, "
        "\"image_prompt\": \"用于文生图的英文详细提示词，包含商品、场景、光影、相机参数、风格等\"}。\n"
        "2. 如果用户需求不明确，请返回 JSON：{\"reply\": \"向用户提出的澄清问题（中文）\", "
        "\"need_image\": false, \"image_prompt\": \"\"}。\n\n"
        "重要：仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本。"
        "reply 字段必须使用中文。image_prompt 字段必须使用英文，且足够详细用于 AI 生图。"
    )

    # 构建用户消息内容（含参考图）
    llm_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    # 将对话历史转换为 LLM 消息格式，最后一条用户消息可能需要附加参考图
    for i, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role not in ("user", "assistant"):
            role = "user"

        # 仅在最后一条用户消息上附加参考图
        if role == "user" and i == len(messages) - 1 and reference_images:
            user_content: List[Dict[str, Any]] = [{"type": "text", "text": content}]
            for img_b64 in reference_images:
                if not img_b64.startswith("data:"):
                    img_b64 = f"data:image/png;base64,{img_b64}"
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_b64}
                })
            llm_messages.append({"role": role, "content": user_content})
        else:
            llm_messages.append({"role": role, "content": content})

    request_body = {
        "model": model_name,
        "messages": llm_messages,
        "temperature": 0.5,
        "max_tokens": 2048,
    }

    try:
        print(f"[工具箱-对话生图] 处理 {len(messages)} 条消息，参考图 {len(reference_images or [])} 张", flush=True)
        data = _call_multimodal_api(request_body, operation_name="工具箱-对话生图", user_id=user_id)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            raise ToolboxError(
                code=5002,
                message="对话生图服务返回空结果，请重试",
                http_status=502
            )

        # 解析 LLM 返回的 JSON
        try:
            result = _extract_json_from_text(content)
        except ToolboxError:
            # 解析失败，直接返回原始文本作为回复
            print(f"[工具箱-对话生图] JSON 解析失败，返回原始文本", flush=True)
            return {"reply": content, "images": []}

        reply = result.get("reply", content)
        need_image = bool(result.get("need_image", False))
        image_prompt = result.get("image_prompt", "")

        images: List[str] = []
        if need_image and image_prompt:
            try:
                print(f"[工具箱-对话生图] 调用文生图，提示词: {image_prompt[:100]}...", flush=True)
                image_data_url = text_to_image(image_prompt, user_id=user_id)
                images.append(image_data_url)
            except ToolboxError as e:
                # 生图失败不影响回复，在 reply 中追加提示
                print(f"[工具箱-对话生图] 文生图失败: {e.message}", flush=True)
                reply = f"{reply}\n\n（图片生成失败：{e.message}）"

        return {"reply": reply, "images": images}

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"对话生图失败: {str(e)}",
            http_status=500
        )


# ── Task 8 扩展: 产品替换 ──

def replace_product(
    task_id: str,
    product_image: str,
    reference_image: str,
    prompt: Optional[str] = None,
    user_id: int = None,
) -> str:
    """
    产品替换：将参考图中的商品替换为用户上传的商品

    实现策略：
    1. 调用多模态 LLM 分析商品图和参考图，生成详细英文生图提示词
    2. 提示词包含：商品特征描述 + 参考图场景描述 + 用户提示词（如有）
    3. 调用 text_to_image 生成替换后图片

    Args:
        task_id: 任务 ID，用于追踪任务状态
        product_image: 用户上传的商品图 base64（可能含 data:image/...;base64, 前缀）
        reference_image: 参考图 base64（可能含 data:image/...;base64, 前缀）
        prompt: 可选的用户提示词

    Returns:
        data URL 格式图片

    Raises:
        ToolboxError: 处理失败时抛出
    """
    model_name = AIConfig.MULTIMODAL_MODEL_NAME

    system_prompt = (
        "你是一位资深的电商商品图设计师。请根据用户上传的商品图和参考图，"
        "生成一段详细的英文生图提示词，用于将参考图中的商品替换为用户上传的商品。\n"
        "提示词必须包含：\n"
        "1. 用户商品的核心特征（形状、颜色、材质、品牌标识、包装等）\n"
        "2. 参考图的场景描述（背景、布光、构图、氛围、道具等）\n"
        "3. 保持参考图的拍摄风格和视觉调性不变\n"
        "4. 若用户提供了额外提示词，需合理融入\n\n"
        "必须以 JSON 格式返回：{\"image_prompt\": \"详细英文提示词\"}\n"
        "重要：仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本。"
        "image_prompt 字段必须使用英文，且足够详细用于 AI 生图。"
    )

    user_content: List[Dict[str, Any]] = []

    user_text = (
        "第一张图是用户上传的商品图，第二张图是参考图。"
        "请生成英文生图提示词，将参考图中的商品替换为用户上传的商品，"
        "保持参考图的场景和风格不变。"
    )
    if prompt:
        user_text += f"\n用户额外提示词：{prompt}"
    user_content.append({"type": "text", "text": user_text})

    for img_b64 in [product_image, reference_image]:
        if not img_b64.startswith("data:"):
            img_b64 = f"data:image/png;base64,{img_b64}"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": img_b64}
        })

    request_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.4,
        "max_tokens": 2048,
    }

    set_progress_sync(task_id, "正在分析商品图与参考图...")

    try:
        print(f"[工具箱-产品替换] 开始分析商品图与参考图...", flush=True)
        data = _call_multimodal_api(request_body, operation_name="工具箱-产品替换", user_id=user_id)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            raise ToolboxError(
                code=5002,
                message="产品替换服务返回空结果，请重试",
                http_status=502
            )

        try:
            result = _extract_json_from_text(content)
        except ToolboxError:
            print(f"[工具箱-产品替换] JSON 解析失败，使用原始文本作为提示词", flush=True)
            image_prompt = content.strip()
        else:
            image_prompt = result.get("image_prompt", "").strip()
            if not image_prompt:
                image_prompt = content.strip()

        set_progress_sync(task_id, "正在生成替换图片...")

        try:
            ref_w, ref_h = _get_image_dimensions(reference_image, "参考图")
            target_size = _calc_size_from_aspect(ref_w, ref_h)
            print(f"[工具箱-产品替换] 参考图尺寸: {ref_w}x{ref_h}, 目标生图尺寸: {target_size}", flush=True)
        except ToolboxError:
            target_size = None

        print(f"[工具箱-产品替换] 调用文生图，提示词: {image_prompt[:100]}...", flush=True)
        result = text_to_image(image_prompt, size=target_size, user_id=user_id)
        set_progress_sync(task_id, "处理完成", pct=100)
        complete_task_sync(task_id, {"image": result})
        return result

    except ToolboxError as e:
        fail_task_sync(task_id, e.message)
        raise
    except Exception as e:
        fail_task_sync(task_id, str(e))
        raise ToolboxError(
            code=5002,
            message=f"产品替换失败: {str(e)}",
            http_status=500
        )


# ── Task 8 扩展: AI 模特三视图 ──

def _image_to_image_edit_by_channel(
    image_base64: str,
    prompt: str,
    size: str,
    quality: str,
    api_base: str,
    api_key: str,
    model_name: str,
) -> str:
    """在单一通道内完成「解码入参 + 构建表单 + 重试循环」，全部重试失败时抛 ToolboxError"""
    max_retries = AIConfig.IMAGE_GEN_MAX_RETRIES
    timeout = AIConfig.IMAGE_GEN_TIMEOUT

    img_bytes = _decode_base64_image(image_base64, "人物图")

    form_data = {
        "model": model_name,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": int(1),
    }

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                print(f"[工具箱-AI模特-编辑] 第 {attempt} 次重试...", flush=True)
                import time as _time
                _time.sleep(2 * attempt)

            response = requests.post(
                f"{api_base}/images/edits",
                files=[("image", ("person.png", img_bytes, "image/png"))],
                data=form_data,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )

            if response.status_code == 200:
                result = _parse_image_response(response)
                b64 = result.get("b64_json")
                if b64:
                    return f"data:image/png;base64,{b64}"
                url = result.get("url")
                if url:
                    try:
                        img_resp = requests.get(url, timeout=timeout)
                        if img_resp.status_code == 200:
                            return _encode_bytes_to_data_url(img_resp.content, "image/png")
                    except Exception as e:
                        print(f"[工具箱-AI模特-编辑] 下载图片 URL 失败: {e}", flush=True)
                    return url
                raise ToolboxError(code=5002, message="图片编辑返回结果为空", http_status=502)

            if response.status_code == 429:
                last_error = ToolboxError(code=5002, message="生图服务繁忙，正在重试...", http_status=503)
                continue

            error_msg = _safe_error_msg(response)
            raise ToolboxError(code=5002, message=f"图片编辑失败: {error_msg}", http_status=502)

        except requests.exceptions.Timeout:
            last_error = ToolboxError(code=5002, message="AI模型响应超时，请稍后重试", http_status=504)
        except requests.exceptions.ConnectionError:
            last_error = ToolboxError(code=5002, message="无法连接生图服务，请检查网络后重试", http_status=503)
        except ToolboxError as e:
            if e.http_status == 503:
                last_error = e
                continue
            raise

    raise last_error or ToolboxError(code=5002, message="图片编辑失败，已达最大重试次数", http_status=502)


def _image_to_image_edit(
    image_base64: str,
    prompt: str,
    size: str = "1024x1024",
    quality: str = "high",
    user_id: int = None,
) -> str:
    """
    图片编辑：调用 /v1/images/edits 端点，以人物图为输入生成角色卡

    跨境电商场景下，图片编辑接口能以原图作为视觉锚点，
    在保留人物核心特征的基础上应用人种/国家/风格等编辑指令，
    生成更真实、更可控的模特图。

    Args:
        image_base64: 人物图 base64
        prompt: 英文生图提示词
        size: 输出尺寸，默认 1024x1024
        quality: 画质，"low" | "medium" | "high" | "auto"，默认 "high"
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    注意：球球Token 网关将 gpt-image-2 映射为 gpt-image-2-codex，该模型不支持 input_fidelity 参数。

    Returns:
        data URL 格式图片

    Raises:
        ToolboxError: 处理失败时抛出
    """
    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_IMAGE_GEN):
        try:
            edited = _image_to_image_edit_by_channel(
                image_base64, prompt, size, quality,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return edited
        except ToolboxError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, e.message)

    raise last_channel_error or ToolboxError(code=5002, message="图片编辑失败，已达最大重试次数", http_status=502)


def generate_ai_model(
    person_image: Optional[str],
    country: str,
    race: str,
    prompt: str,
    user_id: int = None,
) -> str:
    """
    AI模特：生成专业模特角色卡（三视图、发型展示、表情排列）

    实现策略：
    1. 有 person_image → 走图片编辑接口（/images/edits），以原图为视觉锚点保留人物特征
    2. 无 person_image → 走文生图接口（/images/generations），从零创作
    3. quality 默认设为 "high" 确保输出质量

    Args:
        person_image: 可选的人物图 base64
        country: 国家名称（用于风格特征）
        race: 人种（用于人种特征）
        prompt: 用户提示词

    Returns:
        data URL 格式图片

    Raises:
        ToolboxError: 处理失败时抛出
    """
    # 构建角色卡生图提示词
    # 人种/国家设置放在最后，确保最高优先级
    image_prompt_parts = [
        "character card template, professional character design sheet, character concept art",
        "full body standing pose, front view, three-quarter view, side view, back view",
        "hairstyle display: front hair view, back hair view, side hair detail",
        "expression sheet: neutral, happy smile, surprised, confident, thoughtful",
        "outfit variations: casual, formal, sportswear",
        "color palette reference, accessory details",
        "detailed facial features, consistent character design across all views",
        prompt,
    ]
    image_prompt_parts.append(
        f"IMPORTANT: The character MUST be {race} ethnicity with authentic {country} facial features and skin tone, "
        f"this is the most critical requirement, strictly follow the {race} ethnic appearance"
    )

    image_prompt = ", ".join([p for p in image_prompt_parts if p])
    image_prompt += ", professional fashion model character card, character design reference sheet, pure white background (#FFFFFF), uniform studio lighting, high quality, no text, no watermark"

    if person_image:
        # 有图：走图片编辑接口，保留原图人物特征
        print(f"[工具箱-AI模特] 有参考图，调用图片编辑接口...", flush=True)
        return _image_to_image_edit(person_image, image_prompt, quality="high", user_id=user_id)
    else:
        # 无图：走文生图接口
        print(f"[工具箱-AI模特] 无参考图，调用文生图接口，quality=high...", flush=True)
        return text_to_image(image_prompt, quality="high", user_id=user_id)


# ── Task 8 扩展: 模特商品图 ──

def generate_model_product(
    product_image: str,
    model_image: str,
    prompt: str,
    resolution: Optional[str] = None,
    user_id: int = 0
) -> Dict[str, str]:
    # Task 7 迁移：原 start_model_product_task 后台线程 → ARQ 任务（模特商品图）
    try:
        from services.model_product_service import MODEL_PRODUCT_TASK_NAME
    except ImportError as e:
        raise ToolboxError(
            code=5002,
            message=f"模特商品图服务模块加载失败: {str(e)}",
            http_status=500
        )
    task_id = submit_task(
        MODEL_PRODUCT_TASK_NAME,
        {
            'task_image': product_image,
            'model_image': model_image,
            'a0_prompt': prompt,
            'resolution': resolution or "1024x1024",
            'user_id': user_id,
        },
        module='toolbox',
    )
    return {"task_id": task_id, "status": "processing"}


def get_model_product_task_status(task_id: str) -> dict:
    """获取模特商品图任务状态"""
    from services.model_product_service import get_model_product_task_status as _get_status
    return _get_status(task_id)


# ── Task 8 扩展: 反推提示词 ──

def reverse_prompt(image_base64: str, user_id: int = None) -> Dict[str, str]:
    """
    反推提示词：AI 反推图片的中文和英文提示词

    Args:
        image_base64: 图片 base64（可能含 data:image/...;base64, 前缀）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        {"prompt_cn": "反推出的中文提示词", "prompt_en": "反推出的英文提示词"}

    Raises:
        ToolboxError: 处理失败时抛出
    """
    model_name = AIConfig.MULTIMODAL_MODEL_NAME

    system_prompt = (
        "你是一位资深的 AI 绘画提示词工程师。请根据用户提供的图片，"
        "反推出详细的中文和英文提示词，用于复现该图片。\n"
        "提示词需包含：\n"
        "1. 主体描述（人物、物体、动作等）\n"
        "2. 场景与背景\n"
        "3. 光影效果（光线方向、强度、色温等）\n"
        "4. 视觉风格（写实、动漫、油画、摄影等）\n"
        "5. 相机参数（焦距、光圈、视角、景深等，若适用）\n"
        "6. 色彩与氛围\n\n"
        "必须以 JSON 格式返回：\n"
        '{"prompt_cn": "中文提示词（详细描述画面内容，可直接复用于国内生图工具）", '
        '"prompt_en": "英文提示词（详细描述画面内容，可用于 Midjourney/SDXL/Flux 等工具）"}\n\n'
        "重要：仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本。"
    )

    img_b64 = image_base64
    if not img_b64.startswith("data:"):
        img_b64 = f"data:image/png;base64,{img_b64}"

    user_content: List[Dict[str, Any]] = [
        {"type": "text", "text": "请反推这张图片的详细提示词，同时输出中文和英文版本。"},
        {"type": "image_url", "image_url": {"url": img_b64}},
    ]

    request_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    try:
        print(f"[工具箱-反推提示词] 开始分析图片...", flush=True)
        data = _call_multimodal_api(request_body, operation_name="工具箱-反推提示词", user_id=user_id)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            raise ToolboxError(
                code=5002,
                message="反推提示词服务返回空结果，请重试",
                http_status=502
            )

        # 解析 JSON 响应，提取中英文提示词
        try:
            result = _extract_json_from_text(content)
            prompt_cn = result.get("prompt_cn", "")
            prompt_en = result.get("prompt_en", "")
            if prompt_cn and prompt_en:
                return {"prompt_cn": prompt_cn.strip(), "prompt_en": prompt_en.strip()}
        except ToolboxError:
            pass

        # 兜底：若 JSON 解析失败，尝试将整个内容作为英文提示词，中文留空
        cleaned = content.strip()
        code_block_match = re.search(r'```(?:[a-zA-Z]*)?\s*([\s\S]*?)\s*```', cleaned)
        if code_block_match:
            cleaned = code_block_match.group(1).strip()
        print(f"[工具箱-反推提示词] JSON 解析失败，使用原始文本作为英文提示词", flush=True)
        return {"prompt_cn": "", "prompt_en": cleaned}

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"反推提示词失败: {str(e)}",
            http_status=500
        )
