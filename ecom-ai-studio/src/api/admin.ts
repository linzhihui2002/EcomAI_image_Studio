/**
 * 管理后台 API 请求层
 * 封装仪表盘、定价方案、团队消耗、兑换码、公告管理接口调用
 */
import { api } from './client'
import type {
  ApiResponse,
  AdminStats,
  PricingPlan,
  TeamConsumption,
  RedemptionCode,
  Announcement,
  FeaturePricingAdmin,
  FeaturePricingConfig,
  PricingType,
} from '@/types'

/** 将后端蛇形命名定价方案转换为前端驼峰命名 */
function mapPricingPlan(raw: any): PricingPlan {
  return {
    id: raw.id,
    name: raw.name,
    price: Number(raw.price),
    coins: raw.coins,
    bonusCoins: raw.bonus_coins ?? raw.bonusCoins ?? 0,
    isActive: Boolean(raw.is_active ?? raw.isActive ?? false),
    sortOrder: raw.sort_order ?? raw.sortOrder ?? 0,
    createdAt: raw.created_at ?? raw.createdAt ?? '',
  }
}

/** 将后端兑换码数据转换为前端驼峰命名（兼容 snake_case 降级） */
function mapRedemptionCode(raw: any): RedemptionCode {
  return {
    id: String(raw.id ?? ''),
    code: raw.code ?? '',
    coins: Number(raw.coins ?? 0),
    expiresAt: raw.expiresAt ?? raw.expires_at ?? '',
    isUsed: Boolean(raw.isUsed ?? raw.is_used ?? false),
    usedBy: raw.usedBy ?? raw.used_by ?? undefined,
    usedAt: raw.usedAt ?? raw.used_at ?? undefined,
    createdAt: raw.createdAt ?? raw.created_at ?? '',
    remark: raw.remark ?? '',
    // 扩展：次数限制相关字段
    maxUses: Number(raw.maxUses ?? raw.max_uses ?? 1),
    maxUsesPerUser: Number(raw.maxUsesPerUser ?? raw.max_uses_per_user ?? 1),
    useCount: Number(raw.useCount ?? raw.use_count ?? 0),
    remainingUses: raw.remainingUses ?? raw.max_uses - raw.use_count,
  }
}

/** 将后端公告数据转换为前端驼峰命名（兼容 snake_case 降级） */
function mapAnnouncement(raw: any): Announcement {
  return {
    id: String(raw.id),
    title: raw.title ?? '',
    content: raw.content ?? '',
    type: raw.type ?? 'info',
    isPinned: Boolean(raw.is_pinned ?? raw.isPinned ?? false),
    isActive: Boolean(raw.is_active ?? raw.isActive ?? true),
    createdAt: raw.created_at ?? raw.createdAt ?? '',
    createdBy: raw.created_by ?? raw.createdBy,
    expiresAt: raw.expires_at ?? raw.expiresAt,
  }
}

// ==================== 仪表盘 ====================

export async function getAdminStats(): Promise<AdminStats> {
  const res = await api.get<ApiResponse<AdminStats>>('/admin/stats')
  return res.data
}

// ==================== 定价方案管理 ====================

export async function getAllPricingPlans(): Promise<PricingPlan[]> {
  const res = await api.get<ApiResponse<{ plans: any[] }>>('/admin/pricing-plans')
  return res.data.plans.map(mapPricingPlan)
}

export async function createPricingPlan(data: {
  name: string
  price: number
  coins: number
  bonusCoins: number
}): Promise<PricingPlan> {
  const res = await api.post<ApiResponse<{ plan: any }>>('/admin/pricing-plans', data)
  return mapPricingPlan(res.data.plan)
}

export async function updatePricingPlan(
  planId: string | number,
  data: { name: string; price: number; coins: number; bonusCoins: number },
): Promise<PricingPlan> {
  const res = await api.put<ApiResponse<{ plan: any }>>(
    `/admin/pricing-plans/${planId}`,
    data,
  )
  return mapPricingPlan(res.data.plan)
}

export async function togglePricingPlanActive(planId: string | number): Promise<{ isActive: boolean }> {
  const res = await api.put<ApiResponse<{ isActive: boolean }>>(
    `/admin/pricing-plans/${planId}/toggle`,
  )
  return res.data
}

export async function deletePricingPlan(planId: string | number): Promise<void> {
  await api.delete(`/admin/pricing-plans/${planId}`)
}

// ==================== 团队消耗 ====================

export async function getTeamConsumptions(sortBy?: string, order?: string): Promise<TeamConsumption[]> {
  const res = await api.get<ApiResponse<{ consumptions: TeamConsumption[] }>>(
    '/admin/team-consumptions',
    { sortBy, order },
  )
  return res.data.consumptions
}

// ==================== 兑换码管理 ====================

export async function getAdminRedemptionCodes(status?: string): Promise<RedemptionCode[]> {
  const res = await api.get<ApiResponse<{ codes: any[] }>>(
    '/admin/redemption-codes',
    { status },
  )
  return (res.data.codes || []).map(mapRedemptionCode)
}

export async function generateRedemptionCode(data: {
  coins: number
  expiresDays: number
  remark: string
  maxUses?: number
  maxUsesPerUser?: number
}): Promise<RedemptionCode> {
  const res = await api.post<ApiResponse<{ code: any }>>(
    '/admin/redemption-codes',
    data,
  )
  return mapRedemptionCode(res.data.code)
}

export async function deleteRedemptionCode(codeId: string | number): Promise<void> {
  await api.delete(`/admin/redemption-codes/${codeId}`)
}

