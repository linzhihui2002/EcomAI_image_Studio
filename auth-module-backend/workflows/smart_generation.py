"""简单模式智能套图生成 LangGraph 工作流"""
import asyncio
import uuid
import json
from typing import TypedDict, List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from langgraph.graph import StateGraph, END

from config import AIConfig
from models.generation_task import (
    ProductInfo, GenerationTask, ImageType, TaskStatus
)
from services.generation_service import (
    analyze_product, call_image_edit_model, GenerationError
)
from services.feature_pricing_service import (
    calculate_image_cost, refund_coins,
)
from services.history_service import save_history
from services.task_queue import (
    register_task, submit_task, set_progress, complete_task, fail_task,
)
from services.generation_store import get_task_store
from prompts.builder import PromptBuilder
from services import multilang_engine
from services import compliance_service


# ── State 定义 ──

class SmartGenerationState(TypedDict):
    """工作流状态"""
    # 输入
    product_images: List[str]           # 商品图 Base64 列表
    reference_image: Optional[str]      # 参考图 Base64（风格参考，非编辑主图）
    reference_text: Optional[str]       # 参考维度描述（可选，留空默认参考风格）
    platform: str
    region: str
    target_language: str
    site: Optional[str]                 # 站点码（P0-1 可选，缺省行为不变）
    scene: Optional[str]                # 中文场景（P0-1 可选，用于环境映射）
    size: str                           # "widthxheight" 格式
    product_info_json: Optional[str]    # 用户填写的商品信息 JSON 字符串
    image_groups: List[Dict[str, Any]]  # 套图结构配置
    user_id: Optional[int]              # 用户 ID（BYOK：模型调用按用户自备通道号池依次尝试）

    # 中间结果
    product_info: Optional[ProductInfo]  # 商品信息
    tasks: List[GenerationTask]          # 所有生成任务
    prompt_variables: Dict[str, str]     # 提示词公共变量

    # 输出
    batch_id: str
    error: Optional[str]

    # 实时更新用：节点内直接写入 _task_store，前端轮询实时看到结果
    task_store_ref: Optional[dict]       # _task_store 的引用
    task_id_mapping: List[str]           # 工作流位置 → 原始 task_id 映射


# ── 节点函数 ──

def validate_inputs(state: SmartGenerationState) -> SmartGenerationState:
    """校验输入参数"""
    if not state.get("product_images") or len(state["product_images"]) == 0:
        state["error"] = "请至少上传一张商品图片"
        return state

    # 统计总图片数量
    total_slots = 0
    for group in state.get("image_groups", []):
        total_slots += len(group.get("slots", []))

    if total_slots == 0:
        state["error"] = "请至少配置一种图片类型"
        return state

    if not state.get("batch_id"):
        state["batch_id"] = f"batch-{uuid.uuid4().hex[:8]}"
    return state


def prepare_product_info(state: SmartGenerationState) -> SmartGenerationState:
    """确认/补全商品信息"""
    # 尝试从 JSON 字符串解析已有商品信息
    product_info = None
    existing_text = None

    if state.get("product_info_json"):
        try:
            data = json.loads(state["product_info_json"])
            product_info = ProductInfo(
                product_name=data.get("product_name", ""),
                target_audience=data.get("target_audience", ""),
                selling_points=data.get("selling_points", ""),
                usage_scenario=data.get("usage_scenario", ""),
                product_category=data.get("product_category", ""),
            )
            if product_info.is_complete():
                state["product_info"] = product_info
                state["prompt_variables"] = _build_prompt_variables(product_info, state)
                return state
            # 部分信息 → 作为已有文本传入分析
            existing_text = json.dumps(data, ensure_ascii=False)
        except json.JSONDecodeError:
            product_info = None

    # 商品信息为空或不完整 → 调用多模态分析
    # 使用第一张商品图进行分析
    first_image = state["product_images"][0]
    try:
        product_info = analyze_product(first_image, existing_text, user_id=state.get("user_id"))
        state["product_info"] = product_info
        state["prompt_variables"] = _build_prompt_variables(product_info, state)
    except GenerationError as e:
        state["error"] = e.message
        return state
    except Exception as e:
        state["error"] = f"商品信息分析失败: {str(e)}"
        return state

    return state


