import { api } from './client'
import type { HistoryRecordItem, HistoryRecordDetail, HistoryCategory, HistorySubCategory, PaginatedResponse, ApiResponse } from '@/types'

export interface FetchHistoryParams {
  category?: HistoryCategory
  sub_category?: HistorySubCategory
  page?: number
  page_size?: number
}

export function fetchHistory(params: FetchHistoryParams = {}): Promise<PaginatedResponse<HistoryRecordItem[]>> {
  return api.getCached<PaginatedResponse<HistoryRecordItem[]>>('/history', params as any)
}

export function fetchHistoryDetail(id: number): Promise<ApiResponse<HistoryRecordDetail>> {
  return api.get<ApiResponse<HistoryRecordDetail>>(`/history/${id}`)
}

export function deleteHistory(id: number): Promise<ApiResponse<null>> {
  return api.delete<ApiResponse<null>>(`/history/${id}`)
}

export function shareToTeam(id: number, teamId: string): Promise<ApiResponse<null>> {
  return api.post<ApiResponse<null>>(`/history/${id}/share`, { team_id: teamId })
}

export function unshareFromTeam(id: number): Promise<ApiResponse<null>> {
  return api.delete<ApiResponse<null>>(`/history/${id}/share`)
}

export function fetchTeamHistory(teamId: number, params: FetchHistoryParams = {}): Promise<PaginatedResponse<HistoryRecordItem[]>> {
  return api.getCached<PaginatedResponse<HistoryRecordItem[]>>(`/history/team/${teamId}`, params as any)
}