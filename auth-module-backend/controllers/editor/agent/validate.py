"""
编辑器 Agent 计划校验器

对 LLM 生成的工具调用计划做服务端校验：
- steps 非空、id 唯一、tool 存在于 registry、params 符合 params_schema（必填/类型/枚举）
- depends_on 引用存在且无环（DFS 检测）
- 依赖补全：只做引用级补全（如计划中同时存在抠图与换背景、但换背景漏写依赖时
  自动补 depends_on），不自动添加步骤
- 拓扑排序（Kahn）输出执行序列

返回 {'valid': bool, 'errors': [中文错误], 'order': [按执行顺序排列的 step_id]}
"""
from controllers.editor.tools.registry import EDITOR_TOOLS, validate_params

# 引用级依赖补全规则：key 工具若与 value 工具的步骤同时出现在计划中，
# 且 key 步骤漏写对 value 步骤的依赖，则自动补上（不新增步骤）
_SOFT_DEPENDENCIES = {
    'replace_background': 'remove_background',  # 换背景前需先抠出主体
}

_MASK_FIELD = 'mask_data_uri'


def _check_structure(plan):
    """结构性校验，返回 (steps, errors)"""
    errors = []
    if not isinstance(plan, dict):
        return [], ['计划必须为 JSON 对象']
    steps = plan.get('steps')
    if not isinstance(steps, list) or not steps:
        return [], ['计划不能为空（steps 需为非空数组）']

    seen_ids = set()
    clean_steps = []
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            errors.append(f'第 {idx} 个步骤必须为对象')
            continue
        step_id = step.get('id')
        if not isinstance(step_id, str) or not step_id.strip():
            errors.append(f'第 {idx} 个步骤缺少有效的 id')
            continue
        if step_id in seen_ids:
            errors.append(f'步骤 id 重复: {step_id}')
        seen_ids.add(step_id)
        clean_steps.append(step)
    return clean_steps, errors


def _check_tools_and_params(steps, tool_map):
    """工具存在性与参数校验，返回错误列表"""
    errors = []
    for step in steps:
        sid = step.get('id')
        tool_name = step.get('tool')
        if not isinstance(tool_name, str) or tool_name not in tool_map:
            errors.append(f'步骤 {sid}：未知工具 "{tool_name}"')
            continue
        schema = tool_map[tool_name].get('params_schema') or {}
        params = step.get('params')
        if params is None:
            params = {}
            step['params'] = params
        if not isinstance(params, dict):
            errors.append(f'步骤 {sid}：params 必须为对象')
            continue
        try:
            validate_params(schema, params)
        except ValueError as e:
            errors.append(f'步骤 {sid}：{e}')
    return errors


def _check_dependencies(steps):
    """依赖字段校验（引用存在、类型正确），返回错误列表"""
    errors = []
    all_ids = {s.get('id') for s in steps if isinstance(s.get('id'), str)}
    for step in steps:
        sid = step.get('id')
        deps = step.get('depends_on')
        if deps is None:
            step['depends_on'] = []
            continue
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            errors.append(f'步骤 {sid}：depends_on 必须为字符串数组')
            step['depends_on'] = []
            continue
        for dep in deps:
            if dep == sid:
                errors.append(f'步骤 {sid}：依赖了自身')
            elif dep not in all_ids:
                errors.append(f'步骤 {sid}：依赖的步骤不存在: {dep}')
    return errors


def _complete_dependencies(steps):
    """
    引用级依赖补全：规则见表 _SOFT_DEPENDENCIES
    仅当被依赖步骤确实存在于计划中且依赖尚未写入时补 depends_on
    """
    tool_by_id = {s.get('id'): s.get('tool') for s in steps}
    for step in steps:
        required_tool = _SOFT_DEPENDENCIES.get(step.get('tool'))
        if not required_tool:
            continue
        for other in steps:
            if other is step or other.get('tool') != required_tool:
                continue
            if other.get('id') in step['depends_on']:
                continue
            step['depends_on'].append(other.get('id'))


def _detect_cycle(steps):
    """
    DFS 环检测（仅统计依赖引用有效的步骤）
    返回环路径描述（如 'a -> b -> a'）或 None
    """
    deps = {}
    valid_ids = {s.get('id') for s in steps}
    for s in steps:
        deps[s.get('id')] = [d for d in s.get('depends_on', []) if d in valid_ids]

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {sid: WHITE for sid in deps}
    cycle_path = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for dep in deps.get(node, []):
            if color[dep] == GRAY:
                cycle_path.extend(path[path.index(dep):] + [dep])
                return True
            if color[dep] == WHITE and dfs(dep, path):
                return True
        path.pop()
        color[node] = BLACK
        return False

    for sid in deps:
        if color[sid] == WHITE and dfs(sid, []):
            return ' -> '.join(cycle_path)
    return None


def _topological_order(steps):
    """
    Kahn 拓扑排序（前提：无环、id 唯一）
    返回按执行顺序排列的 step_id 列表
    """
    ids = [s.get('id') for s in steps]
    in_degree = {sid: 0 for sid in ids}
    dependents = {sid: [] for sid in ids}
    for s in steps:
        for dep in s.get('depends_on', []):
            if dep in in_degree:
                in_degree[s.get('id')] += 1
                dependents[dep].append(s.get('id'))

    queue = [sid for sid in ids if in_degree[sid] == 0]
    order = []
    while queue:
        sid = queue.pop(0)
        order.append(sid)
        for nxt in dependents[sid]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    return order


def validate_plan(plan, tools=None):
    """
    校验 Agent 修图计划（校验过程会就地补全 plan 的缺省字段：
    params 缺省为 {}、depends_on 缺省为 []、引用级依赖补全）

    Args:
        plan: LLM 生成的计划对象 {'steps': [...]}
        tools: 工具定义列表（缺省用 registry.EDITOR_TOOLS）

    Returns:
        {'valid': bool, 'errors': [中文], 'order': [step_id, ...]}
        存在环时 order 为空列表
    """
    if tools is None:
        tools = EDITOR_TOOLS
    tool_map = {t['name']: t for t in tools}

    steps, errors = _check_structure(plan)
    if steps:
        errors.extend(_check_tools_and_params(steps, tool_map))
        errors.extend(_check_dependencies(steps))
        _complete_dependencies(steps)
        cycle = _detect_cycle(steps)
        if cycle:
            errors.append(f'步骤依赖存在循环: {cycle}')
            return {'valid': False, 'errors': errors, 'order': []}
        order = _topological_order(steps)
    else:
        order = []
    return {'valid': not errors, 'errors': errors, 'order': order}
