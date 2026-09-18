<script setup lang="ts">
/**
 * 编辑器 Agent 对话面板（右侧"AI 助手"页签）
 *
 * 交互流程：
 * 1. 输入中文编辑指令 → POST /agent/plan（LLM 同步规划，约 3-8 秒）
 * 2. 计划卡片：步骤列表（序号 / 工具中文 label / 状态徽标 / 依赖提示）
 *    - 确认执行 → POST /agent/execute → useTaskSse 订阅任务进度
 *      （执行前把当前涂抹选区填入空缺的 mask 步骤，并做必填参数预校验）
 *    - 执行中：卡片内整体进度（step/pct）+ 各步实时状态（按拓扑序推导）
 *    - 取消后续步骤 → POST /agent/tasks/<id>/cancel（当前步完成后停止）
 *    - 单步重试（失败步骤）→ POST /agent/tasks/<id>/retry → 新 task_id 重新订阅
 * 3. 执行完成：result.final_image_url → pushSnapshot → replaceBackgroundImage 更新画布
 * 4. LLM 失败（502）/ 校验失败（400）以中文错误消息显示在对话流中
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  AlertCircle,
  CheckCircle2,
  ListChecks,
  Loader2,
  Send,
  Sparkles,
  Square,
} from 'lucide-vue-next'
import { getErrorMessage } from '@/lib/error'
import { useEditorStore } from '@/stores/editor'
import {
  agentCancelTask,
  agentExecute,
  agentPlan,
  agentRetryTask,
  fetchEditorTaskStatus,
  type AgentPlan,
  type AgentStep,
  type AgentTaskError,
  type AgentTaskResult,
} from '@/api/editor'
import { useTaskSse } from '@/composables/useTaskSse'
import EditorMaskBrushPanel from './EditorMaskBrushPanel.vue'

const store = useEditorStore()

// ===== 消息模型 =====

type StepStatus = 'pending' | 'running' | 'success' | 'failed'
type PlanPhase = 'draft' | 'executing' | 'failed' | 'cancelled' | 'completed'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  /** text 普通消息 / plan 计划卡片 / error 错误 / success 完成提示 */
  kind: 'text' | 'plan' | 'error' | 'success'
  text: string
  plan?: AgentPlan
  /** 拓扑执行序列（step id 列表） */
  order?: string[]
  /** 计划校验错误（非空时不允许执行） */
  errors?: string[]
  phase?: PlanPhase
  taskId?: string
  stepStates?: Record<string, StepStatus>
  /** 执行中整体进度 */
  progressStep?: string
  progressPct?: number
  /** 正在提交重试的步骤 id */
  retryingStepId?: string
  /** execute 请求进行中 */
  submitting?: boolean
}

const messages = ref<ChatMessage[]>([])
let messageSeq = 0

function pushMessage(
  role: ChatMessage['role'],
  kind: ChatMessage['kind'],
  text: string,
): ChatMessage {
  messageSeq += 1
  const msg: ChatMessage = { id: `msg-${Date.now()}-${messageSeq}`, role, kind, text }
  messages.value = [...messages.value, msg]
  void nextTick(scrollToBottom)
  return msg
}

function removeMessage(id: string) {
  messages.value = messages.value.filter((m) => m.id !== id)
}

// ===== 输入区 =====

const input = ref('')
const planning = ref(false)
const EXAMPLE_INSTRUCTIONS = ['把背景换成白色摄影棚', '消除画面里的杂物', '提高亮度再放大两倍']

function applyExample(text: string) {
  input.value = text
}

function handleInputKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void handleSend()
  }
}

/** 执行目标图层：选中的图片图层优先，否则背景图层（与工具执行规则一致） */
const targetLayer = computed(() => {
  const selected = store.selectedLayer
  if (selected && selected.type === 'image' && selected.url) return selected
  return store.backgroundLayer
})

// ===== 计划生成 =====

