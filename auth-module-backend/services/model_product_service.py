"""模特商品图服务层 - 商品图分析、模特图分析、提示词优化、模特商品图生成"""
import asyncio
import json
from typing import Any, Dict, Optional

import requests
from config import AIConfig
from services.toolbox_service import ToolboxError, _extract_json_from_text, text_to_image
from services.user_ai_provider_service import (
    CATEGORY_MULTIMODAL,
    iter_channel_entries,
    report_entry_failure,
    report_entry_success,
)

# Task 7 迁移：原 MODEL_PRODUCT_TASKS 内存字典 + 后台线程 → ARQ + Redis task:{id}
from services.task_queue import register_task, set_progress
from services.task_state_sync import set_progress_sync, complete_task_sync, fail_task_sync

MODEL_PRODUCT_TASK_NAME = 'toolbox_model_product'


# ── 内部辅助函数 ──

def _call_multimodal_llm_by_channel(system_prompt: str, user_text: str, image_base64: Optional[str],
                                    temperature: float, max_tokens: int,
                                    api_base: str, api_key: str, model_name: str) -> str:
    """在单一通道内调用多模态 LLM /chat/completions，返回响应文本"""
    if image_base64:
        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/png;base64,{image_base64}"
        user_content: Any = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": image_base64}},
        ]
    else:
        user_content = user_text

    request_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        response = requests.post(
            f"{api_base}/chat/completions",
            json=request_body,
            headers=headers,
            timeout=120,
        )

        if response.status_code != 200:
            try:
                err_detail = response.json()
            except Exception:
                err_detail = response.text[:500]
            print(f"[模特商品图-LLM] API 返回非 200: status={response.status_code}, detail={err_detail}", flush=True)
            raise ToolboxError(
                code=5002,
                message="AI分析服务暂时不可用，请稍后重试",
                http_status=503
            )

        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"[模特商品图-LLM] AI 返回内容长度: {len(content)} 字符", flush=True)

        if not content:
            raise ToolboxError(
                code=5002,
                message="AI分析服务返回空结果，请重试",
                http_status=502
            )

        return content

    except requests.exceptions.Timeout:
        raise ToolboxError(
            code=5002,
            message="AI分析服务响应超时，请稍后重试",
            http_status=504
        )
    except requests.exceptions.ConnectionError:
        raise ToolboxError(
            code=5002,
            message="无法连接AI分析服务，请检查网络后重试",
            http_status=503
        )
    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"AI分析失败: {str(e)}",
            http_status=500
        )


def _call_multimodal_llm(system_prompt: str, user_text: str, image_base64: Optional[str] = None,
                         temperature: float = 0.3, max_tokens: int = 4096,
                         user_id: int = None) -> str:
    """调用多模态 LLM /chat/completions，返回响应文本

    Args:
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    """
    last_channel_error = None
    for entry in iter_channel_entries(user_id, CATEGORY_MULTIMODAL):
        try:
            content = _call_multimodal_llm_by_channel(
                system_prompt, user_text, image_base64, temperature, max_tokens,
                entry.api_base, entry.api_key, entry.model_name,
            )
            report_entry_success(entry.provider_id)
            return content
        except ToolboxError as e:
            last_channel_error = e
            report_entry_failure(entry.provider_id, e.message)

    raise last_channel_error or ToolboxError(
        code=5002,
        message="AI分析失败，已达最大重试次数",
        http_status=502
    )


# ── 1. 商品图分析 ──

