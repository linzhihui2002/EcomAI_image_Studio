"""
商品图生成路由模块
提供商品分析、套图生成、任务查询接口
"""
import asyncio
import json
import uuid
from flask import Blueprint, request, jsonify, g
from middleware.auth_middleware import token_required
from services.generation_service import analyze_product, GenerationError, call_image_edit_model
from services.feature_pricing_service import (
    calculate_image_cost, deduct_coins, FeaturePricingError,
)
from services.user_ai_provider_service import is_feature_byok
from services.compliance_service import precheck_prompt, normalize_platform
from services.task_queue import register_task, submit_task, set_progress, complete_task, fail_task
from services.generation_store import get_task_store, get_batch_store, get_batch_context_store
from services.history_service import update_history_tasks_for_batch
from workflows.smart_generation import run_smart_generation_async
from workflows.pro_generation import (
    run_pro_analyze_integrate,
    apply_dialog_optimize,
    confirm_and_generate,
    auto_fill_empty_schemes,
    get_pro_batch,
    get_pro_batch_tasks,
)
from models.generation_task import GenerationTask, TaskStatus

generation_bp = Blueprint('generation', __name__, url_prefix='/api/v1')

# ── 任务存储（Task 7 迁移：原进程内字典 → Redis Hash 适配器，dict 语义不变）──
_task_store = get_task_store()      # task_id -> GenerationTask dict（generation:tasks）
_batch_store = get_batch_store()    # batch_id -> list[task_id]（generation:batches）
_batch_context = get_batch_context_store()  # batch_id -> {product_images, reference_image, reference_text, size}（generation:batchctx）


def _register_batch(batch_id: str, tasks_data: list):
    """将批次任务注册到内存存储"""
    task_ids = []
    for t in tasks_data:
        task_id = t.get("task_id", "")
        task_ids.append(task_id)
        _task_store[task_id] = t
    _batch_store[batch_id] = task_ids


