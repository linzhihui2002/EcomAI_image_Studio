"""
编辑器 AI 图像工具（module='ai'）

与 basic 工具相同约定：
- 工具函数签名统一为 func(image: PIL.Image.Image, params: dict) -> PIL.Image.Image
- 参数错误一律抛 ValueError（中文消息），由任务层转为任务失败
- AI 调用耗时较长（约 10-30 秒），tasks.py 会对 module='ai' 展示区分文案

实现方法说明（通道选型）：
- 通道：复用现有 OpenAI 兼容生图编辑通道（IMAGE_GEN_API_BASE 的 POST /images/edits，
  模型 IMAGE_GEN_MODEL_NAME=gpt-image-2），HTTP 超时 IMAGE_GEN_TIMEOUT、失败重试 1 次
- remove_background：通道生成"纯白背景主体图" → PIL 边缘泛洪去白底（阈值泛洪）→ 透明 PNG；
  通道不可用时回退为对原图直接泛洪去白底（原图本身白底/浅色纯色底时有效）
- replace_background：通道整图重绘，prompt 模板见 REPLACE_BACKGROUND_PROMPT_TEMPLATE
- inpaint_erase / inpaint_replace：优先走 /images/edits + mask（OpenAI 约定：mask 中
  完全透明区域 = 需要编辑的区域，故把前端"白=选区"蒙版反相为透明区）；通道不支持或调用
  失败时回退 PIL 扩散填充（用周边颜色多级下采样模糊后逐级回贴，逐步向选区内延展）。
  兜底局限：纯像素级填充，无生成能力——erase 效果可接受，replace 无法真正按 prompt 生成内容
- upscale：优先调通道高清化重绘（成功后再精确缩放回 2 倍目标尺寸）；失败回退
  Pillow LANCZOS 2x + UnsharpMask 锐化
"""
import io
import base64
import time
from collections import deque

import requests
from PIL import Image, ImageFilter

from config import AIConfig
from services.generation_service import _parse_image_response, _safe_error_msg
from services.user_ai_provider_service import (
    CATEGORY_IMAGE_GEN,
    iter_channel_entries,
    report_entry_failure,
    report_entry_success,
)

# ========== Prompt 常量（风格与 prompts/ 目录一致，中文描述 + 电商场景约束） ==========

REMOVE_BACKGROUND_PROMPT = (
    "抠出商品主体：保持商品主体完全一致，不要改变主体的形状、颜色与细节，"
    "将背景完全替换为纯白色（#FFFFFF），画面中除商品主体外不得出现任何其他物体、阴影或文字"
)

REPLACE_BACKGROUND_PROMPT_TEMPLATE = "保持商品主体完全一致，将背景替换为{background_prompt}，电商风格"

INPAINT_ERASE_PROMPT = (
    "移除选区内的物体，用周围背景自然填补选区，保持画面完整协调，"
    "不得出现明显的填补痕迹或重复纹理"
)

INPAINT_REPLACE_PROMPT_TEMPLATE = (
    "将选区内容替换为：{prompt}。新内容需与周围画面自然融合，"
    "保持整体光影、透视与风格一致，选区外内容保持完全不变"
)

UPSCALE_PROMPT = (
    "将图片高清放大：保持画面内容、构图与主体完全一致，"
    "增强细节纹理与边缘清晰度，不新增任何物体"
)

# 去白底时"接近白色"的判定阈值（RGB 每通道与 255 的最大差值）
_WHITE_THRESHOLD = 30


# ========== 通用辅助 ==========

def _require_params(params):
    """校验 params 为 dict"""
    if not isinstance(params, dict):
        raise ValueError('参数必须为对象（dict）')


def _get_str(params, key, required=True, max_len=500):
    """从 params 中取字符串参数并校验"""
    value = params.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f'缺少必填参数: {key}')
        return ''
    if not isinstance(value, str):
        raise ValueError(f'参数 {key} 必须为字符串')
    if len(value) > max_len:
        raise ValueError(f'参数 {key} 过长（最多 {max_len} 字）')
    return value.strip()


def _to_editable(image):
    """转为可编辑模式：有透明通道 → RGBA，否则 RGB"""
    if image.mode in ('RGBA', 'LA', 'PA') or (image.mode == 'P' and 'transparency' in image.info):
        return image.convert('RGBA')
    return image.convert('RGB')


def _nearest_api_size(width, height):
    """把任意宽高映射到生图通道支持的档位（gpt-image：1024x1024/1536x1024/1024x1536）"""
    if width > height:
        return '1536x1024'
    if height > width:
        return '1024x1536'
    return '1024x1024'