def analyze_product_image(image_base64: str, user_id: int = None) -> dict:
    """
    调用多模态 LLM 分析商品图，提取颜色、形状、材质、品牌标识、尺寸比例等特征

    Args:
        image_base64: 商品图 base64（可能含 data:image/...;base64, 前缀）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        dict: {"product_type": "...", "color": "...", "material": "...", "shape": "...",
               "brand_identifiers": "...", "size_ratio": "...", "key_features": "..."}

    Raises:
        ToolboxError: 分析失败时抛出
    """
    system_prompt = (
        "你是一位专业的电商商品图分析专家，拥有丰富的商品视觉特征识别经验。\n"
        "请仔细分析用户提供的商品图片，提取以下特征信息：\n\n"
        "1. product_type（商品类型）：商品的具体品类，如 \"手提包\"、\"运动鞋\"、\"蓝牙耳机\"\n"
        "2. color（颜色）：商品的主色调和配色方案，如 \"棕色\"、\"黑色主体+红色logo\"\n"
        "3. material（材质）：商品的主要材质，如 \"皮革\"、\"不锈钢\"、\"硅胶\"、\"ABS塑料\"\n"
        "4. shape（形状）：商品的外形描述，如 \"矩形\"、\"圆形\"、\"圆柱形\"、\"不规则\"\n"
        "5. brand_identifiers（品牌标识）：商品上的品牌logo或文字信息，位置和颜色，如 \"金色logo\"、\"鞋舌处红色标志\"\n"
        "6. size_ratio（尺寸比例）：商品的大致尺寸比例，如 \"1:1\"、\"3:2\"、\"紧凑型\"\n"
        "7. key_features（关键特征）：其他值得注意的视觉细节，如接口位置、按键布局、特殊结构、纹理等\n\n"
        "必须以 JSON 格式返回，结构如下：\n"
        '{"product_type": "", "color": "", "material": "", "shape": "", "brand_identifiers": "", "size_ratio": "", "key_features": ""}\n\n'
        "重要规则：\n"
        "- 仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本\n"
        "- 所有字段都必须填写，未知信息填 \"未识别\"\n"
        "- key_features 字段应详细描述，包含所有值得注意的视觉细节"
    )

    user_text = "请分析这张商品图片，提取商品特征信息。"

    try:
        print(f"[模特商品图-分析商品] 开始分析商品图...", flush=True)
        content = _call_multimodal_llm(system_prompt, user_text, image_base64=image_base64,
                                       user_id=user_id)
        result = _extract_json_from_text(content)

        # 补全缺失字段
        fields = ["product_type", "color", "material", "shape", "brand_identifiers", "size_ratio", "key_features"]
        for field in fields:
            result.setdefault(field, "未识别")

        print(f"[模特商品图-分析商品] 分析完成: product_type={result.get('product_type', '')}", flush=True)
        return result

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"商品图分析失败: {str(e)}",
            http_status=500
        )


# ── 2. 模特图分析 ──

def analyze_model_image(image_base64: str, user_id: int = None) -> dict:
    """
    调用多模态 LLM 分析模特图，提取姿态、肤色、发型、服装风格、场景等特征

    Args:
        image_base64: 模特图 base64（可能含 data:image/...;base64, 前缀）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        dict: {"pose": "...", "skin_tone": "...", "hair_style": "...", "clothing_style": "...",
               "scene": "...", "key_features": "..."}

    Raises:
        ToolboxError: 分析失败时抛出
    """
    system_prompt = (
        "你是一位专业的时尚摄影与模特分析专家，拥有丰富的模特形象分析经验。\n"
        "请仔细分析用户提供的模特图片，提取以下特征信息：\n\n"
        "1. pose（姿态）：模特的姿势和动作，如 \"站立\"、\"坐姿\"、\"行走\"、\"侧身\"\n"
        "2. skin_tone（肤色）：模特的肤色描述，如 \"白皙\"、\"小麦色\"、\"深色\"\n"
        "3. hair_style（发型）：模特的发型特征，如 \"长发\"、\"短发\"、\"卷发\"、\"马尾\"\n"
        "4. clothing_style（服装风格）：模特的穿着风格，如 \"休闲\"、\"正式\"、\"运动\"、\"时尚\"\n"
        "5. scene（场景）：模特所处的拍摄场景，如 \"室内白色背景\"、\"户外街景\"、\"工作室\"\n"
        "6. key_features（关键特征）：其他值得注意的视觉细节，如表情、配饰、妆容、拍摄角度等\n\n"
        "必须以 JSON 格式返回，结构如下：\n"
        '{"pose": "", "skin_tone": "", "hair_style": "", "clothing_style": "", "scene": "", "key_features": ""}\n\n'
        "重要规则：\n"
        "- 仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本\n"
        "- 所有字段都必须填写，未知信息填 \"未识别\"\n"
        "- key_features 字段应详细描述，包含所有值得注意的视觉细节"
    )

    user_text = "请分析这张模特图片，提取模特特征信息。"

    try:
        print(f"[模特商品图-分析模特] 开始分析模特图...", flush=True)
        content = _call_multimodal_llm(system_prompt, user_text, image_base64=image_base64,
                                       user_id=user_id)
        result = _extract_json_from_text(content)

        # 补全缺失字段
        fields = ["pose", "skin_tone", "hair_style", "clothing_style", "scene", "key_features"]
        for field in fields:
            result.setdefault(field, "未识别")

        print(f"[模特商品图-分析模特] 分析完成: pose={result.get('pose', '')}", flush=True)
        return result

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"模特图分析失败: {str(e)}",
            http_status=500
        )


# ── 3. 提示词详细程度判断 ──