@generation_bp.route('/generation/analyze-product', methods=['POST'])
@token_required
def analyze_product_api():
    """
    AI帮写 - 分析商品图片返回结构化商品信息
    
    Request Body:
    {
        "image_base64": "base64 encoded image data",
        "existing_text": "optional partial product info text"
    }
    
    Response:
    {
        "code": 0,
        "data": {
            "product_name": "...",
            "target_audience": "...",
            "selling_points": "...",
            "usage_scenario": "...",
            "product_category": "..."
        }
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        image_base64 = data.get("image_base64", "")
        if not image_base64:
            return jsonify({"code": 4001, "message": "请上传商品图片", "data": None}), 400

        # 基本图片格式校验
        if not _is_valid_base64_image(image_base64):
            return jsonify({"code": 4001, "message": "图片格式不支持，请上传 JPG/PNG/WebP 格式", "data": None}), 400

        existing_text = data.get("existing_text")

        user_id = g.current_user['user_id']
        product_info = analyze_product(image_base64, existing_text, user_id=user_id)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": product_info.to_dict()
        })

    except GenerationError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        return jsonify({"code": 5001, "message": f"商品分析失败: {str(e)}", "data": None}), 500


@generation_bp.route('/generation/smart-generate', methods=['POST'])
@token_required
def smart_generate_api():
    """
    简单模式智能套图生成
    
    Request Body:
    {
        "product_images": ["base64_string", ...],
        "reference_image": "base64_string or null",
        "platform": "Amazon",
        "region": "美国",
        "target_language": "英语",
        "size": "1024x1024",
        "product_info": {product_name, target_audience, ...} or null,
        "image_groups": [
            {
                "key": "white",
                "slots": [{id, name, desc}, ...]
            },
            ...
        ]
    }
    
    Response:
    {
        "code": 0,
        "data": {
            "batch_id": "batch-xxx",
            "tasks": [{task_id, image_type, status, prompt_used, ...}, ...]
        }
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        # 提取参数
        product_images = data.get("product_images", [])
        reference_image = data.get("reference_image")
        reference_text = data.get("reference_text")
        platform = data.get("platform", "Amazon")
        region = data.get("region", "美国")
        target_language = data.get("target_language", "英语")
        size = data.get("size", "1024x1024")
        site = data.get("site", "")          # P0-1 可选：站点码（US/DE/JP...）
        scene = data.get("scene", "")        # P0-1 可选：中文场景
        product_info = data.get("product_info")
        image_groups = data.get("image_groups", [])

        # 校验
        if not product_images or len(product_images) == 0:
            return jsonify({"code": 4001, "message": "请至少上传一张商品图片", "data": None}), 400

        total_slots = sum(len(group.get("slots", [])) for group in image_groups)
        if total_slots == 0:
            return jsonify({"code": 4001, "message": "请至少配置一种图片类型", "data": None}), 400

        # 序列化商品信息
        product_info_json = json.dumps(product_info, ensure_ascii=False) if product_info else None

        # ── P0-2 平台合规预校验（block 级命中直接拒绝，不扣费）──
        _precheck_text = ' '.join(filter(None, [
            (product_info or {}).get('selling_points', '') if isinstance(product_info, dict) else '',
            (product_info or {}).get('usage_scenario', '') if isinstance(product_info, dict) else '',
            reference_text or '',
        ]))
        if _precheck_text.strip():
            _precheck = precheck_prompt(normalize_platform(platform), 'scene', _precheck_text)
            if _precheck['blocks']:
                return jsonify({
                    "code": 4003,
                    "message": "内容包含平台禁用元素，请修改后重试",
                    "data": {"blocks": _precheck['blocks'], "warnings": _precheck['warnings']},
                }), 400

        # ── 灵感币扣费（在启动后台生图前扣减，避免欠费生图）──
        # BYOK：命中用户自备模型通道时不扣费（single/total 均为 0，跳过 deduct_coins）
        user_id = g.current_user['user_id']
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        if is_feature_byok(user_id, 'ai_product_image.smart_mode'):
            single_cost = 0
            total_cost = 0
        else:
            single_cost = calculate_image_cost('ai_product_image.smart_mode', size)
            total_cost = single_cost * total_slots
        if total_cost > 0:
            try:
                deduct_coins(
                    user_id=user_id,
                    amount=total_cost,
                    feature_key='ai_product_image.smart_mode',
                    description=f'AI商品图-简单模式 生图 {total_slots} 张',
                    related_batch_id=batch_id,
                )
                print(f"[简单模式扣费] 扣费成功 user_id={user_id} batch_id={batch_id} "
                      f"single_cost={single_cost} total_cost={total_cost} slots={total_slots}", flush=True)
            except FeaturePricingError as e:
                print(f"[简单模式扣费] 扣费失败 user_id={user_id} code={e.code} msg={e.message}", flush=True)
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            print(f"[简单模式扣费] 未定价或费用为0，跳过扣费降级处理: "
                  f"feature_key=ai_product_image.smart_mode, size={size}", flush=True)

        # 执行异步工作流（立即返回，后台生成）
        result = run_smart_generation_async(
            product_images=product_images,
            platform=platform,
            region=region,
            target_language=target_language,
            size=size,
            image_groups=image_groups,
            product_info_json=product_info_json,
            reference_image=reference_image,
            reference_text=reference_text,
            task_store=_task_store,
            batch_store=_batch_store,
            user_id=user_id,
            batch_id=batch_id,
            site=site,
            scene=scene,
            prepaid_coins=total_cost,
            history_input_data={
                'product_images': data.get('product_images', []),
                'reference_image': data.get('reference_image'),
                'reference_text': data.get('reference_text'),
                'platform': data.get('platform', ''),
                'region': data.get('region', ''),
                'target_language': data.get('target_language', ''),
                'size': data.get('size', ''),
                'product_info': data.get('product_info', {}),
                'image_groups': data.get('image_groups', []),
            },
            history_config_snapshot=data,
        )

        # 存储批次上下文，供重试时复用
        _batch_context[result["batch_id"]] = {
            "product_images": product_images,
            "reference_image": reference_image,
            "reference_text": reference_text,
            "size": size,
        }

        return jsonify({
            "code": 0,
            "message": "success",
            "data": {
                "batch_id": result["batch_id"],
                "tasks": result["tasks"],
            }
        })

    except Exception as e:
        return jsonify({"code": 5001, "message": f"生成失败: {str(e)}", "data": None}), 500


@generation_bp.route('/generation/tasks/<task_id>', methods=['GET'])
@token_required
def get_task_status(task_id):
    """
    查询单个任务状态
    
    Response:
    {
        "code": 0,
        "data": {task_id, batch_id, image_type, status, image_url, error_msg, ...}
    }
    """
    task = _task_store.get(task_id)
    if not task:
        return jsonify({"code": 4004, "message": "任务不存在", "data": None}), 404

    return jsonify({
        "code": 0,
        "message": "success",
        "data": task
    })


@generation_bp.route('/generation/batches/<batch_id>', methods=['GET'])
@token_required
def get_batch_status(batch_id):
    """
    查询批次下所有任务状态
    
    Response:
    {
        "code": 0,
        "data": {
            "batch_id": "...",
            "tasks": [{...}, {...}]
        }
    }
    """
    task_ids = _batch_store.get(batch_id, [])
    if not task_ids:
        print(f"[轮询] batch={batch_id} 不存在于 _batch_store 中（当前 batches: {list(_batch_store.keys())}）", flush=True)
        return jsonify({"code": 4004, "message": "批次不存在", "data": None}), 404

    # 使用浅拷贝避免修改 _task_store 中的原始数据
    tasks = [dict(_task_store.get(tid)) for tid in task_ids if _task_store.get(tid)]
    # 剥离 base64 数据 URI，避免轮询响应过大导致 ERR_HTTP2_PROTOCOL_ERROR
    # 前端通过 has_image 标志判断是否需要单独调用 getTaskStatus 获取图片
    for t in tasks:
        img_url = t.get("image_url", "")
        if img_url and img_url.startswith("data:"):
            t["has_image"] = True
            t["image_url"] = ""
    statuses = [t.get("status", "?") for t in tasks]
    has_images = [bool(t.get("has_image")) for t in tasks]
    print(f"[轮询] batch={batch_id} task_count={len(tasks)} statuses={statuses} has_images={has_images}", flush=True)

    return jsonify({
        "code": 0,
        "message": "success",
        "data": {
            "batch_id": batch_id,
            "tasks": tasks,
        }
    })


@generation_bp.route('/generation/tasks/<task_id>', methods=['DELETE'])
@token_required
def delete_task(task_id):
    """
    删除单个生成任务
    
    Response:
    {
        "code": 0,
        "message": "删除成功",
        "data": {"task_id": "...", "batch_id": "..."}
    }
    """
    try:
        task = _task_store.get(task_id)
        if not task:
            return jsonify({"code": 4004, "message": "任务不存在", "data": None}), 404

        batch_id = task.get("batch_id", "")

        # 从任务存储中删除
        del _task_store[task_id]

        # 从批次中移除该任务
        if batch_id and batch_id in _batch_store:
            _batch_store[batch_id] = [tid for tid in _batch_store[batch_id] if tid != task_id]
            # 若批次为空，清理批次条目
            if not _batch_store[batch_id]:
                del _batch_store[batch_id]

        return jsonify({
            "code": 0,
            "message": "删除成功",
            "data": {"task_id": task_id, "batch_id": batch_id}
        })

    except Exception as e:
        return jsonify({"code": 5001, "message": f"删除任务失败: {str(e)}", "data": None}), 500


@generation_bp.route('/generation/batches/<batch_id>', methods=['DELETE'])
@token_required
def delete_batch(batch_id):
    """
    删除整个批次及其下所有任务
    
    Response:
    {
        "code": 0,
        "message": "删除成功",
        "data": {"batch_id": "...", "deleted_tasks": N}
    }
    """
    try:
        task_ids = _batch_store.get(batch_id, [])
        if not task_ids:
            return jsonify({"code": 4004, "message": "批次不存在", "data": None}), 404

        deleted_count = 0
        for tid in task_ids:
            if tid in _task_store:
                del _task_store[tid]
                deleted_count += 1

        # 删除批次条目
        del _batch_store[batch_id]

        # 清理批次上下文
        if batch_id in _batch_context:
            del _batch_context[batch_id]

        return jsonify({
            "code": 0,
            "message": "删除成功",
            "data": {"batch_id": batch_id, "deleted_tasks": deleted_count}
        })

    except Exception as e:
        return jsonify({"code": 5001, "message": f"删除批次失败: {str(e)}", "data": None}), 500


@generation_bp.route('/generation/tasks/<task_id>/retry', methods=['POST'])
@token_required
def retry_task(task_id):
    """
    重试单个失败的生成任务

    从 _task_store 获取失败任务，从 _batch_context 获取批次上下文，
    在后台线程中重新调用 call_image_edit_model 生成该图片。

    Response:
    {
        "code": 0,
        "message": "success",
        "data": {task_id, batch_id, status: "processing", ...}
    }
    """
    try:
        task = _task_store.get(task_id)
        if not task:
            return jsonify({"code": 4004, "message": "任务不存在", "data": None}), 404

        if task.get("status") not in ("failed",):
            return jsonify({"code": 4001, "message": "仅失败的任务可以重试", "data": None}), 400

        batch_id = task.get("batch_id", "")
        context = _batch_context.get(batch_id)
        if not context:
            return jsonify({"code": 4004, "message": "批次生成上下文已过期，请重新提交生成", "data": None}), 404

        # 立即更新状态为 processing（即时反馈给前端轮询）
        # Task 7 迁移：task 为 Redis 写回代理，原地修改自动持久化
        task["status"] = "processing"
        task["error_msg"] = None
        _task_store[task_id] = task

        # Task 7 迁移：原后台线程 _retry_run → ARQ 任务（执行体见 generation_retry_task）
        submit_task(
            GENERATION_RETRY_TASK_NAME,
            {'gen_task_id': task_id, 'batch_id': batch_id,
             'user_id': g.current_user['user_id']},
            module='generation',
        )
        print(f"[重试生图] ARQ 任务已提交 task_id={task_id} batch_id={batch_id}", flush=True)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": task,
        })

    except Exception as e:
        return jsonify({"code": 5001, "message": f"重试任务失败: {str(e)}", "data": None}), 500


