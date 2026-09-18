"""专业模式套图生成工作流

流程设计（遵循技术文档 2.4.3 节）：
1. AI 分析整合阶段（同步返回方案给用户）：
   validate → prepare_product_info → analyze_integrate
2. AI 对话优化阶段（独立 API，阻塞等待用户交互，不纳入工作流）
3. 图像生成阶段（用户确认后异步执行）：
   build_prompts → generate_images → finalize

状态管理：
- _pro_batch_store: batch_id -> 专业模式批次上下文（含任务状态/方案/对话历史）
  Task 7 迁移后为 Redis Hash 适配器（services/generation_store），原内存字典退役
"""
import uuid
import json
import time
import random
import asyncio
from typing import TypedDict, List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from models.generation_task import (
    ProductInfo, ImageType, TaskStatus, SchemeStatus,
    PromptScheme, ProTaskState, IMAGE_TYPE_LABEL_CN,
)
from services.generation_service import (
    analyze_product, call_image_edit_model, analyze_integrate_scheme,
    GenerationError,
)
from services.feature_pricing_service import (
    calculate_image_cost, refund_coins,
)
from services.history_service import save_history
from services.task_queue import (
    register_task, submit_task, set_progress, complete_task, fail_task,
)
from services.generation_store import get_task_store, get_pro_batch_store
from prompts.builder import PromptBuilder
from agents.pro_optimizer_agent import ProOptimizerAgent
from services import multilang_engine
from services import compliance_service
from services.style_lock import derive_style_lock


# ── 专业模式批次存储（Task 7 迁移：内存字典 → Redis Hash） ──
# batch_id -> {
#     "product_images": [...],
#     "reference_image": ...,
#     "reference_text": ...,
#     "platform": ...,
#     "region": ...,
#     "target_language": ...,
#     "size": ...,
#     "requirement": ...,
#     "product_info": {...},
#     "tasks": [ProTaskState.to_dict(), ...],
#     "locked": bool,
# }
_pro_batch_store = get_pro_batch_store()
# Agent 实例缓存：batch_id:task_id -> ProOptimizerAgent（运行时缓存，非任务状态）
_agent_cache: Dict[str, ProOptimizerAgent] = {}


def get_pro_batch(batch_id: str) -> Optional[dict]:
    """获取专业模式批次上下文"""
    return _pro_batch_store.get(batch_id)


def set_pro_batch(batch_id: str, context: dict) -> None:
    """设置/更新专业模式批次上下文"""
    _pro_batch_store[batch_id] = context


def delete_pro_batch(batch_id: str) -> bool:
    """删除专业模式批次"""
    if batch_id in _pro_batch_store:
        del _pro_batch_store[batch_id]
        return True
    return False


# ── 工具函数 ──

def _map_image_type(image_type_value: str) -> ImageType:
    """字符串转 ImageType 枚举"""
    try:
        return ImageType(image_type_value)
    except ValueError:
        return ImageType.OTHER


def _build_base_variables(
    product_info: dict,
    platform: str,
    region: str,
    target_language: str,
    size: str,
    requirement: str = "",
) -> Dict[str, str]:
    """构建提示词公共变量

    P0-1：platform/region/target_language 已有，引擎只补场景英文映射
    （scene_env）与站点语言变量（site/site_language），避免重复注入。
    """
    variables = {
        "product_name": product_info.get("product_name", "商品"),
        "target_audience": product_info.get("target_audience", ""),
        "selling_points": product_info.get("selling_points", "高品质"),
        "usage_scenario": product_info.get("usage_scenario", "日常使用"),
        "product_category": product_info.get("product_category", "通用"),
        "platform": platform,
        "region": region,
        "target_language": target_language,
        "size": size,
        "site": "",
        "site_language": "",
        "scene_env": "",
    }

    # P0-1 引擎融合：region 为受支持站点码时补充站点语言变量
    site = str(region or "").strip().upper()
    if site and site in multilang_engine.SUPPORTED_SITES:
        site_info = multilang_engine.resolve_site(site)
        variables["site"] = site_info["site"]
        variables["site_language"] = site_info["language"]

    # P0-1 场景英文映射（中文 usage_scenario → 英文环境描述）
    variables["scene_env"] = multilang_engine.map_scene_to_env(
        product_info.get("usage_scenario", "")
    )

    return variables


