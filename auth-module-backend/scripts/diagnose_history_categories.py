"""
历史记录 category 字段诊断脚本

用法:
    cd auth-module-backend
    python scripts/diagnose_history_categories.py

功能:
    1. 查询 history_records 表中所有 category 值的分布
    2. 标记非标准值（标准值: ai_product_image / ai_toolbox）
    3. 展示非标准记录的 sub_category，辅助判断应归一化到哪个标准值
"""
import os
import sys

# 将父目录加入 sys.path，使 config 模块可被导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from config import get_config

STANDARD_CATEGORIES = {'ai_product_image', 'ai_toolbox'}

# sub_category → 标准 category 映射（用于兜底推断展示）
SUB_TO_CATEGORY = {
    'smart_mode': 'ai_product_image',
    'pro_mode': 'ai_product_image',
    'plan_analysis': 'ai_toolbox',
    'image_merge': 'ai_toolbox',
    'text_to_image': 'ai_toolbox',
    'chat_gen': 'ai_toolbox',
    'product_replace': 'ai_toolbox',
    'ai_model': 'ai_toolbox',
    'model_product': 'ai_toolbox',
    'prompt_reverse': 'ai_toolbox',
}


def main():
    config = get_config()
    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )

    try:
        with conn.cursor() as cursor:
            # 1. category 值分布
            cursor.execute(
                'SELECT category, COUNT(*) AS cnt FROM history_records GROUP BY category ORDER BY cnt DESC'
            )
            rows = cursor.fetchall()

            print('=' * 70)
            print('历史记录 category 值分布')
            print('=' * 70)
            print(f'{"category":<30} {"数量":>8}  {"是否标准":<10}')
            print('-' * 70)

            total = 0
            abnormal_count = 0
            for row in rows:
                cat = row['category'] if row['category'] is not None else '(NULL)'
                cnt = row['cnt']
                is_standard = row['category'] in STANDARD_CATEGORIES
                flag = '✓ 标准' if is_standard else '✗ 非标准'
                print(f'{cat:<30} {cnt:>8}  {flag}')
                total += cnt
                if not is_standard:
                    abnormal_count += cnt

            print('-' * 70)
            print(f'{"总计":<30} {total:>8}')
            print(f'{"非标准记录数":<30} {abnormal_count:>8}')
            print()

            # 2. 非标准记录的 sub_category 分布（辅助判断归一化目标）
            if abnormal_count > 0:
                print('=' * 70)
                print('非标准 category 记录的 sub_category 分布')
                print('=' * 70)
                cursor.execute(
                    '''SELECT category, sub_category, COUNT(*) AS cnt
                       FROM history_records
                       WHERE category NOT IN ('ai_product_image', 'ai_toolbox')
                          OR category IS NULL
                       GROUP BY category, sub_category
                       ORDER BY cnt DESC'''
                )
                sub_rows = cursor.fetchall()
                print(f'{"category":<25} {"sub_category":<25} {"数量":>8}  {"建议归一化":<20}')
                print('-' * 70)
                for row in sub_rows:
                    cat = row['category'] if row['category'] is not None else '(NULL)'
                    sub = row['sub_category'] if row['sub_category'] is not None else '(NULL)'
                    suggested = SUB_TO_CATEGORY.get(row['sub_category'], '? 需人工判断')
                    print(f'{cat:<25} {sub:<25} {row["cnt"]:>8}  {suggested:<20}')
                print()
                print('提示: 执行 migrations/006_normalize_history_categories.sql 可修复这些记录')
            else:
                print('✓ 所有记录的 category 值均已标准化，无需修复')

    finally:
        conn.close()


if __name__ == '__main__':
    main()
