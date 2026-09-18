"""
编辑器图层文档格式定义与结构校验

图层文档格式（服务端只存 JSON 不深度解释，仅校验结构）:
[
    {
        "id": "layer-1",               # 必填，图层唯一标识（非空字符串）
        "type": "image" | "text",      # 必填，图层类型
        "url": "/api/v1/images/...",   # image 类型必填，图层图片地址
        "text": "文字内容",             # text 类型必填，文字内容（字符串）
        "x": 0, "y": 0,                # 必填，左上角坐标（数字）
        "width": 100, "height": 100,   # 必填，宽高（数字）
        "rotation": 0,                 # 可选，旋转角度（数字，默认 0）
        "opacity": 1,                  # 可选，不透明度 0~1（数字，默认 1）
        "visible": true,               # 可选，是否可见（布尔，默认 true）
        "locked": false,               # 可选，是否锁定（布尔，默认 false）
        "z": 0                         # 可选，层级（数字，越大越靠上）
    },
    ...
]
"""

# 支持的图层类型
LAYER_TYPES = ('image', 'text')

# 数值型字段（存在时必须是数字）
_NUMERIC_KEYS = ('x', 'y', 'width', 'height', 'rotation', 'z')

# 必填数值字段
_REQUIRED_NUMERIC_KEYS = ('x', 'y', 'width', 'height')

# 布尔型字段（存在时必须是布尔值）
_BOOLEAN_KEYS = ('visible', 'locked')


def _is_number(value):
    """判断是否为数字（布尔值不算）"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_layers(layers):
    """
    校验图层数组结构，非法抛 ValueError（中文消息），合法静默返回
    """
    if not isinstance(layers, list):
        raise ValueError('layers 必须为数组')
    for index, layer in enumerate(layers):
        label = f'第 {index + 1} 个图层'
        if not isinstance(layer, dict):
            raise ValueError(f'{label} 必须为对象（dict）')

        layer_id = layer.get('id')
        if not isinstance(layer_id, str) or not layer_id.strip():
            raise ValueError(f'{label} 缺少有效的 id（非空字符串）')

        layer_type = layer.get('type')
        if layer_type not in LAYER_TYPES:
            raise ValueError(f'{label}（{layer_id}）type 仅支持: {" / ".join(LAYER_TYPES)}')

        for key in _NUMERIC_KEYS:
            if key in layer and not _is_number(layer[key]):
                raise ValueError(f'{label}（{layer_id}）参数 {key} 必须为数字')
        for key in _REQUIRED_NUMERIC_KEYS:
            if key not in layer or not _is_number(layer[key]):
                raise ValueError(f'{label}（{layer_id}）缺少必填参数: {key}')
        for key in _BOOLEAN_KEYS:
            if key in layer and not isinstance(layer[key], bool):
                raise ValueError(f'{label}（{layer_id}）参数 {key} 必须为布尔值')
        if 'opacity' in layer:
            opacity = layer['opacity']
            if not _is_number(opacity) or not (0 <= opacity <= 1):
                raise ValueError(f'{label}（{layer_id}）opacity 必须为 0~1 的数字')

        if layer_type == 'image' and not (isinstance(layer.get('url'), str) and layer['url'].strip()):
            raise ValueError(f'{label}（{layer_id}）image 图层必须提供 url')
        if layer_type == 'text' and not isinstance(layer.get('text'), str):
            raise ValueError(f'{label}（{layer_id}）text 图层必须提供 text 字符串')
