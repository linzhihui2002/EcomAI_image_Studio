"""
编辑器 Agent 修图规划器（LangGraph）

图结构：START → plan（LLM 生成结构化计划）→ validate（服务端校验）
        → [校验失败且未修复过 → repair（带错误反馈重新生成，一次）→ validate] → END

- plan 节点：system prompt 动态注入 registry 工具清单（name/description/params_schema），
  要求只输出 JSON；JSON 解析失败时重试一次 LLM 调用，仍失败返回结构化错误
- LLM 调用复用 services.generation_service.call_llm_chat（LLM_MODEL_NAME/LLM_API_BASE/
  LLM_API_KEY 环境变量，DashScope compatible-mode）
- validate/repair：复用 controllers/editor/agent/validate.py
"""
import json
from typing import TypedDict, Optional, List, Dict, Any

from langgraph.graph import StateGraph, END

from services.generation_service import call_llm_chat, GenerationError
from controllers.editor.tools.registry import list_tools
from controllers.editor.agent.validate import validate_plan

# ========== Prompt（中文，工具清单动态注入） ==========

PLAN_SYSTEM_PROMPT_TEMPLATE = """你是「EcomAI Studio」图片编辑器的智能修图规划助手。用户会给出一条针对当前画布图片的编辑指令，你需要把它拆解为一个可顺序执行的工具调用计划。

可用工具清单（name / description / params_schema）：
{tools_json}

输出要求：
1. 只输出一个合法的 JSON 对象，不要用 markdown 代码块包裹，不要任何额外文字解释
2. JSON 结构必须严格符合：
{{"steps": [{{"id": "step-1", "tool": "<工具name>", "params": {{}}, "depends_on": []}}]}}
3. id 用 step-1、step-2…… 依次编号；params 只能包含该工具 params_schema 中定义的参数，必填参数必须给值
4. 步骤之间存在处理顺序依赖时必须写 depends_on（引用前置步骤的 id），例如"换背景"前需要先"抠图"：换背景步骤的 depends_on 写抠图步骤的 id
5. 只能使用清单内的工具与参数，不要发明工具或参数；用户没有提到的编辑维度不要画蛇添足
6. 计划步骤尽量精简（通常 1-3 步）；mask_data_uri 类参数（选区蒙版）留空字符串，由前端画布提供"""

PARSE_ERROR = {
    'code': 'PLAN_PARSE_FAILED',
    'message': 'AI 生成的计划无法解析为有效 JSON，请调整描述后重试',
}
LLM_ERROR = {
    'code': 'LLM_UNAVAILABLE',
    'message': 'AI 规划服务暂时不可用，请稍后重试',
}


# ========== LangGraph 状态 ==========

class PlannerState(TypedDict):
    """规划工作流状态"""
    instruction: str
    tools: List[dict]              # 工具定义（不含 func）
    plan: Optional[dict]           # 生成的计划
    order: List[str]               # 拓扑执行序列
    errors: List[str]              # 校验错误（中文）
    repaired: bool                 # 是否已执行过修复重试
    error: Optional[dict]          # 结构化错误（不可恢复时）
    user_id: Optional[int]         # 用户 ID（BYOK：透传至 LLM 通道解析；None 走平台通道）


# ========== JSON 解析 ==========

def _strip_json_fences(text):
    """剥掉 ```json ... ``` 包裹"""
    text = (text or '').strip()
    if text.startswith('```'):
        first_newline = text.find('\n')
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.rstrip().endswith('```'):
            text = text.rstrip()[:-3]
    return text.strip()


def _parse_plan_json(text):
    """解析 LLM 输出的计划 JSON；失败抛 ValueError（中文）"""
    for candidate in (text, _strip_json_fences(text)):
        if not candidate:
            continue
        try:
            plan = json.loads(candidate)
            if isinstance(plan, dict):
                return plan
        except (json.JSONDecodeError, ValueError):
            continue
    raise ValueError('AI 输出无法解析为 JSON 对象')


# ========== LLM 调用封装（一次调用 + 解析失败重试一次） ==========