def _build_prompt_variables(product_info: ProductInfo, state: SmartGenerationState) -> Dict[str, str]:
    """构建提示词公共变量（含品类/平台/地区等结构化构建所需字段）

    P0-1：site 可选透传（缺省行为不变）；site 存在时融合引擎变量
    （site/site_language/scene_env/文字语言约束），供模板与约束增强使用。
    """
    variables = {
        "product_name": product_info.product_name or "商品",
        "target_audience": product_info.target_audience or "大众消费者",
        "selling_points": product_info.selling_points or "高品质",
        "usage_scenario": product_info.usage_scenario or "日常使用",
        "product_category": product_info.product_category or "通用",
        "platform": state.get("platform", "Amazon"),
        "region": state.get("region", "US"),
        "target_language": state.get("target_language", "English"),
        "size": state.get("size", "1024x1024"),
        "site": "",
        "site_language": "",
        "scene_env": "",
    }

    # P0-1 引擎变量融合（site 缺省或非法时保持空值，不改变既有行为）
    site = str(state.get("site") or "").strip().upper()
    if site and site in multilang_engine.SUPPORTED_SITES:
        site_info = multilang_engine.resolve_site(site)
        variables["site"] = site_info["site"]
        variables["site_language"] = site_info["language"]

    scene_zh = str(state.get("scene") or "").strip()
    if scene_zh:
        variables["scene_env"] = multilang_engine.map_scene_to_env(scene_zh)
    elif product_info.usage_scenario:
        variables["scene_env"] = multilang_engine.map_scene_to_env(
            product_info.usage_scenario
        )

    return variables


def _apply_site_constraints(prompt: str, site: str, image_type: ImageType) -> str:
    """P0-1：site 存在且受支持时用引擎约束增强最终 prompt（幂等追加）"""
    site = str(site or "").strip().upper()
    if not site:
        return prompt
    try:
        constraint = multilang_engine.site_constraints_if_supported(site, image_type.value)
        return multilang_engine.append_constraint(prompt, constraint)
    except Exception as e:
        # 约束增强失败不阻断主流程
        print(f"[多语言引擎] 约束追加失败（忽略）: {e}", flush=True)
        return prompt


def build_prompts(state: SmartGenerationState) -> SmartGenerationState:
    """为每种图片类型构造专用提示词"""
    builder = PromptBuilder()
    variables = state.get("prompt_variables", {})
    batch_id = state["batch_id"]
    tasks: List[GenerationTask] = []

    image_groups = state.get("image_groups", [])

    for group in image_groups:
        group_key = group.get("key", "")
        image_type = _map_group_key_to_image_type(group_key)
        if image_type is None:
            continue

        slots = group.get("slots", [])
        for idx, slot in enumerate(slots):
            task = GenerationTask(
                batch_id=batch_id,
                image_type=image_type,
                slot_index=idx,
                slot_name=slot.get("name", "") if isinstance(slot, dict) else "",
                slot_desc=slot.get("desc", "") if isinstance(slot, dict) else "",
            )

            # 构造提示词
            extra_context = {}
            if image_type == ImageType.OTHER:
                extra_context = {
                    "slot_name": task.slot_name or "custom graphic",
                    "slot_desc": task.slot_desc or "product showcase",
                }

            try:
                prompt = builder.build_structured(image_type, variables, extra_context)
                # P0-1：site 存在时用引擎约束增强最终 prompt（白底无文字/文字语言约束）
                prompt = _apply_site_constraints(prompt, state.get("site", ""), image_type)
                # P0-2：平台合规约束注入（主图白底/占比，与引擎约束去重，幂等）
                try:
                    prompt = compliance_service.apply_platform_constraints(
                        state.get("platform", ""), image_type.value, prompt
                    )
                except Exception as e:
                    print(f"[平台合规] 约束注入失败（忽略）: {e}", flush=True)
                task.prompt_used = prompt
                print(f"[构建提示词] type={image_type.value} slot={idx} prompt_len={len(task.prompt_used)}", flush=True)
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_msg = f"提示词构建失败: {str(e)}"

            tasks.append(task)

    state["tasks"] = tasks
    return state


def _map_group_key_to_image_type(key: str) -> Optional[ImageType]:
    """将前端 group key 映射为 ImageType 枚举"""
    mapping = {
        "white": ImageType.WHITE_BG,
        "scene": ImageType.SCENE,
        "selling": ImageType.SELLING_POINT,
        "other": ImageType.OTHER,
    }
    return mapping.get(key)


