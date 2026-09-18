<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'
import {
  Plus,
  Trash2,
  X,
  ChevronDown,
  Sparkles,
  ArrowLeft,
  Upload,
  AlertCircle,
  MessageSquare,
  Check,
  Eye,
  Lock,
  Loader2,
  RotateCcw,
} from 'lucide-vue-next'
import type {
  AspectRatio,
  ProImageType,
  ProTaskState,
  PromptScheme,
  SchemeStatus,
} from '@/types'
import {
  resolveSizeFromRatioAndResolution,
  parseCustomSize,
  type SizeResult,
  imageUrlToBase64,
} from '@/lib/utils'
import { getContextualErrorMessage } from '@/lib/error'
import {
  proAnalyzeIntegrate,
  proDialogOptimize,
  proConfirmGenerate,
  getProBatchStatus,
  proAutoFillSchemes,
  getTaskStatus,
} from '@/api/generation'
import { useWorkspaceStore } from '@/stores/workspace'
import { useTaskSse, type TaskStatus } from '@/composables/useTaskSse'
import { previewPrompt, type PromptPreview } from '@/api/template'

const workspaceStore = useWorkspaceStore()

// ==================== 基础设置选项 ====================
const platforms = [
  'Amazon', 'AliExpress', 'Shopee', 'Lazada', 'TikTok Shop',
  'Temu', 'Shein', 'Walmart', 'eBay', 'Etsy',
  'Rakuten', 'Mercado Libre', 'Jumia', 'Daraz', 'Ozon',
  '独立站',
]
const regions = [
  '美国', '英国', '德国', '法国', '日本',
  '韩国', '澳大利亚', '加拿大', '巴西', '墨西哥',
  '印度', '印尼', '泰国', '越南', '菲律宾',
  '马来西亚', '新加坡', '沙特阿拉伯', '阿联酋', '土耳其',
  '波兰', '西班牙', '意大利', '荷兰', '俄罗斯',
]
const languages = [
  '英语', '中文', '日语', '韩语',
  '德语', '法语', '西班牙语', '意大利语',
  '葡萄牙语', '荷兰语', '波兰语', '俄语',
  '泰语', '越南语', '印尼语',
  '阿拉伯语', '土耳其语', '印地语', '马来语',
]
const ratios: AspectRatio[] = ['1:1', '3:4', '4:3', '16:9']
const resolutions = [
  { value: '1024x1024', label: '1K' },
  { value: '2048x2048', label: '2K' },
  { value: '3840x2160', label: '4K' },
  { value: 'custom', label: '自定义' },
]
const ratioOptions: { value: AspectRatio; label: string }[] = [
  { value: '1:1', label: '1:1' },
  { value: '3:4', label: '3:4' },
  { value: '4:3', label: '4:3' },
  { value: '16:9', label: '16:9' },
  { value: 'custom', label: '自定义' },
]

// 9 类图片类型(与后端 ImageType 枚举对齐)
const imageTypeOptions: { value: ProImageType; label: string; desc: string }[] = [
  { value: 'main_image', label: '主图', desc: '平台首图,决定点击率' },
  { value: 'sub_image', label: '副图', desc: '补充展示商品多角度' },
  { value: 'white_bg', label: '白底图', desc: '纯白背景商品图' },
  { value: 'scene', label: '场景图', desc: '生活化场景展示' },
  { value: 'selling_point', label: '卖点图', desc: '突出商品卖点' },
  { value: 'checklist', label: '清单图', desc: '商品清单/参数' },
  { value: 'material', label: '材质图', desc: '材质细节特写' },
  { value: 'size_chart', label: '尺寸图', desc: '尺寸说明图' },
  { value: 'other', label: '其他', desc: '其他类型图片' },
]

function imageTypeLabel(t: ProImageType): string {
  return imageTypeOptions.find((o) => o.value === t)?.label || t
}

// ==================== 第一块区域:基础设置 ====================
const selectedPlatform = ref('Amazon')
const selectedRegion = ref('美国')
const selectedLanguage = ref('英语')
const selectedRatio = ref<AspectRatio>('1:1')
const customRatioInput = ref('')
const selectedResolution = ref('1024x1024')
const customWidth = ref('')
const customHeight = ref('')
const requirementText = ref('')

const customPlatform = ref('')
const customRegion = ref('')
const customLanguage = ref('')

const platformOpen = ref(false)
const regionOpen = ref(false)
const languageOpen = ref(false)
const ratioOpen = ref(false)

const platformTrigger = ref<HTMLElement | null>(null)
const regionTrigger = ref<HTMLElement | null>(null)
const languageTrigger = ref<HTMLElement | null>(null)
const ratioTrigger = ref<HTMLElement | null>(null)

const platformPos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })
const regionPos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })
const languagePos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })
const ratioPos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })

const selectedPromptLang = ref('English')
const promptLangOpen = ref(false)
const promptLangTrigger = ref<HTMLElement | null>(null)
const promptLangPos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })

async function updatePosition(trigger: HTMLElement | null, pos: typeof platformPos) {
  if (!trigger) return
  await nextTick()
  const rect = trigger.getBoundingClientRect()
  pos.value = {
    top: rect.bottom + window.scrollY + 4,
    left: rect.left + window.scrollX,
    width: rect.width,
  }
}

function closeAllDropdowns() {
  platformOpen.value = false
  regionOpen.value = false
  languageOpen.value = false
  ratioOpen.value = false
  promptLangOpen.value = false
}

function openDropdown(which: 'platform' | 'region' | 'language' | 'ratio' | 'promptLang') {
  closeAllDropdowns()
  if (which === 'platform') {
    platformOpen.value = true
    updatePosition(platformTrigger.value, platformPos)
  } else if (which === 'region') {
    regionOpen.value = true
    updatePosition(regionTrigger.value, regionPos)
  } else if (which === 'language') {
    languageOpen.value = true
    updatePosition(languageTrigger.value, languagePos)
  } else if (which === 'ratio') {
    ratioOpen.value = true
    updatePosition(ratioTrigger.value, ratioPos)
  } else if (which === 'promptLang') {
    promptLangOpen.value = true
    updatePosition(promptLangTrigger.value, promptLangPos)
  }
}

// ==================== 尺寸约束 ====================
const sizeWarning = ref('')

const resolvedSize = computed<SizeResult>(() => {
  const resInput = selectedResolution.value === 'custom'
    ? (customWidth.value && customHeight.value ? `${customWidth.value}x${customHeight.value}` : '')
    : selectedResolution.value
  return resolveSizeFromRatioAndResolution(selectedRatio.value, resInput)
})

watch([customWidth, customHeight], ([w, h]) => {
  if (selectedResolution.value !== 'custom') return
  if (!w || !h) {
    sizeWarning.value = ''
    return
  }
  const wNum = parseInt(String(w), 10)
  const hNum = parseInt(String(h), 10)
  if (!wNum || !hNum || wNum <= 0 || hNum <= 0) {
    sizeWarning.value = ''
    return
  }
  const result = parseCustomSize(`${wNum}x${hNum}`)
  if (result?.corrected) {
    sizeWarning.value = result.reason || '输入值已自动调整以符合规则'
  } else {
    sizeWarning.value = ''
  }
})

watch([selectedRatio, selectedResolution], () => {
  if (selectedResolution.value !== 'custom') {
    sizeWarning.value = ''
  }
})

// ==================== 批次级商品图 / 参考图 ====================
interface BatchImage {
  id: string
  url: string
  name?: string
}

const batchProductImages = ref<BatchImage[]>([])
const batchReferenceImage = ref<BatchImage | null>(null)

