import { api } from './client'
import type { ApiResponse, PricingPlan } from '@/types'

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

export async function fetchPricingPlans(isActive?: boolean): Promise<PricingPlan[]> {
  const res = await api.get<ApiResponse<{ plans: any[] }>>('/pricing-plans', { isActive })
  return res.data.plans.map(mapPricingPlan)
}

export function redeemCode(data: {
  code: string
  walletType: string
  teamId?: string | null
}): Promise<
  ApiResponse<{
    coinsAdded: number
    newBalance: number
    codeInfo: { code: string; originalCoins: number }
  }>
> {
  return api.post<ApiResponse<any>>('/purchase/redeem', data)
}