GENERATION_RETRY_TASK_NAME = 'generation_retry'


@register_task(GENERATION_RETRY_TASK_NAME)
async def generation_retry_task(ctx, payload: dict, task_id: str):
    """
    失败任务重试生图任务（ARQ）：执行体与原 retry_task 后台线程 _retry_run 完全一致。
    task / 批次上下文从 Redis 存储重新读取（写回代理自动持久化修改）。
    payload: {gen_task_id, batch_id, user_id}
    """
    gen_task_id = payload['gen_task_id']
    batch_id = payload['batch_id']
    user_id = payload.get('user_id')

    await set_progress(ctx, task_id, '正在重试生图...')

    def _run():
        try:
            task = _task_store.get(gen_task_id)
            context = _batch_context.get(batch_id)
            if task is None or context is None:
                print(f"[重试生图] 任务或上下文不存在 task_id={gen_task_id} batch_id={batch_id}", flush=True)
                return
            print(f"[重试生图] 开始重试 task_id={gen_task_id} batch_id={batch_id}", flush=True)
            product_image = context["product_images"][0] if context["product_images"] else None
            reference_image = context.get("reference_image")
            reference_text = context.get("reference_text")
            size = context.get("size", "1024x1024")
            prompt = task.get("prompt_used", "")

            if not product_image:
                task["status"] = "failed"
                task["error_msg"] = "缺少商品图，无法重试生成"
                _task_store[gen_task_id] = task
                return

            if not prompt:
                task["status"] = "failed"
                task["error_msg"] = "缺少生成提示词，无法重试生成"
                _task_store[gen_task_id] = task
                return

            result = call_image_edit_model(
                product_image=product_image,
                prompt=prompt,
                size=size,
                reference_image=reference_image,
                reference_text=reference_text,
                user_id=user_id,
            )

            url = result.get("url")
            b64 = result.get("b64_json")
            if url:
                task["image_url"] = url
            elif b64:
                task["image_url"] = f"data:image/png;base64,{b64}"
            task["status"] = "success"
            task["error_msg"] = None
            _task_store[gen_task_id] = task
            print(f"[重试生图] 重试成功 task_id={gen_task_id}", flush=True)

            # 回写历史记录：用批次内全部任务的最新快照覆盖原记录的 tasks
            try:
                batch_task_ids = _batch_store.get(batch_id) or [gen_task_id]
                final_tasks = [
                    dict(_task_store[tid]) for tid in batch_task_ids if tid in _task_store
                ]
                update_history_tasks_for_batch(user_id, batch_id, final_tasks)
            except Exception as history_err:
                print(f"[重试生图] 历史记录回写失败（不影响主流程）: {history_err}", flush=True)

        except Exception as e:
            import traceback
            print(f"[重试生图] 重试失败 task_id={gen_task_id}: {e}", flush=True)
            print(f"[重试生图] 异常堆栈: {traceback.format_exc()}", flush=True)
            task = _task_store.get(gen_task_id)
            if task is not None:
                task["status"] = "failed"
                task["error_msg"] = str(e)
                _task_store[gen_task_id] = task

    try:
        await asyncio.to_thread(_run)
        await set_progress(ctx, task_id, '处理完成', pct=100)
        await complete_task(ctx, task_id, {'gen_task_id': gen_task_id})
    except Exception as e:
        await fail_task(ctx, task_id, f"重试任务执行异常: {str(e)}")