// ==================== 公告管理 ====================

export async function getAdminAnnouncements(): Promise<Announcement[]> {
  const res = await api.get<ApiResponse<{ announcements: any[] }>>('/admin/announcements')
  return (res.data.announcements || []).map(mapAnnouncement)
}

export async function createAnnouncement(data: {
  title: string
  content: string
  type: string
  isPinned: boolean
  expiresAt: string | null
}): Promise<Announcement> {
  const res = await api.post<ApiResponse<{ announcement: any }>>(
    '/admin/announcements',
    data,
  )
  return mapAnnouncement(res.data.announcement)
}

export async function updateAnnouncement(
  annId: string | number,
  data: {
    title: string
    content: string
    type: string
    isPinned: boolean
    expiresAt: string | null
  },
): Promise<Announcement> {
  const res = await api.put<ApiResponse<{ announcement: any }>>(
    `/admin/announcements/${annId}`,
    data,
  )
  return mapAnnouncement(res.data.announcement)
}

export async function toggleAnnouncementActive(annId: string | number): Promise<{ isActive: boolean }> {
  const res = await api.put<ApiResponse<{ isActive: boolean }>>(
    `/admin/announcements/${annId}/toggle`,
  )
  return res.data
}

export async function deleteAnnouncement(annId: string | number): Promise<void> {
  await api.delete(`/admin/announcements/${annId}`)
}

// ==================== 公开公告 ====================

export async function getPublicAnnouncements(): Promise<Announcement[]> {
  const res = await api.get<ApiResponse<{ announcements: any[] }>>('/announcements')
  return (res.data.announcements || []).map(mapAnnouncement)
}

// ==================== 功能定价(Feature Pricing)管理 ====================

/**
 * 将后端蛇形命名功能定价数据转换为前端驼峰命名。
 * config 字段后端可能以对象或 JSON 字符串形式返回，统一解析为对象。
 */
function mapFeaturePricingAdmin(raw: any): FeaturePricingAdmin {
  // config 可能是对象、JSON 字符串或缺失
  let config: FeaturePricingConfig = {}
  if (raw.config != null) {
    if (typeof raw.config === 'string') {
      try {
        config = JSON.parse(raw.config)
      } catch {
        config = {}
      }
    } else {
      config = raw.config
    }
  }

  return {
    id: raw.id,
    featureKey: raw.feature_key ?? raw.featureKey ?? '',
    displayName: raw.display_name ?? raw.displayName ?? '',
    category: raw.category ?? '',
    pricingType: (raw.pricing_type ?? raw.pricingType ?? 'per_use') as PricingType,
    config,
    sortOrder: raw.sort_order ?? raw.sortOrder ?? 0,
    description: raw.description ?? null,
    isActive: Boolean(raw.is_active ?? raw.isActive ?? false),
    createdAt: raw.created_at ?? raw.createdAt ?? '',
    updatedAt: raw.updated_at ?? raw.updatedAt ?? '',
  }
}

/** 拉取功能定价列表（管理员视角） */
export async function getFeaturePricingList(): Promise<FeaturePricingAdmin[]> {
  const res = await api.get<ApiResponse<{ pricings: any[] }>>('/admin/feature-pricing')
  return (res.data.pricings || []).map(mapFeaturePricingAdmin)
}

/** 创建功能定价 */
export async function createFeaturePricing(data: {
  featureKey: string
  displayName: string
  category: string
  pricingType: PricingType
  config: FeaturePricingConfig
  description?: string
}): Promise<FeaturePricingAdmin> {
  const res = await api.post<ApiResponse<{ pricing: any }>>(
    '/admin/feature-pricing',
    data,
  )
  return mapFeaturePricingAdmin(res.data.pricing)
}

/** 更新功能定价 */
export async function updateFeaturePricing(
  id: number,
  data: {
    displayName: string
    category: string
    pricingType: PricingType
    config: FeaturePricingConfig
    description?: string
  },
): Promise<FeaturePricingAdmin> {
  const res = await api.put<ApiResponse<{ pricing: any }>>(
    `/admin/feature-pricing/${id}`,
    data,
  )
  return mapFeaturePricingAdmin(res.data.pricing)
}

/** 切换功能定价启用状态 */
export async function toggleFeaturePricingActive(id: number): Promise<{ isActive: boolean }> {
  const res = await api.put<ApiResponse<{ isActive: boolean }>>(
    `/admin/feature-pricing/${id}/toggle`,
  )
  return res.data
}

/** 删除功能定价 */
export async function deleteFeaturePricing(id: number): Promise<void> {
  await api.delete(`/admin/feature-pricing/${id}`)
}

/** 功能标识选项（供管理员创建定价时下拉选择） */
export interface FeatureKeyOption {
  featureKey: string
  displayName: string
  description: string
  category: string
  pricingType: PricingType
}

/** 获取可用的功能标识选项列表 */
export async function getFeatureKeyOptions(): Promise<FeatureKeyOption[]> {
  const res = await api.get<ApiResponse<{ options: any[] }>>('/admin/feature-pricing/keys')
  return (res.data.options || []).map((raw: any) => ({
    featureKey: raw.feature_key ?? raw.featureKey ?? '',
    displayName: raw.display_name ?? raw.displayName ?? '',
    description: raw.description ?? '',
    category: raw.category ?? '',
    pricingType: (raw.pricing_type ?? raw.pricingType ?? 'per_use') as PricingType,
  }))
}