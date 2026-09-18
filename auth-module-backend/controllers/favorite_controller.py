"""
收藏夹控制器
处理 HTTP 请求参数校验、调用业务服务、格式化响应
"""
from flask import request, jsonify, g
from services.favorite_service import get_favorites, add_favorite, remove_favorite, add_history_favorite
from services.auth_service import AuthError


def success_response(data=None, message='success', code=0):
    """统一成功响应"""
    return jsonify({'code': code, 'message': message, 'data': data})


def error_response(code, message, http_status=400, data=None):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': data}), http_status


def list_favorites():
    """
    获取收藏列表
    GET /api/v1/favorites
    查询参数: page, pageSize
    """
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('pageSize', 20))
    except ValueError:
        return error_response(3002, '分页参数格式无效', 400)

    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    try:
        result = get_favorites(g.current_user['user_id'], page, page_size)
        return jsonify({
            'code': 0,
            'message': 'success',
            'data': result['items'],
            'pagination': {
                'page': page,
                'pageSize': page_size,
                'total': result['total'],
                'totalPages': result['total_pages']
            }
        })
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def create_favorite():
    """
    添加收藏
    POST /api/v1/favorites
    请求体: { "imageUrl": "...", "batchId": "...", "config": {...} }
    """
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    image_url = data.get('imageUrl', '').strip()
    if not image_url:
        return error_response(3002, '图片URL不能为空', 400)

    batch_id = data.get('batchId')
    config = data.get('config')

    try:
        favorite_id = add_favorite(g.current_user['user_id'], image_url, batch_id, config)
        return success_response({'id': favorite_id}, '收藏成功'), 201
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def delete_favorite(favorite_id):
    """
    删除收藏
    DELETE /api/v1/favorites/<favorite_id>
    """
    try:
        remove_favorite(favorite_id, g.current_user['user_id'])
        return success_response(message='已取消收藏')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def create_history_favorite():
    """
    收藏历史记录
    POST /api/v1/favorites/history
    请求体: { "recordId": 123 }
    """
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    record_id = data.get('recordId')
    if not isinstance(record_id, int) or record_id <= 0:
        return error_response(3002, 'recordId 无效', 400)

    try:
        favorite_id = add_history_favorite(g.current_user['user_id'], record_id)
        return success_response({'id': favorite_id}, '收藏成功'), 201
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)