def generate_images(state: SmartGenerationState) -> SmartGenerationState:
    """并发调用图像编辑模型生成所有图片，每完成一张立即更新 task_store"""
    tasks: List[GenerationTask] = state.get("tasks", [])
    size = state.get("size", "1024x1024")
    product_images = state.get("product_images", [])
    reference_image = state.get("reference_image")
    reference_text = state.get("reference_text")
    user_id = state.get("user_id")

    # 实时更新所需引用
    task_store = state.get("task_store_ref")
    task_id_mapping = state.get("task_id_mapping", [])
    batch_id = state.get("batch_id", "")

    # 商品图始终作为编辑主图（取第一张）
    product_image = product_images[0] if product_images else None

    def _generate_single(task: GenerationTask) -> GenerationTask:
        if task.status == TaskStatus.FAILED:
            return task

        if not product_image:
            task.status = TaskStatus.FAILED
            task.error_msg = "缺少商品图，无法生成"
            return task

        task.status = TaskStatus.PROCESSING
        try:
            result = call_image_edit_model(
                product_image=product_image,
                prompt=task.prompt_used,
                size=size,
                reference_image=reference_image,
                reference_text=reference_text,
                user_id=user_id,
            )
            url = result.get("url")
            b64 = result.get("b64_json")
            if url:
                task.image_url = url
            elif b64:
                # b64_json 需要加上 data URI 前缀，前端才能直接渲染
                task.image_url = f"data:image/png;base64,{b64}"
            task.status = TaskStatus.SUCCESS
            print(f"[异步生图] 单图生成完成: status={task.status.value} image_url={'有' if task.image_url else '无'}", flush=True)
        except GenerationError as e:
            task.status = TaskStatus.FAILED
            task.error_msg = e.message
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_msg = str(e)
        return task

    # 使用线程池并发执行
    max_workers = min(len(tasks), 5)  # 最多5个并发
    print(f"[异步生图] 开始并发生成 {len(tasks)} 张图片 (max_workers={max_workers})...", flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_generate_single, t): i for i, t in enumerate(tasks)}
        results = [None] * len(tasks)
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                tasks[idx].status = TaskStatus.FAILED
                tasks[idx].error_msg = str(e)
                results[idx] = tasks[idx]

            # 每完成一张图片，立即更新 task_store，前端轮询实时看到结果
            if task_store is not None and idx < len(task_id_mapping):
                tid = task_id_mapping[idx]
                task_dict = tasks[idx].to_dict()
                task_dict["task_id"] = tid
                task_dict["batch_id"] = batch_id
                task_store[tid] = task_dict
                print(f"[异步生图] 实时更新 task_store[{idx}] id={tid} status={task_dict['status']}", flush=True)

    state["tasks"] = [r for r in results if r is not None]
    return state


def finalize(state: SmartGenerationState) -> SmartGenerationState:
    """汇总结果"""
    # 结果已经在 tasks 中，无需额外处理
    return state


# ── 条件路由 ──

def should_continue(state: SmartGenerationState) -> str:
    """判断是否有错误，决定是否继续"""
    if state.get("error"):
        return END
    return "prepare_product_info"


def should_generate(state: SmartGenerationState) -> str:
    """判断是否进入生图阶段"""
    if state.get("error"):
        return END
    return "build_prompts"


def should_finalize(state: SmartGenerationState) -> str:
    if state.get("error"):
        return END
    return "finalize"


# ── 构建工作流图 ──

def create_smart_generation_graph() -> StateGraph:
    """创建简单模式套图生成工作流"""
    workflow = StateGraph(SmartGenerationState)

    # 添加节点
    workflow.add_node("validate_inputs", validate_inputs)
    workflow.add_node("prepare_product_info", prepare_product_info)
    workflow.add_node("build_prompts", build_prompts)
    workflow.add_node("generate_images", generate_images)
    workflow.add_node("finalize", finalize)

    # 设置入口
    workflow.set_entry_point("validate_inputs")

    # 添加边：validate → prepare_info → build_prompts → generate_images → finalize → END
    workflow.add_conditional_edges("validate_inputs", should_continue, {
        "prepare_product_info": "prepare_product_info",
        END: END,
    })
    workflow.add_conditional_edges("prepare_product_info", should_generate, {
        "build_prompts": "build_prompts",
        END: END,
    })
    workflow.add_edge("build_prompts", "generate_images")
    workflow.add_conditional_edges("generate_images", should_finalize, {
        "finalize": "finalize",
        END: END,
    })
    workflow.add_edge("finalize", END)

    return workflow.compile()


