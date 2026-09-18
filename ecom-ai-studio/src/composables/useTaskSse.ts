/**
 * 任务进度 SSE 订阅组合式函数
 *
 * 优先通过 EventSource 订阅 GET /api/v1/sse/tasks/{taskId} 实时进度；
 * EventSource 无法携带 Header，token 通过 ?token= query 参数传递。
 * 连续 3 次错误或环境不支持 EventSource 时，自动降级为 pollFn 轮询（2s 间隔）。
 * 终态（completed/failed）自动关闭连接并触发对应回调。
 */
import { getCurrentInstance, onUnmounted, reactive, ref, unref, type Ref } from 'vue'
import { getToken } from '@/api/client'

/** 任务状态对象（与后端 get_task / SSE 推送字段对应） */
export interface TaskStatus {
  task_id?: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  step: string
  pct: number
  result: any
  error: string | null
  module?: string
  created_at?: string
  updated_at?: string
}

/** 状态来源：sse 实时推送 / poll 降级轮询 */
export type TaskSource = 'sse' | 'poll'

export interface UseTaskSseOptions {
  /** 任务 ID，支持响应式 Ref */
  taskId: string | Ref<string>
  /** 降级轮询使用的既有 GET 函数（应返回 TaskStatus） */
  pollFn?: (taskId: string) => Promise<TaskStatus>
  /** 任务完成回调 */
  onCompleted?: (result: any) => void
  /** 任务失败回调 */
  onFailed?: (error: string) => void
}

/** SSE 最大连续错误次数，超过后降级为轮询 */
const MAX_SSE_ERRORS = 3
/** 降级轮询间隔（毫秒） */
const POLL_INTERVAL = 2000

export function useTaskSse(options: UseTaskSseOptions) {
  const status = ref<TaskStatus['status']>('queued')
  const step = ref('')
  const pct = ref(0)
  const result = ref<any>(null)
  const error = ref<string | null>(null)
  const source = ref<TaskSource>('sse')
  /** 最近一帧原始事件负载（批量任务等非标准 TaskStatus 形状的事件由此透出） */
  const raw = ref<any>(null)

  let eventSource: EventSource | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let errorCount = 0
  let stopped = false

  /** 用后端状态更新本地响应式对象 */
  function applyStatus(next: TaskStatus) {
    // 批量任务等事件的负载可能缺省 status 字段，此时保留上一状态不被清空
    if (next.status) status.value = next.status
    step.value = next.step ?? ''
    pct.value = Number(next.pct ?? 0)
    result.value = next.result ?? null
    error.value = next.error ?? null
    raw.value = next
  }

  /** 终态处理：更新状态、触发回调 */
  function handleTerminal(next: TaskStatus) {
    applyStatus(next)
    if (next.status === 'completed') options.onCompleted?.(next.result)
    else if (next.status === 'failed') options.onFailed?.(String(next.error ?? '任务失败'))
  }

  /** 关闭 SSE 连接 */
  function closeSource() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  /** 降级轮询：复用调用方传入的 GET 轮询函数 */
  function startPolling(taskId: string) {
    if (stopped) return
    if (!options.pollFn) {
      console.error('[useTaskSse] SSE 不可用且未提供 pollFn，无法继续跟踪任务进度')
      return
    }
    source.value = 'poll'
    pollTimer = setInterval(async () => {
      try {
        const next = await options.pollFn!(taskId)
        if (next.status === 'completed' || next.status === 'failed') {
          handleTerminal(next)
          stop()
        } else {
          applyStatus(next)
        }
      } catch (err) {
        console.error('[useTaskSse] 轮询任务状态失败', err)
      }
    }, POLL_INTERVAL)
  }

  /** 开始订阅任务进度（重复调用会先停止旧订阅） */
  function start() {
    stop()
    stopped = false
    errorCount = 0
    const taskId = unref(options.taskId)
    if (!taskId) return

    // 环境不支持 EventSource 时直接降级轮询
    if (typeof EventSource === 'undefined') {
      startPolling(taskId)
      return
    }

    source.value = 'sse'
    const url = `/api/v1/sse/tasks/${taskId}?token=${encodeURIComponent(getToken() ?? '')}`
    eventSource = new EventSource(url)

    eventSource.addEventListener('progress', (e) => {
      errorCount = 0
      try {
        applyStatus(JSON.parse((e as MessageEvent).data) as TaskStatus)
      } catch {
        // 忽略无法解析的数据帧
      }
    })
    eventSource.addEventListener('completed', (e) => {
      try {
        handleTerminal(JSON.parse((e as MessageEvent).data) as TaskStatus)
      } finally {
        stop()
      }
    })
    eventSource.addEventListener('failed', (e) => {
      try {
        handleTerminal(JSON.parse((e as MessageEvent).data) as TaskStatus)
      } finally {
        stop()
      }
    })
    eventSource.onerror = () => {
      errorCount += 1
      closeSource()
      if (errorCount >= MAX_SSE_ERRORS) startPolling(taskId)
    }
  }

  /** 停止订阅与轮询（终态自动调用，也可手动调用） */
  function stop() {
    stopped = true
    closeSource()
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  // 在组件 setup 上下文中使用时，组件卸载自动清理
  if (getCurrentInstance()) onUnmounted(stop)

  return reactive({ status, step, pct, result, error, raw, source, start, stop })
}