function handleBatchProductUpload(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files) return
  const validFiles = Array.from(files).filter((f) =>
    ['image/jpeg', 'image/png', 'image/webp'].includes(f.type),
  )
  const newImages: BatchImage[] = validFiles.map((f) => ({
    id: `bp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    url: URL.createObjectURL(f),
    name: f.name,
  }))
  batchProductImages.value.push(...newImages)
  ;(e.target as HTMLInputElement).value = ''
}

function handleBatchRefUpload(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files || !files[0]) return
  const file = files[0]
  batchReferenceImage.value = {
    id: `br-${Date.now()}`,
    url: URL.createObjectURL(file),
    name: file.name,
  }
  ;(e.target as HTMLInputElement).value = ''
}

function removeBatchProductImage(id: string) {
  batchProductImages.value = batchProductImages.value.filter((img) => img.id !== id)
}

function removeBatchReferenceImage() {
  batchReferenceImage.value = null
}

// ==================== 第二块区域:任务卡片(配置阶段) ====================
interface ProTaskConfig {
  id: string
  name: string
  imageType: ProImageType
  requirement: string
  aspectRatio: AspectRatio
}

const taskCards = ref<ProTaskConfig[]>([])
let taskCounter = 0

function makeTaskId() {
  taskCounter++
  return `task-${Date.now()}-${taskCounter}`
}

function addTaskCard() {
  const defaultRatio: AspectRatio = (
    ['1:1', '3:4', '4:3', '16:9', 'custom'].includes(selectedRatio.value)
      ? selectedRatio.value
      : '1:1'
  ) as AspectRatio
  taskCards.value.push({
    id: makeTaskId(),
    name: `生图任务 ${taskCards.value.length + 1}`,
    imageType: 'main_image',
    requirement: '',
    aspectRatio: defaultRatio,
  })
}

function removeTaskCard(id: string) {
  taskCards.value = taskCards.value.filter((t) => t.id !== id)
}

// 任务配置弹窗(编辑 imageType/requirement/aspectRatio)
const configDialogTaskId = ref<string | null>(null)
const configDialogTask = computed<ProTaskConfig | null>(
  () => taskCards.value.find((t) => t.id === configDialogTaskId.value) || null,
)

function openConfigDialog(id: string) {
  configDialogTaskId.value = id
}

function closeConfigDialog() {
  configDialogTaskId.value = null
}

// ==================== 三阶段流程状态 ====================
type ProPhase = 'config' | 'optimize' | 'generate'
const proPhase = ref<ProPhase>('config')

// 阶段一:AI 分析整合
const isAnalyzing = ref(false)
const analyzeError = ref('')

// 批次 ID
const proBatchId = ref<string | null>(null)

// 阶段二:任务方案列表(来自后端)
const proTasks = ref<ProTaskState[]>([])

// 阶段二:对话面板
const dialogTaskId = ref<string | null>(null)
const dialogInput = ref('')
const isOptimizing = ref(false)
const dialogError = ref('')
const dialogPanelRef = ref<HTMLElement | null>(null)

// 阶段三:确认生图
const isConfirming = ref(false)
const confirmError = ref('')

// 一键补全空方案
const isAutoFilling = ref(false)
const autoFillError = ref('')

// ==================== 提示词预览（方案确认区入口） ====================
const previewOpen = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const previewResult = ref<PromptPreview | null>(null)
const previewTaskId = ref('')

const previewTask = computed<ProTaskState | null>(
  () => proTasks.value.find((t) => t.task_id === previewTaskId.value) || null,
)

async function loadPromptPreview() {
  const task = previewTask.value
  if (!task) return
  previewLoading.value = true
  previewError.value = ''
  try {
    const platform = selectedPlatform.value === '其他' ? customPlatform.value : selectedPlatform.value
    const result = await previewPrompt({
      // 专业模式未采集结构化商品信息，productInfo 留空，由后端基于批次商品图补全
      productInfo: {
        productName: '',
        targetAudience: '',
        usageScenario: '',
        productCategory: '',
        sellingPoints: [],
      },
      // ProTaskState 类型未含 requirement 字段（配置卡片的 requirement 由后端透传时才存在）
      scene: (task as ProTaskState & { requirement?: string }).requirement
        || task.scheme?.image_role
        || '',
      site: platform,
      imageType: task.image_type,
    })
    previewResult.value = result
  } catch (err) {
    previewError.value = getContextualErrorMessage(err, '提示词预览失败，请稍后重试', 'pro')
  } finally {
    previewLoading.value = false
  }
}

function openPreviewPanel() {
  if (proTasks.value.length === 0) return
  // 当前选中任务不在批次中（如重新分析后）时回退为第一个任务
  if (!proTasks.value.some((t) => t.task_id === previewTaskId.value)) {
    previewTaskId.value = proTasks.value[0].task_id
  }
  previewResult.value = null
  previewError.value = ''
  previewOpen.value = true
  loadPromptPreview()
}

function selectPreviewTask(taskId: string) {
  if (taskId === previewTaskId.value) return
  previewTaskId.value = taskId
  loadPromptPreview()
}

function closePreviewPanel() {
  previewOpen.value = false
}

// 当前打开对话的任务
const dialogTask = computed<ProTaskState | null>(
  () => proTasks.value.find((t) => t.task_id === dialogTaskId.value) || null,
)

// ==================== 专业模式定价加载 ====================
// 挂载时预加载专业模式定价（任务数暂取当前 taskCards 数，分析后会刷新）
// 这样 ConfigPanel/AssetPanel 中的 CostEstimator 在专业模式下也能显示真实估算
onMounted(() => {
  const size = `${resolvedSize.value.width}x${resolvedSize.value.height}`
  workspaceStore.loadProPricing(size, taskCards.value.length)
})

// 尺寸变化时刷新专业模式定价
watch(resolvedSize, (val) => {
  if (!val?.width || !val?.height) return
  const size = `${val.width}x${val.height}`
  workspaceStore.loadProPricing(size, proTasks.value.length || taskCards.value.length)
})

// 任务数变化时刷新专业模式定价（分析后用 proTasks，分析前用 taskCards）
watch(
  () => proTasks.value.length || taskCards.value.length,
  (count) => {
    const size = `${resolvedSize.value.width}x${resolvedSize.value.height}`
    workspaceStore.loadProPricing(size, count)
  },
)

// ==================== 阶段一:触发 AI 分析整合 ====================
async function handleAnalyzeIntegrate() {
  analyzeError.value = ''

  if (batchProductImages.value.length === 0) {
    analyzeError.value = '请先上传至少一张商品图'
    return
  }
  if (taskCards.value.length === 0) {
    analyzeError.value = '请先添加至少一个生图任务'
    return
  }

  isAnalyzing.value = true
  try {
    const allProductBase64 = await Promise.all(
      batchProductImages.value.map((img) => imageUrlToBase64(img.url)),
    )
    const referenceImageBase64 = batchReferenceImage.value
      ? await imageUrlToBase64(batchReferenceImage.value.url)
      : undefined

    const platform = selectedPlatform.value === '其他' ? customPlatform.value : selectedPlatform.value
    const region = selectedRegion.value === '其他' ? customRegion.value : selectedRegion.value
    const targetLanguage = selectedLanguage.value === '其他' ? customLanguage.value : selectedLanguage.value
    const size = `${resolvedSize.value.width}x${resolvedSize.value.height}`

    const result = await proAnalyzeIntegrate({
      product_images: allProductBase64,
      reference_image: referenceImageBase64,
      reference_text: requirementText.value || undefined,
      platform,
      region,
      target_language: targetLanguage,
      size,
      requirement: requirementText.value || undefined,
      prompt_language: selectedPromptLang.value === '中文' ? 'zh' : 'en',
      image_tasks: taskCards.value.map((t) => ({
        task_name: t.name,
        image_type: t.imageType,
        requirement: t.requirement || undefined,
        aspect_ratio: t.aspectRatio,
      })),
    })

    proBatchId.value = result.batch_id
    proTasks.value = result.tasks
    proPhase.value = 'optimize'
    workspaceStore.setProBatchId(result.batch_id)
    // 分析完成后加载专业模式定价（任务数已知）
    workspaceStore.loadProPricing(size, proTasks.value.length)
  } catch (err) {
    analyzeError.value = getContextualErrorMessage(err, 'AI 分析整合失败,请稍后重试', 'pro')
  } finally {
    isAnalyzing.value = false
  }
}

// ==================== 阶段二:对话优化 ====================
function openDialog(taskId: string) {
  dialogTaskId.value = taskId
  dialogInput.value = ''
  dialogError.value = ''
  nextTick(() => {
    if (dialogPanelRef.value) {
      dialogPanelRef.value.scrollTop = dialogPanelRef.value.scrollHeight
    }
  })
}

function closeDialog() {
  dialogTaskId.value = null
  dialogInput.value = ''
  dialogError.value = ''
}

async function sendDialogOptimize() {
  if (!dialogTaskId.value || !proBatchId.value) return
  if (!dialogInput.value.trim() || isOptimizing.value) return

  const taskId = dialogTaskId.value
  const userInput = dialogInput.value.trim()
  const task = proTasks.value.find((t) => t.task_id === taskId)
  if (!task) return

  isOptimizing.value = true
  dialogError.value = ''
  try {
    const result = await proDialogOptimize({
      batch_id: proBatchId.value,
      task_id: taskId,
      user_input: userInput,
      dialog_history: task.dialog_history,
    })

    task.scheme = result.scheme
    task.dialog_history = result.dialog_history
    task.status = 'pending'

    dialogInput.value = ''
    nextTick(() => {
      if (dialogPanelRef.value) {
        dialogPanelRef.value.scrollTop = dialogPanelRef.value.scrollHeight
      }
    })
  } catch (err) {
    dialogError.value = getContextualErrorMessage(err, '对话优化失败,请稍后重试', 'pro')
  } finally {
    isOptimizing.value = false
  }
}

function handleDialogKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendDialogOptimize()
  }
}

// ==================== 阶段三:确认方案并触发生图 ====================
const canConfirm = computed(() => {
  if (proTasks.value.length === 0) return false
  return proTasks.value.every((t) => !isSchemeEmpty(t.scheme))
})

function isSchemeEmpty(scheme?: PromptScheme): boolean {
  if (!scheme) return true
  return !scheme.image_name && !scheme.image_role
    && !scheme.layout_prompt.product_state
    && !scheme.layout_prompt.composition
    && !scheme.layout_prompt.background
}

// 判断是否存在空方案
const hasEmptyScheme = computed(() => {
  return proTasks.value.some((t) => isSchemeEmpty(t.scheme))
})

// 单个任务重新生成方案
const regeneratingTaskIds = ref<Set<string>>(new Set())

async function handleAutoFillSchemes() {
  if (!proBatchId.value || isAutoFilling.value) return

  isAutoFilling.value = true
  autoFillError.value = ''
  try {
    const result = await proAutoFillSchemes(proBatchId.value)
    proTasks.value = result.tasks as ProTaskState[]
  } catch (err) {
    autoFillError.value = getContextualErrorMessage(err, '方案补全失败，请稍后重试', 'pro')
  } finally {
    isAutoFilling.value = false
  }
}

async function handleRegenerateScheme(taskId: string) {
  if (!proBatchId.value || regeneratingTaskIds.value.has(taskId)) return

  regeneratingTaskIds.value.add(taskId)
  try {
    const result = await proAutoFillSchemes(proBatchId.value)
    proTasks.value = result.tasks as ProTaskState[]
  } catch (err) {
    autoFillError.value = getContextualErrorMessage(err, '方案生成失败，请稍后重试', 'pro')
  } finally {
    regeneratingTaskIds.value.delete(taskId)
  }
}

async function handleConfirmGenerate() {
  if (!proBatchId.value || isConfirming.value) return

  isConfirming.value = true
  confirmError.value = ''
  try {
    // 触发生图前确保专业模式定价已加载（不阻塞失败，由后端最终判定扣点）
    const size = `${resolvedSize.value.width}x${resolvedSize.value.height}`
    await workspaceStore.loadProPricing(size, proTasks.value.length)

    await proConfirmGenerate({ batch_id: proBatchId.value })
    proPhase.value = 'generate'
    workspaceStore.setProGenerating(true)
    startProPolling()
  } catch (err) {
    confirmError.value = getContextualErrorMessage(err, '触发生图失败,请稍后重试', 'pro')
  } finally {
    isConfirming.value = false
  }
}

// ==================== 生图进度订阅（SubTask 8.4：SSE + 降级轮询） ====================
/** 兜底超时：与原轮询 15 分钟上限一致 */
const MAX_PRO_TRACKING_DURATION = 15 * 60 * 1000
const proSseTaskId = ref('')
let proTrackingTimer: ReturnType<typeof setTimeout> | null = null
let proFinished = true
const fetchedProImageTaskIds = new Set<string>()

/** 远程任务形状：SSE 批次聚合事件与降级轮询 GET 归一化后的公共字段 */
interface ProRemoteTask {
  task_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  image_url?: string | null
  has_image?: boolean
  error_msg?: string | null
}

/** 专业模式 GET 响应任务（方案任务 + gen_status 合并）→ 统一远程任务形状 */
function proResponseTaskToRemote(t: any): ProRemoteTask {
  const gen = (t as any).gen_status
  return {
    task_id: t.task_id,
    status: gen === 'success' ? 'completed' : gen === 'failed' ? 'failed' : 'running',
    image_url: t.result_url || '',
    has_image: !!(t as any).has_image,
    error_msg: t.error_message || null,
  }
}

async function fetchProTaskImage(taskId: string): Promise<void> {
  try {
    const task = await getTaskStatus(taskId)
    if (task.image_url) {
      const localTask = proTasks.value.find((t) => t.task_id === taskId)
      if (localTask) {
        localTask.result_url = task.image_url
      }
      // 同步到 workspaceStore.generatedImages
      workspaceStore.generatedImages = workspaceStore.generatedImages.map(img =>
        img.id === taskId ? { ...img, url: task.image_url || '' } : img
      )
    } else {
      console.warn(`[专业模式图片获取] task=${taskId} 返回成功但无 image_url`)
      const localTask = proTasks.value.find((t) => t.task_id === taskId)
      if (localTask) { localTask.error_message = '图片数据获取失败' }
      workspaceStore.generatedImages = workspaceStore.generatedImages.map(img =>
        img.id === taskId ? { ...img, status: 'failed' as const, errorMsg: '图片数据获取失败' } : img
      )
    }
  } catch (err) {
    console.error(`[专业模式图片获取] task=${taskId} 失败:`, err)
    const localTask = proTasks.value.find((t) => t.task_id === taskId)
    if (localTask) { localTask.error_message = '图片加载失败，请重试' }
    workspaceStore.generatedImages = workspaceStore.generatedImages.map(img =>
      img.id === taskId ? { ...img, status: 'failed' as const, errorMsg: '图片加载失败，请重试' } : img
    )
    fetchedProImageTaskIds.delete(taskId)
  }
}

/** 降级轮询：专业模式批次 GET → 统一 TaskStatus（SSE 连续失败时由 useTaskSse 调用，2s 间隔） */
async function pollProBatchStatus(bid: string): Promise<TaskStatus> {
  const result = await getProBatchStatus(bid)
  const tasks = result.tasks.map(proResponseTaskToRemote)
  const allDone = tasks.length > 0 && tasks.every(
    t => t.status === 'completed' || t.status === 'failed',
  )
  return {
    status: allDone ? 'completed' : 'running',
    step: '',
    pct: 0,
    result: { batch_id: bid, tasks },
    error: null,
  }
}

/**
 * 应用一次生图进度刷新（SSE 事件与降级轮询同源），返回是否全部任务到终态。
 * 单任务完成数（successCount/finishedCount）仍由前端基于 proTasks 聚合计算，
 * 仅把"每次状态刷新"的来源从轮询响应换成 SSE 事件。
 */
async function applyProBatchTasks(tasks: ProRemoteTask[]): Promise<boolean> {
  if (!tasks.length) return false

  for (const remote of tasks) {
    const localTask = proTasks.value.find((t) => t.task_id === remote.task_id)
    if (localTask) {
      // 生图阶段方案状态固定为 locked（与原轮询 remoteTask.status 一致）
      localTask.status = 'locked'
      // 保留已有 result_url：后端已剥离 base64 数据，仅 has_image=true 时不覆盖
      if (remote.status === 'completed' && remote.image_url) {
        localTask.result_url = remote.image_url
      }
      localTask.has_image = remote.has_image
      localTask.error_message = remote.error_msg || undefined
    }
  }

  // 后端已剥离 base64 数据 URI，对成功但缺图的任务单独获取图片
  const imageFetches: Promise<void>[] = []
  for (const remote of tasks) {
    if (remote.has_image && !remote.image_url) {
      const tid = remote.task_id
      if (!fetchedProImageTaskIds.has(tid)) {
        fetchedProImageTaskIds.add(tid)
        imageFetches.push(fetchProTaskImage(tid))
      }
    }
  }
  // 等待所有图片获取完成后再判定是否全部完成
  if (imageFetches.length > 0) {
    await Promise.allSettled(imageFetches)
  }

  // 同步 proTasks 结果到 workspaceStore.generatedImages，供 CanvasArea 展示
  workspaceStore.generatedImages = proTasks.value
    .filter(t => t.result_url || t.has_image || t.error_message)
    .map(t => ({
      id: t.task_id,
      taskId: t.generation_task_id || t.task_id,
      batchId: proBatchId.value || '',
      url: t.result_url || '',
      prompt: '',
      status: ((t.result_url || t.has_image) ? 'success' : 'failed') as 'success' | 'failed',
      errorMsg: t.error_message,
      favorited: false,
    }))

  return tasks.every(t => t.status === 'completed' || t.status === 'failed')
}

function clearProTrackingTimer() {
  if (proTrackingTimer) {
    clearTimeout(proTrackingTimer)
    proTrackingTimer = null
  }
}

/** 结束本次生图进度跟踪（幂等） */
function finishProGeneration() {
  if (proFinished) return
  proFinished = true
  clearProTrackingTimer()
  proSse.stop()
  workspaceStore.setProGenerating(false)
}

/** 生图进度订阅：订阅 task-events:{pro_batch_id} 批次聚合事件（SSE 失败自动降级轮询） */
const proSse = useTaskSse({
  taskId: proSseTaskId,
  pollFn: pollProBatchStatus,
  onCompleted: async (result) => {
    const tasks = (result as { tasks?: ProRemoteTask[] } | null)?.tasks || []
    await applyProBatchTasks(tasks)
    finishProGeneration()
  },
  onFailed: (err) => {
    console.warn('[专业模式] 批次失败事件:', err)
    // 批次聚合不发布 failed 终态；兜底把未完成任务标记为失败
    for (const t of proTasks.value) {
      if (!t.result_url && !t.error_message) {
        t.status = 'failed'
        t.error_message = err || '生成失败'
      }
    }
    finishProGeneration()
  },
})

// 每次状态刷新（SSE progress / 降级轮询响应）→ 更新生图进度 UI
watch(() => proSse.result, async (result) => {
  if (proFinished) return
  const tasks = (result as { tasks?: ProRemoteTask[] } | null)?.tasks
  if (!tasks || tasks.length === 0) return
  const allDone = await applyProBatchTasks(tasks)
  if (allDone) finishProGeneration()
})

/** 开始跟踪生图进度：订阅批次 SSE，重试/重新触发生成时重建订阅 */
function startProPolling() {
  if (!proBatchId.value) return
  stopProPolling()
  proFinished = false
  proSseTaskId.value = proBatchId.value
  proSse.start()

  // 兜底超时：SSE 与轮询都拿不到终态时强制结束（与原轮询 15 分钟上限行为一致）
  proTrackingTimer = setTimeout(() => {
    if (proFinished) return
    for (const t of proTasks.value) {
      if (!t.result_url && !t.error_message) {
        t.status = 'failed'
        t.error_message = '生成超时,请重试'
      }
    }
    finishProGeneration()
  }, MAX_PRO_TRACKING_DURATION)
}

function stopProPolling() {
  proFinished = true
  clearProTrackingTimer()
  proSse.stop()
  fetchedProImageTaskIds.clear()
}

onBeforeUnmount(() => {
  stopProPolling()
})

// ==================== 重置整个专业模式 ====================
function resetProMode() {
  stopProPolling()
  proPhase.value = 'config'
  proBatchId.value = null
  proTasks.value = []
  analyzeError.value = ''
  confirmError.value = ''
  dialogError.value = ''
  autoFillError.value = ''
  dialogTaskId.value = null
  dialogInput.value = ''
  isAutoFilling.value = false
  regeneratingTaskIds.value = new Set()
  previewOpen.value = false
  previewResult.value = null
  previewError.value = ''
  previewTaskId.value = ''
  workspaceStore.setProGenerating(false)
  workspaceStore.setProBatchId(null)
  workspaceStore.generatedImages = []
}

// ==================== UI 辅助:状态徽章 ====================
function statusBadgeClass(status: SchemeStatus): string {
  switch (status) {
    case 'pending': return 'bg-slate-100 text-slate-500'
    case 'analyzing': return 'bg-blue-100 text-blue-600'
    case 'optimizing': return 'bg-purple-100 text-purple-600'
    case 'confirmed': return 'bg-emerald-100 text-emerald-600'
    case 'locked': return 'bg-amber-100 text-amber-600'
    case 'failed': return 'bg-red-100 text-red-600'
    default: return 'bg-slate-100 text-slate-500'
  }
}

function statusLabel(status: SchemeStatus): string {
  switch (status) {
    case 'pending': return '待处理'
    case 'analyzing': return '分析中'
    case 'optimizing': return '优化中'
    case 'confirmed': return '已确认'
    case 'locked': return '生图中'
    case 'failed': return '失败'
    default: return '未知'
  }
}

// 生图完成数 / 失败数
const finishedCount = computed(
  () => proTasks.value.filter((t) => t.result_url || t.error_message).length,
)
const successCount = computed(
  () => proTasks.value.filter((t) => t.result_url).length,
)
</script>

<template>
  <div class="space-y-5">
    <!-- ==================== 第一块区域:基础设置 ==================== -->
    <div v-if="proPhase === 'config'">
      <h4 class="text-xs font-semibold text-slate-800 mb-3">生成设置</h4>

      <div class="grid grid-cols-2 gap-2 mb-2">
        <!-- 平台 -->
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            selectedPlatform === '其他'
              ? 'border-brand-purple ring-2 ring-brand-purple/20 bg-white'
              : platformOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <template v-if="selectedPlatform !== '其他'">
            <button ref="platformTrigger" @click="openDropdown('platform')"
              class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
              <span>{{ selectedPlatform }}</span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', platformOpen && 'rotate-180']" />
            </button>
          </template>
          <div v-else class="flex items-center gap-1 pr-1">
            <button @click="selectedPlatform = 'Amazon'; customPlatform = ''; platformOpen = false"
              class="p-1 rounded-md hover:bg-slate-100 text-slate-400 transition-colors flex-shrink-0" title="返回选择">
              <ArrowLeft class="w-3.5 h-3.5" />
            </button>
            <input v-model="customPlatform" placeholder="输入平台名称..."
              class="flex-1 min-w-0 py-2 pl-1 pr-2 text-sm text-brand-purple placeholder:text-slate-300 bg-transparent focus:outline-none" />
            <span class="text-[10px] font-medium text-brand-purple/60 flex-shrink-0">自定义</span>
          </div>
        </div>

        <!-- 地区 -->
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            selectedRegion === '其他'
              ? 'border-brand-purple ring-2 ring-brand-purple/20 bg-white'
              : regionOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <template v-if="selectedRegion !== '其他'">
            <button ref="regionTrigger" @click="openDropdown('region')"
              class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
              <span>{{ selectedRegion }}</span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', regionOpen && 'rotate-180']" />
            </button>
          </template>
          <div v-else class="flex items-center gap-1 pr-1">
            <button @click="selectedRegion = '美国'; customRegion = ''; regionOpen = false"
              class="p-1 rounded-md hover:bg-slate-100 text-slate-400 transition-colors flex-shrink-0" title="返回选择">
              <ArrowLeft class="w-3.5 h-3.5" />
            </button>
            <input v-model="customRegion" placeholder="输入目标地区..."
              class="flex-1 min-w-0 py-2 pl-1 pr-2 text-sm text-brand-purple placeholder:text-slate-300 bg-transparent focus:outline-none" />
            <span class="text-[10px] font-medium text-brand-purple/60 flex-shrink-0">自定义</span>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-2 mb-3">
        <!-- 语言 -->
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            selectedLanguage === '其他'
              ? 'border-brand-purple ring-2 ring-brand-purple/20 bg-white'
              : languageOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <template v-if="selectedLanguage !== '其他'">
            <button ref="languageTrigger" @click="openDropdown('language')"
              class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
              <span>{{ selectedLanguage }}</span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', languageOpen && 'rotate-180']" />
            </button>
          </template>
          <div v-else class="flex items-center gap-1 pr-1">
            <button @click="selectedLanguage = '英语'; customLanguage = ''; languageOpen = false"
              class="p-1 rounded-md hover:bg-slate-100 text-slate-400 transition-colors flex-shrink-0" title="返回选择">
              <ArrowLeft class="w-3.5 h-3.5" />
            </button>
            <input v-model="customLanguage" placeholder="输入语言..."
              class="flex-1 min-w-0 py-2 pl-1 pr-2 text-sm text-brand-purple placeholder:text-slate-300 bg-transparent focus:outline-none" />
            <span class="text-[10px] font-medium text-brand-purple/60 flex-shrink-0">自定义</span>
          </div>
        </div>

        <!-- 比例 -->
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            ratioOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <button ref="ratioTrigger" @click="openDropdown('ratio')"
            class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
            <span>{{ selectedRatio === 'custom' ? (customRatioInput || '自定义') : selectedRatio }}</span>
            <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', ratioOpen && 'rotate-180']" />
          </button>
        </div>
      </div>

      <!-- 提示词语言 -->
      <label class="text-xs font-medium text-slate-500 mb-1.5 block">提示词语言</label>
      <div class="grid grid-cols-2 gap-2 mb-3">
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            promptLangOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <button ref="promptLangTrigger" @click="openDropdown('promptLang')"
            class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
            <span>{{ selectedPromptLang === '中文' ? '中文' : 'English' }}</span>
            <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', promptLangOpen && 'rotate-180']" />
          </button>
        </div>
        <div />
      </div>

      <!-- Teleported dropdowns -->
      <Teleport to="body">
        <Transition name="dropdown">
          <div v-if="platformOpen"
            :style="{ position: 'fixed', top: platformPos.top + 'px', left: platformPos.left + 'px', width: platformPos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]" @click.stop>
            <div class="max-h-[10rem] overflow-y-auto">
              <button v-for="p in platforms" :key="p" @mousedown="selectedPlatform = p; platformOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedPlatform === p && 'bg-brand-gradient-subtle text-brand-purple font-medium']">{{ p }}</button>
              <div class="border-t border-slate-100" />
              <button @mousedown="selectedPlatform = '其他'; platformOpen = false"
                class="w-full text-left px-3 py-1.5 text-sm text-brand-purple hover:bg-brand-gradient-subtle transition-colors flex items-center gap-1.5">✏️ 自定义...</button>
            </div>
          </div>
        </Transition>

        <Transition name="dropdown">
          <div v-if="regionOpen"
            :style="{ position: 'fixed', top: regionPos.top + 'px', left: regionPos.left + 'px', width: regionPos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]" @click.stop>
            <div class="max-h-[10rem] overflow-y-auto">
              <button v-for="r in regions" :key="r" @mousedown="selectedRegion = r; regionOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedRegion === r && 'bg-brand-gradient-subtle text-brand-purple font-medium']">{{ r }}</button>
              <div class="border-t border-slate-100" />
              <button @mousedown="selectedRegion = '其他'; regionOpen = false"
                class="w-full text-left px-3 py-1.5 text-sm text-brand-purple hover:bg-brand-gradient-subtle transition-colors flex items-center gap-1.5">✏️ 自定义...</button>
            </div>
          </div>
        </Transition>

        <Transition name="dropdown">
          <div v-if="languageOpen"
            :style="{ position: 'fixed', top: languagePos.top + 'px', left: languagePos.left + 'px', width: languagePos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]" @click.stop>
            <div class="max-h-[10rem] overflow-y-auto">
              <button v-for="l in languages" :key="l" @mousedown="selectedLanguage = l; languageOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedLanguage === l && 'bg-brand-gradient-subtle text-brand-purple font-medium']">{{ l }}</button>
              <div class="border-t border-slate-100" />
              <button @mousedown="selectedLanguage = '其他'; languageOpen = false"
                class="w-full text-left px-3 py-1.5 text-sm text-brand-purple hover:bg-brand-gradient-subtle transition-colors flex items-center gap-1.5">✏️ 自定义...</button>
            </div>
          </div>
        </Transition>

        <Transition name="dropdown">
          <div v-if="ratioOpen"
            :style="{ position: 'fixed', top: ratioPos.top + 'px', left: ratioPos.left + 'px', width: ratioPos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]" @click.stop>
            <div class="max-h-[10rem] overflow-y-auto">
              <button v-for="r in ratios" :key="r" @mousedown="selectedRatio = r; ratioOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedRatio === r && 'bg-brand-gradient-subtle text-brand-purple font-medium']">{{ r }}</button>
              <div class="border-t border-slate-100" />
              <button @mousedown="selectedRatio = 'custom'; ratioOpen = false"
                class="w-full text-left px-3 py-1.5 text-sm text-brand-purple hover:bg-brand-gradient-subtle transition-colors flex items-center gap-1.5">✏️ 自定义...</button>
            </div>
          </div>
        </Transition>

        <Transition name="dropdown">
          <div v-if="promptLangOpen"
            :style="{ position: 'fixed', top: promptLangPos.top + 'px', left: promptLangPos.left + 'px', width: promptLangPos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]" @click.stop>
            <div class="max-h-[10rem] overflow-y-auto">
              <button @mousedown="selectedPromptLang = '中文'; promptLangOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedPromptLang === '中文' && 'bg-brand-gradient-subtle text-brand-purple font-medium']">中文</button>
              <button @mousedown="selectedPromptLang = 'English'; promptLangOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedPromptLang === 'English' && 'bg-brand-gradient-subtle text-brand-purple font-medium']">English</button>
            </div>
          </div>
        </Transition>
      </Teleport>

      <!-- 点击空白关闭下拉 -->
      <div v-if="platformOpen || regionOpen || languageOpen || ratioOpen || promptLangOpen"
        class="fixed inset-0 z-[9998]" @click="closeAllDropdowns" />

      <!-- 自定义比例输入 -->
      <Transition name="fade">
        <div v-if="selectedRatio === 'custom'" class="mb-3 animate-fade-in">
          <label class="text-xs font-medium text-slate-700 mb-1.5 block">自定义比例</label>
          <input
            v-model="customRatioInput"
            type="text"
            placeholder="例如: 3:4 或 9:16"
            class="glass-input w-full px-3 py-2 text-sm"
          />
        </div>
      </Transition>

      <!-- 分辨率 -->
      <div class="mb-4">
        <label class="text-xs font-medium text-slate-700 mb-1.5 block">分辨率</label>
        <div class="grid grid-cols-4 gap-2">
          <button
            v-for="res in resolutions"
            :key="res.value"
            @click="selectedResolution = res.value"
            :class="[
              'py-2 rounded-xl text-xs font-medium transition-all duration-200 border',
              selectedResolution === res.value
                ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-glow'
                : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50',
            ]"
          >
            {{ res.label }}
          </button>
        </div>
        <Transition name="fade">
          <div v-if="selectedResolution === 'custom'" class="mt-2 animate-fade-in">
            <div class="flex items-center gap-1.5">
              <input
                v-model.number="customWidth"
                type="number"
                min="16"
                max="3840"
                step="16"
                placeholder="宽"
                class="glass-input flex-1 px-3 py-2.5 text-sm text-center [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              />
              <span class="text-slate-400 font-medium text-sm select-none">×</span>
              <input
                v-model.number="customHeight"
                type="number"
                min="16"
                max="3840"
                step="16"
                placeholder="高"
                class="glass-input flex-1 px-3 py-2.5 text-sm text-center [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              />
            </div>
            <p class="text-[10px] text-slate-400 mt-1">宽 × 高，需为 16 的倍数，最大不超过 3840</p>
          </div>
        </Transition>

        <!-- 有效尺寸提示 & 校验警告 -->
        <div class="mt-2 rounded-lg p-2.5 space-y-1.5" :class="sizeWarning ? 'bg-amber-50 border border-amber-200' : 'bg-slate-50 border border-slate-100'">
          <div class="flex items-center justify-between">
            <span class="text-[10px] text-slate-500">有效输出尺寸</span>
            <span class="text-xs font-semibold tabular-nums" :class="resolvedSize.corrected ? 'text-amber-600' : 'text-slate-800'">
              {{ resolvedSize.width }} × {{ resolvedSize.height }}
            </span>
          </div>
          <div class="flex items-center gap-2 text-[10px]" :class="sizeWarning ? 'text-amber-600' : 'text-slate-400'">
            <AlertCircle v-if="sizeWarning" class="w-3 h-3 flex-shrink-0" />
            <span>{{ sizeWarning || `${(Number(resolvedSize.width) * Number(resolvedSize.height) / 10000).toFixed(1)} 万像素 · 比例约束已应用` }}</span>
          </div>
        </div>
      </div>

      <!-- 要求 -->
      <div>
        <label class="text-xs font-medium text-slate-700 mb-1.5 block">整体要求(可选)</label>
        <textarea
          v-model="requirementText"
          rows="3"
          placeholder="描述整体生成要求,如:整体风格统一为简约北欧风,色调偏暖,突出产品质感..."
          class="glass-input w-full px-3 py-2.5 text-sm resize-none leading-relaxed"
        />
      </div>
    </div>

    <!-- ==================== 批次级商品图(仅配置阶段) ==================== -->
    <div v-if="proPhase === 'config'">
      <div class="flex items-center justify-between mb-3">
        <h4 class="text-xs font-semibold text-slate-800">商品图<span class="text-red-500 ml-0.5">*</span></h4>
        <span class="text-[10px] text-slate-400">{{ batchProductImages.length }} / 10</span>
      </div>

      <div v-if="batchProductImages.length === 0" class="border-2 border-dashed border-slate-200 rounded-xl p-4 text-center hover:border-brand-purple/40 transition-colors">
        <input type="file" accept="image/jpeg,image/png,image/webp" multiple class="hidden" id="batch-product-upload" @change="handleBatchProductUpload" />
        <label for="batch-product-upload" class="cursor-pointer block">
          <Upload class="w-5 h-5 text-slate-400 mx-auto mb-1.5" />
          <p class="text-xs text-slate-500">上传商品图</p>
          <p class="text-[10px] text-slate-400 mt-0.5">支持多张, jpg / png / webp, 整个批次共享</p>
        </label>
      </div>
      <div v-else>
        <div class="grid grid-cols-3 gap-2 mb-2">
          <div
            v-for="(img, idx) in batchProductImages"
            :key="img.id"
            class="relative aspect-square rounded-xl overflow-hidden border border-slate-200 group bg-slate-50"
          >
            <img :src="img.url" class="w-full h-full object-cover" />
            <span class="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-slate-900/70 text-[10px] text-white font-medium">
              {{ idx + 1 }}
            </span>
            <button
              @click="removeBatchProductImage(img.id)"
              class="absolute top-1 right-1 w-5 h-5 rounded-full bg-red-500/90 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-red-600 transition-all shadow-sm"
            >
              <X class="w-3 h-3" />
            </button>
          </div>
        </div>
        <input type="file" accept="image/jpeg,image/png,image/webp" multiple class="hidden" id="batch-product-upload-more" @change="handleBatchProductUpload" />
        <label for="batch-product-upload-more" class="flex items-center justify-center gap-1 py-2 rounded-xl border border-dashed border-slate-200 text-xs text-slate-500 cursor-pointer hover:border-brand-purple/40 hover:text-brand-purple transition-colors">
          <Plus class="w-3.5 h-3.5" />
          继续添加
        </label>
      </div>

      <!-- 批次级参考图 -->
      <div class="mt-4">
        <h4 class="text-xs font-semibold text-slate-800 mb-2">参考图(可选)</h4>
        <template v-if="!batchReferenceImage">
          <div class="border-2 border-dashed border-slate-200 rounded-xl p-4 text-center hover:border-brand-cyan/40 transition-colors">
            <input type="file" accept="image/jpeg,image/png,image/webp" class="hidden" id="batch-ref-upload" @change="handleBatchRefUpload" />
            <label for="batch-ref-upload" class="cursor-pointer block">
              <Upload class="w-5 h-5 text-slate-400 mx-auto mb-1.5" />
              <p class="text-xs text-slate-500">上传参考图</p>
              <p class="text-[10px] text-slate-400 mt-0.5">仅支持单张,整个批次共享</p>
            </label>
          </div>
        </template>
        <div v-else class="relative aspect-square w-full max-w-[160px] mx-auto rounded-xl overflow-hidden border border-slate-200 group bg-slate-50">
          <img :src="batchReferenceImage.url" class="w-full h-full object-cover" />
          <button @click="removeBatchReferenceImage"
            class="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-red-500/90 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-red-600 transition-all shadow-sm">
            <X class="w-3.5 h-3.5" />
          </button>
          <div class="absolute bottom-0 left-0 right-0 px-2 py-1 bg-gradient-to-t from-black/60 to-transparent">
            <p class="text-[10px] text-white font-medium">参考图</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 第二块区域:任务卡片(配置阶段) ==================== -->
    <div v-if="proPhase === 'config'">
      <div class="flex items-center justify-between mb-3">
        <h4 class="text-xs font-semibold text-slate-800">生图任务</h4>
        <button
          @click="addTaskCard"
          class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium text-brand-purple bg-brand-gradient-subtle border border-brand-purple/20 hover:border-brand-purple/40 transition-all duration-200"
        >
          <Plus class="w-3.5 h-3.5" />
          添加任务
        </button>
      </div>

      <div v-if="taskCards.length === 0" class="rounded-xl border-2 border-dashed border-slate-200 p-6 text-center">
        <div class="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center mx-auto mb-2">
          <Plus class="w-5 h-5 text-slate-400" />
        </div>
        <p class="text-xs text-slate-500">点击上方「添加任务」创建生图任务</p>
        <p class="text-[10px] text-slate-400 mt-1">每个任务可独立配置图片类型、需求与比例</p>
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="(task, idx) in taskCards"
          :key="task.id"
          class="group relative flex items-center gap-3 p-3 rounded-xl border border-slate-200 bg-white hover:border-brand-purple/30 hover:shadow-sm transition-all duration-200"
        >
          <span class="w-6 h-6 flex-shrink-0 rounded-lg bg-brand-gradient-subtle text-brand-purple text-[11px] font-bold flex items-center justify-center">
            {{ idx + 1 }}
          </span>

          <div class="flex-1 min-w-0">
            <p class="text-xs font-medium text-slate-800 truncate">{{ task.name }}</p>
            <div class="flex items-center gap-2 mt-1">
              <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-600">
                {{ imageTypeLabel(task.imageType) }}
              </span>
              <span class="text-slate-300">|</span>
              <span class="text-[10px] text-slate-500">{{ task.aspectRatio }}</span>
              <template v-if="task.requirement">
                <span class="text-slate-300">|</span>
                <span class="text-[10px] text-slate-400 truncate max-w-[120px]">{{ task.requirement }}</span>
              </template>
            </div>
          </div>

          <button
            @click="openConfigDialog(task.id)"
            class="flex-shrink-0 px-2 py-1 rounded-lg text-[11px] text-slate-500 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
            title="配置任务"
          >
            配置
          </button>

          <button
            @click="removeTaskCard(task.id)"
            class="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-slate-400 opacity-0 group-hover:opacity-100 hover:text-red-500 hover:bg-red-50 transition-all"
            title="删除任务"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>

        <p class="text-[10px] text-slate-400 pl-1">
          共计 {{ taskCards.length }} 个生图任务
        </p>
      </div>
    </div>

    <!-- ==================== 第三块区域:AI 分析整合按钮(配置阶段) ==================== -->
    <div v-if="proPhase === 'config'">
      <div v-if="analyzeError" class="mb-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-600 flex items-start gap-2">
        <AlertCircle class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <span>{{ analyzeError }}</span>
      </div>
      <button
        @click="handleAnalyzeIntegrate"
        :disabled="isAnalyzing"
        class="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border-2 transition-all duration-200 text-xs font-medium"
        :class="
          isAnalyzing
            ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple cursor-wait'
            : 'border-brand-purple border-dashed text-brand-purple bg-brand-gradient-subtle hover:shadow-glow'
        "
      >
        <Loader2 v-if="isAnalyzing" class="w-4 h-4 animate-spin" />
        <Sparkles v-else class="w-4 h-4" />
        {{ isAnalyzing ? 'AI 分析整合中...' : 'AI 分析整合' }}
      </button>
      <p class="text-[10px] text-slate-400 mt-1.5 text-center">
        AI 将基于商品图与任务列表,为每个任务生成结构化提示词方案
      </p>
    </div>

    <!-- ==================== 阶段二:方案优化 ==================== -->
    <div v-if="proPhase === 'optimize'">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <button @click="resetProMode"
            class="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <ArrowLeft class="w-3.5 h-3.5" />
            返回
          </button>
          <h4 class="text-xs font-semibold text-slate-800">方案优化</h4>
        </div>
        <span class="text-[10px] text-slate-400">批次 {{ proBatchId?.slice(0, 8) }}...</span>
      </div>

      <div v-if="confirmError" class="mb-3 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-600 flex items-start gap-2">
        <AlertCircle class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <span>{{ confirmError }}</span>
      </div>

      <!-- 空方案提示区域 -->
      <div v-if="hasEmptyScheme" class="mb-3 rounded-xl bg-amber-50 border border-amber-200 p-3">
        <div class="flex items-start gap-2 mb-2">
          <AlertCircle class="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
          <div class="flex-1">
            <p class="text-xs font-medium text-amber-700">部分任务方案为空</p>
            <p class="text-[11px] text-amber-600 mt-0.5">
              AI 在首次分析时未能为部分任务生成完整方案，可点击下方按钮自动补全
            </p>
          </div>
        </div>
        <button
          @click="handleAutoFillSchemes"
          :disabled="isAutoFilling"
          class="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium transition-all duration-200"
          :class="
            isAutoFilling
              ? 'bg-amber-100 text-amber-500 cursor-wait'
              : 'bg-amber-100 text-amber-700 hover:bg-amber-200'
          "
        >
          <Loader2 v-if="isAutoFilling" class="w-3.5 h-3.5 animate-spin" />
          <Sparkles v-else class="w-3.5 h-3.5" />
          {{ isAutoFilling ? 'AI 正在补全方案...' : '一键AI补全空方案' }}
        </button>
        <p v-if="autoFillError" class="text-[11px] text-red-500 mt-1.5">{{ autoFillError }}</p>
      </div>

      <div class="space-y-3 mb-4">
        <div
          v-for="task in proTasks"
          :key="task.task_id"
          class="rounded-xl border border-slate-200 bg-white p-3 transition-all duration-200 hover:shadow-sm"
        >
          <!-- 任务头部 -->
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2 min-w-0">
              <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-600 flex-shrink-0">
                {{ imageTypeLabel(task.image_type) }}
              </span>
              <p class="text-xs font-medium text-slate-800 truncate">{{ task.scheme?.image_name || task.task_name }}</p>
            </div>
            <span :class="['inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0', statusBadgeClass(task.status)]">
              {{ statusLabel(task.status) }}
            </span>
          </div>

          <!-- 方案概览 -->
          <div class="space-y-1.5 text-[11px] text-slate-600">
            <div v-if="task.scheme?.image_role" class="flex items-start gap-1.5">
              <span class="text-slate-400 flex-shrink-0">定位:</span>
              <span class="flex-1">{{ task.scheme?.image_role }}</span>
            </div>
            <div v-if="task.scheme?.layout_prompt?.product_state" class="flex items-start gap-1.5">
              <span class="text-slate-400 flex-shrink-0">呈现:</span>
              <span class="flex-1">{{ task.scheme.layout_prompt.product_state }}</span>
            </div>
            <div v-if="task.scheme?.layout_prompt?.composition" class="flex items-start gap-1.5">
              <span class="text-slate-400 flex-shrink-0">构图:</span>
              <span class="flex-1">{{ task.scheme.layout_prompt.composition }}</span>
            </div>
            <div v-if="task.scheme?.layout_prompt?.background" class="flex items-start gap-1.5">
              <span class="text-slate-400 flex-shrink-0">背景:</span>
              <span class="flex-1">{{ task.scheme.layout_prompt.background }}</span>
            </div>
            <div v-if="task.scheme?.copy?.main_title" class="flex items-start gap-1.5">
              <span class="text-slate-400 flex-shrink-0">主标题:</span>
              <span class="flex-1 text-brand-purple font-medium">{{ task.scheme.copy.main_title }}</span>
            </div>
            <div v-if="task.scheme?.copy?.sub_title" class="flex items-start gap-1.5">
              <span class="text-slate-400 flex-shrink-0">副标题:</span>
              <span class="flex-1">{{ task.scheme.copy.sub_title }}</span>
            </div>
            <div v-if="task.scheme?.copy?.tags && task.scheme.copy.tags.length" class="flex items-start gap-1.5">
              <span class="text-slate-400 flex-shrink-0">标签:</span>
              <div class="flex-1 flex flex-wrap gap-1">
                <span v-for="tag in task.scheme.copy.tags" :key="tag"
                  class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-600">{{ tag }}</span>
              </div>
            </div>
          </div>

          <!-- 对话历史简览 -->
          <div v-if="task.dialog_history && task.dialog_history.length > 0" class="mt-2 pt-2 border-t border-slate-100">
            <p class="text-[10px] text-slate-400 mb-1">已进行 {{ task.dialog_history.filter(d => d.role === 'user').length }} 轮对话优化</p>
          </div>

          <!-- 操作按钮 -->
          <div class="mt-2 flex items-center gap-2">
            <button
              v-if="isSchemeEmpty(task.scheme) || task.status === 'failed'"
              @click="handleRegenerateScheme(task.task_id)"
              :disabled="regeneratingTaskIds.has(task.task_id)"
              class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all"
              :class="
                regeneratingTaskIds.has(task.task_id)
                  ? 'text-amber-500 bg-amber-50 cursor-wait'
                  : 'text-amber-700 bg-amber-50 hover:bg-amber-100'
              "
            >
              <Loader2 v-if="regeneratingTaskIds.has(task.task_id)" class="w-3 h-3 animate-spin" />
              <Sparkles v-else class="w-3 h-3" />
              {{ regeneratingTaskIds.has(task.task_id) ? '生成中...' : '重新生成方案' }}
            </button>
            <button
              @click="openDialog(task.task_id)"
              class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium text-brand-purple bg-brand-gradient-subtle hover:shadow-glow transition-all"
            >
              <MessageSquare class="w-3 h-3" />
              {{ task.dialog_history && task.dialog_history.length > 0 ? '继续优化' : '对话优化' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 提示词预览入口（方案确认区） -->
      <button
        @click="openPreviewPanel"
        :disabled="proTasks.length === 0 || previewLoading"
        class="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-medium border transition-all duration-200 mb-2 disabled:opacity-40 disabled:cursor-not-allowed"
        :class="
          previewLoading
            ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple cursor-wait'
            : 'border-slate-200 bg-white text-slate-600 hover:border-brand-purple/40 hover:text-brand-purple'
        "
      >
        <Loader2 v-if="previewLoading" class="w-3.5 h-3.5 animate-spin" />
        <Eye v-else class="w-3.5 h-3.5" />
        {{ previewLoading ? '提示词生成中...' : '预览提示词' }}
      </button>

      <!-- 确认方案并生图按钮 -->
      <button
        @click="handleConfirmGenerate"
        :disabled="!canConfirm || isConfirming"
        class="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-medium transition-all duration-200"
        :class="
          canConfirm && !isConfirming
            ? 'text-white bg-brand-gradient hover:shadow-glow'
            : 'text-slate-400 bg-slate-100 cursor-not-allowed'
        "
      >
        <Loader2 v-if="isConfirming" class="w-4 h-4 animate-spin" />
        <Lock v-else class="w-3.5 h-3.5" />
        {{ isConfirming ? '正在触发...' : '确认方案并生图' }}
      </button>
      <p v-if="!canConfirm" class="text-[10px] text-amber-500 mt-1.5 text-center">
        存在方案为空的任务，请点击上方「一键AI补全空方案」自动生成
      </p>
    </div>

    <!-- ==================== 阶段三:生图进度 ==================== -->
    <div v-if="proPhase === 'generate'">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <button @click="resetProMode"
            class="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <RotateCcw class="w-3.5 h-3.5" />
            重新开始
          </button>
          <h4 class="text-xs font-semibold text-slate-800">生图进度</h4>
        </div>
        <span class="text-[10px] text-slate-400">
          {{ successCount }}/{{ proTasks.length }} 成功
          <span v-if="finishedCount < proTasks.length" class="text-brand-purple">· 生成中...</span>
        </span>
      </div>

      <div class="space-y-2">
        <div
          v-for="task in proTasks"
          :key="task.task_id"
          class="rounded-xl border border-slate-200 bg-white p-3"
        >
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2 min-w-0">
              <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-600 flex-shrink-0">
                {{ imageTypeLabel(task.image_type) }}
              </span>
              <p class="text-xs font-medium text-slate-800 truncate">{{ task.scheme?.image_name || task.task_name }}</p>
            </div>
            <span :class="['inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0', statusBadgeClass(task.status)]">
              <Loader2 v-if="task.status === 'locked' && !task.result_url && !task.error_message" class="w-2.5 h-2.5 animate-spin" />
              <Check v-else-if="task.result_url" class="w-2.5 h-2.5" />
              <X v-else-if="task.error_message" class="w-2.5 h-2.5" />
              {{ task.result_url ? '完成' : task.error_message ? '失败' : statusLabel(task.status) }}
            </span>
          </div>

          <!-- 结果图 -->
          <div v-if="task.result_url" class="rounded-lg overflow-hidden border border-slate-100 bg-slate-50">
            <img :src="task.result_url" class="w-full h-auto max-h-[400px] object-contain" />
          </div>

          <!-- 错误信息 -->
          <div v-else-if="task.error_message" class="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-[11px] text-red-600 flex items-start gap-1.5">
            <AlertCircle class="w-3 h-3 flex-shrink-0 mt-0.5" />
            <span>{{ task.error_message }}</span>
          </div>

          <!-- 加载占位 -->
          <div v-else class="rounded-lg bg-slate-50 border border-slate-100 px-3 py-6 flex items-center justify-center gap-2 text-[11px] text-slate-400">
            <Loader2 class="w-3 h-3 animate-spin" />
            <span>正在生成图片,请耐心等待...</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 任务配置弹窗 ========== -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="configDialogTask" class="fixed inset-0 z-[10000] flex items-center justify-center" @click.self="closeConfigDialog">
          <div class="fixed inset-0 bg-black/40 backdrop-blur-sm" />
          <div class="relative bg-white rounded-2xl shadow-2xl w-[480px] max-h-[85vh] overflow-y-auto z-10 animate-in">
            <div class="sticky top-0 bg-white border-b border-slate-100 px-5 py-4 flex items-center justify-between rounded-t-2xl">
              <h3 class="text-sm font-semibold text-slate-900">任务配置 — {{ configDialogTask.name }}</h3>
              <button @click="closeConfigDialog" class="w-7 h-7 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors">
                <X class="w-4 h-4" />
              </button>
            </div>

            <div class="p-5 space-y-5">
              <!-- 任务名称 -->
              <div>
                <label class="text-xs font-medium text-slate-700 mb-2 block">任务名称</label>
                <input v-model="configDialogTask.name"
                  class="glass-input w-full px-3 py-2 text-sm" placeholder="例如:主图-正面" />
              </div>

              <!-- 图片类型 -->
              <div>
                <label class="text-xs font-medium text-slate-700 mb-2 block">图片类型</label>
                <div class="grid grid-cols-3 gap-1.5">
                  <button
                    v-for="opt in imageTypeOptions"
                    :key="opt.value"
                    @click="configDialogTask!.imageType = opt.value"
                    :class="[
                      'py-2 px-2 rounded-xl text-[11px] font-medium transition-all duration-200 border text-center',
                      configDialogTask.imageType === opt.value
                        ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-glow'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
                    ]"
                    :title="opt.desc"
                  >
                    {{ opt.label }}
                  </button>
                </div>
                <p class="text-[10px] text-slate-400 mt-1.5">
                  {{ imageTypeOptions.find(o => o.value === configDialogTask?.imageType)?.desc }}
                </p>
              </div>

              <!-- 任务需求 -->
              <div>
                <label class="text-xs font-medium text-slate-700 mb-2 block">任务需求(可选)</label>
                <textarea
                  v-model="configDialogTask.requirement"
                  rows="3"
                  placeholder="描述该任务的特殊要求,如:重点突出商品顶部 logo,背景留白用于后期添加文字..."
                  class="glass-input w-full px-3 py-2 text-sm resize-none leading-relaxed"
                />
              </div>

              <!-- 图片比例 -->
              <div>
                <label class="text-xs font-medium text-slate-700 mb-2 block">图片比例</label>
                <div class="grid grid-cols-5 gap-1.5">
                  <button
                    v-for="opt in ratioOptions"
                    :key="opt.value"
                    @click="configDialogTask!.aspectRatio = opt.value"
                    :class="[
                      'py-2 rounded-xl text-[11px] font-medium transition-all duration-200 border',
                      configDialogTask.aspectRatio === opt.value
                        ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-glow'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
                    ]"
                  >
                    {{ opt.label }}
                  </button>
                </div>
              </div>
            </div>

            <div class="sticky bottom-0 bg-slate-50 border-t border-slate-100 px-5 py-4 flex justify-end gap-2 rounded-b-2xl">
              <button @click="closeConfigDialog" class="px-4 py-2 rounded-xl text-xs font-medium text-slate-600 border border-slate-200 hover:bg-slate-100 transition-colors">
                取消
              </button>
              <button @click="closeConfigDialog" class="px-4 py-2 rounded-xl text-xs font-medium text-white bg-brand-gradient hover:shadow-glow transition-all">
                确认保存
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ========== 对话优化面板(右侧抽屉) ========== -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="dialogTask" class="fixed inset-0 z-[10000]">
          <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="closeDialog" />
          <div class="absolute right-0 top-0 bottom-0 w-[440px] max-w-[90vw] bg-white shadow-2xl flex flex-col">
            <!-- 抽屉头部 -->
            <div class="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
              <div class="flex items-center gap-2 min-w-0">
                <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-600 flex-shrink-0">
                  {{ imageTypeLabel(dialogTask.image_type) }}
                </span>
                <h3 class="text-sm font-semibold text-slate-900 truncate">对话优化</h3>
              </div>
              <button @click="closeDialog" class="w-7 h-7 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors flex-shrink-0">
                <X class="w-4 h-4" />
              </button>
            </div>

            <!-- 当前方案预览 -->
            <div class="px-4 py-3 bg-slate-50 border-b border-slate-100">
              <p class="text-[10px] text-slate-400 mb-1">当前方案</p>
              <div class="space-y-1 text-[11px] text-slate-600">
                <p v-if="dialogTask.scheme?.image_name"><span class="text-slate-400">名称:</span>{{ dialogTask.scheme?.image_name }}</p>
                <p v-if="dialogTask.scheme?.layout_prompt.product_state"><span class="text-slate-400">呈现:</span>{{ dialogTask.scheme?.layout_prompt.product_state }}</p>
                <p v-if="dialogTask.scheme?.layout_prompt.composition"><span class="text-slate-400">构图:</span>{{ dialogTask.scheme?.layout_prompt.composition }}</p>
                <p v-if="dialogTask.scheme?.layout_prompt.background"><span class="text-slate-400">背景:</span>{{ dialogTask.scheme?.layout_prompt.background }}</p>
                <p v-if="dialogTask.scheme?.copy.main_title"><span class="text-slate-400">主标题:</span><span class="text-brand-purple font-medium">{{ dialogTask.scheme?.copy.main_title }}</span></p>
              </div>
            </div>

            <!-- 对话历史 -->
            <div ref="dialogPanelRef" class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              <div v-if="!dialogTask.dialog_history || dialogTask.dialog_history.length === 0" class="text-center py-8">
                <MessageSquare class="w-8 h-8 text-slate-300 mx-auto mb-2" />
                <p class="text-xs text-slate-500">开始与 AI 对话,优化提示词方案</p>
                <p class="text-[10px] text-slate-400 mt-1">例如:"让背景更简洁"、"主标题改为促销文案"</p>
              </div>

              <div
                v-for="(msg, idx) in dialogTask.dialog_history"
                :key="idx"
                :class="['flex', msg.role === 'user' ? 'justify-end' : 'justify-start']"
              >
                <div
                  :class="[
                    'max-w-[80%] px-3 py-2 rounded-xl text-xs leading-relaxed',
                    msg.role === 'user'
                      ? 'bg-brand-gradient text-white rounded-br-sm'
                      : 'bg-slate-100 text-slate-700 rounded-bl-sm',
                  ]"
                >
                  {{ msg.content }}
                </div>
              </div>
            </div>

            <!-- 错误提示 -->
            <div v-if="dialogError" class="mx-4 mb-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-[11px] text-red-600 flex items-start gap-1.5">
              <AlertCircle class="w-3 h-3 flex-shrink-0 mt-0.5" />
              <span>{{ dialogError }}</span>
            </div>

            <!-- 输入区 -->
            <div class="px-4 py-3 border-t border-slate-100">
              <div class="flex items-end gap-2">
                <textarea
                  v-model="dialogInput"
                  @keydown="handleDialogKeydown"
                  :disabled="isOptimizing"
                  rows="2"
                  placeholder="输入优化指令,Enter 发送,Shift+Enter 换行..."
                  class="glass-input flex-1 px-3 py-2 text-xs resize-none leading-relaxed disabled:bg-slate-50"
                />
                <button
                  @click="sendDialogOptimize"
                  :disabled="!dialogInput.trim() || isOptimizing"
                  class="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  :class="!isOptimizing && dialogInput.trim() ? 'bg-brand-gradient text-white hover:shadow-glow' : 'bg-slate-100 text-slate-400'"
                >
                  <Loader2 v-if="isOptimizing" class="w-4 h-4 animate-spin" />
                  <Sparkles v-else class="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
    <!-- ========== 提示词预览弹窗 ========== -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="previewOpen" class="fixed inset-0 z-[10000] flex items-center justify-center" @click.self="closePreviewPanel">
          <div class="fixed inset-0 bg-black/40 backdrop-blur-sm" />
          <div class="relative bg-white rounded-2xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col z-10 animate-in">
            <!-- 头部 -->
            <div class="sticky top-0 bg-white border-b border-slate-100 px-5 py-4 flex items-center justify-between rounded-t-2xl flex-shrink-0">
              <h3 class="text-sm font-semibold text-slate-900 flex items-center gap-1.5">
                <Eye class="w-4 h-4 text-brand-purple" />
                提示词预览
              </h3>
              <button @click="closePreviewPanel" class="w-7 h-7 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors">
                <X class="w-4 h-4" />
              </button>
            </div>

            <!-- 内容 -->
            <div class="flex-1 overflow-y-auto p-5 space-y-4">
              <!-- 多任务时切换预览对象 -->
              <div v-if="proTasks.length > 1" class="flex flex-wrap gap-1.5">
                <button
                  v-for="t in proTasks"
                  :key="t.task_id"
                  @click="selectPreviewTask(t.task_id)"
                  :class="[
                    'px-2 py-1 rounded-lg text-[11px] font-medium border transition-all max-w-full truncate',
                    previewTaskId === t.task_id
                      ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple'
                      : 'border-slate-200 text-slate-500 hover:border-slate-300',
                  ]"
                >
                  {{ imageTypeLabel(t.image_type) }} · {{ t.scheme?.image_name || t.task_name }}
                </button>
              </div>

              <!-- 加载中 -->
              <div v-if="previewLoading" class="py-10 flex items-center justify-center gap-2 text-xs text-slate-400">
                <Loader2 class="w-4 h-4 animate-spin" />
                正在生成英文提示词...
              </div>

              <!-- 预览失败 -->
              <div v-else-if="previewError" class="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-600 flex items-start gap-2">
                <AlertCircle class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                <span>{{ previewError }}</span>
              </div>

              <template v-else-if="previewResult">
                <!-- 警告信息 -->
                <div v-if="previewResult.warnings && previewResult.warnings.length > 0"
                  class="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5 space-y-1">
                  <div class="flex items-center gap-1.5 text-[11px] font-medium text-amber-700">
                    <AlertCircle class="w-3.5 h-3.5 flex-shrink-0" />
                    提示
                  </div>
                  <ul class="space-y-0.5 pl-5 list-disc">
                    <li v-for="(w, idx) in previewResult.warnings" :key="idx" class="text-[11px] text-amber-600 leading-relaxed">{{ w }}</li>
                  </ul>
                </div>

                <!-- 三段英文提示词 -->
                <div class="space-y-3">
                  <div>
                    <p class="text-[11px] font-medium text-slate-500 mb-1">主提示词 (Main)</p>
                    <pre class="whitespace-pre-wrap break-words rounded-lg bg-slate-50 border border-slate-100 px-3 py-2.5 text-[11px] leading-relaxed text-slate-700 font-mono">{{ previewResult.prompts.main }}</pre>
                  </div>
                  <div>
                    <p class="text-[11px] font-medium text-slate-500 mb-1">场景提示词 (Scene)</p>
                    <pre class="whitespace-pre-wrap break-words rounded-lg bg-slate-50 border border-slate-100 px-3 py-2.5 text-[11px] leading-relaxed text-slate-700 font-mono">{{ previewResult.prompts.scene }}</pre>
                  </div>
                  <div>
                    <p class="text-[11px] font-medium text-slate-500 mb-1">细节提示词 (Detail)</p>
                    <pre class="whitespace-pre-wrap break-words rounded-lg bg-slate-50 border border-slate-100 px-3 py-2.5 text-[11px] leading-relaxed text-slate-700 font-mono">{{ previewResult.prompts.detail }}</pre>
                  </div>
                </div>
              </template>
            </div>

            <!-- 底部操作 -->
            <div class="sticky bottom-0 bg-slate-50 border-t border-slate-100 px-5 py-4 flex items-center justify-between gap-2 rounded-b-2xl flex-shrink-0">
              <p class="text-[10px] text-slate-400">确认无误后点击「确认方案并生图」开始生成</p>
              <button @click="closePreviewPanel" class="px-4 py-2 rounded-xl text-xs font-medium text-white bg-brand-gradient hover:shadow-glow transition-all flex-shrink-0">
                确认
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
/* 抽屉滑入动画 */
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.2s ease;
}
.drawer-enter-active > div:last-child,
.drawer-leave-active > div:last-child {
  transition: transform 0.25s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from > div:last-child,
.drawer-leave-to > div:last-child {
  transform: translateX(100%);
}
</style>
