/**
 * 功能定价（Feature Pricing）公开查询 API
 * 提供「灵感币」消耗规则查询，带内存级缓存以减少请求。
 */
import { api } from './client'
import type { ApiResponse, FeaturePricing } from '@/types'

/** 缓存 TTL（毫秒），默认 60s */
const CACHE_TTL = 60_000

/** 内存缓存：保存全量定价列表与过期时间戳 */
let _cache: { pricings: FeaturePricing[]; expireAt: number } | null = null

/** 将后端蛇形命名定价数据转换为前端驼峰命名 */
export function mapFeaturePricing(raw: any): FeaturePricing {
  return {
    featureKey: raw.feature_key ?? raw.featureKey ?? '',
    displayName: raw.display_name ?? raw.displayName ?? '',
    category: raw.category ?? '',
    pricingType: raw.pricing_type ?? raw.pricingType ?? 'per_use',
    // config 已经是目标结构，原样保留
    config: raw.config ?? {},
    sortOrder: raw.sort_order ?? raw.sortOrder ?? 0,
  }
}

/**
 * 查询功能定价列表。
 * - 命中缓存且未过期时，从缓存中按 category 过滤返回。
 * - 未命中时请求接口，将「全量」数据写入缓存，再按 category 过滤返回。
 * @param category 可选类目过滤
 */
export async function getFeaturePricing(category?: string): Promise<FeaturePricing[]> {
  const now = Date.now()
  if (_cache && _cache.expireAt > now) {
    const all = _cache.pricings
    return category ? all.filter((p) => p.category === category) : all
  }

  const res = await api.get<ApiResponse<{ pricings: any[] }>>('/feature-pricing', { category })
  const mapped = (res.data.pricings || []).map(mapFeaturePricing)
  // 缓存全量数据（即便本次按 category 查询，后续其他类目可复用）
  _cache = { pricings: mapped, expireAt: now + CACHE_TTL }
  return category ? mapped.filter((p) => p.category === category) : mapped
}

/**
 * 按 featureKey 查询单条功能定价。
 * @returns 未找到时返回 null
 */
export async function getFeaturePricingByKey(featureKey: string): Promise<FeaturePricing | null> {
  const list = await getFeaturePricing()
  return list.find((p) => p.featureKey === featureKey) ?? null
}

/** 清空内存缓存。管理员侧编辑后调用，确保下次读取重新拉取。 */
export function clearFeaturePricingCache(): void {
  _cache = null
}

/**
 * 计算按分辨率计费的图片生成消耗（复刻后端逻辑）。
 * 规则：取尺寸最长边，匹配 |最长边 - tier.max_dimension| 最小的档位，返回对应 coins。
 * @param pricing 功能定价对象（可为 null）
 * @param size 形如 "1024x1024" / "1024X1024" / "1024×1024" 的尺寸字符串
 */
export function calculateImageCost(pricing: FeaturePricing | null, size: string): number {
  if (!pricing || pricing.pricingType !== 'per_image_resolution') {
    return 0
  }
  const tiers = pricing.config?.tiers
  if (!tiers || tiers.length === 0) {
    return 0
  }

  // 解析尺寸，兼容 x / X / × 分隔符；解析失败时默认 1024x1024
  let w = 1024
  let h = 1024
  if (size) {
    const parts = size.split(/[xX×]/)
    if (parts.length === 2) {
      const parsedW = parseInt(parts[0], 10)
      const parsedH = parseInt(parts[1], 10)
      if (!Number.isNaN(parsedW) && parsedW > 0) w = parsedW
      if (!Number.isNaN(parsedH) && parsedH > 0) h = parsedH
    }
  }
  const longestEdge = Math.max(w, h)

  // 取与最长边差距最小的档位
  let bestTier = tiers[0]
  let bestDelta = Math.abs(longestEdge - bestTier.max_dimension)
  for (let i = 1; i < tiers.length; i++) {
    const delta = Math.abs(longestEdge - tiers[i].max_dimension)
    if (delta < bestDelta) {
      bestDelta = delta
      bestTier = tiers[i]
    }
  }
  return bestTier.coins
}

/**
 * 获取按次计费的单次消耗。
 * @param pricing 功能定价对象（可为 null）
 */
export function getPerUseCost(pricing: FeaturePricing | null): number {
  if (!pricing || pricing.pricingType !== 'per_use') {
    return 0
  }
  return pricing.config?.coins ?? 0
}