def _call_images_edits_by_channel(image_bytes, prompt, size, mask_bytes,
                                  api_base, api_key, model_name):
    """
    在单一通道内调用生图编辑通道 POST /images/edits（multipart），超时与重试习惯参考 generation_service：
    超时/连接错误/429/502/503 重试 1 次，其余错误立即抛出
    返回 {"url": ...} 或 {"b64_json": ...}；最终失败抛 ValueError（中文消息）
    """
    timeout = AIConfig.IMAGE_GEN_TIMEOUT

    files = [('image', ('image.png', image_bytes, 'image/png'))]
    if mask_bytes:
        files.append(('mask', ('mask.png', mask_bytes, 'image/png')))
    form_data = {'model': model_name, 'prompt': prompt, 'size': size, 'n': 1}

    last_error = None
    for attempt in range(2):  # 首次 + 重试 1 次
        try:
            if attempt > 0:
                print(f'[编辑器AI工具] 第 {attempt} 次重试...', flush=True)
                time.sleep(2)
            response = requests.post(
                f'{api_base}/images/edits',
                files=files,
                data=form_data,
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=timeout,
            )
            if response.status_code == 200:
                return _parse_image_response(response)
            if response.status_code in (429, 502, 503):
                last_error = ValueError(f'AI 图像服务繁忙（HTTP {response.status_code}），重试后仍失败')
                continue
            raise ValueError(
                f'AI 图像服务请求失败（HTTP {response.status_code}）: {_safe_error_msg(response)}'
            )
        except requests.exceptions.Timeout:
            last_error = ValueError('AI 图像服务响应超时，请稍后重试')
        except requests.exceptions.ConnectionError:
            last_error = ValueError('无法连接 AI 图像服务，请检查网络后重试')
    raise last_error or ValueError('AI 图像服务请求失败，已达最大重试次数')


def _call_images_edits(image_bytes, prompt, size, mask_bytes=None, user_id=None):
    """
    调用生图编辑通道 POST /images/edits（multipart），超时与重试习惯参考 generation_service：
    超时/连接错误/429/502/503 重试 1 次，其余错误立即抛出
    返回 {"url": ...} 或 {"b64_json": ...}；最终失败抛 ValueError（中文消息）

    Args:
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    """
    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_IMAGE_GEN):
        try:
            result = _call_images_edits_by_channel(
                image_bytes, prompt, size, mask_bytes,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return result
        except ValueError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, str(e))

    raise last_channel_error or ValueError('AI 图像服务请求失败，已达最大重试次数')


def _result_to_bytes(result):
    """把生图响应（b64_json 或 url）转为图片字节"""
    b64 = result.get('b64_json')
    if b64:
        try:
            return base64.b64decode(b64)
        except Exception as e:
            raise ValueError(f'AI 返回图片 base64 解码失败: {e}')
    url = result.get('url')
    if url:
        if url.startswith('data:'):
            try:
                return base64.b64decode(url.split(',', 1)[1])
            except Exception as e:
                raise ValueError(f'AI 返回图片 base64 解码失败: {e}')
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except requests.exceptions.RequestException as e:
            raise ValueError(f'下载 AI 生成图片失败: {e}')
    raise ValueError('AI 图像服务未返回图片数据')


def _decode_selection_mask(mask_data_uri, size):
    """
    解码前端上传的选区蒙版（base64 PNG / data URI，白=选区）→ L 模式蒙版
    尺寸与原图不一致时按最近邻缩放到原图尺寸
    """
    if not isinstance(mask_data_uri, str) or not mask_data_uri.strip():
        raise ValueError('缺少必填参数: mask_data_uri')
    data = mask_data_uri.strip()
    raw_b64 = data.split(',', 1)[1] if data.startswith('data:') else data
    try:
        mask_bytes = base64.b64decode(raw_b64)
    except Exception as e:
        raise ValueError(f'选区蒙版 base64 解码失败: {e}')
    if not mask_bytes:
        raise ValueError('选区蒙版数据为空')
    try:
        mask = Image.open(io.BytesIO(mask_bytes)).convert('L')
    except Exception:
        raise ValueError('选区蒙版不是有效的图片')
    if mask.size != size:
        mask = mask.resize(size, Image.NEAREST)
    return mask


def _selection_to_api_mask(mask_l):
    """
    选区蒙版（白=选区）→ 生图通道编辑蒙版（OpenAI 约定：完全透明区域=待编辑区域）
    返回 PNG 字节
    """
    api_mask = Image.new('RGBA', mask_l.size, (255, 255, 255, 255))
    alpha = mask_l.point(lambda v: 0 if v >= 128 else 255)
    api_mask.putalpha(alpha)
    buf = io.BytesIO()
    api_mask.save(buf, format='PNG')
    return buf.getvalue()