def evaluate_prompt_detail(prompt_a0: str, user_id: int = None) -> dict:
    """
    调用多模态 LLM（纯文本调用，不需要图片）判断提示词 A0 的详细程度

    详细的标准：包含主体描述、动作/姿态、场景/背景、光影、风格等至少 3 个维度

    Args:
        prompt_a0: 用户原始提示词
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        dict: {"is_detailed": True/False, "reason": "判断理由"}

    Raises:
        ToolboxError: 分析失败时抛出
    """
    system_prompt = (
        "你是一位专业的 AI 生图提示词评审专家。请判断用户提供的提示词是否足够详细，"
        "能够直接用于 AI 图像生成。\n\n"
        "详细的提示词标准（至少包含 3 个维度）：\n"
        "1. 主体描述：明确的主体对象、品类、特征\n"
        "2. 动作/姿态：主体的动作、姿势或使用方式\n"
        "3. 场景/背景：拍摄场景、背景环境\n"
        "4. 光影：光线方向、强度、色温、阴影等\n"
        "5. 风格：视觉风格、色调、氛围、构图等\n\n"
        "必须以 JSON 格式返回，结构如下：\n"
        '{"is_detailed": true/false, "reason": "判断理由（中文）"}\n\n'
        "重要规则：\n"
        "- 仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本\n"
        "- is_detailed 为布尔值，true 表示详细，false 表示不够详细\n"
        "- reason 字段使用中文，简要说明判断理由"
    )

    user_text = f"请判断以下提示词是否足够详细用于 AI 生图：\n\n{prompt_a0}"

    try:
        print(f"[模特商品图-判断详细度] 开始判断提示词详细程度...", flush=True)
        content = _call_multimodal_llm(system_prompt, user_text, user_id=user_id)
        result = _extract_json_from_text(content)

        is_detailed = bool(result.get("is_detailed", False))
        reason = result.get("reason", "")

        print(f"[模特商品图-判断详细度] 判断完成: is_detailed={is_detailed}", flush=True)
        return {"is_detailed": is_detailed, "reason": reason}

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"提示词详细程度判断失败: {str(e)}",
            http_status=500
        )


# ── 4. 提示词优化 ──

def optimize_prompt(prompt_a0: str, product_analysis: dict, model_analysis: dict,
                    user_id: int = None) -> str:
    """
    调用多模态 LLM（纯文本）结合商品分析结果和模特分析结果，
    将模糊的 A0 优化为详细的英文生图提示词 A1

    Args:
        prompt_a0: 用户原始提示词
        product_analysis: 商品图分析结果（来自 analyze_product_image）
        model_analysis: 模特图分析结果（来自 analyze_model_image）
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        str: 优化后的详细英文提示词 A1

    Raises:
        ToolboxError: 优化失败时抛出
    """
    system_prompt = (
        "你是一位跨境电商商品图提示词专家，擅长将模糊的提示词优化为详细的英文 AI 生图提示词。\n"
        "请根据以下信息，生成一段详细、专业、可直接用于 AI 生图工具（如 Midjourney、Stable Diffusion、Flux 等）的英文提示词：\n\n"
        "1. 用户原始提示词（A0）：用户的大致需求描述\n"
        "2. 商品图分析结果：商品的颜色、材质、形状、品牌标识、尺寸比例等特征\n"
        "3. 模特图分析结果：模特的姿态、肤色、发型、服装风格、场景等特征\n\n"
        "优化要求：\n"
        "- 必须包含主体描述（商品+模特）\n"
        "- 必须包含动作/姿态描述（模特如何与商品互动）\n"
        "- 必须包含场景/背景描述\n"
        "- 必须包含光影描述（光线方向、强度、色温）\n"
        "- 必须包含视觉风格描述（色调、氛围、构图）\n"
        "- 严格保持商品特征与模特特征的一致性\n"
        "- 提示词必须是英文，详细且自然流畅\n"
        "- 提示词可直接用于 AI 生图工具\n\n"
        "必须以 JSON 格式返回，结构如下：\n"
        '{"optimized_prompt": "详细英文提示词..."}\n\n'
        "重要规则：\n"
        "- 仅输出合法 JSON，不要使用 markdown 代码块包裹，不要输出任何额外文本\n"
        "- optimized_prompt 字段必须是英文提示词，至少 150 词"
    )

    user_text = (
        f"用户原始提示词（A0）：\n{prompt_a0}\n\n"
        f"商品图分析结果：\n{json.dumps(product_analysis, ensure_ascii=False, indent=2)}\n\n"
        f"模特图分析结果：\n{json.dumps(model_analysis, ensure_ascii=False, indent=2)}\n\n"
        f"请优化上述提示词，生成详细的英文 AI 生图提示词。"
    )

    try:
        print(f"[模特商品图-优化提示词] 开始优化提示词...", flush=True)
        content = _call_multimodal_llm(system_prompt, user_text, max_tokens=4096,
                                       user_id=user_id)
        result = _extract_json_from_text(content)

        optimized_prompt = result.get("optimized_prompt", "").strip()
        if not optimized_prompt:
            print(f"[模特商品图-优化提示词] 警告：optimized_prompt 为空，使用原始内容", flush=True)
            optimized_prompt = content.strip()

        print(f"[模特商品图-优化提示词] 优化完成，提示词长度: {len(optimized_prompt)} 字符", flush=True)
        return optimized_prompt

    except ToolboxError:
        raise
    except Exception as e:
        raise ToolboxError(
            code=5002,
            message=f"提示词优化失败: {str(e)}",
            http_status=500
        )


