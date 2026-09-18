"""AI 工具箱路由模块 - 文生图、图片合并、生图计划分析、对话式生图"""
import traceback
import uuid as _uuid

from flask import Blueprint, request, jsonify, g, send_file

from middleware.auth_middleware import token_required
from services.history_service import save_history
from services.task_queue import submit_task  # Task 7: 异步任务统一经 ARQ 提交
from services.toolbox_service import (
    ToolboxError,
    text_to_image,
    merge_images,
    get_merge_task_status,  # 新增
    analyze_generation_plan,
    chat_generate,
    replace_product,        # 新增
    generate_ai_model,      # 新增
    generate_model_product,  # 新增
    get_model_product_task_status,  # 新增
    reverse_prompt,         # 新增
    get_product_replace_task_status,  # 新增
)

import hashlib
import json
import os
import tempfile
from services.file_security import validate_file_type, is_dangerous_extension, validate_file_size
from services.file_chunk_service import init_upload, upload_chunk, complete_upload, get_upload_status
from services.plan_analysis_queue import enqueue_task, get_task_status, get_user_history
from services.analysis_cache import get_cached_result, set_cache_result
from models.plan_analysis import PlanAnalysisTaskModel
from services.feature_pricing_service import (
    calculate_per_use_cost,
    deduct_coins,
    refund_coins,
    FeaturePricingError,
)
from services.user_ai_provider_service import calculate_effective_cost, is_feature_byok

toolbox_bp = Blueprint('toolbox', __name__, url_prefix='/api/v1/toolbox')

# 模特商品图异步任务计费记录（task_id -> {user_id, cost, refunded}）
# 由于该任务的后台线程在 service 层，路由无法在后台线程中退款，
# 改在状态查询接口检测 'failed' 时退款，以此 dict 防止重复退款。
_model_product_task_billing = {}


def _log_skip_deduct(tool_name, feature_key, user_id):
    """cost 为 0 时区分跳过扣费的原因：命中自备通道免扣费，还是功能未定价"""
    if is_feature_byok(user_id, feature_key):
        print(f'[工具箱-{tool_name}] 命中自备通道，免扣费: feature_key={feature_key}', flush=True)
    else:
        print(f'[工具箱-{tool_name}] 功能未定价，跳过扣费: feature_key={feature_key}', flush=True)


# ── Task 5: 文生图 ──

