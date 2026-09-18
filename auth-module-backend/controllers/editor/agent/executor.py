"""
编辑器 Agent 计划执行引擎（ARQ 异步任务）

按拓扑序逐步执行计划中的工具调用：
- 每步开始前检查取消标记（Redis key agent-plan:{task_id}:cancel，由路由写入）
- 每步 set_progress 中文进度（"步骤 i/n：工具名"），调 registry 工具函数（与
  editor_tool_execute 相同的 func(img, params) 约定，AI 工具为阻塞 HTTP，放入线程执行）
- 每步产物：存图片存储得到 URL（写入 result），同时把 PNG 字节存 Redis
  （key agent-plan:{task_id}:step:{id}，TTL 同任务），供单步重试复用
- 步骤失败：默认终止并 fail_task（error 携带失败步骤与已完成步骤信息）
- 单步重试：payload.retry_from_step 从指定步重跑，payload.source_task_id
  指向原任务（读取原任务的中间产物 agent-plan:{source_task_id}:step:{id}）
"""
import io

from PIL import Image

from services.task_queue import (
    register_task, set_progress, complete_task, fail_task, TASK_RESULT_TTL,
)
from services.image_storage_service import save_image_bytes
from controllers.editor.tools.registry import get_tool
from controllers.editor.tools.tasks import _load_image_bytes
from controllers.editor.agent.validate import validate_plan
from models.editor_task import EditorTaskModel

# Agent 中间产物 / 取消标记的 Redis key 前缀
AGENT_KEY_PREFIX = 'agent-plan:'
CANCEL_KEY_SUFFIX = ':cancel'


def step_key(task_id, step_id):
    """中间产物 Redis key：agent-plan:{task_id}:step:{step_id}"""
    return f'{AGENT_KEY_PREFIX}{task_id}:step:{step_id}'


def cancel_key(task_id):
    """取消标记 Redis key：agent-plan:{task_id}:cancel"""
    return f'{AGENT_KEY_PREFIX}{task_id}{CANCEL_KEY_SUFFIX}'


def _update_task_record(task_id, status, result_url=None, error=None):
    """尽力回写 editor_task 记录（error 截断到 VARCHAR(1024) 以内）"""
    try:
        if error:
            error = str(error)[:1000]
        EditorTaskModel().update_result(task_id, status, result_url=result_url, error=error)
    except Exception as db_err:
        print(f'[编辑器Agent] 任务记录回写失败: task_id={task_id}, error={db_err}', flush=True)


@register_task('editor_agent_execute')
async def editor_agent_execute(ctx, payload: dict, task_id: str):
    """
    Agent 计划执行任务

    payload: {plan, user_id, layer_image_url, document_id?,
              retry_from_step?, source_task_id?}
    成功 result: {steps: [{id, tool, status, image_url?}], final_image_url}
    """
    plan = payload.get('plan')
    user_id = payload.get('user_id')
    layer_image_url = payload.get('layer_image_url')
    retry_from = payload.get('retry_from_step')
    source_task_id = payload.get('source_task_id') or task_id

    try:
        # 1. 服务端再次校验计划（防绕过路由直投任务）
        validation = validate_plan(plan)
        if not validation['valid']:
            raise ValueError('计划校验失败: ' + '；'.join(validation['errors'][:3]))
        order = validation['order']
        steps_by_id = {s.get('id'): s for s in plan.get('steps', [])}

        # 2. 确定起始步（单步重试：从指定步重跑，复用原任务中间产物）
        start_idx = 0
        if retry_from:
            if retry_from not in steps_by_id or retry_from not in order:
                raise ValueError(f'重试步骤不存在: {retry_from}')
            start_idx = order.index(retry_from)

        await set_progress(ctx, task_id, '加载图片', pct=2)
        if start_idx == 0:
            current_bytes = _load_image_bytes(layer_image_url)
        else:
            prev_id = order[start_idx - 1]
            current_bytes = await ctx['redis'].get(step_key(source_task_id, prev_id))
            if not current_bytes:
                raise ValueError('前置步骤的中间产物已过期，请重新执行完整计划')

        # 3. 按拓扑序逐步执行
        results = []
        total = len(order)
        for i, sid in enumerate(order[start_idx:], start=start_idx + 1):
            # 取消检查：每步开始前
            if await ctx['redis'].exists(cancel_key(task_id)):
                print(f'[编辑器Agent] 用户取消任务 task_id={task_id}（第 {i} 步前）', flush=True)
                await fail_task(ctx, task_id, '用户取消后续步骤')
                _update_task_record(task_id, 'failed', error='用户取消后续步骤')
                return

            step = steps_by_id[sid]
            tool = get_tool(step.get('tool'))
            label = tool['label'] if tool else step.get('tool')
            await set_progress(
                ctx, task_id, f'步骤 {i}/{total}：{label}',
                pct=int(5 + 90 * (i - 1) / total),
            )

            try:
                img = Image.open(io.BytesIO(current_bytes))
                step_params = step.get('params') or {}
                with img:
                    # AI 工具（module='ai'）额外透传 user_id 供 BYOK 通道解析；基础工具保持原 (image, params) 协议
                    if tool.get('module') == 'ai':
                        result_img = tool['func'](img, step_params, user_id=user_id)
                    else:
                        result_img = tool['func'](img, step_params)
                    buf = io.BytesIO()
                    result_img.save(buf, format='PNG')
                    out_bytes = buf.getvalue()
            except Exception as e:
                completed = [r['id'] for r in results if r.get('status') == 'completed']
                await fail_task(ctx, task_id, {
                    'message': f'步骤 {i}/{total}（{label}）执行失败: {e}',
                    'failed_step': sid,
                    'completed_steps': completed,
                })
                _update_task_record(
                    task_id, 'failed',
                    error=f'步骤 {i}/{total}（{label}）执行失败: {e}',
                )
                return

            # 产物入库 + 中间产物存 Redis（TTL 同任务）
            image_url = save_image_bytes(out_bytes, user_id, 'png', prefix='editor_agent')
            await ctx['redis'].set(step_key(task_id, sid), out_bytes, ex=TASK_RESULT_TTL)
            current_bytes = out_bytes
            results.append({
                'id': sid, 'tool': step.get('tool'),
                'status': 'completed', 'image_url': image_url,
            })

        final_url = results[-1]['image_url'] if results else None
        await complete_task(ctx, task_id, {
            'steps': results,
            'final_image_url': final_url,
        })
        _update_task_record(task_id, 'completed', result_url=final_url)
    except Exception as e:
        await fail_task(ctx, task_id, str(e) or '未知错误')
        _update_task_record(task_id, 'failed', error=str(e) or '未知错误')