# ========== PIL 兜底算法 ==========

def _flood_remove_white(image, threshold=_WHITE_THRESHOLD):
    """
    边缘泛洪去白底：从图片四边出发，把"接近白色"的连通区域置为透明（BFS）
    返回 (RGBA Image, 移除像素数)；未移除任何像素说明背景不适合自动去底
    """
    img = image.convert('RGBA')
    width, height = img.size
    pixels = img.load()

    def is_near_white(p):
        return (p[0] >= 255 - threshold and p[1] >= 255 - threshold
                and p[2] >= 255 - threshold)

    visited = bytearray(width * height)
    queue = deque()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    removed = 0
    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= width or y >= height:
            continue
        idx = y * width + x
        if visited[idx]:
            continue
        visited[idx] = 1
        p = pixels[x, y]
        transparent = p[3] == 0
        if not transparent and not is_near_white(p):
            continue
        if not transparent:
            pixels[x, y] = (255, 255, 255, 0)
            removed += 1
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return img, removed


def _has_real_alpha(image):
    """判断 RGBA 图是否含有真实的透明像素（最小 alpha < 250）"""
    if image.mode != 'RGBA':
        return False
    alpha = image.getchannel('A')
    return alpha.getextrema()[0] < 250


def _diffusion_fill(image, mask_l, max_levels=5):
    """
    选区扩散填充（PIL 兜底）：把整图多级下采样 + 高斯模糊后逐级回贴到选区，
    让周边颜色逐步向选区内延展，最后轻微模糊接缝
    局限：纯像素级填充，无生成能力，仅保证画面可用
    """
    work = image.convert('RGB')
    width, height = work.size
    for level in range(1, max_levels + 1):
        factor = 2 ** level
        small_size = (max(1, width // factor), max(1, height // factor))
        small = work.resize(small_size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(2))
        upsampled = small.resize((width, height), Image.LANCZOS)
        work = Image.composite(upsampled, work, mask_l)
    smoothed = work.filter(ImageFilter.GaussianBlur(1.5))
    work = Image.composite(smoothed, work, mask_l)
    return work


# ========== AI 工具函数（registry func 约定签名） ==========

def remove_background(image, params, user_id=None):
    """
    抠图（去除背景，输出透明 PNG）

    方法：生图通道生成"纯白背景主体图" → PIL 边缘泛洪去白底；
    通道失败时回退为对原图直接泛洪去白底（原图为白底/浅色纯色底时有效），
    两者都无法分离背景时抛出中文错误

    user_id：用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    """
    _require_params(params)
    src = _to_editable(image)
    buf = io.BytesIO()
    src.save(buf, format='PNG')

    # 1) 生图通道生成纯白背景主体图
    api_error = None
    try:
        result = _call_images_edits(
            buf.getvalue(), REMOVE_BACKGROUND_PROMPT, _nearest_api_size(src.width, src.height),
            user_id=user_id,
        )
        generated = Image.open(io.BytesIO(_result_to_bytes(result)))
        generated = _to_editable(generated)
        # 通道直接返回了透明背景 → 采用
        if _has_real_alpha(generated):
            return generated
        # 通道返回白底图 → 泛洪去白底
        cutout, removed = _flood_remove_white(generated)
        if removed > 0:
            return cutout
        api_error = ValueError('AI 抠图结果未能分离背景，请重试')
    except ValueError as e:
        api_error = e
        print(f'[编辑器AI工具] remove_background 通道失败，尝试原图兜底: {e}', flush=True)

    # 2) 兜底：对原图直接泛洪去白底（原图本身白底/浅色纯色底时有效）
    cutout, removed = _flood_remove_white(src)
    if removed > 0:
        return cutout
    raise api_error or ValueError('抠图失败：无法从图片中分离背景，请重试或更换图片')


def replace_background(image, params, user_id=None):
    """
    换背景（整图重绘）

    参数：
    - background_prompt: 新背景描述（必填字符串，如"大理石台面俯拍场景"）
    方法：生图通道整图重绘，prompt 模板 REPLACE_BACKGROUND_PROMPT_TEMPLATE

    user_id：用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    """
    _require_params(params)
    background_prompt = _get_str(params, 'background_prompt', required=True)
    src = _to_editable(image)
    buf = io.BytesIO()
    src.save(buf, format='PNG')

    prompt = REPLACE_BACKGROUND_PROMPT_TEMPLATE.format(background_prompt=background_prompt)
    result = _call_images_edits(
        buf.getvalue(), prompt, _nearest_api_size(src.width, src.height),
        user_id=user_id,
    )
    output = Image.open(io.BytesIO(_result_to_bytes(result)))
    if output.mode == 'RGBA':
        # 叠到白底，保证输出不透明电商图
        background = Image.new('RGBA', output.size, (255, 255, 255, 255))
        background.paste(output, mask=output.getchannel('A'))
        output = background
    return output.convert('RGB')


def inpaint_erase(image, params, user_id=None):
    """
    选区消除（涂抹擦除并自然填补）

    参数：
    - mask_data_uri: 选区蒙版（必填，base64 PNG / data URI，白=选区）
    方法：优先走生图通道局部重绘（原图 + mask）；通道不支持或失败时回退 PIL 扩散填充，
    兜底局限：用周边像素延展填补，无生成能力，复杂背景可能出现模糊痕迹

    user_id：用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    """
    _require_params(params)
    src = _to_editable(image)
    mask_l = _decode_selection_mask(params.get('mask_data_uri'), src.size)
    buf = io.BytesIO()
    src.save(buf, format='PNG')

    try:
        result = _call_images_edits(
            buf.getvalue(), INPAINT_ERASE_PROMPT, _nearest_api_size(src.width, src.height),
            mask_bytes=_selection_to_api_mask(mask_l),
            user_id=user_id,
        )
        return Image.open(io.BytesIO(_result_to_bytes(result))).convert('RGB')
    except ValueError as e:
        print(f'[编辑器AI工具] inpaint_erase 通道失败，使用扩散填充兜底: {e}', flush=True)
        return _diffusion_fill(src, mask_l)


def inpaint_replace(image, params, user_id=None):
    """
    选区重绘（选区内按 prompt 重新生成内容）

    参数：
    - mask_data_uri: 选区蒙版（必填，base64 PNG / data URI，白=选区）
    - prompt: 重绘内容描述（必填字符串）
    方法：优先走生图通道局部重绘（原图 + mask + prompt）；通道不支持或失败时回退
    PIL 扩散填充，兜底局限：无法真正按 prompt 生成新内容，仅清除原选区内容

    user_id：用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    """
    _require_params(params)
    prompt = _get_str(params, 'prompt', required=True)
    src = _to_editable(image)
    mask_l = _decode_selection_mask(params.get('mask_data_uri'), src.size)
    buf = io.BytesIO()
    src.save(buf, format='PNG')

    final_prompt = INPAINT_REPLACE_PROMPT_TEMPLATE.format(prompt=prompt)
    try:
        result = _call_images_edits(
            buf.getvalue(), final_prompt, _nearest_api_size(src.width, src.height),
            mask_bytes=_selection_to_api_mask(mask_l),
            user_id=user_id,
        )
        return Image.open(io.BytesIO(_result_to_bytes(result))).convert('RGB')
    except ValueError as e:
        print(f'[编辑器AI工具] inpaint_replace 通道失败，使用扩散填充兜底: {e}', flush=True)
        return _diffusion_fill(src, mask_l)


def upscale(image, params, user_id=None):
    """
    高清放大 2 倍

    参数：
    - scale: 放大倍数（目前仅支持 2，默认 2）
    方法：优先调生图通道高清化重绘（成功后再精确缩放到 2 倍目标尺寸）；
    失败回退 Pillow LANCZOS 2x + UnsharpMask 锐化

    user_id：用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    """
    _require_params(params)
    scale = params.get('scale', 2)
    if scale is None:
        scale = 2
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not float(scale).is_integer():
        raise ValueError('参数 scale 必须为整数')
    if scale != 2:
        raise ValueError('参数 scale 仅支持: 2')
    scale = int(scale)

    src = _to_editable(image)
    target_size = (src.width * scale, src.height * scale)
    buf = io.BytesIO()
    src.save(buf, format='PNG')

    try:
        result = _call_images_edits(
            buf.getvalue(), UPSCALE_PROMPT, _nearest_api_size(*target_size),
            user_id=user_id,
        )
        generated = Image.open(io.BytesIO(_result_to_bytes(result)))
        # 通道输出档位固定，精确缩放回 2 倍目标尺寸
        return generated.convert('RGB').resize(target_size, Image.LANCZOS)
    except ValueError as e:
        print(f'[编辑器AI工具] upscale 通道失败，使用 LANCZOS 2x + 锐化兜底: {e}', flush=True)
        upscaled = src.convert('RGB').resize(target_size, Image.LANCZOS)
        return upscaled.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=2))
