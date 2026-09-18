"""
收藏夹业务服务模块
收藏的增删查操作
支持图片收藏与历史记录收藏
"""
import math
import os
import re
import json
import pymysql
from models.favorite import FavoriteModel
from models.history_record import HistoryRecordModel
from services.auth_service import AuthError
from services.image_storage_service import save_base64_image, STORAGE_DIR
from config import get_config

favorite_model = FavoriteModel()
history_model = HistoryRecordModel()

_BASE64_PATTERN = re.compile(r'^data:image/.+;base64,.+', re.IGNORECASE)


def _get_user_team_ids(user_id):
    """
    查询用户所属的所有团队ID列表
    返回 list[int]
    """
    config = get_config()
    conn = pymysql.connect(
        host=config.MYSQL_HOST, port=config.MYSQL_PORT,
        user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT team_id FROM team_members WHERE user_id = %s',
                (user_id,)
            )
            rows = cursor.fetchall()
        return [row['team_id'] for row in rows if row.get('team_id') is not None]
    finally:
        conn.close()


def _is_thumbnail_valid(thumbnail_url):
    """
    检查图片 URL 是否有效（非空、非 base64、若为本地文件则存在）

    Returns:
        bool: True 表示有效，前端可直接使用
    """
    if not thumbnail_url or not isinstance(thumbnail_url, str):
        return False
    url = thumbnail_url.strip()
    if not url or _BASE64_PATTERN.match(url):
        return False
    # 本地文件路径：检查文件是否存在
    if url.startswith('/api/v1/images/'):
        filename = url.replace('/api/v1/images/', '')
        if '..' in filename:
            return False
        file_path = os.path.join(STORAGE_DIR, filename)
        return os.path.isfile(file_path)
    # 外部 URL（http/https）视为有效
    if url.startswith('http://') or url.startswith('https://'):
        return True
    return False


def _extract_first_url_from_value(val):
    """从单个值中提取第一个有效的图片 URL，跳过 base64"""
    if isinstance(val, str):
        if not _BASE64_PATTERN.match(val):
            return val
    if isinstance(val, list) and len(val) > 0:
        first = val[0]
        if isinstance(first, str):
            if not _BASE64_PATTERN.match(first):
                return first
        if isinstance(first, dict):
            return first.get('url') or first.get('image_url')
    return None


def _extract_thumbnail_from_output(output_data):
    """从 output_data 中尝试提取第一张图片 URL"""
    if not output_data:
        return None
    if isinstance(output_data, dict):
        for key in ('image_url', 'url', 'image', 'images', 'result',
                     'merged_image', 'result_image'):
            val = output_data.get(key)
            if val:
                result = _extract_first_url_from_value(val)
                if result:
                    return result
        tasks = output_data.get('tasks')
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict):
                    url = task.get('result_url') or task.get('image_url') or task.get('image')
                    if isinstance(url, str) and not _BASE64_PATTERN.match(url):
                        return url
    if isinstance(output_data, list) and len(output_data) > 0:
        first = output_data[0]
        if isinstance(first, str):
            if _BASE64_PATTERN.match(first):
                return None
            return first
        if isinstance(first, dict):
            return first.get('url') or first.get('image_url')
    return None


def _try_repair_history_thumbnail(item):
    """
    尝试从 history_records 的 output_data 中修复 history 类型收藏的缩略图。

    Args:
        item: 收藏项 dict（含 historyRecordId, sourceUserId 等）

    Returns:
        str or None: 修复后的 URL
    """
    record_id = item.get('historyRecordId')
    if not record_id:
        return None

    config = get_config()
    conn = pymysql.connect(
        host=config.MYSQL_HOST, port=config.MYSQL_PORT,
        user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, sub_category, output_data FROM history_records WHERE id = %s",
                (record_id,)
            )
            record = cursor.fetchone()
    finally:
        conn.close()

    if not record:
        return None

    output_data = record.get('output_data')
    if not output_data:
        return None

    if isinstance(output_data, str):
        try:
            output_data = json.loads(output_data)
        except (json.JSONDecodeError, TypeError):
            return None

    new_thumbnail = _extract_thumbnail_from_output(output_data)

    if new_thumbnail and _BASE64_PATTERN.match(new_thumbnail):
        try:
            prefix = f"{record.get('sub_category', '')}_repair"[:20] or 'repair'
            new_thumbnail = save_base64_image(new_thumbnail, record.get('user_id'), prefix=prefix)
        except Exception:
            new_thumbnail = None

    if new_thumbnail:
        # 更新 history_records 的 thumbnail_url
        try:
            conn2 = pymysql.connect(
                host=config.MYSQL_HOST, port=config.MYSQL_PORT,
                user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
                database=config.MYSQL_DATABASE, charset='utf8mb4',
            )
            try:
                with conn2.cursor() as cursor:
                    cursor.execute(
                        "UPDATE history_records SET thumbnail_url = %s WHERE id = %s",
                        (new_thumbnail, record_id)
                    )
                    conn2.commit()
            finally:
                conn2.close()
            print(f"[收藏] 自动修复缩略图: record_id={record_id}, url={new_thumbnail[:80]}", flush=True)
        except Exception as e:
            print(f"[收藏] 缩略图修复失败: record_id={record_id}, error={e}", flush=True)

    return new_thumbnail


