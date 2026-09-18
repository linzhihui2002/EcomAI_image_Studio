import { api } from './client'
import type { ApiResponse, PaginatedResponse, FavoriteItem } from '@/types'

export interface FavoritesQuery {
  page?: number
  pageSize?: number
}

export function fetchFavorites(params: FavoritesQuery): Promise<PaginatedResponse<FavoriteItem[]>> {
  return api.getCached<PaginatedResponse<FavoriteItem[]>>('/favorites', params as any)
}

export function addFavorite(data: { imageUrl: string; batchId: string; config: any }): Promise<ApiResponse<FavoriteItem>> {
  return api.post<ApiResponse<FavoriteItem>>('/favorites', data)
}

export function removeFavorite(favoriteId: string): Promise<ApiResponse<null>> {
  return api.delete<ApiResponse<null>>(`/favorites/${favoriteId}`)
}

export function addHistoryFavorite(recordId: number): Promise<ApiResponse<{ id: number }>> {
  return api.post<ApiResponse<{ id: number }>>('/favorites/history', { recordId })
}