"""
图片持久化服务
将 base64 图片保存为磁盘文件，返回可访问的 URL 路径
支持缩略图生成（WebP 格式）
"""
import os
import base64
import uuid
import time
import re

from PIL import Image

# 存储目录：auth-module-backend/uploads/history_images/
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(_BACKEND_ROOT, 'uploads', 'history_images')

# 缩略图存储目录
THUMB_DIR = os.path.join(STORAGE_DIR, 'thumbs')

# URL 前缀（相对路径，前端通过 Vite 代理访问）
URL_PREFIX = '/api/v1/images'
THUMB_URL_PREFIX = '/api/v1/images/thumb'

# 支持的图片格式 → MIME 类型映射
_FORMAT_MAP = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'webp': 'image/webp',
    'gif': 'image/gif',
}

# 缩略图默认尺寸
THUMB_SIZES = {
    'small': (200, 200),
    'medium': (400, 400),
}

# data URI 前缀正则：data:image/png;base64,...
_DATA_URI_PATTERN = re.compile(r'^data:(image/(\w+));base64,(.+)$', re.IGNORECASE)


def _ensure_storage_dir():
    """确保存储目录存在"""
    os.makedirs(STORAGE_DIR, exist_ok=True)


def _generate_filename(user_id, prefix, ext):
    """生成唯一文件名：prefix_userId_timestamp_uuid.ext"""
    ext = ext.lower().lstrip('.')
    timestamp = int(time.time())
    short_uuid = uuid.uuid4().hex[:12]
    safe_prefix = re.sub(r'[^a-zA-Z0-9_-]', '', prefix)[:20] or 'img'
    return f"{safe_prefix}_{user_id}_{timestamp}_{short_uuid}.{ext}"


def save_image_bytes(image_bytes, user_id, ext, prefix='img'):
    """
    保存原始图片字节到磁盘，返回可访问的 URL 路径

    Args:
        image_bytes: 图片字节数据
        user_id: 用户 ID（用于文件名隔离）
        ext: 文件扩展名（如 'png', 'jpg'）
        prefix: 文件名前缀（如 'thumb', 'input', 'output'）

    Returns:
        str: URL 路径，如 '/api/v1/images/img_1_1234567890_abc123.png'
    """
    _ensure_storage_dir()
    filename = _generate_filename(user_id, prefix, ext)
    file_path = os.path.join(STORAGE_DIR, filename)
    with open(file_path, 'wb') as f:
        f.write(image_bytes)
    return f"{URL_PREFIX}/{filename}"


def save_base64_image(b64_data, user_id, prefix='img'):
    """
    保存 base64 图片到磁盘，返回可访问的 URL 路径

    支持两种输入格式：
    - data URI: "data:image/png;base64,iVBORw0KGgo..."
    - 纯 base64: "iVBORw0KGgo..."（默认按 png 处理）

    Args:
        b64_data: base64 编码的图片数据（可能含 data URI 前缀）
        user_id: 用户 ID
        prefix: 文件名前缀

    Returns:
        str: URL 路径，如 '/api/v1/images/img_1_1234567890_abc123.png'

    Raises:
        ValueError: base64 数据无效
    """
    if not isinstance(b64_data, str) or not b64_data:
        raise ValueError('base64 数据不能为空')

    # 解析 data URI 前缀
    match = _DATA_URI_PATTERN.match(b64_data)
    if match:
        mime_type = match.group(1).lower()
        ext = match.group(2).lower()
        raw_b64 = match.group(3)
    else:
        # 纯 base64，默认 png
        mime_type = 'image/png'
        ext = 'png'
        raw_b64 = b64_data

    # 校验扩展名
    if ext not in _FORMAT_MAP:
        ext = 'png'

    try:
        image_bytes = base64.b64decode(raw_b64)
    except Exception as e:
        raise ValueError(f'base64 解码失败: {e}')

    if not image_bytes:
        raise ValueError('解码后的图片数据为空')

    return save_image_bytes(image_bytes, user_id, ext, prefix)


def get_image_path(filename):
    """
    根据文件名获取磁盘路径（供路由层调用）

    Args:
        filename: 文件名（不含路径）

    Returns:
        str: 磁盘绝对路径
    """
    return os.path.join(STORAGE_DIR, filename)


def get_content_type(filename):
    """根据文件名扩展名获取 MIME 类型"""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return _FORMAT_MAP.get(ext, 'application/octet-stream')


def _ensure_thumb_dir():
    """确保缩略图目录存在"""
    os.makedirs(THUMB_DIR, exist_ok=True)


def get_thumb_filename(original_filename, size='small'):
    """
    根据原始文件名和尺寸生成缩略图文件名

    缩略图统一为 WebP 格式以减小体积。
    """
    name_without_ext = original_filename.rsplit('.', 1)[0] if '.' in original_filename else original_filename
    return f"{name_without_ext}_thumb_{size}.webp"


def get_thumb_path(filename):
    """获取缩略图磁盘路径"""
    return os.path.join(THUMB_DIR, filename)


def get_or_create_thumbnail(original_filename, size='small'):
    """
    获取或生成缩略图

    - 首次访问时从原图生成 WebP 缩略图并缓存到磁盘
    - 后续访问直接返回缓存的缩略图

    Args:
        original_filename: 原始图片文件名
        size: 缩略图尺寸标识 ('small'=200x200, 'medium'=400x400)

    Returns:
        tuple: (thumb_disk_path, thumb_filename, mime_type) 或 (None, None, None) 生成失败
    """
    if size not in THUMB_SIZES:
        size = 'small'

    thumb_filename = get_thumb_filename(original_filename, size)
    thumb_path = get_thumb_path(thumb_filename)

    # 缩略图已存在，直接返回
    if os.path.exists(thumb_path) and os.path.isfile(thumb_path):
        return thumb_path, thumb_filename, 'image/webp'

    # 原始图路径
    original_path = get_image_path(original_filename)
    if not os.path.exists(original_path) or not os.path.isfile(original_path):
        return None, None, None

    # 生成缩略图
    try:
        _ensure_thumb_dir()
        target_size = THUMB_SIZES[size]

        with Image.open(original_path) as img:
            # 转换为 RGB（WebP 不支持 RGBA 模式下的某些操作）
            if img.mode in ('RGBA', 'P', 'LA'):
                # 有透明通道时保留 RGBA
                if img.mode in ('P', 'LA'):
                    img = img.convert('RGBA')
                # 创建白色背景
                background = Image.new('RGBA', img.size, (255, 255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # 等比例缩放并裁剪到目标尺寸
            img.thumbnail(target_size, Image.LANCZOS)

            # 保存为 WebP，质量 80（体积与质量平衡）
            img.save(thumb_path, 'WEBP', quality=80)

        return thumb_path, thumb_filename, 'image/webp'
    except Exception as e:
        # 缩略图生成失败，静默回退
        return None, None, None


def get_thumbnail_url(original_filename, size='small'):
    """
    获取缩略图的 URL 路径

    用于前端历史记录/收藏列表等需要小图的场景。
    如果生成失败，返回原图 URL 作为回退。

    Args:
        original_filename: 原始图片文件名
        size: 缩略图尺寸 ('small' | 'medium')

    Returns:
        str: 缩略图 URL 路径，失败时返回原图 URL
    """
    _, thumb_filename, _ = get_or_create_thumbnail(original_filename, size)
    if thumb_filename:
        return f"{THUMB_URL_PREFIX}/{thumb_filename}"
    # 回退到原图
    return f"{URL_PREFIX}/{original_filename}"