def get_favorites(user_id, page=1, page_size=20):
    """
    获取用户收藏列表（分页）
    参数:
        user_id: 用户ID
        page: 页码
        page_size: 每页数量
    返回:
        dict: { items, total, total_pages }
    """
    items, total = favorite_model.find_by_user(user_id, page, page_size)

    # 校验并修复无效的图片 URL
    for item in items:
        target_type = item.get('targetType')

        if target_type == 'history':
            # history 类型：优先使用 thumbnailUrl（来自 JOIN），其次 imageUrl
            thumb = item.get('thumbnailUrl')
            img = item.get('imageUrl')

            if not _is_thumbnail_valid(thumb) and not _is_thumbnail_valid(img):
                # 两个都无效，尝试从 output_data 修复
                repaired = _try_repair_history_thumbnail(item)
                if repaired:
                    item['thumbnailUrl'] = repaired
                    item['imageUrl'] = repaired
            elif not _is_thumbnail_valid(thumb):
                # thumbnailUrl 无效但 imageUrl 有效，保持一致
                item['thumbnailUrl'] = img
            elif not _is_thumbnail_valid(img):
                # imageUrl 无效但 thumbnailUrl 有效
                item['imageUrl'] = thumb
        else:
            # image 类型：仅检查 imageUrl
            img = item.get('imageUrl')
            if not _is_thumbnail_valid(img):
                # 标记为无效，前端会显示占位图
                item['imageUrl'] = ''

    return {
        'items': items,
        'total': total,
        'total_pages': math.ceil(total / page_size) if total > 0 else 0
    }


def add_favorite(user_id, image_url, batch_id=None, config=None):
    """
    添加图片收藏
    参数:
        user_id: 用户ID
        image_url: 图片URL
        batch_id: 批次ID（可选）
        config: 生成配置快照（可选）
    返回:
        int: 新收藏记录ID
    异常:
        AuthError: 参数无效 / 已收藏
    """
    if not image_url or not image_url.strip():
        raise AuthError('图片URL不能为空', 3002, 400)

    favorite_id = favorite_model.create(user_id, image_url.strip(), batch_id, config)
    if favorite_id is None:
        raise AuthError('该图片已收藏', 2006, 409)

    return favorite_id


def add_history_favorite(user_id, record_id):
    """
    收藏一条历史记录
    权限规则：
        1. 记录所有者本人可收藏
        2. 记录已分享到团队，且当前用户是该团队成员，可收藏（source_user_id 记录原始所有者）
    参数:
        user_id: 当前用户ID
        record_id: 历史记录ID
    返回:
        int: 新收藏记录ID
    异常:
        AuthError: 记录ID无效 / 记录不存在或无权操作 / 已收藏
    """
    # 1. 校验 record_id
    if record_id is None or not isinstance(record_id, int) or record_id <= 0:
        raise AuthError('记录ID无效', 3002, 400)

    # 2. 直接查 history_records（不依赖 find_by_id 的所有权校验）
    config = get_config()
    conn = pymysql.connect(
        host=config.MYSQL_HOST, port=config.MYSQL_PORT,
        user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                '''SELECT id, user_id, thumbnail_url, title, shared_to_team, shared_team_id
                   FROM history_records WHERE id = %s''',
                (record_id,)
            )
            record = cursor.fetchone()
    finally:
        conn.close()

    if not record:
        raise AuthError('历史记录不存在或无权操作', 3002, 404)

    # 3. 权限判断
    allowed = False
    if record.get('user_id') == user_id:
        allowed = True
    elif record.get('shared_to_team') == 1 and record.get('shared_team_id') is not None:
        user_team_ids = _get_user_team_ids(user_id)
        if record.get('shared_team_id') in user_team_ids:
            allowed = True

    if not allowed:
        raise AuthError('历史记录不存在或无权操作', 3002, 404)

    # 4. 调用 model 写入收藏
    thumbnail = record.get('thumbnail_url') or ''
    favorite_id = favorite_model.create(
        user_id,
        image_url=thumbnail,
        batch_id=None,
        config=None,
        target_type='history',
        history_record_id=record_id,
        source_user_id=record.get('user_id')
    )

    if favorite_id is None:
        raise AuthError('该记录已收藏', 2006, 409)

    return favorite_id


def remove_favorite(favorite_id, user_id):
    """
    删除收藏
    参数:
        favorite_id: 收藏记录ID
        user_id: 用户ID
    异常:
        AuthError: 收藏不存在或无权操作
    """
    deleted = favorite_model.delete_by_id(favorite_id, user_id)
    if not deleted:
        raise AuthError('收藏记录不存在或无权操作', 3002, 404)