def _is_valid_base64_image(base64_str: str) -> bool:
    """基本校验 base64 图片格式"""
    if base64_str.startswith("data:image/"):
        valid_types = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
        for vt in valid_types:
            if base64_str.startswith(f"data:{vt}"):
                return True
        return False
    # 纯 base64（无前缀）也放行，假设调用方已确认格式
    return len(base64_str) > 100  # 基本长度判断


# ================================================================
# 专业模式 API（AI 分析整合 / 对话优化 / 确认生图）
# ================================================================

@generation_bp.route('/generation/pro/analyze-integrate', methods=['POST'])
@token_required
def pro_analyze_integrate_api():
    """
    专业模式 - AI 分析整合

    对提示词方案为空的任务自动补全（含图片定位、排版、文案）。

    Request Body:
    {
        "product_images": ["base64_1", ...],
        "reference_image": "base64 or null",
        "reference_text": "参考维度描述 or null",
        "platform": "Amazon",
        "region": "美国",
        "target_language": "英语",
        "size": "1024x1024",
        "requirement": "整体要求",
        "product_info": {...} or null,
        "image_tasks": [
            {
                "task_id": "task-xxx1",
                "image_type": "main_image",
                "aspect_ratio": "1:1",
                "prompt_scheme": null   // null/空 表示需 AI 补全
            },
            ...
        ]
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        product_images = data.get("product_images", [])
        reference_image = data.get("reference_image")
        reference_text = data.get("reference_text")
        platform = data.get("platform", "Amazon")
        region = data.get("region", "美国")
        target_language = data.get("target_language", "英语")
        size = data.get("size", "1024x1024")
        requirement = data.get("requirement", "")
        product_info = data.get("product_info")
        image_tasks = data.get("image_tasks", [])
        prompt_language = data.get("prompt_language", "en")

        # 校验
        if not product_images:
            return jsonify({"code": 4001, "message": "请至少上传一张商品图片", "data": None}), 400
        if not image_tasks:
            return jsonify({"code": 4001, "message": "请至少配置一个生图任务", "data": None}), 400

        # 校验图片格式
        for img in product_images:
            if not _is_valid_base64_image(img):
                return jsonify({"code": 4001, "message": "图片格式不支持，请上传 JPG/PNG/WebP 格式", "data": None}), 400

        user_id = g.current_user['user_id']
        result = run_pro_analyze_integrate(
            product_images=product_images,
            reference_image=reference_image,
            reference_text=reference_text,
            platform=platform,
            region=region,
            target_language=target_language,
            size=size,
            requirement=requirement,
            image_tasks=image_tasks,
            product_info=product_info,
            prompt_language=prompt_language,
            user_id=user_id,
        )

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result,
        })

    except GenerationError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        return jsonify({"code": 5001, "message": f"AI分析整合失败: {str(e)}", "data": None}), 500


@generation_bp.route('/generation/pro/auto-fill-schemes', methods=['POST'])
@token_required
def pro_auto_fill_schemes_api():
    """
    专业模式 - 一键AI补全空方案

    为批次中所有方案为空或失败的任务重新调用 LLM 生成方案。

    Request Body:
    {
        "batch_id": "pro-batch-xxx"
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        batch_id = data.get("batch_id")
        if not batch_id:
            return jsonify({"code": 4001, "message": "批次ID不能为空", "data": None}), 400

        result = auto_fill_empty_schemes(batch_id, user_id=g.current_user['user_id'])
        return jsonify({"code": 0, "message": "success", "data": result})

    except GenerationError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        return jsonify({"code": 5001, "message": f"方案补全失败: {str(e)}", "data": None}), 500


@generation_bp.route('/generation/pro/dialog-optimize', methods=['POST'])
@token_required
def pro_dialog_optimize_api():
    """
    专业模式 - AI 对话优化

    用户通过自然语言对话迭代优化提示词方案。

    Request Body:
    {
        "batch_id": "pro-batch-xxx",
        "task_id": "task-xxx1",
        "user_input": "把背景改为浅灰色",
        "dialog_history": [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ]
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        batch_id = data.get("batch_id", "")
        task_id = data.get("task_id", "")
        user_input = data.get("user_input", "").strip()
        dialog_history = data.get("dialog_history", [])

        if not batch_id:
            return jsonify({"code": 4001, "message": "批次ID不能为空", "data": None}), 400
        if not task_id:
            return jsonify({"code": 4001, "message": "任务ID不能为空", "data": None}), 400
        if not user_input:
            return jsonify({"code": 4001, "message": "请输入优化指令", "data": None}), 400

        # 对话历史长度限制
        if len(dialog_history) > 40:
            return jsonify({"code": 4003, "message": "对话历史超出长度限制", "data": None}), 400

        result = apply_dialog_optimize(
            batch_id=batch_id,
            task_id=task_id,
            user_input=user_input,
            dialog_history=dialog_history,
            user_id=g.current_user['user_id'],
        )

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result,
        })

    except GenerationError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        return jsonify({"code": 5001, "message": f"对话优化失败: {str(e)}", "data": None}), 500


@generation_bp.route('/generation/pro/confirm', methods=['POST'])
@token_required
def pro_confirm_api():
    """
    专业模式 - 确认方案并触发生图

    校验所有方案已就绪后，锁定方案并异步触发生图工作流。

    Request Body:
    {
        "batch_id": "pro-batch-xxx"
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        batch_id = data.get("batch_id", "")
        if not batch_id:
            return jsonify({"code": 4001, "message": "批次ID不能为空", "data": None}), 400

        # 提前获取批次数据用于构建历史记录输入
        pro_data = get_pro_batch(batch_id) or {}

        # ── P0-2 平台合规预校验（扫描 requirement 与各任务方案文案，block 级命中直接拒绝，不扣费）──
        _platform_key = normalize_platform(pro_data.get('platform', ''))
        _requirement = pro_data.get('requirement', '') or ''
        _blocks = []
        for _t in pro_data.get('tasks', []):
            _scheme = _t.get('scheme') or {}
            _copy = _scheme.get('copy') or {}
            _tags = _copy.get('tags') or []
            if not isinstance(_tags, list):
                _tags = []
            _text = ' '.join(filter(None, [
                _requirement,
                _copy.get('main_title', ''),
                _copy.get('sub_title', ''),
                ' '.join(str(x) for x in _tags),
            ]))
            if not _text.strip():
                continue
            _precheck = precheck_prompt(_platform_key, _t.get('image_type', ''), _text)
            _blocks.extend(_precheck['blocks'])
        if _blocks:
            return jsonify({
                "code": 4003,
                "message": "方案文案包含平台禁用元素，请修改后重试",
                "data": {"blocks": _blocks},
            }), 400

        # ── 灵感币扣费（在启动后台生图前扣减，避免欠费生图）──
        # BYOK：命中用户自备模型通道时不扣费（single/total 均为 0，跳过 deduct_coins）
        user_id = g.current_user['user_id']
        size = pro_data.get('size', '1024x1024')
        pro_tasks = pro_data.get('tasks', [])
        task_count = len(pro_tasks)
        if is_feature_byok(user_id, 'ai_product_image.pro_mode'):
            single_cost = 0
            total_cost = 0
        else:
            single_cost = calculate_image_cost('ai_product_image.pro_mode', size)
            total_cost = single_cost * task_count
        if total_cost > 0:
            try:
                deduct_coins(
                    user_id=user_id,
                    amount=total_cost,
                    feature_key='ai_product_image.pro_mode',
                    description=f'AI商品图-专业模式 生图 {task_count} 张',
                    related_batch_id=batch_id,
                )
                print(f"[专业模式扣费] 扣费成功 user_id={user_id} batch_id={batch_id} "
                      f"single_cost={single_cost} total_cost={total_cost} task_count={task_count}", flush=True)
            except FeaturePricingError as e:
                print(f"[专业模式扣费] 扣费失败 user_id={user_id} code={e.code} msg={e.message}", flush=True)
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            print(f"[专业模式扣费] 未定价或费用为0，跳过扣费降级处理: "
                  f"feature_key=ai_product_image.pro_mode, size={size}", flush=True)

        result = confirm_and_generate(
            batch_id=batch_id,
            task_store=_task_store,
            batch_store=_batch_store,
            user_id=user_id,
            history_input_data={
                'product_images': pro_data.get('product_images', []),
                'reference_image': pro_data.get('reference_image'),
                'requirement': pro_data.get('requirement', ''),
                'platform': pro_data.get('platform', ''),
                'region': pro_data.get('region', ''),
                'target_language': pro_data.get('target_language', ''),
                'size': pro_data.get('size', ''),
                'product_info': pro_data.get('product_info', {}),
                'image_tasks': pro_data.get('tasks', []),
            },
            history_config_snapshot=pro_data,
            prepaid_coins=total_cost,
        )

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result,
        })

    except GenerationError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        return jsonify({"code": 5001, "message": f"触发生图失败: {str(e)}", "data": None}), 500