async function handleSend() {
  const instruction = input.value.trim()
  if (!instruction || planning.value) return
  pushMessage('user', 'text', instruction)
  input.value = ''
  planning.value = true
  try {
    const res = await agentPlan(instruction, {
      imageUrl: targetLayer.value?.url ?? undefined,
      documentId: store.documentId ?? undefined,
    })
    const msg = pushMessage('assistant', 'plan', '已根据你的指令生成修图计划，确认后开始执行：')
    msg.plan = res.plan
    msg.order = res.order
    msg.errors = res.errors ?? []
    msg.phase = 'draft'
    msg.stepStates = initStepStates(res.order)
  } catch (err) {
    console.error('[editor-agent] 计划生成失败', err)
    pushMessage('assistant', 'error', getErrorMessage(err, 'AI 规划失败，请稍后重试'))
  } finally {
    planning.value = false
    void nextTick(scrollToBottom)
  }
}

function initStepStates(order: string[] | undefined): Record<string, StepStatus> {
  const states: Record<string, StepStatus> = {}
  for (const id of order ?? []) states[id] = 'pending'
  return states
}

// ===== 工具中文 label 映射（GET /tools 注册表） =====

function toolLabel(toolName: string): string {
  return store.tools.find((t) => t.name === toolName)?.label ?? toolName
}

// ===== 计划参数预校验与蒙版填入 =====

/** 深拷贝计划并把当前涂抹蒙版填入空缺的 mask 步骤（不改动原消息中的计划） */
function preparePlanForExecute(plan: AgentPlan): AgentPlan {
  const copied = JSON.parse(JSON.stringify(plan)) as AgentPlan
  const maskUri = store.lastMaskDataUri
  if (!maskUri) return copied
  for (const step of copied.steps) {
    const def = store.tools.find((t) => t.name === step.tool)
    if (def?.requires_mask && !String(step.params?.mask_data_uri ?? '').trim()) {
      step.params = { ...(step.params ?? {}), mask_data_uri: maskUri }
    }
  }
  return copied
}

/** 按 params_schema 预校验必填参数，返回中文问题列表 */
function planParamIssues(plan: AgentPlan): string[] {
  const issues: string[] = []
  for (const step of plan.steps) {
    const def = store.tools.find((t) => t.name === step.tool)
    if (!def) {
      issues.push(`步骤 ${step.id}：未知工具「${step.tool}」`)
      continue
    }
    const params = step.params ?? {}
    for (const [key, rule] of Object.entries(def.params_schema)) {
      if (!rule.required) continue
      const value = params[key]
      if (value === undefined || value === null || value === '') {
        if (key === 'mask_data_uri') continue // 蒙版缺失在下方单独提示涂抹
        issues.push(`步骤 ${step.id}（${toolLabel(step.tool)}）缺少参数：${rule.label?.split('（')[0] ?? key}`)
      }
    }
  }
  return issues
}

/** 计划中是否存在空缺蒙版的步骤（需先涂抹选区） */
function planMissingMaskSteps(msg: ChatMessage): AgentStep[] {
  if (!msg.plan) return []
  return msg.plan.steps.filter((step) => {
    const def = store.tools.find((t) => t.name === step.tool)
    return def?.requires_mask && !String(step.params?.mask_data_uri ?? '').trim()
  })
}

// ===== 计划执行（SSE 订阅 + 降级轮询） =====

const agentTaskId = ref('')
const agentTracker = useTaskSse({
  taskId: agentTaskId,
  pollFn: (id) => fetchEditorTaskStatus(id),
  onCompleted: handleAgentCompleted,
  onFailed: handleAgentFailed,
})

/** 当前订阅对应的计划消息（重试后切换到新 task_id，仍指向同一张计划卡片） */
function activePlanMessage(): ChatMessage | null {
  return messages.value.find((m) => m.kind === 'plan' && m.taskId === agentTaskId.value) ?? null
}

const hasExecutingPlan = computed(() =>
  messages.value.some((m) => m.kind === 'plan' && m.phase === 'executing'),
)

