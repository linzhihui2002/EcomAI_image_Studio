import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'
import { cachedRequest, cachedRequestLong } from './cache'

const BASE_URL = '/api/v1'
const REQUEST_TIMEOUT = 300000

class ApiError extends Error {
  code: number
  details?: any
  /** 后端响应的 data 字段原文（如合规阻断的 blocks 列表） */
  data?: any

  constructor(code: number, message: string, details?: any, data?: any) {
    super(message)
    this.code = code
    this.details = details
    this.data = data
    this.name = 'ApiError'
  }
}

function getToken(): string | null {
  return localStorage.getItem('ecomai_token')
}

async function request<T>(url: string, options: RequestInit & { timeout?: number } = {}): Promise<T> {
  const token = getToken()

  const { timeout = REQUEST_TIMEOUT, headers: extraHeaders, ...fetchOptions } = options

  const hasBody = fetchOptions.body !== undefined && fetchOptions.body !== null

  const headers: Record<string, string> = {
    ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
    ...(extraHeaders as Record<string, string> || {}),
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  // 请求超时控制
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${url}`, {
      ...fetchOptions,
      headers,
      signal: controller.signal,
    })
  } catch (err: unknown) {
    clearTimeout(timeoutId)
    // 超时取消
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(-1, '请求超时，请检查网络后重试')
    }
    // 网络层错误（断网、DNS 解析失败、CORS 等）统一翻译为中文
    const msg = getErrorMessage(err)
    if (!msg || msg === ERROR_DEFAULTS.UNKNOWN) {
      throw new ApiError(-1, '无法连接到服务器，请确认后端服务已启动')
    }
    throw new ApiError(-1, msg)
  }

  clearTimeout(timeoutId)

  // HTTP 级别错误（非 JSON 响应，如 502/503 返回 HTML）
  if (!response.ok && !response.headers.get('content-type')?.includes('application/json')) {
    const statusMsgMap: Record<number, string> = {
      401: ERROR_DEFAULTS.AUTH_EXPIRED,
      403: ERROR_DEFAULTS.PERMISSION_DENIED,
      404: '请求的资源不存在',
      429: '操作过于频繁，请稍后再试',
      500: ERROR_DEFAULTS.SERVER,
      502: ERROR_DEFAULTS.SERVER,
      503: '服务暂时不可用，请稍后再试',
      504: '请求超时，请稍后重试',
    }
    throw new ApiError(
      response.status,
      statusMsgMap[response.status] || `请求失败（状态码：${response.status}）`,
    )
  }

  if (!response.headers.get('content-type')?.includes('application/json')) {
    if (import.meta.env.DEV) {
      const text = await response.clone().text()
      console.error('[API:request] 后端返回非 JSON 响应', {
        url: `${BASE_URL}${url}`,
        status: response.status,
        contentType: response.headers.get('content-type'),
        body: text.substring(0, 500),
      })
    }
    throw new ApiError(response.status || -1, '服务器暂时繁忙，请稍后重试')
  }

  const data = await response.json()

  if (data.code !== 0) {
    // 使用统一错误处理翻译后端返回的消息
    const translatedMsg = getErrorMessage(
      { code: data.code, message: data.message },
      ERROR_DEFAULTS.SERVER,
    )

    if (data.code === 1001 || data.code === 1002) {
      // 清除本地 token 并抛出认证错误，由上层调用方处理跳转
      localStorage.removeItem('ecomai_token')
      localStorage.removeItem('ecomai_logged_in')
      throw new ApiError(data.code, translatedMsg, data.details, data.data)
    }
    throw new ApiError(data.code, translatedMsg, data.details, data.data)
  }

  return data
}

export const api = {
  get<T>(url: string, params?: Record<string, any>, timeout?: number): Promise<T> {
    const query = params
      ? '?' +
        new URLSearchParams(
          Object.entries(params)
            .filter(([_, v]) => v !== undefined && v !== null && v !== '')
            .map(([k, v]) => [k, String(v)]),
        ).toString()
      : ''
    return request<T>(`${url}${query}`, { timeout })
  },

  post<T>(url: string, body?: any, timeout?: number): Promise<T> {
    return request<T>(url, { method: 'POST', body: JSON.stringify(body), timeout })
  },

  put<T>(url: string, body?: any, timeout?: number): Promise<T> {
    return request<T>(url, { method: 'PUT', body: JSON.stringify(body), timeout })
  },

  delete<T>(url: string, timeout?: number): Promise<T> {
    return request<T>(url, { method: 'DELETE', timeout })
  },

  /**
   * 带缓存的 GET 请求（30 秒 TTL，含请求去重）
   * 适用于列表数据（历史记录、收藏等）
   */
  getCached<T>(url: string, params?: Record<string, any>, ttl?: number): Promise<T> {
    const query = params
      ? '?' +
        new URLSearchParams(
          Object.entries(params)
            .filter(([_, v]) => v !== undefined && v !== null && v !== '')
            .map(([k, v]) => [k, String(v)]),
        ).toString()
      : ''
    return cachedRequest<T>(
      `${url}${query}`,
      () => this.get<T>(url, params),
      ttl,
      params,
    )
  },

  /**
   * 带长缓存（5 分钟）的 GET 请求
   * 适用于定价、配置等不常变化的数据
   */
  getCachedLong<T>(url: string, params?: Record<string, any>): Promise<T> {
    const query = params
      ? '?' +
        new URLSearchParams(
          Object.entries(params)
            .filter(([_, v]) => v !== undefined && v !== null && v !== '')
            .map(([k, v]) => [k, String(v)]),
        ).toString()
      : ''
    return cachedRequestLong<T>(
      `${url}${query}`,
      () => this.get<T>(url, params),
      params,
    )
  },
}

export { ApiError, getToken }