# ── 阶段一：AI 分析整合（同步）──

def run_pro_analyze_integrate(
    product_images: List[str],
    reference_image: Optional[str],
    reference_text: Optional[str],
    platform: str,
    region: str,
    target_language: str,
    size: str,
    requirement: str,
    image_tasks: List[Dict[str, Any]],
    product_info: Optional[Dict[str, Any]] = None,
    prompt_language: str = "en",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    执行 AI 分析整合：
    1. 校验输入
    2. 准备/补全商品信息（若未提供则调用多模态分析）
    3. 遍历任务，对提示词方案为空的任务调用 LLM 生成
    4. 创建批次上下文，返回方案列表

    Args:
        product_images: 商品图 Base64 列表
        reference_image: 参考图 Base64
        reference_text: 参考维度描述
        platform: 平台
        region: 国家/地区
        target_language: 目标语言
        size: 分辨率 "WxH"
        requirement: 整体生成要求
        image_tasks: 生图任务配置列表 [{task_id, image_type, prompt_scheme, aspect_ratio}]
        product_info: 商品信息（可选，为空则自动分析）
        user_id: 用户 ID（可选，BYOK：模型调用按用户自备通道号池依次尝试）

    Returns:
        {
            "batch_id": "...",
            "product_info": {...},
            "tasks": [ProTaskState.to_dict(), ...],
        }
    """
    # 1. 校验
    if not product_images:
        raise GenerationError(code=4001, message="请至少上传一张商品图片", http_status=400)
    if not image_tasks:
        raise GenerationError(code=4001, message="请至少配置一个生图任务", http_status=400)

    batch_id = f"pro-batch-{uuid.uuid4().hex[:8]}"

    # 2. 准备商品信息
    if product_info and product_info.get("product_name"):
        product_info_dict = product_info
    else:
        # 调用多模态分析补全
        first_image = product_images[0]
        try:
            info = analyze_product(first_image, user_id=user_id)
            product_info_dict = info.to_dict()
        except GenerationError:
            raise
        except Exception as e:
            raise GenerationError(
                code=5002,
                message=f"商品信息分析失败: {str(e)}",
                http_status=500,
            )

    # 3. 并行处理任务，为每个任务补全提示词方案
    def _process_single_task(task_cfg: Dict[str, Any]) -> ProTaskState:
        """处理单个任务（供并行执行），线程安全"""
        task_id = task_cfg.get("task_id") or f"task-{uuid.uuid4().hex[:8]}"
        task_name = task_cfg.get("task_name", "")
        image_type_value = task_cfg.get("image_type", "other")
        image_type = _map_image_type(image_type_value)
        aspect_ratio = task_cfg.get("aspect_ratio", "1:1")
        scheme_dict = task_cfg.get("prompt_scheme")

        pro_task = ProTaskState(
            task_id=task_id,
            image_type=image_type,
            image_type_label=IMAGE_TYPE_LABEL_CN.get(image_type, "其他"),
            aspect_ratio=aspect_ratio,
            prompt_scheme=PromptScheme.from_dict(scheme_dict),
            scheme_status=SchemeStatus.PENDING,
        )

        if pro_task.prompt_scheme.is_empty():
            pro_task.scheme_status = SchemeStatus.ANALYZING
            # 添加随机延迟，避免并发请求同时触发 LLM API 速率限制
            jitter = random.uniform(0, 2.0)
            time.sleep(jitter)
            try:
                generated = analyze_integrate_scheme(
                    image_type_value=image_type_value,
                    product_info_dict=product_info_dict,
                    platform=platform,
                    region=region,
                    target_language=target_language,
                    requirement=requirement,
                    prompt_language=prompt_language,
                    user_id=user_id,
                )
                pro_task.prompt_scheme = PromptScheme.from_dict(generated)
                pro_task.scheme_status = SchemeStatus.PENDING
                pro_task.scheme_versions.append({
                    "version": 1,
                    "scheme": generated,
                    "source": "ai_analyze",
                })
            except GenerationError as e:
                pro_task.scheme_status = SchemeStatus.FAILED
                pro_task.error_msg = e.message
            except Exception as e:
                pro_task.scheme_status = SchemeStatus.FAILED
                pro_task.error_msg = f"分析整合失败: {str(e)}"
        else:
            pro_task.scheme_versions.append({
                "version": 1,
                "scheme": scheme_dict,
                "source": "user_input",
            })
        return pro_task

    # 并行执行所有任务（最多 3 个并发，避免 LLM API 限流）
    max_workers = min(len(image_tasks), 3) or 1
    pro_tasks: List[ProTaskState] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_single_task, task_cfg): idx
            for idx, task_cfg in enumerate(image_tasks)
        }
        # 按原始顺序收集结果
        results: Dict[int, ProTaskState] = {}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                # 并行任务中的意外异常，创建失败状态
                task_cfg = image_tasks[idx]
                task_id = task_cfg.get("task_id") or f"task-{uuid.uuid4().hex[:8]}"
                fallback = ProTaskState(
                    task_id=task_id,
                    image_type=_map_image_type(task_cfg.get("image_type", "other")),
                    image_type_label=IMAGE_TYPE_LABEL_CN.get(
                        _map_image_type(task_cfg.get("image_type", "other")), "其他"
                    ),
                    aspect_ratio=task_cfg.get("aspect_ratio", "1:1"),
                    prompt_scheme=PromptScheme(),
                    scheme_status=SchemeStatus.FAILED,
                )
                fallback.error_msg = f"并行处理异常: {str(e)}"
                results[idx] = fallback
        # 按原始顺序排列
        for idx in sorted(results.keys()):
            pro_tasks.append(results[idx])

    # 4. 存储批次上下文
    context = {
        "product_images": product_images,
        "reference_image": reference_image,
        "reference_text": reference_text,
        "platform": platform,
        "region": region,
        "target_language": target_language,
        "size": size,
        "requirement": requirement,
        "product_info": product_info_dict,
        "tasks": [t.to_dict() for t in pro_tasks],
        "locked": False,
        "prompt_language": prompt_language,
        "user_id": user_id,
    }
    set_pro_batch(batch_id, context)

    return {
        "batch_id": batch_id,
        "product_info": product_info_dict,
        "tasks": [t.to_dict() for t in pro_tasks],
    }


# ── 阶段二：对话优化（使用 ProOptimizerAgent 进行记忆式多轮对话）──

def _get_or_create_optimizer_agent(
    batch_id: str, task_id: str, context: dict, target_task: dict
) -> ProOptimizerAgent:
    """获取或创建 Agent 实例（按 batch_id:task_id 缓存）"""
    cache_key = f"{batch_id}:{task_id}"
    if cache_key not in _agent_cache:
        _agent_cache[cache_key] = ProOptimizerAgent({
            "task_id": task_id,
            "image_type": target_task.get("image_type", "other"),
            "image_type_label": target_task.get("image_type_label", ""),
            "platform": context.get("platform", ""),
            "region": context.get("region", ""),
            "target_language": context.get("target_language", "英语"),
            "product_info": context.get("product_info", {}),
        })
    return _agent_cache[cache_key]


def apply_dialog_optimize(
    batch_id: str,
    task_id: str,
    user_input: str,
    dialog_history: List[Dict[str, str]],
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    对指定任务执行对话优化，使用 Agent 进行记忆式多轮对话

    Returns:
        {"task_id": ..., "scheme": {...}, "dialog_history": [...], "reply": "..."}
    """
    context = get_pro_batch(batch_id)
    if not context:
        raise GenerationError(code=4004, message="批次不存在或已过期", http_status=404)

    if context.get("locked"):
        raise GenerationError(code=4004, message="方案已锁定，无法修改", http_status=400)

    # BYOK：优先使用调用方传入的 user_id，缺失时回退到批次上下文
    user_id = user_id if user_id is not None else context.get("user_id")

    tasks = context.get("tasks", [])
    target_task = None
    for t in tasks:
        if t.get("task_id") == task_id:
            target_task = t
            break

    if not target_task:
        raise GenerationError(code=4004, message="任务不存在", http_status=404)

    current_scheme = target_task.get("scheme", {})

    target_task["status"] = SchemeStatus.OPTIMIZING.value

    try:
        agent = _get_or_create_optimizer_agent(batch_id, task_id, context, target_task)
        result = agent.optimize(
            current_scheme=current_scheme,
            user_input=user_input,
            dialog_history=dialog_history,
            user_id=user_id,
        )
    except GenerationError:
        target_task["status"] = SchemeStatus.PENDING.value
        raise
    except Exception as e:
        target_task["status"] = SchemeStatus.PENDING.value
        raise GenerationError(
            code=5003,
            message=f"对话优化失败: {str(e)}",
            http_status=500,
        )

    optimized_scheme = result["scheme"]
    ai_reply = result["reply"]

    # 更新方案
    target_task["scheme"] = optimized_scheme
    target_task["status"] = SchemeStatus.PENDING.value

    # 追加对话历史
    new_history = list(dialog_history)
    new_history.append({"role": "user", "content": user_input})
    new_history.append({"role": "assistant", "content": ai_reply})
    target_task["dialog_history"] = new_history

    # 保存版本快照
    version_num = len(target_task.get("version_snapshots", [])) + 1
    target_task.setdefault("version_snapshots", []).append({
        "version": version_num,
        "scheme": optimized_scheme,
        "source": "dialog_optimize",
    })

    set_pro_batch(batch_id, context)

    return {
        "task_id": task_id,
        "scheme": optimized_scheme,
        "reply": ai_reply,
        "dialog_history": new_history,
        "version": version_num,
    }


# ── 阶段三：确认方案 + 触发生图 ──

def confirm_and_generate(
    batch_id: str,
    task_store: dict,
    batch_store: dict,
    user_id: Optional[int] = None,
    history_input_data: Optional[Dict[str, Any]] = None,
    history_config_snapshot: Optional[Dict[str, Any]] = None,
    prepaid_coins: int = 0,
) -> Dict[str, Any]:
    """
    确认所有方案并触发生图工作流（异步）

    校验：
    - 所有任务方案非空
    - 批次未锁定

    执行：
    1. 锁定所有方案
    2. 构建生图提示词（build_from_scheme）
    3. 注册到 task_store / batch_store（供前端轮询）
    4. 后台线程并发生成图片

    Args:
        batch_id: 批次ID
        task_store: 内存任务存储
        batch_store: 内存批次存储
        user_id: 用户ID（用于保存历史记录）
        history_input_data: 历史记录输入数据
        history_config_snapshot: 历史记录配置快照
        prepaid_coins: 实际预扣灵感币，用于失败退款封顶；BYOK 命中时为 0（不退款）

    Returns:
        {"batch_id": ..., "tasks": [...]}
    """
    context = get_pro_batch(batch_id)
    if not context:
        raise GenerationError(code=4004, message="批次不存在或已过期", http_status=404)

    if context.get("locked"):
        raise GenerationError(code=4004, message="方案已锁定，无法重复触发生图", http_status=400)

    tasks_data = context.get("tasks", [])
    if not tasks_data:
        raise GenerationError(code=4001, message="批次无生图任务", http_status=400)

    # 校验是否有未确认的失败任务
    has_failed = any(
        t.get("status") == SchemeStatus.FAILED.value
        for t in tasks_data
    )
    if has_failed:
        raise GenerationError(
            code=4005,
            message="存在分析失败的任务，请重试或删除后再次确认",
            http_status=400,
        )

    # 锁定批次
    context["locked"] = True
    for t in tasks_data:
        t["status"] = SchemeStatus.LOCKED.value
        t["gen_status"] = TaskStatus.PENDING.value
    set_pro_batch(batch_id, context)

    # 注册到 task_store / batch_store（供前端轮询）
    task_ids = [t["task_id"] for t in tasks_data]
    for t in tasks_data:
        task_store[t["task_id"]] = {
            "task_id": t["task_id"],
            "batch_id": batch_id,
            "image_type": t["image_type"],
            "slot_index": 0,
            "slot_name": t.get("scheme", {}).get("image_name", ""),
            "slot_desc": t.get("scheme", {}).get("image_role", ""),
            "status": TaskStatus.PENDING.value,
            "prompt_used": "",
            "image_url": None,
            "error_msg": None,
        }
    batch_store[batch_id] = task_ids

    # Task 7 迁移：原后台线程 _run → ARQ 任务（执行体见 generation_pro_confirm_task）
    task_id = submit_task(
        PRO_CONFIRM_TASK_NAME,
        {
            'batch_id': batch_id,
            'task_ids': task_ids,
            'user_id': user_id,
            'history_input_data': history_input_data,
            'history_config_snapshot': history_config_snapshot,
            'prepaid_coins': prepaid_coins,
        },
        module='generation',
    )
    print(f"[专业模式] ARQ 任务已提交 batch_id={batch_id} task_id={task_id}", flush=True)

    return {"batch_id": batch_id, "tasks": [task_store[tid] for tid in task_ids]}


PRO_CONFIRM_TASK_NAME = 'generation_pro_confirm'


@register_task(PRO_CONFIRM_TASK_NAME)
async def generation_pro_confirm_task(ctx, payload: dict, task_id: str):
    """
    专业模式确认生图任务（ARQ）：执行体与原 confirm_and_generate 后台线程 _run
    完全一致（构建提示词 + ThreadPoolExecutor 并发生图）。
    task_store / 批次上下文均取 Redis 适配器单例，与 Flask 侧共享。
    """
    batch_id = payload['batch_id']
    task_ids = payload['task_ids']
    user_id = payload.get('user_id')
    history_input_data = payload.get('history_input_data') or {}
    history_config_snapshot = payload.get('history_config_snapshot')
    prepaid_coins = payload.get('prepaid_coins', 0)

    context = get_pro_batch(batch_id)
    if context is None:
        await fail_task(ctx, task_id, "批次上下文丢失")
        return

    task_store = get_task_store()

    def _try_refund_all_failed():
        """
        全部任务失败时退款（v1 策略：仅全部失败才退款，部分失败不退）
        退款失败仅记录日志，不影响主流程
        """
        try:
            failed_count = 0
            for tid in task_ids:
                if tid in task_store and task_store[tid].get("status") == TaskStatus.FAILED.value:
                    failed_count += 1
            # 仅当全部任务失败才退款
            if failed_count == 0 or failed_count != len(task_ids):
                return
            size = context.get("size", "1024x1024")
            single_cost = calculate_image_cost('ai_product_image.pro_mode', size)
            # 退款额以实际预扣金额封顶（BYOK 时 prepaid_coins=0，必然跳过退款）
            refund_amount = min(prepaid_coins, single_cost * failed_count)
            if refund_amount <= 0 or user_id is None:
                return
            refund_coins(
                user_id=user_id,
                amount=refund_amount,
                feature_key='ai_product_image.pro_mode',
                description=f'AI商品图-专业模式 生成失败退款 {failed_count} 张',
                related_batch_id=batch_id,
            )
            print(f"[专业模式] 全部失败退款成功 batch_id={batch_id} "
                  f"failed_count={failed_count} refund_amount={refund_amount}", flush=True)
        except Exception as refund_err:
            print(f"[专业模式] 退款失败（不影响主流程）: {refund_err}", flush=True)

    tasks_data = context.get("tasks", [])

    await set_progress(ctx, task_id, '正在生成专业模式套图...')

    def _run():
        print(f"[专业模式] ARQ 任务开始执行 batch_id={batch_id}, task_count={len(task_ids)}", flush=True)
        try:
            _execute_generation(batch_id, task_store, task_ids, user_id=user_id)

            # 全部失败 → 退款（检查实际任务状态）
            _try_refund_all_failed()

            # 保存历史记录（所有任务完成后，含 result_url）
            if user_id is not None:
                try:
                    final_tasks = []
                    for tid in task_ids:
                        if tid in task_store:
                            final_tasks.append(dict(task_store[tid]))
                    save_history(
                        user_id=user_id,
                        category='ai_product_image',
                        sub_category='pro_mode',
                        input_data=history_input_data,
                        output_data={'batch_id': batch_id, 'tasks': final_tasks},
                        config_snapshot=history_config_snapshot,
                    )
                    print(f"[专业模式] 历史记录已保存 batch_id={batch_id}", flush=True)
                except Exception as e:
                    print(f"[专业模式] 历史记录保存失败（不影响主流程）: {e}", flush=True)
        except Exception as e:
            import traceback
            print(f"[专业模式] 任务执行异常: {e}", flush=True)
            print(f"[专业模式] 异常堆栈: {traceback.format_exc()}", flush=True)
            for tid in task_ids:
                if tid in task_store:
                    task_store[tid]["status"] = TaskStatus.FAILED.value
                    task_store[tid]["error_msg"] = f"系统异常: {str(e)}"
                # 同步失败状态到 pro_batch_store，让前端轮询可见
                for t in tasks_data:
                    if t.get("task_id") == tid:
                        t["gen_status"] = TaskStatus.FAILED.value
                        t["error_message"] = f"系统异常: {str(e)}"
                        break
            set_pro_batch(batch_id, context)

            # 全部失败 → 退款
            _try_refund_all_failed()

            # 保存失败的历史记录
            if user_id is not None:
                try:
                    save_history(
                        user_id=user_id,
                        category='ai_product_image',
                        sub_category='pro_mode',
                        input_data=history_input_data,
                        output_data={'batch_id': batch_id, 'error': str(e)},
                        config_snapshot=history_config_snapshot,
                    )
                except Exception as e:
                    print(f"[专业模式] 历史记录保存失败(异常分支): {e}", flush=True)

    try:
        await asyncio.to_thread(_run)
        await set_progress(ctx, task_id, '处理完成', pct=100)
        await complete_task(ctx, task_id, {'batch_id': batch_id})
    except Exception as e:
        await fail_task(ctx, task_id, f"专业模式生图任务执行异常: {str(e)}")


def _execute_generation(
    batch_id: str,
    task_store: dict,
    task_ids: List[str],
    user_id: Optional[int] = None,
) -> None:
    """执行构建提示词 + 并发生成图片"""
    import sys
    print(f"[专业模式] _execute_generation 开始 batch_id={batch_id}", flush=True)
    sys.stderr.write(f"[专业模式] _execute_generation 开始 batch_id={batch_id}\n")
    sys.stderr.flush()

    context = get_pro_batch(batch_id)
    if not context:
        print(f"[专业模式] 错误：context 为 None batch_id={batch_id}", flush=True)
        sys.stderr.write(f"[专业模式] 错误：context 为 None batch_id={batch_id}\n")
        sys.stderr.flush()
        for tid in task_ids:
            if tid in task_store:
                task_store[tid]["status"] = TaskStatus.FAILED.value
                task_store[tid]["error_msg"] = "批次上下文丢失，请重新创建方案"
        return

    product_images = context.get("product_images", [])
    reference_image = context.get("reference_image")
    reference_text = context.get("reference_text")
    size = context.get("size", "1024x1024")
    platform = context.get("platform", "")
    region = context.get("region", "")
    target_language = context.get("target_language", "英语")
    product_info = context.get("product_info", {})
    requirement = context.get("requirement", "")
    tasks_data = context.get("tasks", [])

    # BYOK：优先使用调用方传入的 user_id，缺失时回退到批次上下文
    user_id = user_id if user_id is not None else context.get("user_id")

    print(f"[专业模式] 上下文获取成功 product_images={len(product_images)} tasks={len(tasks_data)} platform={platform}", flush=True)
    sys.stderr.write(f"[专业模式] 上下文获取成功 product_images={len(product_images)} tasks={len(tasks_data)}\n")
    sys.stderr.flush()

    base_variables = _build_base_variables(
        product_info, platform, region, target_language, size, requirement
    )

    # ── Task 7 Style Lock：批次确认生图路径派生一次（确定性），
    #    应用于本批次所有任务 prompt，保证同批次成图风格统一；
    #    requirement 作为用户风格提示（user_hint）参与派生 ──
    style_lock_text = derive_style_lock(
        product_info,
        product_info.get('usage_scenario'),
        platform=platform,
        user_hint=requirement,
    )

    prompt_language = context.get("prompt_language", "en")

    builder = PromptBuilder()
    product_image = product_images[0] if product_images else None

    if not product_image:
        print(f"[专业模式] 错误：product_images 为空，无法生成", flush=True)
        sys.stderr.write(f"[专业模式] 错误：product_images 为空\n")
        sys.stderr.flush()

    # 1. 构建每个任务的生图提示词
    build_results: List[Dict[str, Any]] = []
    for task_data in tasks_data:
        tid = task_data["task_id"]
        image_type = _map_image_type(task_data["image_type"])
        scheme = PromptScheme.from_dict(task_data.get("scheme"))

        try:
            prompt = builder.build_from_scheme(image_type, scheme, base_variables, prompt_language)
            # P0-1：引擎约束增强（主图白底无文字 / 其他图型文字语言约束，幂等追加）
            constraint = multilang_engine.site_constraints_if_supported(
                region, image_type.value
            )
            prompt = multilang_engine.append_constraint(prompt, constraint)
            # P0-2：平台合规约束注入（主图白底/占比，与引擎约束去重，幂等）
            try:
                prompt = compliance_service.apply_platform_constraints(
                    platform, image_type.value, prompt
                )
            except Exception as e:
                print(f"[平台合规] 约束注入失败（忽略）: {e}", flush=True)
            # Task 7 Style Lock：本批次统一风格锁定文本前置（幂等，已含则不重复）
            if style_lock_text and 'STYLE LOCK: ' not in prompt:
                prompt = f'{style_lock_text} {prompt}'
            build_results.append({
                "task_id": tid,
                "prompt": prompt,
                "image_type": image_type,
                "error": None,
            })
            print(f"[专业模式] 构建提示词 task_id={tid} type={image_type.value} len={len(prompt)}", flush=True)
        except Exception as e:
            build_results.append({
                "task_id": tid,
                "prompt": "",
                "image_type": image_type,
                "error": f"提示词构建失败: {str(e)}",
            })
            print(f"[专业模式] 构建提示词失败 task_id={tid}: {e}", flush=True)

    # 2. 并发生成图片
    def _sync_pro_batch_task(tid: str, updates: Dict[str, Any]) -> None:
        """同步更新专业模式批次上下文中的任务状态（供前端轮询）"""
        for t in tasks_data:
            if t.get("task_id") == tid:
                t.update(updates)
                break
        # Task 7 迁移：批次上下文存 Redis，原地更新后需显式持久化
        set_pro_batch(batch_id, context)

    def _generate_single(item: Dict[str, Any]) -> None:
        tid = item["task_id"]
        prompt = item["prompt"]
        error = item["error"]

        if error:
            if tid in task_store:
                task_store[tid]["status"] = TaskStatus.FAILED.value
                task_store[tid]["error_msg"] = error
            _sync_pro_batch_task(tid, {
                "gen_status": TaskStatus.FAILED.value,
                "error_message": error,
            })
            return

        if not product_image:
            if tid in task_store:
                task_store[tid]["status"] = TaskStatus.FAILED.value
                task_store[tid]["error_msg"] = "缺少商品图，无法生成"
            _sync_pro_batch_task(tid, {
                "gen_status": TaskStatus.FAILED.value,
                "error_message": "缺少商品图，无法生成",
            })
            return

        # 更新为处理中
        if tid in task_store:
            task_store[tid]["status"] = TaskStatus.PROCESSING.value
            task_store[tid]["prompt_used"] = prompt
        _sync_pro_batch_task(tid, {
            "gen_status": TaskStatus.PROCESSING.value,
            "prompt_used": prompt,
        })

        try:
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
            if tid in task_store:
                if url:
                    task_store[tid]["image_url"] = url
                elif b64:
                    task_store[tid]["image_url"] = f"data:image/png;base64,{b64}"
                task_store[tid]["status"] = TaskStatus.SUCCESS.value
                task_store[tid]["error_msg"] = None
            _sync_pro_batch_task(tid, {
                "gen_status": TaskStatus.SUCCESS.value,
                "result_url": url or (f"data:image/png;base64,{b64}" if b64 else None),
                "error_message": None,
            })
            print(f"[专业模式] 单图生成完成 task_id={tid}", flush=True)
        except GenerationError as e:
            if tid in task_store:
                task_store[tid]["status"] = TaskStatus.FAILED.value
                task_store[tid]["error_msg"] = e.message
            _sync_pro_batch_task(tid, {
                "gen_status": TaskStatus.FAILED.value,
                "error_message": e.message,
            })
        except Exception as e:
            if tid in task_store:
                task_store[tid]["status"] = TaskStatus.FAILED.value
                task_store[tid]["error_msg"] = str(e)
            _sync_pro_batch_task(tid, {
                "gen_status": TaskStatus.FAILED.value,
                "error_message": str(e),
            })

    max_workers = min(len(build_results), 5) or 1
    print(f"[专业模式] 开始并发生成 {len(build_results)} 张图片 (max_workers={max_workers})", flush=True)
    sys.stderr.write(f"[专业模式] 开始并发生成 {len(build_results)} 张图片 (max_workers={max_workers})\n")
    sys.stderr.flush()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_generate_single, item): item for item in build_results}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"[专业模式] 并发生成异常: {e}", flush=True)
                sys.stderr.write(f"[专业模式] 并发生成异常: {e}\n")
                sys.stderr.flush()

    print(f"[专业模式] 并发生成完毕 batch_id={batch_id}", flush=True)
    sys.stderr.write(f"[专业模式] 并发生成完毕 batch_id={batch_id}\n")
    sys.stderr.flush()


