import { api } from './client'
import type { TemplateSellingPointEn } from './template'

// ===== 类型定义 =====

/** 批量任务单个商品入参 */
export interface BatchProductInput {
  /** 商品唯一标识（前端生成：序号 + 文件名摘要） */
  product_id: string
  product_name: string
  /** 商品图 Base64 data URL */
  product_image: string
  /** 中文卖点（可选） */
  selling_points?: string
  /** 英文卖点（可选，AI 商品分析编辑后的结构） */
  selling_points_en?: TemplateSellingPointEn[]
  /** 中文场景描述（可选） */
  scene_zh?: string
}

/** POST /batch/tasks 请求体 */
export interface BatchSubmitPayload {
  products: BatchProductInput[]
  /** 目标站点市场码大写列表（如 ["US", "DE"]） */
  sites: string[]
  /** 图片类型列表（如 ["main", "scene", "detail"]） */
  image_types: string[]
  /** 电商平台键（amazon/temu/shopee/tiktok_shop/aliexpress/ozon） */
  platform: string
  /** 输出尺寸（如 "1024x1024"） */
  size: string
  /** 图组预设（如 "tiktok_showcase"，选中后 image_types 由后端固定） */
  image_group?: string
  /** 风格锁定提示（可选） */
  style_lock_hint?: string
}

/** POST /batch/tasks 响应 data（预检通过即锁定灵感币） */
export interface BatchSubmitResult {
  batch_task_id: string
  total_items: number
  coins_locked: number
  unit_cost: number
  feature_key: string
  warnings: string[]
}

/** 批量明细项状态 */
export type BatchItemStatus = 'planned' | 'running' | 'completed' | 'failed'

/** 合规审查问题项 */
export interface BatchReviewIssue {
  rule: string
  detail: string
}

/** 单项合规审查结果（后端审查引擎输出） */
export interface BatchItemReview {
  riskLevel: 'high' | 'medium' | 'low' | 'unknown'
  issues: BatchReviewIssue[]
  fixSuggestions: string[]
}

/** GET /batch/tasks/{id}/manifest 明细项 */
export interface BatchManifestItem {
  item_key: string
  product_id: string
  site: string
  image_type: string
  prompt: string
  status: BatchItemStatus | string
  error: string | null
  result_url: string | null
  review: BatchItemReview | null
  coins: number
}

/** manifest 批次摘要 */
export interface BatchManifestBatch {
  task_id: string
  status: string
  total_items: number
  succeeded_items: number
  failed_items: number
  coins_locked: number
  platform: string
}

/** GET /batch/tasks/{id}/manifest 响应 data */
export interface BatchManifest {
  batch: BatchManifestBatch
  items: BatchManifestItem[]
  /** 各状态计数（如 { completed: 3, failed: 1, running: 2 }） */
  counts: Record<string, number>
  page: number
  total: number
}

/** POST /batch/tasks/{id}/retry 响应 data */
export interface BatchRetryResult {
  batch_task_id: string
  retry_items: number
  task_id: string
}

/** manifest 查询参数 */
export interface BatchManifestParams {
  status?: string
  page?: number
  page_size?: number
}

// ===== API 函数 =====

/**
 * 提交批量生成任务（JWT）
 * 后端预检（库存/定价/合规等）失败时抛出 ApiError（HTTP 400），err.data 内含失败原因
 */
export async function submitBatchTask(
  payload: BatchSubmitPayload
): Promise<BatchSubmitResult> {
  const response = await api.post<{
    code: number
    data: BatchSubmitResult
  }>('/batch/tasks', payload, 120000)  // 商品图 base64 体积较大，2 分钟超时
  return (response as any).data
}

/**
 * 查询批量任务 manifest（批次摘要 + 明细项 + 各状态计数）
 */
export async function getBatchManifest(
  taskId: string,
  params?: BatchManifestParams
): Promise<BatchManifest> {
  const response = await api.get<{
    code: number
    data: BatchManifest
  }>(`/batch/tasks/${taskId}/manifest`, params, 30000)
  return (response as any).data
}

/**
 * 重试批量任务中的失败项（completed 无失败项或 running 中时后端返回 400）
 */
export async function retryBatchTask(taskId: string): Promise<BatchRetryResult> {
  const response = await api.post<{
    code: number
    data: BatchRetryResult
  }>(`/batch/tasks/${taskId}/retry`, undefined, 30000)
  return (response as any).data
}
