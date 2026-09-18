import { api, ApiError } from './client'

// ===== 类型定义 =====

export interface PlanAnalysisRequest {
  images: string[]              // Base64 data URL 数组
  file_content?: string         // 可选的说明文件文本（txt/md/json 等纯文本文件）
  prompt?: string               // 可选的用户自定义提示词
  file_data?: string            // 可选的二进制文件 base64（PDF/DOC/PPT/XLS/图片等需 MinerU 解析的文件）
  file_name?: string            // 可选的二进制文件名
}

export interface PlanImage {
  index: number
  title: string
  plan: string
  reason: string
  prompt_cn: string
  prompt_en: string
  backup_prompt_cn: string
  backup_prompt_en: string
}

export interface PlanAnalysisResult {
  plan: {
    summary: string
    images: PlanImage[]
    raw_text?: string
  }
}

export interface PlanAnalysisAsyncResult {
  task_id: number
  status: string  // "processing"
}

export interface PlanAnalysisTaskStatus {
  id: number
  status: string  // "processing" | "completed" | "failed"
  result_json?: PlanAnalysisResult['plan'] | null
  error_message?: string | null
  created_at?: string
  updated_at?: string
}

export interface ImageMergeRequest {
  images: string[]              // Base64 data URL 数组（2-10 张）
}

export interface ImageMergeAsyncResult {
  task_id: string
  status: string                // "processing"
}

export interface MergeVerification {
  passed: boolean
  issues: string[]
}

export interface MergeTaskResult {
  image: string
  verification: MergeVerification
}

export interface MergeTaskStatus {
  task_id: string
  status: string                // "processing" | "completed" | "failed"
  progress: string              // 当前步骤描述
  result?: MergeTaskResult      // 仅 completed 时存在
  error?: string                // 仅 failed 时存在
}

export interface ImageResult {
  image: string                 // Base64 data URL
}



export interface TextToImageRequest {
  prompt: string
  size?: string                 // 如 "1024x1024"
  quality?: string              // "low" | "medium" | "high" | "auto"
}

export interface ChatMessage {
  role: string
  content: string
}

export interface ChatGenerateRequest {
  messages: ChatMessage[]
  reference_images?: string[]   // 可选参考图 Base64 data URL 数组
}

export interface ChatGenerateResult {
  reply: string
  images: string[]              // data URL 数组
}

// ===== API 函数 =====

/**
 * 生图计划分析 - 调用多模态 LLM 分析商品图，返回结构化生图计划
 */
export async function analyzePlan(
  payload: PlanAnalysisRequest
): Promise<PlanAnalysisAsyncResult> {
  const response = await api.post<{
    code: number
    data: PlanAnalysisAsyncResult
  }>('/toolbox/plan-analysis', payload, 300000)  // 5 分钟超时，适配 MinerU 文档解析 + AI 多模态分析耗时
  return (response as any).data
}

/**
 * 查询生图计划分析任务状态
 */
export async function getPlanAnalysisStatus(
  taskId: number
): Promise<PlanAnalysisTaskStatus> {
  const response = await api.get<{
    code: number
    data: PlanAnalysisTaskStatus
  }>(`/toolbox/plan-analysis/status/${taskId}`)
  return (response as any).data
}

/**
 * 图片合并 - 将多张产品图智能拼接至单张图（重点支持多角度视图合并）
 */
export async function mergeImages(
  payload: ImageMergeRequest
): Promise<ImageMergeAsyncResult> {
  const response = await api.post<{
    code: number
    data: ImageMergeAsyncResult
  }>('/toolbox/image-merge', payload, 300000)  // 5 分钟超时
  return (response as any).data
}

/**
 * 查询图片合并任务状态
 */
export async function getMergeStatus(
  taskId: string
): Promise<MergeTaskStatus> {
  const response = await api.get<{
    code: number
    data: MergeTaskStatus
  }>(`/toolbox/image-merge/status/${taskId}`)
  return (response as any).data
}



/**
 * 文生图 - 根据文本描述生成图片
 */
export async function textToImage(
  payload: TextToImageRequest
): Promise<ImageResult> {
  const response = await api.post<{
    code: number
    data: ImageResult
  }>('/toolbox/text-to-image', payload, 120000)  // 2 分钟超时，适配文生图模型耗时
  return (response as any).data
}

