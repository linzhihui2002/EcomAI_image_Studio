"""
历史记录缩略图修复脚本

扫描 history_records 表中 thumbnail_url 为空、NULL 或 base64 data URI 的记录，
从 output_data JSON 中重新提取图片 URL 并更新。

用法:
    cd auth-module-backend
    python scripts/repair_thumbnails.py [--dry-run] [--limit N]

选项:
    --dry-run   仅扫描不修改，输出诊断信息
    --limit N   限制处理条数（用于分批处理）
    --user-id N 仅处理指定用户的记录
"""
import sys
import os
import argparse
import json
import re
import base64
import uuid
import time

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from config import get_config

# ============================================================
# 复用 history_service 中的缩略图提取逻辑
# （避免循环导入，直接复制核心函数）
# ============================================================

_BASE64_PATTERN = re.compile(r'^data:image/.+;base64,.+', re.IGNORECASE)
_DATA_URI_PATTERN = re.compile(r'^data:(image/(\w+));base64,(.+)$', re.IGNORECASE)

# 存储目录
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(_BACKEND_ROOT, 'uploads', 'history_images')

_FORMAT_MAP = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'webp': 'image/webp',
    'gif': 'image/gif',
}


def _ensure_storage_dir():
    os.makedirs(STORAGE_DIR, exist_ok=True)


def _generate_filename(user_id, prefix, ext):
    ext = ext.lower().lstrip('.')
    timestamp = int(time.time())
    short_uuid = uuid.uuid4().hex[:12]
    safe_prefix = re.sub(r'[^a-zA-Z0-9_-]', '', prefix)[:20] or 'img'
    return f"{safe_prefix}_{user_id}_{timestamp}_{short_uuid}.{ext}"


def save_base64_image(b64_data, user_id, prefix='img'):
    """保存 base64 图片到磁盘，返回 URL 路径"""
    if not isinstance(b64_data, str) or not b64_data:
        return None

    match = _DATA_URI_PATTERN.match(b64_data)
    if match:
        ext = match.group(2).lower()
        raw_b64 = match.group(3)
    else:
        ext = 'png'
        raw_b64 = b64_data

    if ext not in _FORMAT_MAP:
        ext = 'png'

    try:
        image_bytes = base64.b64decode(raw_b64)
    except Exception:
        return None

    if not image_bytes:
        return None

    _ensure_storage_dir()
    filename = _generate_filename(user_id, prefix, ext)
    file_path = os.path.join(STORAGE_DIR, filename)
    try:
        with open(file_path, 'wb') as f:
            f.write(image_bytes)
    except Exception:
        return None

    return f"/api/v1/images/{filename}"


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


def extract_thumbnail(output_data):
    """从 output_data 中提取第一张图片 URL"""
    if not output_data:
        return None
    if isinstance(output_data, dict):
        # 1. 直接的图片键
        for key in ('image_url', 'url', 'image', 'images', 'result',
                     'merged_image', 'result_image'):
            val = output_data.get(key)
            if val:
                result = _extract_first_url_from_value(val)
                if result:
                    return result

        # 2. tasks 数组
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


def _is_valid_thumbnail_url(url):
    """检查 thumbnail_url 是否有效（非空、非 base64、文件存在）"""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url or _BASE64_PATTERN.match(url):
        return False
    # 如果是本地文件路径，检查文件是否存在
    if url.startswith('/api/v1/images/'):
        filename = url.replace('/api/v1/images/', '')
        file_path = os.path.join(STORAGE_DIR, filename)
        return os.path.isfile(file_path)
    # 外部 URL（http/https）视为有效
    if url.startswith('http://') or url.startswith('https://'):
        return True
    return False


def _try_persist_base64_in_output(output_data, user_id):
    """
    如果 output_data 中包含 base64 图片，尝试持久化为文件。
    返回 (处理后的 output_data, 是否修改过)
    """
    modified = False

    def _process(val):
        nonlocal modified
        if isinstance(val, str) and _BASE64_PATTERN.match(val):
            url = save_base64_image(val, user_id, prefix='repair')
            if url:
                modified = True
                return url
        return val

    if isinstance(output_data, dict):
        result = {}
        for k, v in output_data.items():
            if isinstance(v, list):
                result[k] = [_process(item) for item in v]
            else:
                result[k] = _process(v)
        return result, modified
    return output_data, modified


