/**
 * 用户自备模型服务商（BYOK）API 请求层
 *
 * 后端接口一律使用 snake_case 入参，且响应中不返回明文 api_key（仅返回掩码）。
 * 本模块只在「响应侧」做 snake_case → camelCase 映射，请求 body 保持 snake_case。
 */
import { api } from './client'
import type { ApiResponse } from '@/types'

/** 自备通道支持的模型分类 */
export type AiProviderCategory = 'image_gen' | 'multimodal' | 'llm'

/** 分类内移动方向 */
export type AiProviderMoveDirection = 'up' | 'down'

/** 前端视角的自备模型通道（驼峰命名） */
export interface AiProvider {
  id: number
  category: AiProviderCategory
  name: string
  apiBase: string
  /** 后端返回的掩码 Key，形如 'sk-a****mnop'；不含明文 */
  apiKeyMasked: string
  modelName: string
  /** 分类内优先级，数字越小越先尝试 */
  priority: number
  isEnabled: boolean
  lastTestOk: boolean | null
  lastTestAt: string | null
  lastTestError: string | null
  lastUsedAt: string | null
  failureCount: number
  lastError: string | null
  createdAt: string
  updatedAt: string
}

/** 列表 + 总开关 */
export interface AiProviderListResult {
  useOwnProvider: boolean
  items: AiProvider[]
}

/** 连通性测试结果 */
export interface AiProviderTestResult {
  ok: boolean
  error: string | null
  testedAt: string | null
}

/** 新增通道入参 */
export interface AiProviderCreatePayload {
  category: AiProviderCategory
  name: string
  apiBase: string
  apiKey: string
  modelName: string
}

/** 更新通道入参；apiKey 传空串表示不修改 */
export interface AiProviderUpdatePayload {
  name?: string
  apiBase?: string
  apiKey?: string
  modelName?: string
  isEnabled?: boolean
}

/** 将后端蛇形命名通道数据转换为前端驼峰命名（兼容驼峰降级的容错） */
export function mapAiProvider(raw: any): AiProvider {
  return {
    id: Number(raw.id),
    category: (raw.category ?? 'image_gen') as AiProviderCategory,
    name: raw.name ?? '',
    apiBase: raw.api_base ?? raw.apiBase ?? '',
    apiKeyMasked: raw.api_key_masked ?? raw.apiKeyMasked ?? '****',
    modelName: raw.model_name ?? raw.modelName ?? '',
    priority: Number(raw.priority ?? 0),
    isEnabled: Boolean(raw.is_enabled ?? raw.isEnabled ?? false),
    lastTestOk: raw.last_test_ok ?? raw.lastTestOk ?? null,
    lastTestAt: raw.last_test_at ?? raw.lastTestAt ?? null,
    lastTestError: raw.last_test_error ?? raw.lastTestError ?? null,
    lastUsedAt: raw.last_used_at ?? raw.lastUsedAt ?? null,
    failureCount: Number(raw.failure_count ?? raw.failureCount ?? 0),
    lastError: raw.last_error ?? raw.lastError ?? null,
    createdAt: raw.created_at ?? raw.createdAt ?? '',
    updatedAt: raw.updated_at ?? raw.updatedAt ?? '',
  }
}

/** 将测试结果（蛇形命名）转换为前端驼峰命名 */
function mapTestResult(raw: any): AiProviderTestResult {
  return {
    ok: Boolean(raw?.ok ?? false),
    error: raw?.error ?? null,
    testedAt: raw?.tested_at ?? raw?.testedAt ?? null,
  }
}

/** 拉取当前用户全部自备通道与总开关 */
export async function fetchAiProviders(): Promise<AiProviderListResult> {
  const res = await api.get<ApiResponse<{ use_own_provider: boolean; items: any[] }>>(
    '/user/ai-providers',
  )
  return {
    useOwnProvider: Boolean(res.data?.use_own_provider ?? false),
    items: (res.data?.items || []).map(mapAiProvider),
  }
}

/** 新增一条自备通道 */
export async function createAiProvider(payload: AiProviderCreatePayload): Promise<AiProvider> {
  const res = await api.post<ApiResponse<any>>('/user/ai-providers', {
    category: payload.category,
    name: payload.name,
    api_base: payload.apiBase,
    api_key: payload.apiKey,
    model_name: payload.modelName,
  })
  return mapAiProvider(res.data)
}

/** 更新一条自备通道（apiKey 传空串表示不修改） */
export async function updateAiProvider(
  id: number,
  payload: AiProviderUpdatePayload,
): Promise<AiProvider> {
  const body: Record<string, any> = {}
  if (payload.name !== undefined) body.name = payload.name
  if (payload.apiBase !== undefined) body.api_base = payload.apiBase
  if (payload.apiKey !== undefined) body.api_key = payload.apiKey
  if (payload.modelName !== undefined) body.model_name = payload.modelName
  if (payload.isEnabled !== undefined) body.is_enabled = payload.isEnabled

  const res = await api.put<ApiResponse<any>>(`/user/ai-providers/${id}`, body)
  return mapAiProvider(res.data)
}

/** 删除一条自备通道 */
export async function deleteAiProvider(id: number): Promise<void> {
  await api.delete<ApiResponse<null>>(`/user/ai-providers/${id}`)
}

/** 在分类内上移/下移一条自备通道 */
export async function moveAiProvider(
  id: number,
  direction: AiProviderMoveDirection,
): Promise<AiProvider> {
  const res = await api.put<ApiResponse<any>>(`/user/ai-providers/${id}/move`, { direction })
  return mapAiProvider(res.data)
}

/** 连通性测试（后端会请求 {api_base}/models） */
export async function testAiProvider(id: number): Promise<AiProviderTestResult> {
  const res = await api.post<ApiResponse<any>>(`/user/ai-providers/${id}/test`, {})
  return mapTestResult(res.data)
}

/** 读取自备通道总开关 */
export async function fetchAiProviderSettings(): Promise<boolean> {
  const res = await api.get<ApiResponse<{ use_own_provider: boolean }>>(
    '/user/ai-provider-settings',
  )
  return Boolean(res.data?.use_own_provider ?? false)
}

/** 设置自备通道总开关，返回后端确认后的值 */
export async function updateAiProviderSettings(useOwnProvider: boolean): Promise<boolean> {
  const res = await api.put<ApiResponse<{ use_own_provider: boolean }>>(
    '/user/ai-provider-settings',
    { use_own_provider: useOwnProvider },
  )
  return Boolean(res.data?.use_own_provider ?? false)
}