# ── 5. 异步任务编排（Task 7 迁移：原后台线程 run_model_product_task → ARQ 注册任务） ──

@register_task(MODEL_PRODUCT_TASK_NAME)
async def toolbox_model_product_task(ctx, payload: dict, task_id: str):
    """
    模特商品图任务（ARQ）：执行体与原 run_model_product_task 完全一致，
    原 _set_task 写内存字典的位置改为写 Redis task:{task_id} 状态。
    payload: {task_image, model_image, a0_prompt, resolution, user_id}
    """
    task_image = payload['task_image']
    model_image = payload['model_image']
    a0_prompt = payload['a0_prompt']
    resolution = payload.get('resolution', '1024x1024')
    user_id = payload.get('user_id')

    await set_progress(ctx, task_id, "正在初始化...")

    def _run_steps():
        """同步执行体（经 to_thread 在线程池运行，避免阻塞 worker 事件循环）"""
        try:
            # ── 步骤1: 分析商品图 ──
            set_progress_sync(task_id, "正在分析商品图...")
            print(f"[模特商品图-任务] 步骤1: 分析商品图...", flush=True)
            product_analysis = analyze_product_image(task_image, user_id=user_id)

            # ── 步骤2: 分析模特图 ──
            set_progress_sync(task_id, "正在分析模特图...")
            print(f"[模特商品图-任务] 步骤2: 分析模特图...", flush=True)
            model_analysis = analyze_model_image(model_image, user_id=user_id)

            # ── 步骤3: 判断提示词详细程度 ──
            set_progress_sync(task_id, "正在判断提示词详细程度...")
            print(f"[模特商品图-任务] 步骤3: 判断提示词详细程度...", flush=True)
            detail_result = evaluate_prompt_detail(a0_prompt, user_id=user_id)

            # ── 步骤4: 确定最终提示词 ──
            if detail_result.get("is_detailed", False):
                final_prompt = a0_prompt
                print(f"[模特商品图-任务] 步骤4: 提示词已足够详细，直接使用 A0", flush=True)
            else:
                set_progress_sync(task_id, "正在生成优化提示词...")
                print(f"[模特商品图-任务] 步骤4: 提示词不够详细，进行优化...", flush=True)
                final_prompt = optimize_prompt(a0_prompt, product_analysis, model_analysis,
                                               user_id=user_id)

            # ── 步骤5: 生成图片 ──
            set_progress_sync(task_id, "正在生成图片...")
            print(f"[模特商品图-任务] 步骤5: 调用文生图，提示词长度: {len(final_prompt)} 字符", flush=True)
            result_image = text_to_image(final_prompt, size=resolution, user_id=user_id)

            # ── 步骤6: 更新为完成状态 ──
            set_progress_sync(task_id, "处理完成", pct=100)
            complete_task_sync(task_id, {"image": result_image})
            print(f"[模特商品图-任务] 任务完成: task_id={task_id}", flush=True)

        except ToolboxError as e:
            print(f"[模特商品图-任务] 任务失败: {e.message}", flush=True)
            fail_task_sync(task_id, e.message)
        except Exception as e:
            error_msg = f"模特商品图生成失败: {str(e)}"
            print(f"[模特商品图-任务] 任务异常: {error_msg}", flush=True)
            fail_task_sync(task_id, error_msg)

    await asyncio.to_thread(_run_steps)


def get_model_product_task_status(task_id: str) -> dict:
    """
    获取模特商品图任务状态（数据源：Redis task:{task_id}）

    Args:
        task_id: 任务 ID

    Returns:
        dict: {task_id, status, progress, result, error}

    Raises:
        ToolboxError: 任务不存在时抛出
    """
    from services.task_queue import get_task
    state = get_task(task_id)
    if not state:
        raise ToolboxError(
            code=4004,
            message="模特商品图任务不存在或已过期，请重新提交",
            http_status=404
        )
    status = {
        'queued': 'processing',
        'running': 'processing',
        'completed': 'completed',
        'failed': 'failed',
    }.get(state.get('status'), 'processing')
    return {
        "task_id": task_id,
        "status": status,
        "progress": state.get('step', ''),
        "result": state.get('result'),
        "error": state.get('error'),
    }