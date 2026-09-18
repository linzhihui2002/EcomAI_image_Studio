/**
 * AI 图片编辑器 API 封装
 *
 * 端点清单（均需 Bearer Token，响应 {code, message, data}）：
 * - GET    /editor/tools                        工具注册表（工具栏数据源）
 * - POST   /editor/tools/<tool>/execute         提交工具异步任务
 * - GET    /editor/tasks/<task_id>              任务状态查询（SSE 降级轮询通道）
 * - POST   /editor/documents                    创建编辑文档（图层）
 * - GET    /editor/documents/<id>               文档详情（含 layers）
 * - PUT    /editor/documents/<id>               更新文档（自动保存）
 * - GET    /editor/documents                    当前用户文档列表
 * - POST   /editor/documents/<id>/save-history  保存到历史记录
 * - POST   /editor/agent/plan                   AI 生成修图计划（同步）
 * - POST   /editor/agent/execute                校验计划并提交异步执行
 * - POST   /editor/agent/tasks/<id>/cancel      取消后续步骤
 * - POST   /editor/agent/tasks/<id>/retry       单步重试（返回新 task_id）
 */
import { api } from './client'

// ===== 类型定义 =====

/** 单个工具参数的 schema 规则（与后端 registry.params_schema 对齐） */
export interface EditorParamRule {
  /** 参数类型：number（含整数）/ boolean / string */
  type: 'number' | 'boolean' | 'string'
  /** 是否必填 */
  required?: boolean
  /** 数字最小值（含边界） */
  min?: number
  /** 数字最大值（含边界） */
  max?: number
  /** 数字是否必须为整数 */
  integer?: boolean
  /** 允许的枚举值列表（存在时按下拉渲染） */
  choices?: Array<number | string>
  /** 默认值（前端展示用） */
  default?: number | string | boolean
  /** 中文参数名（前端展示用） */
  label?: string
}

/** 工具定义（GET /editor/tools 返回项） */
export interface EditorTool {
  name: string
  label: string
  description: string
  module: string
  params_schema: Record<string, EditorParamRule>
  /** 是否需要选区蒙版（registry 中 module='ai' 的 inpaint 类工具） */
  requires_mask?: boolean
}

/** 图层文档（与后端 controllers/editor/layers.py 定义的 JSON 结构一致） */
export interface EditorLayer {
  id: string
  type: 'image' | 'text'
  /** image 类型必填，图层图片地址（本服务地址或 data URI） */
  url?: string
  /** text 类型必填，文字内容 */
  text?: string
  x: number
  y: number
  width: number
  height: number
  rotation?: number
  /** 不透明度 0~1 */
  opacity?: number
  visible?: boolean
  locked?: boolean
  /** 层级，越大越靠上 */
  z: number
}

/** 编辑文档完整结构 */
export interface EditorDocument {
  id: number
  user_id?: number
  source_image_id?: string | null
  title: string
  layers: EditorLayer[]
  created_at?: string
  updated_at?: string
}

/** 文档列表项（不含 layers） */
export interface EditorDocumentListItem {
  id: number
  title: string
  source_image_id?: string | null
  updated_at: string
}

/** 创建文档请求体 */
export interface CreateEditorDocumentPayload {
  source_image_id?: string
  title?: string
  layers?: EditorLayer[]
}

/** 更新文档请求体（title 与 layers 至少提供一个） */
export interface UpdateEditorDocumentPayload {
  title?: string
  layers?: EditorLayer[]
}

/** 工具执行结果图信息 */
export interface EditorTaskResult {
  image_url: string
  width?: number
  height?: number
  tool?: string
}

/** 工具任务状态（与 useTaskSse 的 TaskStatus 结构兼容，可直接作 pollFn 返回值） */
export interface EditorTaskStatus {
  task_id: string
  tool?: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  step: string
  pct: number
  result: EditorTaskResult | null
  error: string | null
  created_at?: string
  updated_at?: string
}

/** 提交工具执行的响应 */
export interface EditorExecuteResult {
  task_id: string
  status: 'queued'
}

/** 保存到历史记录的响应 */
export interface EditorSaveHistoryResult {
  history_id: number
}

// ===== API 函数 =====

/**
 * 获取工具注册表（工具栏数据源，P1 含 color_adjust/crop/flip/rotate）
 */
export async function fetchEditorTools(): Promise<EditorTool[]> {
  const response = await api.get<{ code: number; message: string; data: EditorTool[] }>(
    '/editor/tools',
  )
  return response.data
}

/**
 * 提交工具执行异步任务
 * @param tool 工具名（如 color_adjust）
 * @param imageUrl 目标图层图片地址（本服务 /api/v1/images/... 或 data URI）
 * @param params 按该工具 params_schema 校验的参数
 */
export async function executeEditorTool(
  tool: string,
  imageUrl: string,
  params: Record<string, number | string | boolean>,
): Promise<EditorExecuteResult> {
  const response = await api.post<{ code: number; message: string; data: EditorExecuteResult }>(
    `/editor/tools/${tool}/execute`,
    { image_url: imageUrl, params },
  )
  return response.data
}

/**
 * 查询工具任务状态（SSE 降级轮询通道，归属校验 403 由 client 统一翻译）
 */
export async function fetchEditorTaskStatus(taskId: string): Promise<EditorTaskStatus> {
  const response = await api.get<{ code: number; message: string; data: EditorTaskStatus }>(
    `/editor/tasks/${taskId}`,
  )
  return response.data
}

/**
 * 创建编辑文档（无 documentId 时自动保存先走此端点）
 */
