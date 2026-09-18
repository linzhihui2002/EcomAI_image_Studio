"""
编辑器基础图像处理工具（PIL 纯函数库）

约定：
- 所有工具函数签名统一为 func(image: PIL.Image.Image, params: dict) -> PIL.Image.Image
- bytes 级编解码与磁盘读写由 tasks.py 负责，本模块只做像素级处理
- 参数错误一律抛出 ValueError（中文消息），由路由层转为 400、由任务层转为任务失败
"""
from PIL import Image, ImageEnhance


def _require_params(params):
    """校验 params 为 dict"""
    if not isinstance(params, dict):
        raise ValueError('参数必须为对象（dict）')


def _format_range(min_value, max_value):
    """格式化范围提示文案"""
    if min_value is not None and max_value is not None:
        return f'{min_value}~{max_value}'
    if min_value is not None:
        return f'不小于 {min_value}'
    return f'不大于 {max_value}'


def _get_number(params, key, default=None, required=False, min_value=None, max_value=None):
    """
    从 params 中取数字参数并校验范围
    - 缺失且 required=True → ValueError；缺失且可选 → 返回 default
    - 布尔值不算数字（True/False 会被误当 1/0）
    """
    value = params.get(key)
    if value is None:
        if required:
            raise ValueError(f'缺少必填参数: {key}')
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'参数 {key} 必须为数字')
    if (min_value is not None and value < min_value) or (max_value is not None and value > max_value):
        raise ValueError(f'参数 {key} 超出允许范围（{_format_range(min_value, max_value)}）')
    return value


def _to_editable(image):
    """转为可编辑模式：有透明通道 → RGBA，否则 RGB"""
    if image.mode in ('RGBA', 'LA', 'PA') or (image.mode == 'P' and 'transparency' in image.info):
        return image.convert('RGBA')
    return image.convert('RGB')


def color_adjust(image, params):
    """
    色彩调整

    参数（均为可选数字，-100~100，0 表示不变）：
    - brightness: 亮度（1 + brightness/100 作为增强系数）
    - contrast: 对比度
    - saturation: 饱和度
    - temperature: 色温（负=偏冷，正=偏暖；用 R/B 通道反向偏移实现，±100 → ±50 色阶）
    """
    _require_params(params)
    brightness = _get_number(params, 'brightness', default=0, min_value=-100, max_value=100)
    contrast = _get_number(params, 'contrast', default=0, min_value=-100, max_value=100)
    saturation = _get_number(params, 'saturation', default=0, min_value=-100, max_value=100)
    temperature = _get_number(params, 'temperature', default=0, min_value=-100, max_value=100)

    img = _to_editable(image)

    # 分离透明通道：增强操作仅作用于 RGB，避免 ImageEnhance 在 RGBA 下扰动透明度
    if img.mode == 'RGBA':
        bands = img.split()
        rgb = Image.merge('RGB', bands[:3])
        alpha = bands[3]
    else:
        rgb = img
        alpha = None

    if temperature != 0:
        # 色温：R/B 通道反向偏移（查找表方式，越界自动截断到 0-255）
        offset = int(round(temperature * 0.5))
        warm_lut = [min(255, max(0, v + offset)) for v in range(256)]
        cool_lut = [min(255, max(0, v - offset)) for v in range(256)]
        r, g, b = rgb.split()
        rgb = Image.merge('RGB', (r.point(warm_lut), g, b.point(cool_lut)))

    if brightness != 0:
        rgb = ImageEnhance.Brightness(rgb).enhance(1 + brightness / 100.0)
    if contrast != 0:
        rgb = ImageEnhance.Contrast(rgb).enhance(1 + contrast / 100.0)
    if saturation != 0:
        rgb = ImageEnhance.Color(rgb).enhance(1 + saturation / 100.0)

    if alpha is not None:
        rgb = rgb.convert('RGBA')
        rgb.putalpha(alpha)
    return rgb


def crop(image, params):
    """
    裁剪

    参数（均为必填整数像素）：
    - x / y: 裁剪起点坐标（左上角，非负）
    - width / height: 裁剪宽高（正整数）
    裁剪区域超出图片边界时抛出 ValueError
    """
    _require_params(params)
    x = _get_number(params, 'x', required=True, min_value=0)
    y = _get_number(params, 'y', required=True, min_value=0)
    width = _get_number(params, 'width', required=True, min_value=1)
    height = _get_number(params, 'height', required=True, min_value=1)
    for name, value in (('x', x), ('y', y), ('width', width), ('height', height)):
        if not float(value).is_integer():
            raise ValueError(f'参数 {name} 必须为整数像素')
    x, y, width, height = int(x), int(y), int(width), int(height)

    img_w, img_h = image.size
    if x + width > img_w or y + height > img_h:
        raise ValueError(f'裁剪区域超出图片边界（图片尺寸 {img_w}x{img_h}）')
    return image.crop((x, y, x + width, y + height))


def flip(image, params):
    """
    翻转

    参数（均为可选布尔值，至少一个为 True）：
    - horizontal: 水平翻转（左右镜像）
    - vertical: 垂直翻转（上下镜像）
    """
    _require_params(params)
    horizontal = params.get('horizontal', False)
    vertical = params.get('vertical', False)
    if not isinstance(horizontal, bool) or not isinstance(vertical, bool):
        raise ValueError('参数 horizontal/vertical 必须为布尔值')
    if not horizontal and not vertical:
        raise ValueError('请至少指定一个翻转方向（horizontal 或 vertical）')
    if horizontal:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if vertical:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return image


# 顺时针旋转角度 → PIL Transpose 操作（PIL 的 ROTATE_N 为逆时针，需换算）
_ROTATE_MAP = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def rotate(image, params):
    """
    旋转

    参数：
    - angle: 旋转角度（必填，仅支持 90/180/270，顺时针方向）
    """
    _require_params(params)
    angle = params.get('angle')
    if angle is None:
        raise ValueError('缺少必填参数: angle')
    if angle not in _ROTATE_MAP:
        raise ValueError('参数 angle 仅支持 90/180/270（顺时针旋转）')
    return image.transpose(_ROTATE_MAP[angle])