async function handleConfirmExecute(msg: ChatMessage) {
  if (!msg.plan || msg.phase !== 'draft' || msg.submitting) return
  if ((msg.errors?.length ?? 0) > 0) return
  if (hasExecutingPlan.value) {
    pushMessage('assistant', 'error', '已有计划正在执行，请等待完成或取消后再执行新计划')
    return
  }
  const target = targetLayer.value
  if (!target?.url) {
    pushMessage('assistant', 'error', '画布为空，无法执行计划')
    return
  }

  const plan = preparePlanForExecute(msg.plan)
  const issues = planParamIssues(plan)
  if (planMissingMaskSteps({ ...msg, plan }).length > 0) {
    pushMessage('assistant', 'error', '计划包含需要选区的步骤：请先在画布上涂抹选区并点击"生成蒙版"，再执行计划')
    return
  }
  if (issues.length > 0) {
    pushMessage('assistant', 'error', `计划无法执行：\n${issues.join('\n')}`)
    return
  }

  msg.submitting = true
  try {
    const res = await agentExecute(plan, {
      imageUrl: target.url,
      documentId: store.documentId ?? undefined,
    })
    msg.taskId = res.task_id
    msg.phase = 'executing'
    msg.stepStates = initStepStates(msg.order)
    msg.progressStep = '任务排队中...'
    msg.progressPct = 0
    agentTaskId.value = res.task_id
    agentTracker.start()
  } catch (err) {
    console.error('[editor-agent] 计划提交失败', err)
    pushMessage('assistant', 'error', getErrorMessage(err, '计划提交失败，请稍后重试'))
  } finally {
    msg.submitting = false
  }
}

/** 执行中：按进度文案"步骤 i/n"推导各步实时状态（执行器按拓扑序串行执行） */
function deriveStepStatesFromProgress(msg: ChatMessage) {
  if (!msg.order) return
  const prev = msg.stepStates ?? {}
  const match = /步骤\s*(\d+)\s*\//.exec(agentTracker.step)
  const currentIdx = match ? Number.parseInt(match[1], 10) - 1 : -1
  const states: Record<string, StepStatus> = {}
  msg.order.forEach((id, i) => {
    // 单步重试时前置步骤已复用原任务产物，保持"已完成"不被重置
    if (prev[id] === 'success') {
      states[id] = 'success'
      return
    }
    if (currentIdx >= 0) {
      states[id] = i < currentIdx ? 'success' : i === currentIdx ? 'running' : 'pending'
    } else {
      states[id] = 'pending'
    }
  })
  if (currentIdx < 0) {
    // 进度文案无法解析（如"加载图片"阶段）时，把首个未完成步骤标记为执行中
    const next = msg.order.find((id) => states[id] !== 'success')
    if (next) states[next] = 'running'
  }
  msg.stepStates = states
}

watch(
  () => [agentTracker.step, agentTracker.pct] as const,
  ([step, pct]) => {
    const msg = activePlanMessage()
    if (!msg || msg.phase !== 'executing') return
    msg.progressStep = step || '处理中...'
    msg.progressPct = pct
    deriveStepStatesFromProgress(msg)
  },
)

// ===== 执行结果处理 =====

/** 解析任务失败信息（兼容后端结构化 error：{message, failed_step, completed_steps}） */
function parseAgentError(raw: unknown): { message: string; failedStep?: string; completedSteps: string[] } {
  if (raw && typeof raw === 'object') {
    const obj = raw as Partial<AgentTaskError>
    return {
      message: String(obj.message ?? '任务失败'),
      failedStep: typeof obj.failed_step === 'string' ? obj.failed_step : undefined,
      completedSteps: Array.isArray(obj.completed_steps)
        ? obj.completed_steps.filter((s): s is string => typeof s === 'string')
        : [],
    }
  }
  return { message: String(raw ?? '任务失败'), completedSteps: [] }
}

function handleAgentCompleted(result: unknown) {
  const msg = activePlanMessage()
  if (!msg) return
  const r = result as AgentTaskResult | null
  const states: Record<string, StepStatus> = { ...msg.stepStates }
  for (const step of Array.isArray(r?.steps) ? r.steps : []) {
    if (step.id && step.status === 'completed') states[step.id] = 'success'
  }
  msg.stepStates = states
  msg.progressStep = '执行完成'
  msg.progressPct = 100
  msg.phase = 'completed'

  if (r?.final_image_url) {
    // 完成时压栈快照，替换后可整体撤销本次 AI 修改
    store.pushSnapshot()
    void store.replaceBackgroundImage(r.final_image_url)
    pushMessage('assistant', 'success', '修改完成，画布已更新为最终结果。可按 Ctrl+Z 撤销本次修改，或继续输入指令微调。')
  } else {
    pushMessage('assistant', 'error', '任务完成但未返回结果图，请重新执行计划')
  }
}