# 全局编译好的工作流实例
smart_generation_graph = create_smart_generation_graph()


def _build_initial_tasks(batch_id: str, image_groups: List[Dict[str, Any]]) -> List[GenerationTask]:
    """根据套图配置构建初始任务列表（状态均为 PENDING，prompt 待工作流填充）"""
    tasks: List[GenerationTask] = []
    for group in image_groups:
        group_key = group.get("key", "")
        image_type = _map_group_key_to_image_type(group_key)
        if image_type is None:
            continue
        slots = group.get("slots", [])
        for idx, slot in enumerate(slots):
            task = GenerationTask(
                batch_id=batch_id,
                image_type=image_type,
                slot_index=idx,
                slot_name=slot.get("name", "") if isinstance(slot, dict) else "",
                slot_desc=slot.get("desc", "") if isinstance(slot, dict) else "",
            )
            tasks.append(task)
    return tasks


def run_smart_generation_async(
    product_images: List[str],
    platform: str,
    region: str,
    target_language: str,
    size: str,
    image_groups: List[Dict[str, Any]],
    product_info_json: Optional[str] = None,
    reference_image: Optional[str] = None,
    reference_text: Optional[str] = None,
    task_store: Optional[dict] = None,
    batch_store: Optional[dict] = None,
    user_id: Optional[int] = None,
    history_input_data: Optional[Dict[str, Any]] = None,
    history_config_snapshot: Optional[Dict[str, Any]] = None,
    batch_id: Optional[str] = None,
    site: Optional[str] = None,
    scene: Optional[str] = None,
    prepaid_coins: int = 0,
) -> Dict[str, Any]:
    """
    异步执行简单模式套图生成工作流
    立即返回 batch_id 和初始任务列表，实际生成在后台线程中进行

    Args:
        product_images: 商品图 Base64 列表
        platform: 平台
        region: 国家/地区
        target_language: 目标语言
        size: 图片尺寸 "WxH"
        image_groups: 套图结构配置
        product_info_json: 商品信息 JSON 字符串（可选）
        reference_image: 参考图 Base64（可选，风格参考）
        reference_text: 参考维度描述（可选）
        task_store: 内存任务存储 dict（task_id → task_dict）
        batch_store: 内存批次存储 dict（batch_id → [task_id, ...]）
        user_id: 用户ID（用于保存历史记录）
        history_input_data: 历史记录输入数据
        history_config_snapshot: 历史记录配置快照
        batch_id: 预生成的批次 ID（可选，用于扣费关联；未传则内部生成）
        prepaid_coins: 实际预扣灵感币，用于失败退款封顶；BYOK 命中时为 0（不退款）

    Returns:
        {"batch_id": "...", "tasks": [...]}
    """
    batch_id = batch_id or f"batch-{uuid.uuid4().hex[:8]}"
    initial_tasks = _build_initial_tasks(batch_id, image_groups)

    # 注册到存储（初始状态均为 pending；Task 7 迁移后为 Redis Hash 适配器）
    tasks_data = [t.to_dict() for t in initial_tasks]
    task_ids = [t.task_id for t in initial_tasks]
    if task_store is not None:
        for t in tasks_data:
            task_store[t["task_id"]] = t
    if batch_store is not None:
        batch_store[batch_id] = task_ids

    # Task 7 迁移：原后台线程 _run → ARQ 任务（执行体见 generation_smart_task）
    submit_task(
        SMART_GENERATION_TASK_NAME,
        {
            'product_images': product_images,
            'reference_image': reference_image,
            'reference_text': reference_text,
            'platform': platform,
            'region': region,
            'target_language': target_language,
            'size': size,
            'product_info_json': product_info_json,
            'image_groups': image_groups,
            'batch_id': batch_id,
            'task_ids': task_ids,
            'user_id': user_id,
            'history_input_data': history_input_data,
            'history_config_snapshot': history_config_snapshot,
            'site': site,
            'scene': scene,
            'prepaid_coins': prepaid_coins,
        },
        module='generation',
    )

    print(f"[异步生图] ARQ 任务已提交 batch_id={batch_id}", flush=True)

    return {"batch_id": batch_id, "tasks": tasks_data}


SMART_GENERATION_TASK_NAME = 'generation_smart'