@toolbox_bp.route('/text-to-image', methods=['POST'])
@token_required
def text_to_image_api():
    """
    文生图 - 根据文本描述生成图片

    Request Body:
    {
        "prompt": "图片描述文本",
        "size": "1024x1024"  // 可选
    }

    Response:
    {
        "code": 0,
        "message": "success",
        "data": { "image": "data:image/png;base64,..." }
    }
    """
    try:
        cost = 0
        deducted = False
        feature_key = 'toolbox.text_to_image'
        tool_name = '文生图'

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        prompt = data.get("prompt", "")
        if not prompt or not prompt.strip():
            return jsonify({"code": 4001, "message": "请输入图片描述", "data": None}), 400

        size = data.get("size")
        quality = data.get("quality")

        # 服务端尺寸格式校验
        if size:
            import re as _re
            size_match = _re.match(r'^(\d+)[xX×](\d+)$', str(size).strip())
            if not size_match:
                return jsonify({"code": 4001, "message": "尺寸格式无效，请使用 宽x高 格式，如 1024x1024", "data": None}), 400
            w = int(size_match.group(1))
            h = int(size_match.group(2))
            if w <= 0 or h <= 0:
                return jsonify({"code": 4001, "message": "尺寸宽高必须为正整数", "data": None}), 400

        user_id = g.current_user.get('user_id')

        # ── 计算并扣费（命中用户自备模型通道时 cost 为 0，跳过扣费）──
        cost = calculate_effective_cost(user_id, feature_key)
        if cost > 0:
            try:
                deduct_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 1 次')
                deducted = True
            except FeaturePricingError as e:
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            _log_skip_deduct(tool_name, feature_key, user_id)

        result_image = text_to_image(prompt.strip(), size=size, quality=quality, user_id=user_id)

        # 保存历史记录
        try:
            save_history(
                user_id=g.current_user['user_id'],
                category='ai_toolbox',
                sub_category='text_to_image',
                input_data={
                    'prompt': data.get('prompt', ''),
                    'size': data.get('size', ''),
                    'quality': data.get('quality', ''),
                },
                output_data={'image': result_image},
            )
        except Exception:
            pass  # 历史记录保存失败不影响主流程

        return jsonify({
            "code": 0,
            "message": "success",
            "data": {"image": result_image}
        })

    except ToolboxError as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        print(f"[工具箱-文生图] 未预期异常: {e}", flush=True)
        print(f"[工具箱-文生图] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"文生图失败: {str(e)}", "data": None}), 500


# ── Task 6: 图片合并（异步）──

@toolbox_bp.route('/image-merge', methods=['POST'])
@token_required
def image_merge_api():
    """
    图片合并 - AI 智能合并多张产品图为一张综合图片（异步处理）

    Request Body:
    {
        "images": ["data:image/...;base64,...", ...]
    }

    Response (立即返回):
    {
        "code": 0,
        "message": "success",
        "data": {
            "task_id": "xxx",
            "status": "processing"
        }
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        images = data.get("images", [])

        if not images or len(images) < 2 or len(images) > 10:
            return jsonify({"code": 4001, "message": "请上传 2-10 张图片进行合并", "data": None}), 400

        user_id = g.current_user.get('user_id')

        # ── 计算并扣费 ──
        feature_key = 'toolbox.image_merge'
        tool_name = '图片合并'
        cost = calculate_effective_cost(user_id, feature_key)
        deducted = False
        if cost > 0:
            try:
                deduct_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 1 次')
                deducted = True
            except FeaturePricingError as e:
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            _log_skip_deduct(tool_name, feature_key, user_id)

        # Task 7 迁移：原后台线程 _run_merge → ARQ 任务（状态存 Redis task:{task_id}）
        task_id = submit_task(
            'toolbox_image_merge',
            {
                'images': images,
                'user_id': user_id,
                'deducted': deducted,
                'cost': cost,
                'feature_key': feature_key,
                'tool_name': tool_name,
            },
            module='toolbox',
        )

        print(f"[工具箱-图片合并] 异步任务已创建: task_id={task_id}, 共 {len(images)} 张图片", flush=True)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": {
                "task_id": task_id,
                "status": "processing"
            }
        })

    except ToolboxError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        print(f"[工具箱-图片合并] 未预期异常: {e}", flush=True)
        print(f"[工具箱-图片合并] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"图片合并失败: {str(e)}", "data": None}), 500


# ── 图片合并任务状态查询 ──

@toolbox_bp.route('/image-merge/status/<task_id>', methods=['GET'])
@token_required
def image_merge_status_api(task_id):
    """
    查询图片合并任务状态

    Response:
    {
        "code": 0,
        "message": "success",
        "data": {
            "task_id": "xxx",
            "status": "processing" | "completed" | "failed",
            "progress": "当前步骤描述",
            "result": {
                "image": "data:image/png;base64,...",
                "verification": {"passed": true, "issues": []}
            },
            "error": "错误描述（仅 failed 状态）"
        }
    }
    """
    try:
        result = get_merge_task_status(task_id)
        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })
    except ToolboxError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        print(f"[工具箱-合并状态] 未预期异常: {e}", flush=True)
        print(f"[工具箱-合并状态] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"查询合并状态失败: {str(e)}", "data": None}), 500


# ── Task 7: 生图计划分析 ──

@toolbox_bp.route('/plan-analysis', methods=['POST'])
@token_required
def plan_analysis_api():
    """
    生图计划分析 - 调用多模态 LLM 分析商品图，返回结构化生图计划

    Request Body:
    {
        "images": ["data:image/...;base64,...", ...],
        "file_content": "可选的说明文件文本（txt/md/json 等纯文本文件直接传内容）",
        "prompt": "可选的用户自定义提示词",
        "file_data": "可选的二进制文件 base64（PDF/DOC/PPT/XLS/图片等需 MinerU 解析的文件）",
        "file_name": "可选的二进制文件名（与 file_data 配合使用）"
    }

    Response:
    {
        "code": 0,
        "message": "success",
        "data": {
            "plan": {
                "summary": "分析数据摘要：商品品类、核心卖点、规格件数、材质颜色、目标市场等",
                "images": [
                    {
                        "index": 1,
                        "title": "主图：整套识别图",
                        "plan": "这张图的方案：拍什么、怎么构图、突出什么",
                        "reason": "选择这个方案的原因",
                        "prompt_cn": "中文 AI 出图提示词（可直接复制）",
                        "prompt_en": "英文 AI 出图提示词（可直接复制）",
                        "backup_prompt_cn": "备用中文提示词",
                        "backup_prompt_en": "备用英文提示词"
                    }
                ]
            }
        }
    }
    """
    try:
        cost = 0
        deducted = False
        feature_key = 'toolbox.plan_analysis'
        tool_name = '生图计划分析'

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        images = data.get("images", [])
        if not images or len(images) == 0:
            return jsonify({"code": 4001, "message": "请至少上传一张商品图", "data": None}), 400

        file_content = data.get("file_content")
        prompt = data.get("prompt")
        file_data = data.get("file_data")
        file_name = data.get("file_name")

        # ── 文件安全检测 ──
        if file_data and file_name:
            # 检查危险扩展名
            is_dangerous, danger_msg = is_dangerous_extension(file_name)
            if is_dangerous:
                return jsonify({"code": 5004, "message": danger_msg, "data": None}), 400

            # 检查文件大小（base64 解码后）
            try:
                import base64 as _b64
                b64_data = file_data.split(",", 1)[1] if "," in file_data else file_data
                decoded_size = len(_b64.b64decode(b64_data))
                is_valid, size_msg = validate_file_size(decoded_size)
                if not is_valid:
                    return jsonify({"code": 5004, "message": size_msg, "data": None}), 400
            except Exception:
                pass  # 解码失败在后续 analyze_generation_plan 中处理

        # ── 缓存逻辑 ──
        # 计算请求内容哈希
        hash_input = json.dumps({
            "images_count": len(images),
            "file_content": file_content or "",
            "prompt": prompt or "",
            "file_name": file_name or "",
        }, sort_keys=True, ensure_ascii=False)
        input_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

        # 查询缓存
        cached = get_cached_result(input_hash)
        if cached:
            # 兼容性检查：旧格式缓存缺少 summary 字段，需跳过
            if 'summary' not in cached:
                print(f"[工具箱-计划分析] 缓存为旧格式，跳过", flush=True)
            else:
                print(f"[工具箱-计划分析] 缓存命中，直接返回结果", flush=True)
                return jsonify({
                    "code": 0,
                    "message": "success",
                    "data": {"plan": cached}
                })

        user_id = g.current_user.get('user_id')

        # ── 创建任务记录 ──
        task_id = enqueue_task(user_id, input_hash, data)

        # ── 更新状态为 processing ──
        task_model = PlanAnalysisTaskModel()
        task_model.update_status(task_id, 'processing')

        # ── 计算并扣费（命中用户自备模型通道时 cost 为 0，跳过扣费）──
        cost = calculate_effective_cost(user_id, feature_key)
        if cost > 0:
            try:
                deduct_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 1 次',
                             related_batch_id=str(task_id))
                deducted = True
            except FeaturePricingError as e:
                try:
                    task_model.update_status(task_id, 'failed', error_message=e.message)
                except Exception:
                    pass
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            _log_skip_deduct(tool_name, feature_key, user_id)

        # ── 异步执行：提交 ARQ 任务，立即返回 task_id ──
        # Task 7 迁移：原后台线程 _run_analysis → ARQ 任务（DB 状态流转逻辑原样平移）
        submit_task(
            'toolbox_plan_analysis',
            {
                'db_task_id': task_id,
                'images': images,
                'file_content': file_content,
                'prompt': prompt,
                'file_data': file_data,
                'file_name': file_name,
                'user_id': user_id,
                'deducted': deducted,
                'cost': cost,
                'feature_key': feature_key,
                'tool_name': tool_name,
                'history_input': {
                    'images': data.get('images', []),
                    'file_content': data.get('file_content'),
                    'prompt': data.get('prompt'),
                },
            },
            module='toolbox',
        )

        print(f"[工具箱-计划分析] 异步任务已创建: task_id={task_id}, 共 {len(images)} 张图片", flush=True)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": {
                "task_id": task_id,
                "status": "processing"
            }
        })

    except ToolboxError as e:
        # 如果 task_id 已创建，更新失败状态
        try:
            if 'task_id' in locals() and task_id:
                task_model = PlanAnalysisTaskModel()
                task_model.update_status(task_id, 'failed', error_message=e.message)
        except Exception:
            pass
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款',
                             related_batch_id=str(task_id) if 'task_id' in locals() and task_id else None)
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        try:
            if 'task_id' in locals() and task_id:
                task_model = PlanAnalysisTaskModel()
                task_model.update_status(task_id, 'failed', error_message=str(e))
        except Exception:
            pass
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款',
                             related_batch_id=str(task_id) if 'task_id' in locals() and task_id else None)
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        print(f"[工具箱-计划分析] 未预期异常: {e}", flush=True)
        print(f"[工具箱-计划分析] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"生图计划分析失败: {str(e)}", "data": None}), 500


# ── 分块上传接口 ──

@toolbox_bp.route('/plan-analysis/chunk-upload/init', methods=['POST'])
@token_required
def chunk_upload_init_api():
    """
    初始化分块上传
    Request Body: {filename: string, total_chunks: int, file_size: int}
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        filename = data.get("filename", "")
        if not filename:
            return jsonify({"code": 4001, "message": "文件名不能为空", "data": None}), 400

        total_chunks = data.get("total_chunks", 0)
        if not isinstance(total_chunks, int) or total_chunks <= 0:
            return jsonify({"code": 4001, "message": "分块总数必须为正整数", "data": None}), 400

        file_size = data.get("file_size", 0)
        if not isinstance(file_size, int) or file_size <= 0:
            return jsonify({"code": 4001, "message": "文件大小必须为正整数", "data": None}), 400

        # 文件安全检测
        is_dangerous, danger_msg = is_dangerous_extension(filename)
        if is_dangerous:
            return jsonify({"code": 5004, "message": danger_msg, "data": None}), 400

        is_valid, size_msg = validate_file_size(file_size)
        if not is_valid:
            return jsonify({"code": 5004, "message": size_msg, "data": None}), 400

        user_id = g.current_user.get('user_id')
        result = init_upload(filename, total_chunks, file_size, user_id)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })

    except ValueError as e:
        return jsonify({"code": 4001, "message": str(e), "data": None}), 400
    except Exception as e:
        print(f"[工具箱-分块上传-初始化] 异常: {e}", flush=True)
        return jsonify({"code": 5001, "message": f"初始化上传失败: {str(e)}", "data": None}), 500


