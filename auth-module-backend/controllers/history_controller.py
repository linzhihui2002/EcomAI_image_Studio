"""
历史记录控制器
处理 HTTP 请求参数校验、调用业务服务、格式化响应
"""
from flask import request, jsonify, g
from services.history_service import save_history, get_history_list, get_history_detail, delete_history, share_history_to_team, unshare_history, get_team_history
from services.auth_service import AuthError


def success_response(data=None, message='success', code=0):
    """统一成功响应"""
    return jsonify({'code': code, 'message': message, 'data': data})


def error_response(code, message, http_status=400, data=None):
    """统一错误响应"""
    return jsonify({'code': code, 'message': message, 'data': data}), http_status


def create_history():
    """
    创建历史记录
    POST /api/v1/history
    请求体: { "category": "...", "sub_category": "...", "title": "...", "thumbnail_url": "...", "input_data": {...}, "output_data": {...}, "config_snapshot": {...} }
    """
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    user_id = g.current_user['user_id']
    category = data.get('category', '').strip()
    sub_category = data.get('sub_category', '').strip()
    title = data.get('title', '').strip()
    thumbnail_url = data.get('thumbnail_url', '').strip()
    input_data = data.get('input_data')
    output_data = data.get('output_data')
    config_snapshot = data.get('config_snapshot')

    if not category:
        return error_response(3002, 'category 不能为空', 400)
    if not sub_category:
        return error_response(3002, 'sub_category 不能为空', 400)

    try:
        record_id = save_history(user_id, category, sub_category, title, thumbnail_url, input_data, output_data, config_snapshot)
        return success_response({'id': record_id}, '创建成功'), 201
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def list_history():
    """
    获取历史记录列表
    GET /api/v1/history
    查询参数: category, sub_category, page, pageSize
    """
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
    except ValueError:
        return error_response(3002, '分页参数格式无效', 400)

    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    category = request.args.get('category', '').strip() or None
    sub_category = request.args.get('sub_category', '').strip() or None

    try:
        result = get_history_list(g.current_user['user_id'], category, sub_category, page, page_size)
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


def get_history_detail_ep(record_id):
    """
    获取历史记录详情
    GET /api/v1/history/<record_id>
    """
    try:
        record = get_history_detail(g.current_user['user_id'], record_id)
        return success_response(record)
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def delete_history_ep(record_id):
    """
    删除历史记录
    DELETE /api/v1/history/<record_id>
    """
    try:
        delete_history(g.current_user['user_id'], record_id)
        return success_response(message='已删除历史记录')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def share_history(record_id):
    """
    分享历史记录到团队
    POST /api/v1/history/<record_id>/share
    请求体: { "team_id": "..." }
    """
    data = request.get_json(silent=True)
    if not data:
        return error_response(3002, '请求体不能为空', 400)

    team_id = str(data.get('team_id', '')).strip()
    if not team_id:
        return error_response(3002, 'team_id 不能为空', 400)

    try:
        share_history_to_team(g.current_user['user_id'], record_id, team_id)
        return success_response(message='已分享到团队')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def unshare_history_ep(record_id):
    """
    取消分享历史记录
    DELETE /api/v1/history/<record_id>/share
    """
    try:
        unshare_history(g.current_user['user_id'], record_id)
        return success_response(message='已取消分享')
    except AuthError as e:
        return error_response(e.code, e.message, e.http_status)


def list_team_history(team_id):
    """
    获取团队历史记录列表
    GET /api/v1/history/team/<team_id>
    查询参数: page, pageSize
    """
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
    except ValueError:
        return error_response(3002, '分页参数格式无效', 400)

    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    try:
        result = get_team_history(g.current_user['user_id'], team_id, page, page_size)
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