@register_task(SMART_GENERATION_TASK_NAME)
async def generation_smart_task(ctx, payload: dict, task_id: str):
    """
    简单模式套图生成任务（ARQ）：执行体与原 run_smart_generation_async 内的
    后台线程 _run 完全一致（LangGraph 工作流调用保持原样，经 to_thread 执行，
    工作流内的 ThreadPoolExecutor 并发生图不受影响）。
    task_store 取 Redis 适配器单例（与 Flask 侧共享同一批 generation:tasks 数据）。
    """
    product_images = payload['product_images']
    reference_image = payload.get('reference_image')
    reference_text = payload.get('reference_text')
    platform = payload['platform']
    region = payload['region']
    target_language = payload['target_language']
    size = payload['size']
    product_info_json = payload.get('product_info_json')
    image_groups = payload['image_groups']
    batch_id = payload['batch_id']
    task_ids = payload['task_ids']
    user_id = payload.get('user_id')
    history_input_data = payload.get('history_input_data') or {}
    history_config_snapshot = payload.get('history_config_snapshot')
    site = payload.get('site')
    scene = payload.get('scene')
    prepaid_coins = payload.get('prepaid_coins', 0)

    task_store = get_task_store()

    await set_progress(ctx, task_id, '正在生成套图...')

    def _run():
        print(f"[异步生图] ARQ 任务开始执行 batch_id={batch_id}, task_count={len(task_ids)}", flush=True)
        initial_state: SmartGenerationState = {
            "product_images": product_images,
            "reference_image": reference_image,
            "reference_text": reference_text,
            "platform": platform,
            "region": region,
            "target_language": target_language,
            "site": site,
            "scene": scene,
            "size": size,
            "product_info_json": product_info_json,
            "image_groups": image_groups,
            "user_id": user_id,
            "product_info": None,
            "tasks": [],
            "prompt_variables": {},
            "batch_id": batch_id,
            "error": None,
            "task_store_ref": task_store,
            "task_id_mapping": task_ids,
        }

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
                single_cost = calculate_image_cost('ai_product_image.smart_mode', size)
                # 退款额以实际预扣金额封顶（BYOK 时 prepaid_coins=0，必然跳过退款）
                refund_amount = min(prepaid_coins, single_cost * failed_count)
                if refund_amount <= 0 or user_id is None:
                    return
                refund_coins(
                    user_id=user_id,
                    amount=refund_amount,
                    feature_key='ai_product_image.smart_mode',
                    description=f'AI商品图-简单模式 生成失败退款 {failed_count} 张',
                    related_batch_id=batch_id,
                )
                print(f"[异步生图] 全部失败退款成功 batch_id={batch_id} "
                      f"failed_count={failed_count} refund_amount={refund_amount}", flush=True)
            except Exception as refund_err:
                print(f"[异步生图] 退款失败（不影响主流程）: {refund_err}", flush=True)

        try:
            print(f"[异步生图] 开始执行工作流...", flush=True)
            result = smart_generation_graph.invoke(initial_state)
            print(f"[异步生图] 工作流执行完毕, tasks_count={len(result.get('tasks', []))}, error={result.get('error')}", flush=True)

            # 处理工作流返回的错误状态（非异常，而是 state.error 被设置）
            if result.get("error"):
                print(f"[异步生图] 工作流返回错误: {result['error']}", flush=True)
                for tid in task_ids:
                    if tid in task_store:
                        task_store[tid]["status"] = "failed"
                        task_store[tid]["error_msg"] = f"工作流错误: {result['error']}"

                # 全部失败 → 退款
                _try_refund_all_failed()

                # 保存失败的历史记录
                if user_id is not None:
                    try:
                        save_history(
                            user_id=user_id,
                            category='ai_product_image',
                            sub_category='smart_mode',
                            input_data=history_input_data,
                            output_data={'batch_id': batch_id, 'error': result['error']},
                            config_snapshot=history_config_snapshot,
                        )
                    except Exception as e:
                        print(f"[异步生图] 历史记录保存失败(错误分支): {e}", flush=True)
                return

            # 兜底：确保 task_store 中所有任务状态已更新（正常情况下 generate_images 节点已实时更新）
            workflow_tasks = result.get("tasks", [])
            print(f"[异步生图] 兜底更新 task_store, workflow_tasks={len(workflow_tasks)}, task_ids={len(task_ids)}", flush=True)
            for i, task in enumerate(workflow_tasks):
                if i < len(task_ids):
                    task_dict = task.to_dict()
                    task_dict["task_id"] = task_ids[i]
                    task_dict["batch_id"] = batch_id
                    task_store[task_ids[i]] = task_dict
                    print(f"[异步生图] 兜底更新 task[{i}] id={task_ids[i]} status={task_dict['status']} image_url={'有' if task_dict.get('image_url') else '无'}", flush=True)
            print(f"[异步生图] 兜底更新完毕", flush=True)

            # 全部失败 → 退款（检查实际任务状态）
            _try_refund_all_failed()

            # 保存历史记录（所有任务完成后，含 image_url）
            if user_id is not None:
                try:
                    final_tasks = []
                    for tid in task_ids:
                        if tid in task_store:
                            final_tasks.append(dict(task_store[tid]))
                    save_history(
                        user_id=user_id,
                        category='ai_product_image',
                        sub_category='smart_mode',
                        input_data=history_input_data,
                        output_data={'batch_id': batch_id, 'tasks': final_tasks},
                        config_snapshot=history_config_snapshot,
                    )
                    print(f"[异步生图] 历史记录已保存 batch_id={batch_id}", flush=True)
                except Exception as e:
                    print(f"[异步生图] 历史记录保存失败（不影响主流程）: {e}", flush=True)

        except Exception as e:
            import traceback
            print(f"[异步生图] 工作流异常: {e}", flush=True)
            print(f"[异步生图] 异常堆栈: {traceback.format_exc()}", flush=True)
            # 将所有任务标记为失败
            for tid in task_ids:
                if tid in task_store:
                    task_store[tid]["status"] = "failed"
                    task_store[tid]["error_msg"] = f"系统异常: {str(e)}"

            # 全部失败 → 退款
            _try_refund_all_failed()

            # 保存失败的历史记录
            if user_id is not None:
                try:
                    save_history(
                        user_id=user_id,
                        category='ai_product_image',
                        sub_category='smart_mode',
                        input_data=history_input_data,
                        output_data={'batch_id': batch_id, 'error': str(e)},
                        config_snapshot=history_config_snapshot,
                    )
                except Exception as e:
                    print(f"[异步生图] 历史记录保存失败(异常分支): {e}", flush=True)

    try:
        await asyncio.to_thread(_run)
        await set_progress(ctx, task_id, '处理完成', pct=100)
        await complete_task(ctx, task_id, {'batch_id': batch_id})
    except Exception as e:
        # to_thread 内部已兜底处理业务异常，这里防御记录执行层异常
        await fail_task(ctx, task_id, f"套图生成任务执行异常: {str(e)}")