def repair_thumbnails(dry_run=False, limit=None, user_id=None):
    """
    扫描并修复历史记录缩略图

    Returns:
        dict: { total, fixed, failed, skipped }
    """
    config = get_config()
    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

    stats = {'total': 0, 'fixed': 0, 'failed': 0, 'skipped': 0}

    try:
        with conn.cursor() as cursor:
            # 查询需要修复的记录
            where_clause = (
                "thumbnail_url IS NULL OR thumbnail_url = '' "
                "OR thumbnail_url LIKE 'data:%%'"
            )
            params = []
            if user_id is not None:
                where_clause = f"({where_clause}) AND user_id = %s"
                params.append(user_id)

            sql = (
                f"SELECT id, user_id, sub_category, thumbnail_url, output_data "
                f"FROM history_records WHERE {where_clause} ORDER BY id"
            )
            if limit is not None:
                sql += " LIMIT %s"
                params.append(limit)

            cursor.execute(sql, params)
            records = cursor.fetchall()

        stats['total'] = len(records)
        print(f"[修复脚本] 找到 {stats['total']} 条需要修复的记录")
        if dry_run:
            print("[修复脚本] DRY-RUN 模式，不会实际修改数据")

        for record in records:
            record_id = record['id']
            uid = record['user_id']
            sub_category = record.get('sub_category', '')
            old_thumbnail = record.get('thumbnail_url', '')
            output_data = record.get('output_data')

            # 解析 output_data JSON
            if isinstance(output_data, str):
                try:
                    output_data = json.loads(output_data)
                except (json.JSONDecodeError, TypeError):
                    output_data = None

            if not output_data:
                stats['skipped'] += 1
                print(f"  [SKIP] id={record_id}: output_data 为空或无效")
                continue

            # 尝试从 output_data 提取缩略图 URL
            new_thumbnail = extract_thumbnail(output_data)

            # 如果提取到的是 base64，尝试持久化
            if new_thumbnail and _BASE64_PATTERN.match(new_thumbnail):
                print(f"  [INFO] id={record_id}: 缩略图是 base64，尝试持久化...")
                persisted_url = save_base64_image(new_thumbnail, uid, prefix=f"{sub_category}_repair")
                if persisted_url:
                    new_thumbnail = persisted_url
                else:
                    new_thumbnail = None

            # 如果提取不到，尝试从 output_data 中持久化 base64 再提取
            if not new_thumbnail:
                processed_output, modified = _try_persist_base64_in_output(output_data, uid)
                if modified:
                    new_thumbnail = extract_thumbnail(processed_output)
                    if new_thumbnail:
                        print(f"  [INFO] id={record_id}: 从 output_data 持久化 base64 后提取到缩略图")

            if not new_thumbnail:
                stats['failed'] += 1
                print(f"  [FAIL] id={record_id}: 无法提取有效的缩略图 URL")
                continue

            if dry_run:
                print(f"  [DRY-RUN] id={record_id}: {old_thumbnail[:80] if old_thumbnail else '(空)'} → {new_thumbnail[:80]}")
                stats['fixed'] += 1
                continue

            # 更新数据库
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE history_records SET thumbnail_url = %s WHERE id = %s",
                        (new_thumbnail, record_id)
                    )
                    conn.commit()
                stats['fixed'] += 1
                print(f"  [FIXED] id={record_id}: {old_thumbnail[:60] if old_thumbnail else '(空)'} → {new_thumbnail[:80]}")
            except Exception as e:
                stats['failed'] += 1
                print(f"  [ERROR] id={record_id}: 更新失败 - {e}")

    finally:
        conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description='历史记录缩略图修复脚本')
    parser.add_argument('--dry-run', action='store_true', help='仅扫描不修改')
    parser.add_argument('--limit', type=int, default=None, help='限制处理条数')
    parser.add_argument('--user-id', type=int, default=None, help='仅处理指定用户')
    args = parser.parse_args()

    print("=" * 60)
    print("历史记录缩略图修复脚本")
    print(f"存储目录: {STORAGE_DIR}")
    print(f"目录存在: {os.path.isdir(STORAGE_DIR)}")
    print("=" * 60)

    stats = repair_thumbnails(
        dry_run=args.dry_run,
        limit=args.limit,
        user_id=args.user_id
    )

    print("\n" + "=" * 60)
    print("修复完成！统计：")
    print(f"  总记录数: {stats['total']}")
    print(f"  已修复:   {stats['fixed']}")
    print(f"  失败:     {stats['failed']}")
    print(f"  跳过:     {stats['skipped']}")
    print("=" * 60)


if __name__ == '__main__':
    main()