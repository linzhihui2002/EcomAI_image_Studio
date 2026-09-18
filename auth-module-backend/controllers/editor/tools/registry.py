"""
编辑器工具注册表（单一数据来源）

- 前端工具栏：GET /api/v1/editor/tools（list_tools()，不含函数引用）
- 后续 Agent（P2）：get_tool(name) 取可调用实现
- 路由层入参校验：validate_params(schema, params)

params_schema 规则字段说明：
- type: 'number' | 'boolean' | 'string'
- required: 是否必填（缺省 False）
- min / max: 数字范围（含边界）
- integer: 数字是否必须为整数
- choices: 允许的枚举值列表
- default: 默认值（前端展示用）
- label: 中文参数名（前端展示用）
"""
from controllers.editor.tools.imaging import color_adjust, crop, flip, rotate
from controllers.editor.tools.ai_imaging import (
    remove_background, replace_background, inpaint_erase, inpaint_replace, upscale,
)

EDITOR_TOOLS = [
    {
        'name': 'color_adjust',
        'label': '色彩调整',
        'description': '调整图片的亮度、对比度、饱和度与色温',
        'module': 'basic',
        'params_schema': {
            'brightness': {'type': 'number', 'min': -100, 'max': 100, 'default': 0,
                           'label': '亮度（-100~100，0 为不变）'},
            'contrast': {'type': 'number', 'min': -100, 'max': 100, 'default': 0,
                         'label': '对比度（-100~100，0 为不变）'},
            'saturation': {'type': 'number', 'min': -100, 'max': 100, 'default': 0,
                           'label': '饱和度（-100~100，0 为不变）'},
            'temperature': {'type': 'number', 'min': -100, 'max': 100, 'default': 0,
                            'label': '色温（-100 冷色 ~ 100 暖色，0 为不变）'},
        },
        'func': color_adjust,
    },
    {
        'name': 'crop',
        'label': '裁剪',
        'description': '按像素坐标与宽高裁剪图片',
        'module': 'basic',
        'params_schema': {
            'x': {'type': 'number', 'integer': True, 'required': True, 'min': 0,
                  'label': '起点 X 坐标（像素）'},
            'y': {'type': 'number', 'integer': True, 'required': True, 'min': 0,
                  'label': '起点 Y 坐标（像素）'},
            'width': {'type': 'number', 'integer': True, 'required': True, 'min': 1,
                      'label': '裁剪宽度（像素）'},
            'height': {'type': 'number', 'integer': True, 'required': True, 'min': 1,
                       'label': '裁剪高度（像素）'},
        },
        'func': crop,
    },
    {
        'name': 'flip',
        'label': '翻转',
        'description': '水平或垂直翻转图片（至少指定一个方向）',
        'module': 'basic',
        'params_schema': {
            'horizontal': {'type': 'boolean', 'default': False, 'label': '水平翻转'},
            'vertical': {'type': 'boolean', 'default': False, 'label': '垂直翻转'},
        },
        'func': flip,
    },
    {
        'name': 'rotate',
        'label': '旋转',
        'description': '按 90/180/270 度顺时针旋转图片',
        'module': 'basic',
        'params_schema': {
            'angle': {'type': 'number', 'integer': True, 'required': True,
                      'choices': [90, 180, 270], 'label': '旋转角度（顺时针）'},
        },
        'func': rotate,
    },
    # ========== AI 工具（module='ai'，耗时约 10-30 秒，实现见 ai_imaging.py） ==========
    {
        'name': 'remove_background',
        'label': 'AI 抠图',
        'description': '智能抠出商品主体，去除背景（输出透明 PNG）',
        'module': 'ai',
        'params_schema': {},
        'func': remove_background,
    },
    {
        'name': 'replace_background',
        'label': 'AI 换背景',
        'description': '保持商品主体不变，按描述替换背景',
        'module': 'ai',
        'params_schema': {
            'background_prompt': {'type': 'string', 'required': True,
                                  'label': '新背景描述（如"大理石台面俯拍场景"）'},
        },
        'func': replace_background,
    },
    {
        'name': 'inpaint_erase',
        'label': 'AI 消除',
        'description': '擦除选区内的物体并用周围背景自然填补（需在画布上涂抹选区）',
        'module': 'ai',
        'requires_mask': True,
        'params_schema': {
            'mask_data_uri': {'type': 'string', 'required': True,
                              'label': '选区蒙版（base64 PNG，白=选区）'},
        },
        'func': inpaint_erase,
    },
    {
        'name': 'inpaint_replace',
        'label': 'AI 局部重绘',
        'description': '在选区内按描述重新生成内容，与周围画面自然融合（需在画布上涂抹选区）',
        'module': 'ai',
        'requires_mask': True,
        'params_schema': {
            'mask_data_uri': {'type': 'string', 'required': True,
                              'label': '选区蒙版（base64 PNG，白=选区）'},
            'prompt': {'type': 'string', 'required': True, 'label': '重绘内容描述'},
        },
        'func': inpaint_replace,
    },
    {
        'name': 'upscale',
        'label': 'AI 高清放大',
        'description': '将图片高清放大 2 倍并增强细节',
        'module': 'ai',
        'params_schema': {
            'scale': {'type': 'number', 'integer': True, 'choices': [2], 'default': 2,
                      'label': '放大倍数（目前支持 2x）'},
        },
        'func': upscale,
    },
]

# 名称 → 工具定义 的查找表（模块加载时构建）
_TOOLS_BY_NAME = {tool['name']: tool for tool in EDITOR_TOOLS}


def get_tool(name):
    """按名称取工具定义（含 func 可调用实现），不存在返回 None"""
    return _TOOLS_BY_NAME.get(name)


def list_tools():
    """工具列表（剔除 func 函数引用），供前端工具栏与 Agent（P2）展示"""
    return [{k: v for k, v in tool.items() if k != 'func'} for tool in EDITOR_TOOLS]


def validate_params(schema, params):
    """
    按 params_schema 做入参基本校验（类型 / 必填 / 范围 / 整数 / 枚举）
    校验失败抛 ValueError（中文消息），通过返回 True
    注意：本函数只做 schema 层校验，跨参数语义校验（如 crop 边界、flip 方向）
    在工具函数执行时进行，失败会反映为任务失败信息
    """
    if not isinstance(params, dict):
        raise ValueError('params 必须为对象（dict）')
    for key, rule in schema.items():
        value = params.get(key)
        if value is None:
            if rule.get('required'):
                raise ValueError(f'缺少必填参数: {key}')
            continue
        param_type = rule.get('type', 'number')
        if param_type == 'number':
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f'参数 {key} 必须为数字')
            if rule.get('integer') and not float(value).is_integer():
                raise ValueError(f'参数 {key} 必须为整数')
            lo, hi = rule.get('min'), rule.get('max')
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                if lo is not None and hi is not None:
                    range_text = f'{lo}~{hi}'
                elif lo is not None:
                    range_text = f'不小于 {lo}'
                else:
                    range_text = f'不大于 {hi}'
                raise ValueError(f'参数 {key} 超出允许范围（{range_text}）')
        elif param_type == 'boolean':
            if not isinstance(value, bool):
                raise ValueError(f'参数 {key} 必须为布尔值')
        elif param_type == 'string':
            if not isinstance(value, str):
                raise ValueError(f'参数 {key} 必须为字符串')
        choices = rule.get('choices')
        if choices is not None and value not in choices:
            raise ValueError(f'参数 {key} 仅支持: {"/".join(str(c) for c in choices)}')
    return True