def _call_plan_llm(instruction, tools, feedback=None, user_id=None):
    """
    调用一次 LLM 生成计划并解析。
    - 首次解析失败 → 再调用一次 LLM 重试（共最多 2 次调用）
    - 仍失败返回 (None, PARSE_ERROR)；网络/服务异常返回 (None, LLM_ERROR)
    - feedback 非空时作为修复反馈拼入用户消息（repair 节点用）
    - user_id：用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）
    """
    system_prompt = PLAN_SYSTEM_PROMPT_TEMPLATE.format(
        tools_json=json.dumps(tools, ensure_ascii=False),
    )
    user_content = f'用户编辑指令：{instruction}'
    if feedback:
        user_content += (
            f'\n\n你上一次生成的计划未通过服务端校验，错误如下：\n'
            f'{json.dumps(feedback, ensure_ascii=False)}\n'
            f'请修正这些问题后重新输出完整计划 JSON（仍然只输出 JSON）。'
        )

    last_parse_error = None
    for attempt in range(2):  # 首次 + 解析失败重试 1 次
        try:
            content = call_llm_chat(
                system_prompt=system_prompt,
                user_content=user_content,
                temperature=0.3,
                max_tokens=2000,
                user_id=user_id,
            )
            return _parse_plan_json(content), None
        except ValueError as e:
            last_parse_error = str(e)
            print(f'[编辑器Agent] 计划 JSON 解析失败（第 {attempt + 1} 次）: {e}', flush=True)
        except GenerationError as e:
            print(f'[编辑器Agent] LLM 调用失败: {e.message}', flush=True)
            return None, {**LLM_ERROR, 'message': f"{LLM_ERROR['message']}（{e.message}）"}
    return None, PARSE_ERROR


# ========== LangGraph 节点 ==========

def plan_node(state: PlannerState) -> dict:
    """plan 节点：LLM 生成结构化计划（解析失败自动重试一次）"""
    plan, error = _call_plan_llm(state['instruction'], state['tools'],
                                 user_id=state.get('user_id'))
    if error:
        return {'error': error}
    return {'plan': plan, 'error': None}


def validate_node(state: PlannerState) -> dict:
    """validate 节点：服务端校验计划"""
    plan = state.get('plan')
    if plan is None:
        return {'errors': [], 'order': []}
    validation = validate_plan(plan, state['tools'])
    return {'errors': validation['errors'], 'order': validation['order']}


def repair_node(state: PlannerState) -> dict:
    """repair 节点：携带校验错误反馈重新生成计划（仅一次）"""
    plan, error = _call_plan_llm(
        state['instruction'], state['tools'], feedback=state.get('errors') or [],
        user_id=state.get('user_id'),
    )
    if error:
        # 修复失败：保留原错误与原计划校验结果，走"不可恢复"出口
        return {'error': error, 'repaired': True}
    return {'plan': plan, 'repaired': True}


def _route_after_plan(state: PlannerState) -> str:
    if state.get('error'):
        return END
    return 'validate'


def _route_after_validate(state: PlannerState) -> str:
    if not state.get('errors'):
        return END
    if not state.get('repaired'):
        return 'repair'
    return END


def _build_planner_graph():
    workflow = StateGraph(PlannerState)
    workflow.add_node('plan', plan_node)
    workflow.add_node('validate', validate_node)
    workflow.add_node('repair', repair_node)
    workflow.set_entry_point('plan')
    workflow.add_conditional_edges('plan', _route_after_plan, {
        'validate': 'validate',
        END: END,
    })
    workflow.add_conditional_edges('validate', _route_after_validate, {
        'repair': 'repair',
        END: END,
    })
    workflow.add_edge('repair', 'validate')
    return workflow.compile()


# 模块级编译好的规划图（与 workflows/smart_generation 的全局图写法一致）
editor_planner_graph = _build_planner_graph()


# ========== 对外入口 ==========

def generate_plan(instruction: str, tools: Optional[List[dict]] = None,
                  user_id: int = None) -> Dict[str, Any]:
    """
    执行规划工作流（同步，LLM 一次调用约 3-8 秒）

    Args:
        user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

    Returns:
        {'plan': dict|None, 'order': [step_id...], 'errors': [中文]|[],
         'error': 结构化错误|None}
        - 校验通过：errors 为空，plan/order 可用
        - 校验失败：errors 非空（plan 仍返回，供前端参考）
        - 解析/服务失败：error 非空
    """
    if tools is None:
        tools = list_tools()
    state = editor_planner_graph.invoke({
        'instruction': instruction,
        'tools': tools,
        'plan': None,
        'order': [],
        'errors': [],
        'repaired': False,
        'error': None,
        'user_id': user_id,
    })
    return {
        'plan': state.get('plan'),
        'order': state.get('order', []),
        'errors': state.get('errors', []),
        'error': state.get('error'),
    }