function handleAgentFailed(rawError: string) {
  const msg = activePlanMessage()
  if (!msg) return
  const info = parseAgentError(agentTracker.error ?? rawError)
  const states: Record<string, StepStatus> = { ...msg.stepStates }
  for (const id of info.completedSteps) {
    if (id in states) states[id] = 'success'
  }
  if (info.failedStep && info.failedStep in states) {
    states[info.failedStep] = 'failed'
  }
  msg.stepStates = states

  if (info.message.includes('取消')) {
    msg.phase = 'cancelled'
    pushMessage('assistant', 'text', '已取消后续步骤，画布未做修改。可重新发送指令，或对已完成的步骤基于原计划重新执行。')
    return
  }
  msg.phase = 'failed'
  pushMessage('assistant', 'error', `执行失败：${info.message}。可在计划卡片中对失败步骤单独重试。`)
}

// ===== 取消 / 重试 / 放弃 =====

async function handleCancel(msg: ChatMessage) {
  if (!msg.taskId || msg.phase !== 'executing') return
  try {
    await agentCancelTask(msg.taskId)
    pushMessage('assistant', 'text', '已发送取消请求，当前步骤完成后即停止。')
  } catch (err) {
    console.error('[editor-agent] 取消失败', err)
    pushMessage('assistant', 'error', getErrorMessage(err, '取消失败，请稍后再试'))
  }
}

async function handleRetryStep(msg: ChatMessage, stepId: string) {
  if (!msg.taskId || msg.retryingStepId || msg.phase === 'executing') return
  msg.retryingStepId = stepId
  try {
    const res = await agentRetryTask(msg.taskId, stepId)
    // 重试产生新任务：切换订阅目标（useTaskSse.start 内部会先停止旧订阅）
    msg.taskId = res.task_id
    msg.phase = 'executing'
    msg.progressStep = '任务排队中...'
    msg.progressPct = 0
    // 重试步之前的步骤复用原任务中间产物，直接标记已完成
    const states: Record<string, StepStatus> = {}
    let reached = false
    for (const id of msg.order ?? []) {
      if (id === stepId) reached = true
      states[id] = reached ? (id === stepId ? 'running' : 'pending') : 'success'
    }
    msg.stepStates = states
    agentTaskId.value = res.task_id
    agentTracker.start()
  } catch (err) {
    console.error('[editor-agent] 步骤重试失败', err)
    pushMessage('assistant', 'error', getErrorMessage(err, '重试失败，请稍后再试'))
  } finally {
    msg.retryingStepId = undefined
  }
}

function handleDiscard(msg: ChatMessage) {
  if (msg.phase === 'executing') return
  removeMessage(msg.id)
}

// ===== 步骤展示辅助 =====

function orderedSteps(msg: ChatMessage): Array<{ step: AgentStep; status: StepStatus; index: number }> {
  if (!msg.plan) return []
  const byId = new Map(msg.plan.steps.map((s) => [s.id, s]))
  const order = msg.order ?? msg.plan.steps.map((s) => s.id)
  return order
    .map((id, index) => {
      const step = byId.get(id)
      if (!step) return null
      return { step, status: msg.stepStates?.[id] ?? 'pending', index }
    })
    .filter((item): item is { step: AgentStep; status: StepStatus; index: number } => item !== null)
}

const STEP_BADGES: Record<StepStatus, { label: string; class: string }> = {
  pending: { label: '待执行', class: 'bg-slate-100 text-slate-500' },
  running: { label: '执行中', class: 'bg-blue-100 text-blue-600' },
  success: { label: '已完成', class: 'bg-emerald-100 text-emerald-600' },
  failed: { label: '失败', class: 'bg-red-100 text-red-600' },
}

function dependencyHint(msg: ChatMessage, step: AgentStep): string {
  const deps = step.depends_on ?? []
  if (deps.length === 0) return ''
  const labels = deps.map((depId) => {
    const dep = msg.plan?.steps.find((s) => s.id === depId)
    return dep ? `步骤 ${stepIndexOf(msg, depId) + 1}（${toolLabel(dep.tool)}）` : depId
  })
  return `依赖：${labels.join('、')}`
}

