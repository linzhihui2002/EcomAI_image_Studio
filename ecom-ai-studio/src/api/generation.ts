import { api, ApiError } from './client'
import type {
  ProAnalyzeIntegrateRequest,
  ProAnalyzeIntegrateResponseData,
  ProDialogOptimizeRequest,
  ProDialogOptimizeResponseData,
  ProConfirmRequest,
  ProConfirmResponseData,
  ProBatchStatusResponse,
  ProTaskState,
} from '@/types'

export interface ProductInfoResult {
  product_name: string
  target_audience: string
  selling_points: string
  usage_scenario: string
  product_category: string
}

export interface ImageGroupSlot {
  id: string
  name: string
  desc: string
}

export interface ImageGroup {
  key: string
  label: string
  hint: string
  min: number
  needName: boolean
  needDesc: boolean
  slots: ImageGroupSlot[]
}

export interface SmartGenerateRequest {
  product_images: string[]
  reference_image?: string | null
  reference_text?: string | null
  platform: string
  region: string
  target_language: string
  size: string
  product_info?: ProductInfoResult | null
  image_groups: ImageGroup[]
}

export interface GenerationTask {
  task_id: string
  batch_id: string
  image_type: 'white_bg' | 'scene' | 'selling_point' | 'other'
  slot_index: number
  slot_name: string
  slot_desc: string
  status: 'pending' | 'processing' | 'success' | 'failed'
  prompt_used: string
  image_url: string | null
  error_msg: string | null
  has_image?: boolean
}

export interface SmartGenerateResponse {
  batch_id: string
  tasks: GenerationTask[]
}

export interface DeleteTaskResponse {
  task_id: string
  batch_id: string
}

export interface DeleteBatchResponse {
  batch_id: string
  deleted_tasks: number
}

export async function analyzeProduct(
  imageBase64: string,
  existingText?: string
): Promise<ProductInfoResult> {
  const response = await api.post<{
    code: number
    data: ProductInfoResult
  }>('/generation/analyze-product', {
    image_base64: imageBase64,
    existing_text: existingText || null,
  }, 120000)
  return (response as any).data
}

export async function smartGenerate(
  params: SmartGenerateRequest
): Promise<SmartGenerateResponse> {
  const response = await api.post<{
    code: number
    data: SmartGenerateResponse
  }>('/generation/smart-generate', params, 30000)
  return (response as any).data
}

export async function getTaskStatus(taskId: string): Promise<GenerationTask> {
  const response = await api.get<{
    code: number
    data: GenerationTask
  }>(`/generation/tasks/${taskId}`)
  return (response as any).data
}

export async function getBatchStatus(batchId: string): Promise<SmartGenerateResponse> {
  const response = await api.get<{
    code: number
    data: SmartGenerateResponse
  }>(`/generation/batches/${batchId}`)
  return (response as any).data
}

export async function deleteTask(taskId: string): Promise<DeleteTaskResponse> {
  const response = await api.delete<{
    code: number
    data: DeleteTaskResponse
  }>(`/generation/tasks/${taskId}`)
  return (response as any).data
}

export async function deleteBatch(batchId: string): Promise<DeleteBatchResponse> {
  const response = await api.delete<{
    code: number
    data: DeleteBatchResponse
  }>(`/generation/batches/${batchId}`)
  return (response as any).data
}

export async function retryTask(taskId: string): Promise<GenerationTask> {
  const response = await api.post<{
    code: number
    data: GenerationTask
  }>(`/generation/tasks/${taskId}/retry`)
  return (response as any).data
}

// ==================== 专业模式(Pro Mode)API ====================

/**
 * 专业模式 - 阶段一:AI 分析整合
 * 提交商品图与任务列表,后端调用 LLM 为每个任务生成结构化提示词方案。
 * 由于可能涉及多模态商品信息补全 + 多任务并发 LLM 调用,设置 300 秒超时。
 */
export async function proAnalyzeIntegrate(
  params: ProAnalyzeIntegrateRequest
): Promise<ProAnalyzeIntegrateResponseData> {
  const response = await api.post<{
    code: number
    data: ProAnalyzeIntegrateResponseData
  }>('/generation/pro/analyze-integrate', params, 300000)
  return (response as any).data
}

/**
 * 专业模式 - 阶段二:AI 对话优化
 * 基于用户指令,对指定任务的提示词方案进行优化。
 * 单轮 LLM 调用,设置 60 秒超时。
 */
export async function proDialogOptimize(
  params: ProDialogOptimizeRequest
): Promise<ProDialogOptimizeResponseData> {
  const response = await api.post<{
    code: number
    data: ProDialogOptimizeResponseData
  }>('/generation/pro/dialog-optimize', params, 60000)
  return (response as any).data
}

/**
 * 专业模式 - 阶段三:确认方案并触发生图
 * 锁定批次方案,后台并发生成图片。立即返回任务 ID 供前端轮询。
 */
export async function proConfirmGenerate(
  params: ProConfirmRequest
): Promise<ProConfirmResponseData> {
  const response = await api.post<{
    code: number
    data: ProConfirmResponseData
  }>('/generation/pro/confirm', params, 30000)
  return (response as any).data
}

/**
 * 专业模式 - 查询批次任务状态(含提示词方案/对话历史/生图进度)
 */
export async function getProBatchStatus(
  batchId: string
): Promise<ProBatchStatusResponse> {
  const response = await api.get<{
    code: number
    data: ProBatchStatusResponse
  }>(`/generation/pro/batches/${batchId}`)
  return (response as any).data
}

/**
 * 专业模式 - 一键AI补全空方案
 * 为批次中所有方案为空或失败的任务重新调用 LLM 生成方案。
 * 由于涉及 LLM 调用，设置 300 秒超时。
 */
export async function proAutoFillSchemes(
  batchId: string
): Promise<{ batch_id: string; tasks: ProTaskState[]; filled_count: number }> {
  const response = await api.post<{
    code: number
    data: { batch_id: string; tasks: ProTaskState[]; filled_count: number }
  }>('/generation/pro/auto-fill-schemes', { batch_id: batchId }, 300000)
  return (response as any).data
}
