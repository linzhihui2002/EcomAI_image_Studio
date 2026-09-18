"""
模板预览路由模块（P0-1 多语言/多站点提示词引擎）
- POST /api/v1/template/preview：提示词预览（不调模型、不计费）
- GET  /api/v1/template/options：站点/场景/图型选项数据源
"""
from flask import Blueprint, request, jsonify

from middleware.auth_middleware import token_required
from services import multilang_engine

template_bp = Blueprint('template', __name__, url_prefix='/api/v1/template')


def _success(data=None, message='success', http_status=200):
    """统一成功响应"""
    return jsonify({'code': 0, 'message': message, 'data': data}), http_status


def _error(message, code=4001, http_status=400):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': None}), http_status


@template_bp.route('/preview', methods=['POST'])
@token_required
def preview_prompt():
    """
    提示词预览：按站点/场景/图型组装英文提示词，全程不调模型不计费

    Request Body:
    {
        "product_info": {"product_name": "...", "title_en": "...", "include_model": false},
        "selling_points": [
            {"zh_title": "...", "zh_desc": "...",
             "en_title": "...", "en_desc": "...", "visual_keywords": "..."}
        ],
        "scene": "居家客厅",
        "site": "US",
        "image_types": ["main", "scene", "detail"]   // 可选，默认全部
    }

    Response:
    {
        "code": 0,
        "data": {
            "prompts": {"main": "...", "scene": "...", "detail": "..."},
            "warnings": [...],
            "site": {"site": "US", "language": "English", ...}
        }
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return _error('请求参数不能为空')

        product_info = data.get('product_info')
        if not isinstance(product_info, dict):
            return _error('product_info 必须为对象')

        selling_points = data.get('selling_points', [])
        if selling_points is None:
            selling_points = []
        if not isinstance(selling_points, list):
            return _error('selling_points 必须为列表')
        # 逐条前置校验（严格模式：非法项直接拒绝，给出字段级错误信息）
        for idx, sp in enumerate(selling_points):
            try:
                multilang_engine.validate_selling_point(sp)
            except ValueError as e:
                return _error(f'第 {idx + 1} 条卖点校验失败: {e}')

        scene = data.get('scene', '')
        site = data.get('site', '')

        image_types = data.get('image_types')
        if not image_types:
            image_types = list(multilang_engine.IMAGE_TYPES)
        if (not isinstance(image_types, list)
                or not all(isinstance(t, str) for t in image_types)):
            return _error('image_types 必须为字符串列表')
        try:
            normalized_types = [
                multilang_engine.normalize_image_type(t) for t in image_types
            ]
        except ValueError as e:
            return _error(str(e))

        result = multilang_engine.build_preview(
            product_info=product_info,
            selling_points=selling_points,
            scene_zh=scene,
            site=site,
            image_types=tuple(normalized_types),
        )
        return _success(result)

    except Exception as e:
        return _error(f'提示词预览失败: {str(e)}', code=5001, http_status=500)


@template_bp.route('/options', methods=['GET'])
@token_required
def template_options():
    """
    模板选项数据源：站点列表（含语言/RTL）+ 场景列表 + 图型枚举

    Response:
    {
        "code": 0,
        "data": {
            "sites": [
                {"code": "us", "name": "美国站 (US)", "language": "English",
                 "isRtl": false,
                 # 兼容字段（既有消费方/测试使用）
                 "site": "US", "language_code": "en", "rtl": false, "non_latin": false}
            ],
            "scenes": [...],
            "image_types": ["main", "scene", "detail"]
        }
    }
    """
    try:
        sites = []
        for code in sorted(multilang_engine.SUPPORTED_SITES):
            info = multilang_engine.resolve_site(code)
            sites.append({
                # 前端契约字段（站点选择器/批量提交使用）
                'code': info['site'].lower(),
                'name': info['name'],
                'language': info['language'],
                'isRtl': info['rtl'],
                # 兼容字段：保留站点码原始大小写与语言代码
                'site': info['site'],
                'language_code': info['language_code'],
                'rtl': info['rtl'],
                'non_latin': info['non_latin'],
            })
        return _success({
            'sites': sites,
            'scenes': multilang_engine.list_scenes(),
            'image_types': list(multilang_engine.IMAGE_TYPES),
        })

    except Exception as e:
        return _error(f'获取模板选项失败: {str(e)}', code=5001, http_status=500)