function stepIndexOf(msg: ChatMessage, stepId: string): number {
  const order = msg.order ?? msg.plan?.steps.map((s) => s.id) ?? []
  return order.indexOf(stepId)
}

function planCardTitle(msg: ChatMessage): string {
  switch (msg.phase) {
    case 'draft':
      return '修图计划（待确认）'
    case 'executing':
      return '修图计划（执行中）'
    case 'completed':
      return '修图计划（已完成）'
    case 'failed':
      return '修图计划（执行失败）'
    case 'cancelled':
      return '修图计划（已取消）'
    default:
      return '修图计划'
  }
}

// ===== 滚动与生命周期 =====

const listRef = ref<HTMLElement | null>(null)

function scrollToBottom() {
  const el = listRef.value
  if (el) el.scrollTop = el.scrollHeight
}

// 面板隐藏（v-show 切换页签）时组件不卸载，SSE 订阅保持运行，任务进度不中断
onBeforeUnmount(() => {
  agentTracker.stop()
})
</script>

<template>
  <div class="flex flex-col min-h-0 h-full">
    <!-- 头部 -->
    <div class="px-4 pt-2 pb-2 border-b border-slate-100 shrink-0">
      <div class="flex items-center gap-2">
        <span class="w-6 h-6 rounded-lg bg-brand-gradient flex items-center justify-center">
          <Sparkles class="w-3.5 h-3.5 text-white" />
        </span>
        <h3 class="text-xs font-semibold text-slate-700">AI 修图助手</h3>
        <span
          v-if="hasExecutingPlan"
          class="ml-auto inline-flex items-center gap-1 text-[10px] text-blue-600"
        >
          <Loader2 class="w-3 h-3 animate-spin" />
          计划执行中
        </span>
      </div>
    </div>

    <!-- 消息列表 -->
    <div ref="listRef" class="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-3">
      <!-- 空态引导 -->
      <div v-if="messages.length === 0" class="text-center py-6 px-2">
        <div class="w-10 h-10 rounded-full bg-brand-gradient-subtle flex items-center justify-center mx-auto mb-2">
          <Sparkles class="w-5 h-5 text-brand-purple" />
        </div>
        <p class="text-xs text-slate-600 font-medium">用一句话描述想要的修改</p>
        <p class="text-[11px] text-slate-400 mt-1 leading-4">
          AI 会拆解为编辑计划，确认后自动执行
        </p>
        <div class="mt-3 space-y-1.5">
          <button
            v-for="example in EXAMPLE_INSTRUCTIONS"
            :key="example"
            type="button"
            class="w-full px-3 py-1.5 rounded-xl text-[11px] text-slate-600 bg-white border border-slate-200 hover:border-brand-purple/40 hover:text-brand-purple transition-colors text-left"
            @click="applyExample(example)"
          >
            {{ example }}
          </button>
        </div>
      </div>

      <!-- 消息 -->
      <template v-for="msg in messages" :key="msg.id">
        <!-- 用户消息 -->
        <div v-if="msg.role === 'user'" class="flex justify-end">
          <div class="max-w-[85%] px-3 py-2 rounded-xl text-xs leading-relaxed bg-brand-gradient text-white rounded-br-sm whitespace-pre-line">
            {{ msg.text }}
          </div>
        </div>

        <!-- 助手文本消息 -->
        <div v-else-if="msg.kind === 'text'" class="flex justify-start">
          <div class="max-w-[85%] px-3 py-2 rounded-xl text-xs leading-relaxed bg-slate-100 text-slate-700 rounded-bl-sm whitespace-pre-line">
            {{ msg.text }}
          </div>
        </div>

        <!-- 错误消息 -->
        <div v-else-if="msg.kind === 'error'" class="flex justify-start">
          <div class="max-w-[90%] rounded-xl bg-red-50 border border-red-100 px-3 py-2 text-xs leading-relaxed text-red-600 flex items-start gap-1.5">
            <AlertCircle class="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span class="whitespace-pre-line">{{ msg.text }}</span>
          </div>
        </div>

        <!-- 完成提示 -->
        <div v-else-if="msg.kind === 'success'" class="flex justify-start">
          <div class="max-w-[90%] rounded-xl bg-emerald-50 border border-emerald-100 px-3 py-2 text-xs leading-relaxed text-emerald-700 flex items-start gap-1.5">
            <CheckCircle2 class="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{{ msg.text }}</span>
          </div>
        </div>

        <!-- 计划卡片 -->
        <div v-else-if="msg.kind === 'plan' && msg.plan" class="rounded-xl border border-slate-200 bg-white overflow-hidden">
          <!-- 卡片头 -->
          <div class="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-slate-100">
            <div class="flex items-center gap-1.5 min-w-0">
              <ListChecks class="w-3.5 h-3.5 text-brand-purple shrink-0" />
              <span class="text-xs font-medium text-slate-700 truncate">{{ planCardTitle(msg) }}</span>
              <span class="text-[10px] text-slate-400 shrink-0">{{ msg.plan.steps.length }} 步</span>
            </div>
            <span
              v-if="msg.taskId"
              class="text-[10px] text-slate-300 truncate ml-2"
              :title="msg.taskId"
            >
              #{{ msg.taskId.slice(0, 8) }}
            </span>
          </div>

          <!-- 计划校验错误（后端返回 errors 时不可执行） -->
          <div
            v-if="(msg.errors?.length ?? 0) > 0"
            class="mx-3 mt-2 rounded-lg bg-amber-50 border border-amber-200 px-2.5 py-2 text-[11px] text-amber-700 leading-4"
          >
            <p class="font-medium mb-0.5">计划校验未通过，无法执行：</p>
            <p v-for="(error, i) in msg.errors" :key="i">{{ error }}</p>
          </div>

          <!-- 步骤列表 -->
          <div class="px-3 py-2 space-y-1.5">
            <div
              v-for="item in orderedSteps(msg)"
              :key="item.step.id"
              class="rounded-lg border px-2.5 py-2"
              :class="item.status === 'failed' ? 'border-red-200 bg-red-50/50' : 'border-slate-100 bg-slate-50/60'"
            >
              <div class="flex items-center gap-2">
                <span class="w-5 h-5 shrink-0 rounded-md bg-white border border-slate-200 text-[10px] font-semibold text-slate-500 flex items-center justify-center">
                  {{ item.index + 1 }}
                </span>
                <span class="flex-1 min-w-0 text-xs text-slate-700 truncate" :title="item.step.tool">
                  {{ toolLabel(item.step.tool) }}
                </span>
                <span
                  class="shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
                  :class="STEP_BADGES[item.status].class"
                >
                  <Loader2 v-if="item.status === 'running'" class="w-2.5 h-2.5 animate-spin" />
                  {{ STEP_BADGES[item.status].label }}
                </span>
              </div>
              <p v-if="dependencyHint(msg, item.step)" class="mt-1 pl-7 text-[10px] text-slate-400">
                {{ dependencyHint(msg, item.step) }}
              </p>
              <div
                v-if="item.status === 'failed' && msg.taskId && msg.phase !== 'executing'"
                class="mt-1.5 pl-7"
              >
                <button
                  type="button"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  :disabled="!!msg.retryingStepId || hasExecutingPlan"
                  @click="handleRetryStep(msg, item.step.id)"
                >
                  <Loader2 v-if="msg.retryingStepId === item.step.id" class="w-3 h-3 animate-spin" />
                  {{ msg.retryingStepId === item.step.id ? '重试中...' : '重试此步' }}
                </button>
              </div>
            </div>
          </div>

          <!-- 执行中整体进度 -->
          <div v-if="msg.phase === 'executing'" class="mx-3 mb-2">
            <div class="flex items-center gap-2 mb-1">
              <Loader2 class="w-3 h-3 text-brand-purple animate-spin shrink-0" />
              <p class="flex-1 min-w-0 text-[11px] text-slate-500 truncate">
                {{ msg.progressStep || '处理中...' }}
              </p>
              <span class="text-[11px] font-semibold text-brand-purple shrink-0 tabular-nums">
                {{ Math.round(msg.progressPct ?? 0) }}%
              </span>
            </div>
            <div class="h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div
                class="h-full rounded-full bg-brand-gradient transition-all duration-300"
                :style="{ width: Math.min(100, Math.max(2, msg.progressPct ?? 0)) + '%' }"
              />
            </div>
          </div>

          <!-- 蒙版步骤提示：需要涂抹选区（草稿 / 失败状态可补充） -->
          <div
            v-if="planMissingMaskSteps(msg).length > 0 && (msg.phase === 'draft' || msg.phase === 'failed' || msg.phase === 'cancelled')"
            class="mx-3 mb-2 rounded-lg bg-brand-gradient-subtle border border-brand-purple/20 px-2.5 py-2"
          >
            <p class="text-[11px] text-brand-purple font-medium mb-1.5">
              该计划包含需要选区的步骤（{{ planMissingMaskSteps(msg).map((s) => toolLabel(s.tool)).join('、') }}）
            </p>
            <EditorMaskBrushPanel />
          </div>

          <!-- 卡片操作 -->
          <div class="flex items-center gap-2 px-3 py-2 border-t border-slate-100 bg-slate-50/60">
            <template v-if="msg.phase === 'draft'">
              <button
                type="button"
                class="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-[11px] font-medium text-white bg-brand-gradient hover:shadow-glow transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                :disabled="!!msg.submitting || (msg.errors?.length ?? 0) > 0 || hasExecutingPlan"
                @click="handleConfirmExecute(msg)"
              >
                <Loader2 v-if="msg.submitting" class="w-3 h-3 animate-spin" />
                <Sparkles v-else class="w-3 h-3" />
                {{ msg.submitting ? '提交中...' : '确认执行' }}
              </button>
              <button
                type="button"
                class="px-3 py-1.5 rounded-lg text-[11px] text-slate-500 bg-white border border-slate-200 hover:border-slate-300 transition-colors"
                @click="handleDiscard(msg)"
              >
                放弃
              </button>
            </template>
            <template v-else-if="msg.phase === 'executing'">
              <button
                type="button"
                class="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-[11px] font-medium text-red-600 bg-white border border-red-200 hover:bg-red-50 transition-colors"
                @click="handleCancel(msg)"
              >
                <Square class="w-3 h-3" />
                取消后续步骤
              </button>
            </template>
            <template v-else>
              <p class="flex-1 text-[10px] text-slate-400 leading-4">
                {{ msg.phase === 'completed' ? '结果已应用，画布可继续编辑' : '计划未完成，可重试失败步骤或重新发送指令' }}
              </p>
              <button
                v-if="msg.phase !== 'completed'"
                type="button"
                class="px-3 py-1.5 rounded-lg text-[11px] text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors shrink-0"
                @click="handleDiscard(msg)"
              >
                移除卡片
              </button>
            </template>
          </div>
        </div>
      </template>

      <!-- 规划中占位 -->
      <div v-if="planning" class="flex justify-start">
        <div class="px-3 py-2 rounded-xl bg-slate-100 text-slate-500 text-xs flex items-center gap-2">
          <Loader2 class="w-3.5 h-3.5 animate-spin" />
          AI 正在规划修改方案...
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="px-3 py-3 border-t border-slate-100 shrink-0">
      <div class="flex items-end gap-2">
        <textarea
          v-model="input"
          rows="2"
          placeholder="描述想要的修改，如：把背景换成白色摄影棚"
          class="glass-input flex-1 px-3 py-2 text-xs resize-none leading-relaxed"
          :disabled="planning"
          @keydown="handleInputKeydown"
        />
        <button
          type="button"
          class="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          :class="input.trim() && !planning ? 'bg-brand-gradient text-white hover:shadow-glow' : 'bg-slate-100 text-slate-400'"
          :disabled="!input.trim() || planning"
          title="发送指令（Enter）"
          @click="handleSend"
        >
          <Loader2 v-if="planning" class="w-4 h-4 animate-spin" />
          <Send v-else class="w-4 h-4" />
        </button>
      </div>
      <p class="mt-1.5 text-[10px] text-slate-300">Enter 发送，Shift+Enter 换行</p>
    </div>
  </div>
</template>
