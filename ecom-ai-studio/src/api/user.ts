import { api } from './client'
import type { ApiResponse, PaginatedResponse, User, PointsRecord } from '@/types'

export interface PointsRecordsQuery {
  wallet?: string
  type?: string
  page?: number
  pageSize?: number
}

export function fetchUserProfile(): Promise<ApiResponse<User>> {
  return api.get<ApiResponse<User>>('/user/profile')
}

export function fetchUserBalance(
  wallet?: string,
  teamId?: string,
): Promise<
  ApiResponse<{
    walletType: string
    balance: number
    teamBalance?: number | null
  }>
> {
  return api.get<ApiResponse<any>>('/user/balance', { wallet, teamId })
}

export function fetchPointsRecords(params: PointsRecordsQuery): Promise<PaginatedResponse<PointsRecord[]>> {
  return api.get<PaginatedResponse<PointsRecord[]>>('/user/points-records', params as any)
}