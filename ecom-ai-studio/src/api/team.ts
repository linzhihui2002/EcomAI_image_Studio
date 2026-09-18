/**
 * 团队管理 API
 * 封装团队创建、加入、查询、邀请码管理、成员管理接口调用
 */
import { api } from './client'
import type { ApiResponse, Team, TeamInvitation, InvitationVerification, TeamMember, TransferLog, PaginatedResponse } from '@/types'

// ==================== 团队管理 ====================

export async function createTeam(data: {
  name: string
  category: string
}): Promise<ApiResponse<{ team: Team }>> {
  return api.post<ApiResponse<{ team: Team }>>('/teams', data)
}

export async function joinTeam(inviteCode: string): Promise<ApiResponse<{ team: Team }>> {
  return api.post<ApiResponse<{ team: Team }>>('/teams/join', { inviteCode })
}

export async function getMyTeams(): Promise<ApiResponse<{ teams: Team[] }>> {
  return api.get<ApiResponse<{ teams: Team[] }>>('/teams/mine')
}

// ==================== 邀请码管理 ====================

export async function getTeamInvitation(
  teamId: string,
): Promise<ApiResponse<{ invitation: TeamInvitation | null }>> {
  return api.get<ApiResponse<{ invitation: TeamInvitation | null }>>(
    `/teams/${teamId}/invitation`,
  )
}

export async function refreshInvitation(
  teamId: string,
): Promise<ApiResponse<{ invitation: TeamInvitation }>> {
  return api.post<ApiResponse<{ invitation: TeamInvitation }>>(
    `/teams/${teamId}/invitation/refresh`,
  )
}

export async function verifyInvitation(
  code: string,
): Promise<ApiResponse<{ verification: InvitationVerification }>> {
  return api.post<ApiResponse<{ verification: InvitationVerification }>>(
    '/teams/invitation/verify',
    { code },
  )
}

// ==================== 团队成员管理 ====================

export async function getTeamMembers(
  teamId: string,
): Promise<ApiResponse<{ members: TeamMember[] }>> {
  return api.get<ApiResponse<{ members: TeamMember[] }>>(`/teams/${teamId}/members`)
}

// ==================== 解散团队 ====================

export async function dissolveTeam(teamId: string): Promise<ApiResponse<{
  transferredAmount: number
  message: string
}>> {
  return api.delete<ApiResponse<{ transferredAmount: number; message: string }>>(`/teams/${teamId}`)
}

// ==================== 转账功能 ====================

export async function transferToTeam(teamId: string, amount: number): Promise<ApiResponse<{
  amount: number
  newTeamBalance: number
  newPersonalBalance: number
}>> {
  return api.post<ApiResponse<{
    amount: number
    newTeamBalance: number
    newPersonalBalance: number
  }>>(`/teams/${teamId}/transfer`, { amount })
}

export async function getTeamTransferLogs(
  teamId: string,
  page?: number,
): Promise<PaginatedResponse<TransferLog[]> & ApiResponse<{ logs: TransferLog[] }>> {
  return api.get<PaginatedResponse<TransferLog[]> & ApiResponse<{ logs: TransferLog[] }>>(
    `/teams/${teamId}/transfer-logs`,
    { page, pageSize: 20 },
  )
}