@toolbox_bp.route('/plan-analysis/chunk-upload', methods=['POST'])
@token_required
def chunk_upload_api():
    """
    上传分块
    Request Body: {upload_id: string, chunk_index: int, chunk_data: string (base64)}
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        upload_id = data.get("upload_id", "")
        if not upload_id:
            return jsonify({"code": 4001, "message": "upload_id 不能为空", "data": None}), 400

        chunk_index = data.get("chunk_index")
        if chunk_index is None or not isinstance(chunk_index, int) or chunk_index < 0:
            return jsonify({"code": 4001, "message": "chunk_index 必须为非负整数", "data": None}), 400

        chunk_data = data.get("chunk_data", "")
        if not chunk_data:
            return jsonify({"code": 4001, "message": "chunk_data 不能为空", "data": None}), 400

        result = upload_chunk(upload_id, chunk_index, chunk_data)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })

    except ValueError as e:
        return jsonify({"code": 4001, "message": str(e), "data": None}), 400
    except Exception as e:
        print(f"[工具箱-分块上传] 异常: {e}", flush=True)
        return jsonify({"code": 5001, "message": f"分块上传失败: {str(e)}", "data": None}), 500


@toolbox_bp.route('/plan-analysis/chunk-upload/complete', methods=['POST'])
@token_required
def chunk_upload_complete_api():
    """
    合并分块
    Request Body: {upload_id: string}
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        upload_id = data.get("upload_id", "")
        if not upload_id:
            return jsonify({"code": 4001, "message": "upload_id 不能为空", "data": None}), 400

        result = complete_upload(upload_id)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })

    except ValueError as e:
        return jsonify({"code": 4001, "message": str(e), "data": None}), 400
    except Exception as e:
        print(f"[工具箱-分块合并] 异常: {e}", flush=True)
        return jsonify({"code": 5001, "message": f"分块合并失败: {str(e)}", "data": None}), 500