export async function createEditorDocument(
  payload: CreateEditorDocumentPayload,
): Promise<EditorDocument> {
  const response = await api.post<{ code: number; message: string; data: EditorDocument }>(
    '/editor/documents',
    payload,
  )
  return response.data
}

/**
 * 获取文档详情（含 layers）
 */
export async function fetchEditorDocument(documentId: number): Promise<EditorDocument> {
  const response = await api.get<{ code: number; message: string; data: EditorDocument }>(
    `/editor/documents/${documentId}`,
  )
  return response.data
}

/**
 * 更新文档（自动保存用），返回更新后的完整文档
 */
export async function updateEditorDocument(
  documentId: number,
  payload: UpdateEditorDocumentPayload,
): Promise<EditorDocument> {
  const response = await api.put<{ code: number; message: string; data: EditorDocument }>(
    `/editor/documents/${documentId}`,
    payload,
  )
  return response.data
}

/**
 * 当前用户文档列表（updated_at 倒序，不含 layers）
 */
export async function fetchEditorDocuments(): Promise<{
  items: EditorDocumentListItem[]
  total: number
}> {
  const response = await api.get<{
    code: number
    message: string
    data: { items: EditorDocumentListItem[]; total: number }
  }>('/editor/documents')
  return response.data
}

/**
 * 保存文档当前效果到历史记录（sub_category='editor'）
 * @param documentId 文档 ID
 * @param resultImageUrl 编辑结果图地址（本服务地址或 data URI）
 */
export async function saveEditorDocumentHistory(
  documentId: number,
  resultImageUrl: string,
): Promise<EditorSaveHistoryResult> {
  const response = await api.post<{
    code: number
    message: string
    data: EditorSaveHistoryResult
  }>(`/editor/documents/${documentId}/save-history`, { result_image_url: resultImageUrl })
  return response.data
}

// ===== Agent 修图规划与执行 =====

/** Agent 计划中的单个工具调用步骤 */
export interface AgentStep {
  id: string
  tool: string
  params: Record<string, number | string | boolean>
  /** 依赖的前置步骤 id 列表（后端校验会补全缺省为 []） */
  depends_on?: string[]
}

/** Agent 计划对象（plan.steps，可人工微调后提交执行） */
export interface AgentPlan {
  steps: AgentStep[]
}

/** POST /editor/agent/plan 响应 data */
export interface AgentPlanResult {
  plan: AgentPlan
  /** 拓扑执行序列（step id 列表） */
  order: string[]
  /** 计划校验错误（非空时计划不可直接执行） */
  errors?: string[]
}

/** Agent 执行 / 重试任务提交响应 data */
export interface AgentTaskRef {
  task_id: string
  status: 'queued' | string
}

/** POST /editor/agent/tasks/<task_id>/cancel 响应 data */
export interface AgentCancelResult {
  ok: boolean
}

/** Agent 任务 result.steps 中的单项（执行中/完成后逐步填充） */
export interface AgentStepResult {
  id: string
  tool: string
  status: string
  image_url?: string
}

/** Agent 任务 result 结构（GET /editor/tasks/<task_id> 的 result 字段） */
export interface AgentTaskResult {
  steps: AgentStepResult[]
  final_image_url: string | null
}

/** Agent 任务失败时的结构化 error（后端 fail_task 传入对象时） */
export interface AgentTaskError {
  message: string
  failed_step?: string
  completed_steps?: string[]
}

/**
 * AI 生成修图计划（同步，LLM 一次调用约 3-8 秒；LLM 不可用时后端返回 502）
 * @param instruction 中文编辑指令
 * @param opts 可选上下文：来源文档 ID / 来源图地址（仅作规划上下文，不读图）
 */
export async function agentPlan(
  instruction: string,
  opts: { documentId?: number; imageUrl?: string } = {},
): Promise<AgentPlanResult> {
  const response = await api.post<{ code: number; message: string; data: AgentPlanResult }>(
    '/editor/agent/plan',
    {
      instruction,
      ...(opts.documentId !== undefined ? { document_id: opts.documentId } : {}),
      ...(opts.imageUrl ? { image_url: opts.imageUrl } : {}),
    },
  )
  return response.data
}

/**
 * 校验计划并提交异步执行（校验失败后端返回 400，errors 随 message 返回）
 * @param plan 计划对象（mask_data_uri 为空的蒙版步骤需前端先填入涂抹生成的蒙版）
 * @param opts 来源：image_url 与 document_id 二选一（document_id 取文档第一个图片图层）
 */
export async function agentExecute(
  plan: AgentPlan,
  opts: { imageUrl?: string; documentId?: number } = {},
): Promise<AgentTaskRef> {
  const response = await api.post<{ code: number; message: string; data: AgentTaskRef }>(
    '/editor/agent/execute',
    {
      plan,
      ...(opts.imageUrl ? { image_url: opts.imageUrl } : {}),
      ...(opts.documentId !== undefined ? { document_id: opts.documentId } : {}),
    },
  )
  return response.data
}

/** 取消后续步骤（写入取消标记，执行器在每步开始前检查） */
export async function agentCancelTask(taskId: string): Promise<AgentCancelResult> {
  const response = await api.post<{ code: number; message: string; data: AgentCancelResult }>(
    `/editor/agent/tasks/${taskId}/cancel`,
  )
  return response.data
}

/** 单步重试：从指定步骤重跑（复用原任务已完成步的中间产物），返回新任务 */
export async function agentRetryTask(taskId: string, stepId: string): Promise<AgentTaskRef> {
  const response = await api.post<{ code: number; message: string; data: AgentTaskRef }>(
    `/editor/agent/tasks/${taskId}/retry`,
    { step_id: stepId },
  )
  return response.data
}