def run_smart_generation(
    product_images: List[str],
    platform: str,
    region: str,
    target_language: str,
    size: str,
    image_groups: List[Dict[str, Any]],
    product_info_json: Optional[str] = None,
    reference_image: Optional[str] = None,
    reference_text: Optional[str] = None,
    site: Optional[str] = None,
    scene: Optional[str] = None,
    user_id: Optional[int] = None,
    prepaid_coins: int = 0,
) -> Dict[str, Any]:
    """
    执行简单模式套图生成工作流

    Args:
        product_images: 商品图 Base64 列表
        platform: 平台
        region: 国家/地区
        target_language: 目标语言
        size: 图片尺寸 "WxH"
        image_groups: 套图结构配置
        product_info_json: 商品信息 JSON 字符串（可选）
        reference_image: 参考图 Base64（可选，风格参考）
        reference_text: 参考维度描述（可选）
        user_id: 用户 ID（可选，BYOK：模型调用按用户自备通道号池依次尝试）
        prepaid_coins: 实际预扣灵感币，用于失败退款封顶；BYOK 命中时为 0（不退款）

    Returns:
        {"batch_id": "...", "tasks": [...], "error": "..."}
    """
    initial_state: SmartGenerationState = {
        "product_images": product_images,
        "reference_image": reference_image,
        "reference_text": reference_text,
        "platform": platform,
        "region": region,
        "target_language": target_language,
        "site": site,
        "scene": scene,
        "size": size,
        "product_info_json": product_info_json,
        "image_groups": image_groups,
        "user_id": user_id,
        "product_info": None,
        "tasks": [],
        "prompt_variables": {},
        "batch_id": "",
        "error": None,
    }

    result = smart_generation_graph.invoke(initial_state)

    tasks_data = []
    for task in result.get("tasks", []):
        tasks_data.append(task.to_dict())

    return {
        "batch_id": result.get("batch_id", ""),
        "tasks": tasks_data,
        "error": result.get("error"),
    }