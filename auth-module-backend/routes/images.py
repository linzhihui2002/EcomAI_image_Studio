"""
图片服务路由模块
提供历史记录图片文件的访问接口，含缩略图生成
"""
import os
from flask import Blueprint, jsonify, send_file, abort, request

from services.image_storage_service import (
    get_image_path,
    get_content_type,
    STORAGE_DIR,
    get_or_create_thumbnail,
    THUMB_DIR,
)

images_bp = Blueprint('images', __name__, url_prefix='/api/v1')


@images_bp.route('/images/<path:filename>', methods=['GET'])
def serve_image(filename):
    """
    提供图片文件访问（无需认证）

    安全说明：
    - 文件名包含 UUID + 时间戳，不可猜测
    - 路径遍历检查防止目录穿越攻击
    - 仅允许访问 STORAGE_DIR 下的文件
    """
    # 安全检查：防止路径遍历
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        return jsonify({'code': 4004, 'message': '无效的文件名'}), 404

    # 规范化路径并校验是否在存储目录内
    file_path = get_image_path(filename)
    real_path = os.path.realpath(file_path)
    real_storage = os.path.realpath(STORAGE_DIR)
    if not real_path.startswith(real_storage + os.sep):
        return jsonify({'code': 4004, 'message': '无效的文件路径'}), 404

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return jsonify({'code': 4004, 'message': '图片不存在'}), 404

    content_type = get_content_type(filename)

    response = send_file(file_path, mimetype=content_type)
    # 图片内容不可变，可长期缓存
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@images_bp.route('/images/thumb/<path:filename>', methods=['GET'])
def serve_thumbnail(filename):
    """
    提供缩略图访问（无需认证）

    支持的查询参数：
    - size: 缩略图尺寸，'small'(200x200) 或 'medium'(400x400)，默认 'small'
    - original: 原始图片文件名（用于按需生成缩略图）

    两种使用方式：
    1. 直接访问已生成的缩略图：/api/v1/images/thumb/img_1_xxx_thumb_small.webp
    2. 按需生成：/api/v1/images/thumb/img_1_xxx_thumb_small.webp?original=img_1_xxx.png&size=small
    """
    # 安全检查：防止路径遍历
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        return jsonify({'code': 4004, 'message': '无效的文件名'}), 404

    thumb_path = os.path.join(THUMB_DIR, filename)
    real_path = os.path.realpath(thumb_path)
    real_thumb_dir = os.path.realpath(THUMB_DIR)
    if not real_path.startswith(real_thumb_dir + os.sep):
        return jsonify({'code': 4004, 'message': '无效的文件路径'}), 404

    # 缩略图已存在，直接返回
    if os.path.exists(thumb_path) and os.path.isfile(thumb_path):
        response = send_file(thumb_path, mimetype='image/webp')
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response

    # 按需生成：通过 original 参数指定原始图片
    original_filename = request.args.get('original', '')
    size = request.args.get('size', 'small')

    if original_filename:
        # 安全检查 original 参数
        if '..' in original_filename or original_filename.startswith('/') or original_filename.startswith('\\'):
            return jsonify({'code': 4004, 'message': '无效的文件名'}), 404

        gen_path, gen_filename, mime_type = get_or_create_thumbnail(original_filename, size)
        if gen_path and os.path.exists(gen_path):
            response = send_file(gen_path, mimetype=mime_type)
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            return response

    return jsonify({'code': 4004, 'message': '缩略图不存在'}), 404