@toolbox_bp.route('/plan-analysis/chunk-upload/status/<upload_id>', methods=['GET'])
@token_required
def chunk_upload_status_api(upload_id):
    """
    查询分块上传进度
    """
    try:
        result = get_upload_status(upload_id)
        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })
    except ValueError as e:
        return jsonify({"code": 4001, "message": str(e), "data": None}), 400
    except Exception as e:
        print(f"[工具箱-上传进度] 异常: {e}", flush=True)
        return jsonify({"code": 5001, "message": f"查询上传进度失败: {str(e)}", "data": None}), 500


# ── 任务状态与历史记录 ──

@toolbox_bp.route('/plan-analysis/status/<int:task_id>', methods=['GET'])
@token_required
def plan_analysis_status_api(task_id):
    """
    查询任务状态
    """
    try:
        result = get_task_status(task_id)
        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })
    except ValueError as e:
        return jsonify({"code": 4001, "message": str(e), "data": None}), 400
    except Exception as e:
        print(f"[工具箱-任务状态] 异常: {e}", flush=True)
        return jsonify({"code": 5001, "message": f"查询任务状态失败: {str(e)}", "data": None}), 500


# ── Task 8: 对话式生图 ──

@toolbox_bp.route('/chat-gen', methods=['POST'])
@token_required
def chat_gen_api():
    """
    对话式生图 - AI 判断用户需求是否明确，明确则调用文生图，不明确则返回澄清问题

    Request Body:
    {
        "messages": [{"role": "user", "content": "..."}, ...],
        "reference_images": ["data:image/...;base64,...", ...]  // 可选
    }

    Response:
    {
        "code": 0,
        "message": "success",
        "data": {
            "reply": "AI 回复文本",
            "images": ["data:image/png;base64,..."]
        }
    }
    """
    try:
        cost = 0
        deducted = False
        feature_key = 'toolbox.chat_gen'
        tool_name = '对话式生图'

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        messages = data.get("messages", [])
        if not messages or len(messages) == 0:
            return jsonify({"code": 4001, "message": "对话消息不能为空", "data": None}), 400

        reference_images = data.get("reference_images")

        user_id = g.current_user.get('user_id')

        # ── 计算并扣费（命中用户自备模型通道时 cost 为 0，跳过扣费）──
        cost = calculate_effective_cost(user_id, feature_key)
        if cost > 0:
            try:
                deduct_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 1 次')
                deducted = True
            except FeaturePricingError as e:
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            _log_skip_deduct(tool_name, feature_key, user_id)

        result = chat_generate(messages, reference_images=reference_images, user_id=user_id)

        # 保存历史记录（仅当生成了图片时）
        try:
            if result.get('images'):
                save_history(
                    user_id=g.current_user['user_id'],
                    category='ai_toolbox',
                    sub_category='chat_gen',
                    input_data={
                        'messages': data.get('messages', []),
                        'reference_images': data.get('reference_images'),
                    },
                    output_data={'reply': result.get('reply', ''), 'images': result.get('images', [])},
                )
        except Exception:
            pass  # 历史记录保存失败不影响主流程

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })

    except ToolboxError as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        print(f"[工具箱-对话生图] 未预期异常: {e}", flush=True)
        print(f"[工具箱-对话生图] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"对话生图失败: {str(e)}", "data": None}), 500


# ── Task 9: 产品替换 ──

@toolbox_bp.route('/product-replace', methods=['POST'])
@token_required
def product_replace_api():
    """
    产品替换 - 将参考图中的商品替换为用户上传的商品（异步处理）

    Request Body:
    {
        "product_image": "data:image/...;base64,...",
        "reference_image": "data:image/...;base64,...",
        "prompt": "可选提示词"
    }

    Response (立即返回):
    {
        "code": 0,
        "message": "success",
        "data": {
            "task_id": "xxx",
            "status": "processing"
        }
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        product_image = data.get("product_image", "")
        if not product_image:
            return jsonify({"code": 4001, "message": "请上传商品图", "data": None}), 400

        reference_image = data.get("reference_image", "")
        if not reference_image:
            return jsonify({"code": 4001, "message": "请上传参考图", "data": None}), 400

        prompt = data.get("prompt")

        user_id = g.current_user.get('user_id')

        # ── 计算并扣费 ──
        feature_key = 'toolbox.product_replace'
        tool_name = '产品替换'
        cost = calculate_effective_cost(user_id, feature_key)
        deducted = False
        if cost > 0:
            try:
                deduct_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 1 次')
                deducted = True
            except FeaturePricingError as e:
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            _log_skip_deduct(tool_name, feature_key, user_id)

        # Task 7 迁移：原后台线程 _run_replace → ARQ 任务（状态存 Redis task:{task_id}，
        # replace_product 内部的进度/完成/失败写字典位置已改为写 Redis）
        task_id = submit_task(
            'toolbox_product_replace',
            {
                'product_image': product_image,
                'reference_image': reference_image,
                'prompt': prompt,
                'user_id': user_id,
                'deducted': deducted,
                'cost': cost,
                'feature_key': feature_key,
                'tool_name': tool_name,
                'history_input': {
                    'product_image': data.get('product_image', ''),
                    'reference_image': data.get('reference_image', ''),
                    'prompt': data.get('prompt'),
                },
            },
            module='toolbox',
        )

        print(f"[工具箱-产品替换] 异步任务已创建: task_id={task_id}", flush=True)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": {
                "task_id": task_id,
                "status": "processing"
            }
        })

    except ToolboxError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        print(f"[工具箱-产品替换] 未预期异常: {e}", flush=True)
        print(f"[工具箱-产品替换] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"产品替换失败: {str(e)}", "data": None}), 500


# ── 产品替换任务状态查询 ──

@toolbox_bp.route('/product-replace/status/<task_id>', methods=['GET'])
@token_required
def product_replace_status_api(task_id):
    """
    查询产品替换任务状态

    Response:
    {
        "code": 0,
        "message": "success",
        "data": {
            "task_id": "xxx",
            "status": "processing" | "completed" | "failed",
            "progress": "当前步骤描述",
            "result": {
                "image": "data:image/png;base64,..."
            },
            "error": "错误描述（仅 failed 状态）"
        }
    }
    """
    try:
        result = get_product_replace_task_status(task_id)
        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })
    except ToolboxError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        print(f"[工具箱-产品替换状态] 未预期异常: {e}", flush=True)
        print(f"[工具箱-产品替换状态] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"查询替换状态失败: {str(e)}", "data": None}), 500


# ── Task 9: AI 模特 ──

@toolbox_bp.route('/ai-model', methods=['POST'])
@token_required
def ai_model_api():
    """
    AI模特 - 生成专业模特角色卡（三视图、发型展示、表情排列）

    Request Body:
    {
        "person_image": "data:image/...;base64,...",  // 可选
        "country": "美国",
        "race": "东亚人种",
        "prompt": "提示词"
    }
    """
    try:
        cost = 0
        deducted = False
        feature_key = 'toolbox.ai_model'
        tool_name = 'AI模特'

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        country = data.get("country", "")
        if not country or not country.strip():
            return jsonify({"code": 4001, "message": "请选择国家", "data": None}), 400

        race = data.get("race", "")
        if not race or not race.strip():
            return jsonify({"code": 4001, "message": "请选择人种", "data": None}), 400

        prompt = data.get("prompt", "")
        if not prompt or not prompt.strip():
            return jsonify({"code": 4001, "message": "请输入提示词", "data": None}), 400

        person_image = data.get("person_image")

        user_id = g.current_user.get('user_id')

        # ── 计算并扣费（命中用户自备模型通道时 cost 为 0，跳过扣费）──
        cost = calculate_effective_cost(user_id, feature_key)
        if cost > 0:
            try:
                deduct_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 1 次')
                deducted = True
            except FeaturePricingError as e:
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            _log_skip_deduct(tool_name, feature_key, user_id)

        result_image = generate_ai_model(person_image, country.strip(), race.strip(), prompt.strip(),
                                         user_id=user_id)

        # 保存历史记录
        try:
            save_history(
                user_id=g.current_user['user_id'],
                category='ai_toolbox',
                sub_category='ai_model',
                input_data={
                    'person_image': data.get('person_image'),
                    'country': data.get('country', ''),
                    'race': data.get('race', ''),
                    'prompt': data.get('prompt', ''),
                },
                output_data={'image': result_image},
            )
        except Exception:
            pass  # 历史记录保存失败不影响主流程

        return jsonify({
            "code": 0,
            "message": "success",
            "data": {"image": result_image}
        })

    except ToolboxError as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        print(f"[工具箱-AI模特] 未预期异常: {e}", flush=True)
        print(f"[工具箱-AI模特] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"AI模特生成失败: {str(e)}", "data": None}), 500


# ── Task 9: 模特商品图 ──

@toolbox_bp.route('/model-product', methods=['POST'])
@token_required
def model_product_api():
    """
    模特商品图 - 生成模特使用商品的图片（异步）

    Request Body:
    {
        "product_image": "data:image/...;base64,...",
        "model_image": "data:image/...;base64,...",
        "prompt": "提示词（A0，支持模糊描述）",
        "resolution": "1024x1024"  // 可选
    }
    """
    try:
        cost = 0
        deducted = False
        feature_key = 'toolbox.model_product'
        tool_name = '模特商品图'

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        product_image = data.get("product_image", "")
        if not product_image:
            return jsonify({"code": 4001, "message": "请上传商品图", "data": None}), 400

        model_image = data.get("model_image", "")
        if not model_image:
            return jsonify({"code": 4001, "message": "请上传模特图", "data": None}), 400

        prompt = data.get("prompt", "")
        if not prompt or not prompt.strip():
            return jsonify({"code": 4001, "message": "请输入提示词", "data": None}), 400

        resolution = data.get("resolution", "1024x1024")

        user_id = g.current_user.get('user_id')

        # ── 计算并扣费（命中用户自备模型通道时 cost 为 0，跳过扣费）──
        cost = calculate_effective_cost(user_id, feature_key)
        if cost > 0:
            try:
                deduct_coins(user_id, cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 1 次')
                deducted = True
            except FeaturePricingError as e:
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            _log_skip_deduct(tool_name, feature_key, user_id)

        result = generate_model_product(product_image, model_image, prompt.strip(), resolution, user_id=user_id)

        # 记录计费信息，供状态查询接口在任务失败时退款（后台线程在 service 层，无法在此退款）
        if deducted:
            _model_product_task_billing[result.get('task_id')] = {
                'user_id': user_id,
                'cost': cost,
                'feature_key': feature_key,
                'tool_name': tool_name,
                'refunded': False,
            }

        # 保存历史记录
        try:
            save_history(
                user_id=user_id,
                category='ai_toolbox',
                sub_category='model_product',
                input_data={
                    'product_image': data.get('product_image', ''),
                    'model_image': data.get('model_image', ''),
                    'prompt': data.get('prompt', ''),
                    'resolution': data.get('resolution', ''),
                },
                output_data={'task_id': result.get('task_id'), 'status': result.get('status')},
            )
        except Exception:
            pass  # 历史记录保存失败不影响主流程

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })

    except ToolboxError as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        print(f"[工具箱-模特商品图] 未预期异常: {e}", flush=True)
        print(f"[工具箱-模特商品图] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"模特商品图生成失败: {str(e)}", "data": None}), 500


@toolbox_bp.route('/model-product/status/<task_id>', methods=['GET'])
@token_required
def model_product_status_api(task_id):
    """
    查询模特商品图任务状态

    Response:
    {
        "code": 0,
        "message": "success",
        "data": {
            "task_id": "...",
            "status": "processing" | "completed" | "failed",
            "progress": "当前步骤描述",
            "result": {"image": "data:..."} | null,
            "error": null | "错误信息"
        }
    }
    """
    try:
        status = get_model_product_task_status(task_id)

        # 异步任务失败时退款（后台线程在 service 层，路由无法在后台线程中退款）
        if status.get('status') == 'failed':
            billing = _model_product_task_billing.get(task_id)
            if billing and not billing.get('refunded'):
                billing['refunded'] = True
                try:
                    refund_coins(
                        billing['user_id'], billing['cost'],
                        feature_key=billing['feature_key'],
                        description=f"AI工具箱-{billing['tool_name']} 执行失败退款",
                        related_batch_id=task_id,
                    )
                except Exception as refund_e:
                    print(f"[工具箱-模特商品图] 退款失败: task_id={task_id}, error={refund_e}", flush=True)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": status
        })
    except ToolboxError as e:
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        print(f"[工具箱-模特商品图状态] 未预期异常: {e}", flush=True)
        print(f"[工具箱-模特商品图状态] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"查询任务状态失败: {str(e)}", "data": None}), 500


# ── Task 9: 反推提示词 ──

@toolbox_bp.route('/prompt-reverse', methods=['POST'])
@token_required
def prompt_reverse_api():
    """
    反推提示词 - AI 反推图片的提示词

    Request Body:
    {
        "image": "data:image/...;base64,..."
    }
    """
    try:
        cost = 0
        deducted = False
        feature_key = 'toolbox.prompt_reverse'
        tool_name = '反推提示词'

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"code": 4001, "message": "请求参数不能为空", "data": None}), 400

        image = data.get("image", "")
        if not image:
            return jsonify({"code": 4001, "message": "请上传图片", "data": None}), 400

        user_id = g.current_user.get('user_id')

        # ── 计算并扣费（命中用户自备模型通道时 cost 为 0，跳过扣费）──
        cost = calculate_effective_cost(user_id, feature_key)
        if cost > 0:
            try:
                deduct_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 1 次')
                deducted = True
            except FeaturePricingError as e:
                return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
        else:
            _log_skip_deduct(tool_name, feature_key, user_id)

        result = reverse_prompt(image, user_id=user_id)

        # 保存历史记录
        try:
            save_history(
                user_id=g.current_user['user_id'],
                category='ai_toolbox',
                sub_category='prompt_reverse',
                input_data={'image': data.get('image', '')},
                output_data=result,
            )
        except Exception:
            pass  # 历史记录保存失败不影响主流程

        return jsonify({
            "code": 0,
            "message": "success",
            "data": result
        })

    except ToolboxError as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        return jsonify({"code": e.code, "message": e.message, "data": None}), e.http_status
    except Exception as e:
        if deducted:
            try:
                refund_coins(g.current_user.get('user_id'), cost, feature_key=feature_key,
                             description=f'AI工具箱-{tool_name} 执行失败退款')
            except Exception as refund_e:
                print(f'[工具箱-{tool_name}] 退款失败: {refund_e}', flush=True)
        print(f"[工具箱-反推提示词] 未预期异常: {e}", flush=True)
        print(f"[工具箱-反推提示词] 异常堆栈: {traceback.format_exc()}", flush=True)
        return jsonify({"code": 5001, "message": f"反推提示词失败: {str(e)}", "data": None}), 500


# ── Plan B: 临时文件服务（供 MinerU 单文件提取 API 回调下载）──
# 当 MinerU CDN 基础 URL 不可直接访问时，可作为备用方案。
# 注意：此方案要求服务器可被公网访问（生产环境通常满足），
# 本地开发时需使用内网穿透工具（如 ngrok）。

_TEMP_FILE_DIR = os.path.join(tempfile.gettempdir(), 'mineru_uploads')
os.makedirs(_TEMP_FILE_DIR, exist_ok=True)


def save_temp_file(file_bytes: bytes, filename: str) -> str:
    """
    保存文件到临时目录，返回文件 ID 和访问 URL

    Returns:
        tuple: (file_id, file_url)
    """
    file_id = f"{_uuid.uuid4().hex}_{filename}"
    file_path = os.path.join(_TEMP_FILE_DIR, file_id)
    with open(file_path, 'wb') as f:
        f.write(file_bytes)
    return file_id


def get_temp_file_url(file_id: str, base_url: str) -> str:
    """获取临时文件的完整访问 URL"""
    return f"{base_url.rstrip('/')}/api/v1/toolbox/temp-file/{file_id}"


@toolbox_bp.route('/temp-file/<file_id>', methods=['GET'])
def serve_temp_file(file_id):
    """
    临时文件服务（无需认证，供 MinerU 回调下载）

    安全说明：
    - 文件 ID 包含 UUID，不可猜测
    - 文件仅在上传后短时间内有效
    - 仅用于 MinerU API 回调下载场景
    """
    # 安全检查：防止路径遍历
    if '..' in file_id or '/' in file_id or '\\' in file_id:
        return jsonify({"code": 4004, "message": "无效的文件 ID"}), 400

    file_path = os.path.join(_TEMP_FILE_DIR, file_id)
    if not os.path.exists(file_path):
        return jsonify({"code": 4004, "message": "文件不存在或已过期"}), 404

    return send_file(file_path)
