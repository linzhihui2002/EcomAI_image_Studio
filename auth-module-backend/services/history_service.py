"""
历史记录业务服务模块
保存 / 查询 / 删除 / 团队分享
"""
import math
import os
import re
import json
from datetime import datetime
import pymysql
from models.history_record import HistoryRecordModel
from services.auth_service import AuthError
from services.image_storage_service import save_base64_image, STORAGE_DIR
from config import get_config

history_model = HistoryRecordModel()

_BASE64_PATTERN = re.compile(r'^data:image/.+;base64,.+', re.IGNORECASE)


def _strip_base64_images(obj):
    """递归遍历对象，将 base64 图片替换为占位符以减小存储体积"""
    if isinstance(obj, dict):
        return {k: _strip_base64_images(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_base64_images(v) for v in obj]
    if isinstance(obj, str) and _BASE64_PATTERN.match(obj):
        return f'[BASE64_IMAGE:{len(obj)} chars]'
    return obj

SUB_CATEGORY_CN = {
    'smart_mode': '简单模式',
    'pro_mode': '专业模式',
    'plan_analysis': '生图计划分析',
    'image_merge': '图片合并',
    'text_to_image': '文生图',
    'chat_gen': '对话式生图',
    'product_replace': '产品替换',
    'ai_model': 'AI模特',
    'model_product': '模特商品图',
    'prompt_reverse': '反推提示词',
    'editor': '图片编辑器',
}


def _is_team_member(user_id, team_id):
    """检查用户是否属于指定团队"""
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
                'SELECT id FROM team_members WHERE team_id = %s AND user_id = %s',
                (team_id, user_id)
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def _get_user_team_ids(user_id):
    """查询用户所属的所有团队ID列表"""
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
            return [row['team_id'] for row in rows]
    finally:
        conn.close()


def _extract_first_url_from_value(val):
    """从单个值中提取第一个有效的图片 URL，跳过 base64 数据"""
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


def _persist_images_in_data(data, user_id, sub_category):
    """
    递归遍历数据结构，将 base64 图片保存为磁盘文件并用 URL 替换

    在保存历史记录前调用此函数，确保 output_data 和 input_data 中的图片
    以文件 URL 形式持久化，避免被 _strip_base64_images 销毁。

    Args:
        data: 待处理的数据（dict / list / 标量）
        user_id: 用户 ID
        sub_category: 子分类（用于文件名前缀）

    Returns:
        处理后的数据（base64 已替换为 URL）
    """
    if isinstance(data, dict):
        return {k: _persist_images_in_data(v, user_id, sub_category) for k, v in data.items()}
    if isinstance(data, list):
        return [_persist_images_in_data(v, user_id, sub_category) for v in data]
    if isinstance(data, str) and _BASE64_PATTERN.match(data):
        try:
            prefix = f"{sub_category}_img"[:20] if sub_category else 'img'
            return save_base64_image(data, user_id, prefix=prefix)
        except Exception as e:
            print(f"[历史记录] 图片持久化失败，将回退为占位符: {e}", flush=True)
            return f'[BASE64_IMAGE:{len(data)} chars]'
    return data


def _extract_thumbnail(output_data):
    """从 output_data 中尝试提取第一张图片 URL"""
    if not output_data:
        return None
    if isinstance(output_data, dict):
        # 1. 检查直接的图片键
        for key in ('image_url', 'url', 'image', 'images', 'result',
                     'merged_image', 'result_image'):
            val = output_data.get(key)
            if val:
                result = _extract_first_url_from_value(val)
                if result:
                    return result

        # 2. 检查 tasks 数组（smart_mode / pro_mode 输出格式）
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


def save_history(user_id, category, sub_category, title=None, thumbnail_url=None,
                 input_data=None, output_data=None, config_snapshot=None):
    """
    保存历史记录
    参数:
        user_id: 用户ID
        category: 分类
        sub_category: 子分类
        title: 标题（可选，自动生成）
        thumbnail_url: 缩略图URL（可选，自动从 output_data 提取）
        input_data: 输入数据
        output_data: 输出数据
        config_snapshot: 配置快照（可选）
    返回:
        int: 新历史记录ID
    异常:
        AuthError: 参数无效
    """
    if title is None:
        sub_label = SUB_CATEGORY_CN.get(sub_category, sub_category)
        title = f"{sub_label} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    # 持久化 base64 图片为磁盘文件，用 URL 替换 base64 字符串
    # 必须在 _extract_thumbnail 之前执行，以便缩略图提取能找到 URL
    if input_data is not None:
        input_data = _persist_images_in_data(input_data, user_id, sub_category)
    if output_data is not None:
        output_data = _persist_images_in_data(output_data, user_id, sub_category)

    if thumbnail_url is None:
        thumbnail_url = _extract_thumbnail(output_data)

    # 安全网：剥离残留的 base64（理论上 _persist_images_in_data 已处理完毕）
    input_data = _strip_base64_images(input_data)
    output_data = _strip_base64_images(output_data)

    # 校验必填字段
    if not user_id:
        raise AuthError('用户ID不能为空', 3002, 400)
    if not category:
        raise AuthError('分类不能为空', 3002, 400)
    if not sub_category:
        raise AuthError('子分类不能为空', 3002, 400)
    if input_data is None:
        raise AuthError('输入数据不能为空', 3002, 400)
    if output_data is None:
        raise AuthError('输出数据不能为空', 3002, 400)

    print(f"[历史记录] 保存: user_id={user_id}, category={category}, sub_category={sub_category}", flush=True)

    return history_model.create(
        user_id, category, sub_category, title, thumbnail_url,
        input_data, output_data, config_snapshot
    )


def _is_thumbnail_valid(thumbnail_url):
    """
    检查 thumbnail_url 是否有效（非空、非 base64、若为本地文件则存在）

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
        # 安全检查：防止路径遍历
        if '..' in filename:
            return False
        file_path = os.path.join(STORAGE_DIR, filename)
        return os.path.isfile(file_path)
    # 外部 URL（http/https）视为有效
    if url.startswith('http://') or url.startswith('https://'):
        return True
    return False


def _repair_thumbnail_for_item(item):
    """
    尝试修复单条历史记录的 thumbnail_url。

    从 output_data 中提取有效图片 URL，必要时持久化 base64 图片。
    如果修复成功，更新数据库。

    Args:
        item: 历史记录 dict（含 id, user_id, sub_category, thumbnail_url, output_data）

    Returns:
        str or None: 修复后的 thumbnail_url，无法修复返回 None
    """
    record_id = item.get('id')
    user_id = item.get('user_id')
    sub_category = item.get('sub_category', '')
    output_data = item.get('output_data')

    if not output_data:
        return None

    # 解析 JSON（如果是字符串）
    if isinstance(output_data, str):
        try:
            output_data = json.loads(output_data)
        except (json.JSONDecodeError, TypeError):
            return None

    # 尝试提取缩略图
    new_thumbnail = _extract_thumbnail(output_data)

    # 如果提取到的是 base64，持久化为文件
    if new_thumbnail and _BASE64_PATTERN.match(new_thumbnail):
        try:
            prefix = f"{sub_category}_repair"[:20] if sub_category else 'repair'
            new_thumbnail = save_base64_image(new_thumbnail, user_id, prefix=prefix)
        except Exception:
            new_thumbnail = None

    if not new_thumbnail:
        return None

    # 更新数据库
    try:
        config = get_config()
        conn = pymysql.connect(
            host=config.MYSQL_HOST, port=config.MYSQL_PORT,
            user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE, charset='utf8mb4',
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE history_records SET thumbnail_url = %s WHERE id = %s",
                    (new_thumbnail, record_id)
                )
                conn.commit()
        finally:
            conn.close()
        print(f"[历史记录] 自动修复缩略图: id={record_id}, url={new_thumbnail[:80]}", flush=True)
    except Exception as e:
        print(f"[历史记录] 缩略图修复失败: id={record_id}, error={e}", flush=True)

    return new_thumbnail


def get_history_list(user_id, category=None, sub_category=None, page=1, page_size=20):
    """
    获取用户历史记录列表（分页）
    参数:
        user_id: 用户ID
        category: 分类过滤（可选）
        sub_category: 子分类过滤（可选）
        page: 页码
        page_size: 每页数量
    返回:
        dict: { items, total, total_pages }
    """
    print(f"[历史记录] 查询: user_id={user_id}, category={category}, sub_category={sub_category}, page={page}", flush=True)
    items, total = history_model.find_by_user(
        user_id, category=category, sub_category=sub_category,
        page=page, page_size=page_size
    )

    # 检查并修复无效的 thumbnail_url（在移除 output_data 之前）
    for item in items:
        thumbnail_url = item.get('thumbnail_url')
        if not _is_thumbnail_valid(thumbnail_url):
            repaired = _repair_thumbnail_for_item(item)
            if repaired:
                item['thumbnail_url'] = repaired

        # 移除 input_data 和 output_data 以减小响应体积
        item.pop('input_data', None)
        item.pop('output_data', None)

    return {
        'items': items,
        'total': total,
        'total_pages': math.ceil(total / page_size) if total > 0 else 0
    }


def get_history_detail(user_id, record_id):
    """
    获取历史记录详情
    参数:
        user_id: 用户ID
        record_id: 记录ID
    返回:
        dict: 完整记录
    异常:
        AuthError: 历史记录不存在或无权查看
    """
    user_team_ids = _get_user_team_ids(user_id)
    record = history_model.find_by_id_accessible(record_id, user_id, user_team_ids)
    if not record:
        raise AuthError('历史记录不存在或无权查看', 3002, 404)
    return record


def update_history_tasks_for_batch(user_id, batch_id, tasks):
    """
    用最新的任务快照回写该批次对应的历史记录（重试成功后调用，原地更新不新增记录）

    参数:
        user_id: 用户ID
        batch_id: 批次ID
        tasks: 批次内全部任务的最新快照列表（含失败的）
    返回:
        int or None: 被更新的历史记录ID；未找到记录返回 None
    """
    if not user_id or not batch_id:
        return None

    record = history_model.find_latest_by_batch_id(user_id, batch_id)
    if not record:
        print(f"[历史记录] 未找到批次对应的记录，跳过回写 batch_id={batch_id}", flush=True)
        return None

    record_id = record.get('id')
    sub_category = record.get('sub_category') or ''
    output_data = record.get('output_data')
    if not isinstance(output_data, dict):
        output_data = {'batch_id': batch_id}

    # 已成功任务在首次保存时已落盘为 URL，复用该 URL 避免重复写盘
    persisted_urls = {}
    prev_tasks = output_data.get('tasks')
    if isinstance(prev_tasks, list):
        for prev in prev_tasks:
            if isinstance(prev, dict):
                prev_url = prev.get('image_url')
                if isinstance(prev_url, str) and prev_url and not _BASE64_PATTERN.match(prev_url):
                    persisted_urls[prev.get('task_id')] = prev_url

    merged_tasks = []
    for task in tasks:
        if isinstance(task, dict):
            task_id = task.get('task_id')
            image_url = task.get('image_url')
            if (isinstance(image_url, str) and _BASE64_PATTERN.match(image_url)
                    and task_id in persisted_urls):
                task = {**task, 'image_url': persisted_urls[task_id]}
        merged_tasks.append(task)
    output_data['tasks'] = merged_tasks

    # 全部成功时清除首次失败写入的错误信息
    statuses = [t.get('status') for t in merged_tasks if isinstance(t, dict)]
    if statuses and all(s == 'success' for s in statuses):
        output_data.pop('error', None)

    # 复用保存管线：base64 图片落盘为 URL
    output_data = _persist_images_in_data(output_data, user_id, sub_category)
    output_data = _strip_base64_images(output_data)

    # 缩略图缺失时（首次全部失败）补齐
    thumbnail_url = record.get('thumbnail_url')
    if not _is_thumbnail_valid(thumbnail_url):
        thumbnail_url = _extract_thumbnail(output_data) or thumbnail_url

    updated = history_model.update_output_data(record_id, output_data, thumbnail_url=thumbnail_url)
    print(f"[历史记录] 重试结果已回写 id={record_id} batch_id={batch_id} updated={updated}", flush=True)
    return record_id if updated else None


def delete_history(user_id, record_id):
    """
    删除历史记录
    参数:
        user_id: 用户ID
        record_id: 历史记录ID
    异常:
        AuthError: 历史记录不存在或无权操作
    """
    deleted = history_model.delete_by_id(record_id, user_id)
    if not deleted:
        raise AuthError('历史记录不存在或无权操作', 3002, 404)


def share_history_to_team(user_id, record_id, team_id):
    """
    将历史记录分享到团队
    参数:
        user_id: 用户ID
        record_id: 记录ID
        team_id: 团队ID
    异常:
        AuthError: 不是团队成员 / 历史记录不存在或无权操作
    """
    if not _is_team_member(user_id, team_id):
        raise AuthError('您不是该团队成员，无法分享', 3002, 400)

    shared = history_model.share_to_team(record_id, user_id, team_id)
    if not shared:
        raise AuthError('历史记录不存在或无权操作', 3002, 404)


def unshare_history(user_id, record_id):
    """
    取消团队分享
    参数:
        user_id: 用户ID
        record_id: 记录ID
    异常:
        AuthError: 历史记录不存在或无权操作
    """
    unshared = history_model.unshare(record_id, user_id)
    if not unshared:
        raise AuthError('历史记录不存在或无权操作', 3002, 404)


def get_team_history(user_id, team_id, page=1, page_size=20):
    """
    获取团队分享的历史记录列表（分页）
    参数:
        user_id: 当前用户ID
        team_id: 团队ID
        page: 页码
        page_size: 每页数量
    返回:
        dict: { items, total, total_pages }
    异常:
        AuthError: 不是团队成员，无权查看
    """
    if not _is_team_member(user_id, team_id):
        raise AuthError('您不是该团队成员，无权查看', 3002, 403)

    items, total = history_model.find_by_team(team_id, page=page, page_size=page_size)

    # 检查并修复无效的 thumbnail_url（在移除 output_data 之前）
    for item in items:
        thumbnail_url = item.get('thumbnail_url')
        if not _is_thumbnail_valid(thumbnail_url):
            repaired = _repair_thumbnail_for_item(item)
            if repaired:
                item['thumbnail_url'] = repaired

        # 移除 input_data 和 output_data 以减小响应体积
        item.pop('input_data', None)
        item.pop('output_data', None)

    return {
        'items': items,
        'total': total,
        'total_pages': math.ceil(total / page_size) if total > 0 else 0
    }