@generation_bp.route('/generation/pro/batches/<batch_id>', methods=['GET'])
@token_required
def get_pro_batch_status(batch_id):
    """
    专业模式 - 查询批次任务状态（含提示词方案）

    Response:
    {
        "code": 0,
        "data": {
            "batch_id": "...",
            "locked": false,
            "tasks": [{task_id, image_type, prompt_scheme, scheme_status, ...}, ...]
        }
    }
    """
    context = get_pro_batch(batch_id)
    if not context:
        return jsonify({"code": 4004, "message": "批次不存在", "data": None}), 404

    tasks = context.get("tasks", [])

    # 若批次已锁定（生图中），从 task_store 合并生图结果到方案任务中
    if context.get("locked"):
        for t in tasks:
            tid = t.get("task_id")
            if tid and tid in _task_store:
                gen_task = _task_store[tid]
                gen_status = gen_task.get("status", "")
                # 合并 gen_status（包括 processing 状态）
                if not t.get("gen_status") or t.get("gen_status") == "pending":
                    t["gen_status"] = gen_status
                # 仅当生图有终态结果时才更新
                if gen_status in (TaskStatus.SUCCESS.value, TaskStatus.FAILED.value):
                    if not t.get("result_url") and gen_task.get("image_url"):
                        t["result_url"] = gen_task["image_url"]
                    if not t.get("error_message") and gen_task.get("error_msg"):
                        t["error_message"] = gen_task["error_msg"]
                    t["gen_status"] = gen_status

    # 浅拷贝任务列表，剥离 base64 数据 URI，避免响应过大导致 ERR_HTTP2_PROTOCOL_ERROR
    response_tasks = []
    for t in tasks:
        rt = dict(t)
        result_url = rt.get("result_url", "")
        if result_url and result_url.startswith("data:"):
            rt["has_image"] = True
            rt["result_url"] = ""
        response_tasks.append(rt)

    return jsonify({
        "code": 0,
        "message": "success",
        "data": {
            "batch_id": batch_id,
            "status": "locked" if context.get("locked") else "pending",
            "locked": context.get("locked", False),
            "product_info": context.get("product_info", {}),
            "tasks": response_tasks,
            "created_at": context.get("created_at", ""),
            "updated_at": context.get("updated_at", ""),
        },
    })