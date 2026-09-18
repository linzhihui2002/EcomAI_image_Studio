/**
 * API 请求缓存与去重模块
 *
 * - 请求去重：同一请求并发时共享一个 Promise，避免重复请求
 * - 内存缓存：对列表/配置数据提供短期缓存，减少 API 调用
 */

interface CacheEntry<T> {
  data: T
  timestamp: number
  ttl: number
}

/** 默认 TTL（毫秒） */
const DEFAULT_TTL = 30_000       // 列表数据：30 秒
const LONG_TTL = 300_000         // 配置/定价：5 分钟

/** 结果缓存 */
const resultCache = new Map<string, CacheEntry<unknown>>()

/** 进行中的请求（用于去重） */
const inflightRequests = new Map<string, Promise<unknown>>()

/**
 * 生成缓存 key
 */
function buildKey(url: string, params?: Record<string, unknown>): string {
  if (!params) return url
  const sorted = Object.keys(params)
    .sort()
    .map((k) => `${k}=${String(params[k])}`)
    .join('&')
  return `${url}?${sorted}`
}

/**
 * 带去重和缓存的请求包装器
 *
 * @param url      API 路径
 * @param fetcher  实际请求函数
 * @param ttl      缓存有效期（毫秒），默认 30 秒
 * @param params   请求参数（用于区分缓存 key）
 */
export async function cachedRequest<T>(
  url: string,
  fetcher: () => Promise<T>,
  ttl: number = DEFAULT_TTL,
  params?: Record<string, unknown>,
): Promise<T> {
  const key = buildKey(url, params)

  // 1. 检查内存缓存
  const cached = resultCache.get(key)
  if (cached && Date.now() - cached.timestamp < cached.ttl) {
    return cached.data as T
  }

  // 2. 检查是否有进行中的相同请求（去重）
  const inflight = inflightRequests.get(key)
  if (inflight) {
    return inflight as Promise<T>
  }

  // 3. 发起新请求
  const promise = fetcher()
    .then((data) => {
      // 请求成功，存入缓存
      resultCache.set(key, { data, timestamp: Date.now(), ttl })
      return data
    })
    .finally(() => {
      // 无论成功失败，都从进行中队列移除
      inflightRequests.delete(key)
    })

  inflightRequests.set(key, promise)
  return promise
}

/**
 * 手动清除某个缓存
 */
export function clearCache(url: string, params?: Record<string, unknown>): void {
  const key = buildKey(url, params)
  resultCache.delete(key)
}

/**
 * 清除所有缓存
 */
export function clearAllCache(): void {
  resultCache.clear()
}

/**
 * 带更长 TTL 的请求（用于定价/配置等不常变化的数据）
 */
export async function cachedRequestLong<T>(
  url: string,
  fetcher: () => Promise<T>,
  params?: Record<string, unknown>,
): Promise<T> {
  return cachedRequest(url, fetcher, LONG_TTL, params)
}

export { DEFAULT_TTL, LONG_TTL }