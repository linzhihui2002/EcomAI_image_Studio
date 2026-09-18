"""生图计划分析任务队列 - 提供任务入队、状态查询、历史记录等功能"""

import json
import traceback
from typing import Any, Dict

from services.task_queue import (
    register_task,
    set_progress,
    complete_task,
    fail_task,
)
from models.plan_analysis import PlanAnalysisTaskModel


def enqueue_task(user_id: int, input_hash: str, payload: dict) -> int:
    """创建分析任务记录，返回 task_id"""
    model = PlanAnalysisTaskModel()
    task_id = model.create(user_id=user_id, input_hash=input_hash, status='pending')
    return task_id


def process_next_task() -> bool:
    """
    处理下一个待处理任务（简化版，由路由层驱动实际分析调用）

    路由层负责：
    1. 创建任务 status='pending'
    2. 更新为 status='processing'
    3. 调用 analyze_generation_plan
    4. 更新为 status='completed' 或 status='failed'

    此函数作为占位/存根，主要提供状态流转的模板。
    """
    model = PlanAnalysisTaskModel()
    task = model.find_pending()
    if task is None:
        return False

    task_id = task['id']

    model.update_status(task_id=task_id, status='processing')

    try:
        from services.toolbox_service import analyze_generation_plan
        result = analyze_generation_plan(images_base64_list=[], file_content=None, prompt=None)
        result_json = json.dumps(result, ensure_ascii=False)
        model.update_status(task_id=task_id, status='completed', result_json=result_json)
    except Exception as e:
        error_message = str(e)
        model.update_status(task_id=task_id, status='failed', error_message=error_message)

    return True


def get_task_status(task_id: int) -> dict:
    """查询任务状态，返回 dict；若任务不存在则抛出 ValueError"""
    model = PlanAnalysisTaskModel()
    task = model.find_by_id(task_id)
    if task is None:
        raise ValueError("任务不存在")

    result_json = task.get('result_json')
    return {
        'id': task['id'],
        'status': task['status'],
        'result_json': json.loads(result_json) if result_json else None,
        'error_message': task.get('error_message'),
        'created_at': str(task['created_at']) if task.get('created_at') else None,
        'updated_at': str(task['updated_at']) if task.get('updated_at') else None,
    }


def get_user_history(user_id: int, page: int = 1, page_size: int = 10) -> dict:
    """分页查询用户的任务历史"""
    model = PlanAnalysisTaskModel()
    items, total = model.find_by_user(user_id=user_id, page=page, page_size=page_size)

    def _format_task(task: dict) -> dict:
        result_json = task.get('result_json')
        return {
            'id': task['id'],
            'status': task['status'],
            'result_json': json.loads(result_json) if result_json else None,
            'error_message': task.get('error_message'),
            'created_at': str(task['created_at']) if task.get('created_at') else None,
            'updated_at': str(task['updated_at']) if task.get('updated_at') else None,
        }

    return {
        'items': [_format_task(t) for t in items],
        'total': total,
        'page': page,
        'page_size': page_size,
    }


# ── ARQ 任务体（Task 7 迁移：原 routes/toolbox.py 后台线程 _run_analysis 平移） ──

@register_task('toolbox_plan_analysis')
async def toolbox_plan_analysis_task(ctx, payload: dict, task_id: str):
    """
    生图计划分析任务（ARQ）：执行体与原后台线程 _run_analysis 完全一致。
    - task_id: Redis 任务 ID（ARQ job_id，仅用于执行观测）
    - payload['db_task_id']: 业务任务 ID（DB 自增主键，GET /plan-analysis/status 轮询的数据源不变）
    """
    from services.toolbox_service import analyze_generation_plan, ToolboxError
    from services.analysis_cache import set_cache_result
    from services.history_service import save_history
    from services.feature_pricing_service import refund_coins

    db_task_id = payload['db_task_id']
    images = payload['images']
    file_content = payload.get('file_content')
    prompt = payload.get('prompt')
    file_data = payload.get('file_data')
    file_name = payload.get('file_name')
    user_id = payload.get('user_id')
    deducted = payload.get('deducted', False)
    cost = payload.get('cost', 0)
    feature_key = payload.get('feature_key', 'toolbox.plan_analysis')
    tool_name = payload.get('tool_name', '生图计划分析')
    history_input = payload.get('history_input', {})

    task_model = PlanAnalysisTaskModel()

    await set_progress(ctx, task_id, "正在分析生图计划...")

    try:
        plan = analyze_generation_plan(
            images,
            file_content=file_content,
            prompt=prompt,
            file_data=file_data,
            file_name=file_name,
            user_id=user_id,
        )
        # 写入缓存和结果（同时把 DB 状态写为 completed，原逻辑）
        set_cache_result(db_task_id, plan)
        await complete_task(ctx, task_id, plan)
        # 保存历史记录
        try:
            save_history(
                user_id=user_id,
                category='ai_toolbox',
                sub_category='plan_analysis',
                input_data=history_input,
                output_data=plan,
            )
        except Exception:
            pass  # 历史记录保存失败不影响主流程
    except ToolboxError as e:
        try:
            task_model.update_status(db_task_id, 'failed', error_message=e.message)
        except Exception:
            pass
        await fail_task(ctx, task_id, e.message)
        if deducted:
            try:
                refund_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款',
                             related_batch_id=str(db_task_id))
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
    except Exception as e:
        print(f"[工具箱-计划分析] 后台任务异常: {e}", flush=True)
        print(f"[工具箱-计划分析] 异常堆栈: {traceback.format_exc()}", flush=True)
        try:
            task_model.update_status(db_task_id, 'failed', error_message=str(e))
        except Exception:
            pass
        await fail_task(ctx, task_id, str(e))
        if deducted:
            try:
                refund_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款',
                             related_batch_id=str(db_task_id))
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)