# ── 任务状态查询 ──

def get_pro_batch_tasks(batch_id: str) -> Optional[List[Dict[str, Any]]]:
    """获取专业模式批次的任务列表（含方案/状态）"""
    context = get_pro_batch(batch_id)
    if not context:
        return None
    return context.get("tasks", [])


def update_pro_task_scheme(
    batch_id: str,
    task_id: str,
    scheme: dict,
) -> Optional[dict]:
    """更新指定任务的提示词方案（用户手动编辑）"""
    context = get_pro_batch(batch_id)
    if not context:
        return None
    if context.get("locked"):
        raise GenerationError(code=4004, message="方案已锁定，无法修改", http_status=400)

    for t in context.get("tasks", []):
        if t.get("task_id") == task_id:
            t["scheme"] = scheme
            t["status"] = SchemeStatus.PENDING.value
            version_num = len(t.get("version_snapshots", [])) + 1
            t.setdefault("version_snapshots", []).append({
                "version": version_num,
                "scheme": scheme,
                "source": "manual_edit",
            })
            set_pro_batch(batch_id, context)
            return t
    return None


# ── 一键AI补全空方案 ──

def auto_fill_empty_schemes(batch_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    为批次中所有空方案/失败方案的任务重新调用 LLM 生成方案

    Args:
        batch_id: 批次 ID
        user_id: 用户 ID（可选，BYOK：模型调用按用户自备通道号池依次尝试）

    Returns:
        {"batch_id": ..., "tasks": [...], "filled_count": int}
    """
    context = get_pro_batch(batch_id)
    if not context:
        raise GenerationError(code=4004, message="批次不存在或已过期", http_status=404)

    if context.get("locked"):
        raise GenerationError(code=4004, message="方案已锁定，无法修改", http_status=400)

    product_info_dict = context.get("product_info", {})
    platform = context.get("platform", "")
    region = context.get("region", "")
    target_language = context.get("target_language", "英语")
    requirement = context.get("requirement", "")
    prompt_language = context.get("prompt_language", "en")

    # BYOK：优先使用调用方传入的 user_id，缺失时回退到批次上下文
    user_id = user_id if user_id is not None else context.get("user_id")

    tasks = context.get("tasks", [])
    filled_count = 0

    for task in tasks:
        scheme = task.get("scheme", {})
        ps = PromptScheme.from_dict(scheme)

        if not ps.is_empty() and task.get("status") != SchemeStatus.FAILED.value:
            continue

        image_type_value = task.get("image_type", "other")
        task["status"] = SchemeStatus.ANALYZING.value

        try:
            generated = analyze_integrate_scheme(
                image_type_value=image_type_value,
                product_info_dict=product_info_dict,
                platform=platform,
                region=region,
                target_language=target_language,
                requirement=requirement,
                prompt_language=prompt_language,
                user_id=user_id,
            )
            task["scheme"] = generated
            task["status"] = SchemeStatus.PENDING.value
            task["error_message"] = None

            version_num = len(task.get("version_snapshots", [])) + 1
            task.setdefault("version_snapshots", []).append({
                "version": version_num,
                "scheme": generated,
                "source": "auto_fill",
            })
            filled_count += 1
        except Exception as e:
            task["status"] = SchemeStatus.FAILED.value
            task["error_message"] = f"自动补全失败: {str(e)}"

    set_pro_batch(batch_id, context)

    return {
        "batch_id": batch_id,
        "tasks": tasks,
        "filled_count": filled_count,
    }
