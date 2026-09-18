"""
平台合规路由模块（P0-2 / P1-4）
- GET  /api/v1/compliance/rules：平台图型规则 + globalForbidden
- POST /api/v1/compliance/review：AI 视觉合规审查（单图手动审查，JWT）
"""
from flask import Blueprint, request, jsonify

from middleware.auth_middleware import token_required
from services.compliance_service import get_platform_rules, normalize_platform
from services.compliance_review_service import review_image

compliance_bp = Blueprint('compliance', __name__, url_prefix='/api/v1/compliance')

# base64 图片大小上限（8MB，按 base64 字符串长度校验）
MAX_REVIEW_IMAGE_B64 = 8 * 1024 * 1024


def _success(data=None, message='success', http_status=200):
    """统一成功响应"""
    return jsonify({'code': 0, 'message': message, 'data': data}), http_status


def _error(message, code=4001, http_status=400):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': None}), http_status


def _serialize_forbidden(items):
    """禁元素序列化：保留原始字段（name/keywords），补充前端契约字段 term"""
    serialized = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        data = dict(item)
        data.setdefault('term', str(item.get('name') or ''))
        serialized.append(data)
    return serialized


@compliance_bp.route('/rules', methods=['GET'])
@token_required
def get_rules():
    """
    查询平台合规规则

    Query Params:
        platform: 平台标识（amazon/temu/shopee/tiktok_shop/aliexpress/ozon）

    Response:
    {
        "code": 0,
        "data": {
            "platform": "amazon",
            "imageTypes": {"main_image": {...}, "scene": {...}, "detail": {...}},
            # 兼容字段：与 imageTypes 同值
            "image_rules": {"main_image": {...}, "scene": {...}, "detail": {...}},
            "globalForbidden": [{"term": "...", "name": "...",
                                 "severity": "block", "keywords": [...]}]
        }
    }
    """
    try:
        platform = request.args.get('platform', '')
        if not platform.strip():
            return _error('platform 参数不能为空')

        rules = get_platform_rules(platform)
        if not rules["image_rules"] and not rules["global_forbidden"]:
            return _error(
                f'平台 {normalize_platform(platform)} 暂无合规规则',
                code=4004, http_status=404,
            )

        return _success({
            'platform': rules["platform"],
            'imageTypes': rules["image_rules"],
            # 兼容字段：保留既有下划线命名
            'image_rules': rules["image_rules"],
            'globalForbidden': _serialize_forbidden(rules["global_forbidden"]),
        })

    except Exception as e:
        return _error(f'查询合规规则失败: {str(e)}', code=5001, http_status=500)


@compliance_bp.route('/review', methods=['POST'])
@token_required
def review_image_api():
    """AI 视觉合规审查（单图手动审查）

    Request Body:
    {
        "image": "base64 图片（可含 data: 前缀）或 http(s) 图片 url",
        "platform": "amazon",
        "image_type": "main"   // main/scene/detail，缺省 main
    }

    Response data:
    {
        "riskLevel": "high|medium|low|unknown",
        "issues": [{"rule": "...", "detail": "..."}],
        "fixSuggestions": ["..."]
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return _error('请求参数不能为空')

        image = str(data.get('image') or '').strip()
        platform = data.get('platform', '')
        image_type = data.get('image_type') or 'main'
        if not image:
            return _error('image 不能为空')
        # 大小限制校验：base64 输入 ≤8MB（http url 不适用）
        if not (image.startswith('http://') or image.startswith('https://')):
            if len(image) > MAX_REVIEW_IMAGE_B64:
                return _error('image 超出大小限制（base64 ≤ 8MB）')

        result = review_image(image, platform, image_type)
        return _success(result)

    except Exception as e:
        return _error(f'合规审查失败: {str(e)}', code=5001, http_status=500)