/**
 * 对话式生图 - AI 判断用户需求是否明确，明确则调用文生图，不明确则返回澄清问题
 */
export async function chatGenerate(
  payload: ChatGenerateRequest
): Promise<ChatGenerateResult> {
  const response = await api.post<{
    code: number
    data: ChatGenerateResult
  }>('/toolbox/chat-gen', payload, 120000)  // 2 分钟超时，适配对话+生图耗时
  return (response as any).data
}

export interface ProductReplaceRequest {
  product_image: string       // 商品图 Base64 data URL（必填）
  reference_image: string     // 参考图 Base64 data URL（必填）
  prompt?: string             // 可选提示词
}

export interface ProductReplaceAsyncResult {
  task_id: string
  status: string                // "processing"
}

export interface ProductReplaceTaskStatus {
  task_id: string
  status: string                // "processing" | "completed" | "failed"
  progress: string              // 当前步骤描述
  result?: ImageResult          // 仅 completed 时存在
  error?: string                // 仅 failed 时存在
}

export interface AiModelRequest {
  person_image?: string       // 人物图 Base64 data URL（可选）
  country: string             // 国家（必填）
  race: string                // 人种（必填）
  prompt: string              // 提示词（必填）
}

export interface ModelProductRequest {
  product_image: string       // 商品图 Base64 data URL（必填）
  model_image: string         // 模特图 Base64 data URL（必填）
  prompt: string              // 提示词（必填）
  resolution?: string         // 分辨率（可选，默认后端处理为 "1024x1024"）
}

export interface ModelProductAsyncResult {
  task_id: string
  status: string                // "processing"
}

export interface ModelProductTaskStatus {
  task_id: string
  status: string                // "processing" | "completed" | "failed"
  progress: string              // 当前步骤描述
  result?: ImageResult          // 仅 completed 时存在
  error?: string                // 仅 failed 时存在
}

export interface PromptReverseRequest {
  image: string               // 图片 Base64 data URL（必填）
}

export interface PromptReverseResult {
  prompt_cn: string           // 反推出的中文提示词
  prompt_en: string           // 反推出的英文提示词
}

/**
 * 产品替换 - 将参考图中的商品替换为用户上传的商品
 */
export async function replaceProduct(
  payload: ProductReplaceRequest
): Promise<ProductReplaceAsyncResult> {
  const response = await api.post<{
    code: number
    data: ProductReplaceAsyncResult
  }>('/toolbox/product-replace', payload, 300000)
  return (response as any).data
}

/**
 * 查询产品替换任务状态
 */
export async function getProductReplaceStatus(
  taskId: string
): Promise<ProductReplaceTaskStatus> {
  const response = await api.get<{
    code: number
    data: ProductReplaceTaskStatus
  }>(`/toolbox/product-replace/status/${taskId}`)
  return (response as any).data
}

/**
 * AI模特 - 生成专业模特三视图
 */
export async function generateAiModel(
  payload: AiModelRequest
): Promise<ImageResult> {
  const response = await api.post<{
    code: number
    data: ImageResult
  }>('/toolbox/ai-model', payload, 300000)  // 5 分钟超时，对齐后端 IMAGE_GEN_TIMEOUT
  return (response as any).data
}

/**
 * 模特商品图 - 生成模特使用商品的图片（异步）
 */
export async function generateModelProduct(
  payload: ModelProductRequest
): Promise<ModelProductAsyncResult> {
  const response = await api.post<{
    code: number
    data: ModelProductAsyncResult
  }>('/toolbox/model-product', payload, 300000)  // 5 分钟超时
  return (response as any).data
}

/**
 * 查询模特商品图任务状态
 */
export async function getModelProductStatus(
  taskId: string
): Promise<ModelProductTaskStatus> {
  const response = await api.get<{
    code: number
    data: ModelProductTaskStatus
  }>(`/toolbox/model-product/status/${taskId}`)
  return (response as any).data
}

/**
 * 反推提示词 - AI 反推图片的提示词
 */
export async function reversePrompt(
  payload: PromptReverseRequest
): Promise<PromptReverseResult> {
  const response = await api.post<{
    code: number
    data: PromptReverseResult
  }>('/toolbox/prompt-reverse', payload, 120000)
  return (response as any).data
}
