import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type {
  GenerationMode,
  SceneStyle,
  ProductImage,
  ReferenceImage,
  ProConfig,
  GeneratedImage,
  LightingStyle,
  CameraAngle,
  AspectRatio,
  GenerationConfig,
  FeaturePricing,
} from '@/types'
import { imageUrlToBase64 } from '@/lib/utils'
import { getErrorMessage } from '@/lib/error'
import { smartGenerate, getBatchStatus, getTaskStatus, retryTask, type GenerationTask } from '@/api/generation'
import { submitBatchTask, getBatchManifest, retryBatchTask, type BatchSubmitPayload, type BatchSubmitResult, type BatchManifest, type BatchManifestItem } from '@/api/batch'
import { useTaskSse, type TaskStatus } from '@/composables/useTaskSse'
import { getFeaturePricingByKey, calculateImageCost } from '@/api/featurePricing'
import type { TemplateSellingPointEn } from '@/api/template'
import type { ComplianceBlock } from '@/api/compliance'

/** 功能定价 featureKey 常量（与后端配置对齐） */
const SMART_FEATURE_KEY = 'ai_product_image.smart_mode'
const PRO_FEATURE_KEY = 'ai_product_image.pro_mode'

export const useWorkspaceStore = defineStore('workspace', () => {
  const mode = ref<GenerationMode>('smart')
  const productImages = ref<ProductImage[]>([])
  const referenceImage = ref<ReferenceImage | null>(null)
  const sceneStyle = ref<SceneStyle | null>(null)
  const proConfig = ref<ProConfig>({
    rawPrompt: '',
    polishedPrompt: '',
    zhTags: [],
    lighting: 'studio-soft',
    cameraAngle: 'eye-level',
    aspectRatio: '1:1',
    promptHistory: [],
  })
  const generatedImages = ref<GeneratedImage[]>([])
  const isGenerating = ref(false)
  const batchId = ref<string | null>(null)

  // 专业模式状态(供全局 UI 感知,实际流程由 ProMode.vue 自管理)
  const isProGenerating = ref(false)
  const proBatchId = ref<string | null>(null)

  // ===== 批次进度跟踪（SubTask 8.4：SSE 订阅 + 降级轮询，见 startPolling） =====
  /** 兜底超时：与原自适应轮询的 15 分钟上限一致 */
  const MAX_TRACKING_DURATION = 15 * 60 * 1000
  const batchSseTaskId = ref('')
  let trackingTimer: ReturnType<typeof setTimeout> | null = null
  let batchFinished = true
  const fetchedImageTaskIds = new Set<string>()

  const smartModeConfig = ref<{
    platform: string
    region: string
    targetLanguage: string
    size: string
    productInfo: any
    imageGroups: any[]
    referenceText?: string
    /** 模板引擎站点编码（来自 /template/options），可选 */
    site?: string
    /** 英文卖点（AI 商品分析返回后编辑提交），可选 */
    sellingPointsEn?: TemplateSellingPointEn[]
  } | null>(null)

  // ===== 智能模式英文卖点校验状态（SmartMode 写入，ConfigPanel 生图前校验） =====
  /** 英文卖点视觉关键词是否含中文/全角字符（true 时禁止提交生图） */
  const smartEnPointsInvalid = ref(false)

  function setSmartEnPointsInvalid(invalid: boolean) {
    smartEnPointsInvalid.value = invalid
  }

  // ===== 合规阻断信息（生图提交 400 且 data.blocks 存在时展示） =====
  const complianceBlocks = ref<ComplianceBlock[]>([])

  // ===== 功能定价状态 =====
  /** 智能模式当前定价（null 表示未加载或未配置） */
  const currentPricing = ref<FeaturePricing | null>(null)
  /** 智能模式单张图片消耗（基于 currentPricing + smartModeConfig.size 计算） */
  const singleImageCost = ref(0)
  /** 专业模式当前定价 */
  const proPricing = ref<FeaturePricing | null>(null)
  /** 专业模式单张图片消耗 */
  const proSingleImageCost = ref(0)
  /** 专业模式任务数（用于估算总价） */
  const proTaskCount = ref(0)

  function setSmartModeConfig(config: typeof smartModeConfig.value) {
    const prevSize = smartModeConfig.value?.size
    smartModeConfig.value = config
    // 尺寸变化时重新计算单张成本（若定价已加载）
    if (config?.size !== prevSize) {
      recomputeCost()
    }
  }

  function getSmartModeConfig() {
    return smartModeConfig.value
  }

  /** 根据当前 currentPricing 和 smartModeConfig.size 重新计算智能模式单张成本 */
  function recomputeCost() {
    const size = smartModeConfig.value?.size || '1024x1024'
    singleImageCost.value = calculateImageCost(currentPricing.value, size)
  }

  /**
   * 加载智能模式定价并刷新 singleImageCost。
   * 失败时静默置 0（不阻塞生成，由后端最终判定扣点）。
   */
  async function loadPricing(featureKey: string = SMART_FEATURE_KEY) {
    try {
      const pricing = await getFeaturePricingByKey(featureKey)
      currentPricing.value = pricing
      recomputeCost()
    } catch (err) {
      console.error('[workspace] loadPricing failed:', err)
      currentPricing.value = null
      singleImageCost.value = 0
    }
  }

  /**
   * 加载专业模式定价。
   * @param size 当前输出尺寸（如 "1024x1024"）
   * @param taskCount 任务总数（用于估算总价）
   */
  async function loadProPricing(size: string, taskCount: number) {
    proTaskCount.value = taskCount
    try {
      const pricing = await getFeaturePricingByKey(PRO_FEATURE_KEY)
      proPricing.value = pricing
      proSingleImageCost.value = calculateImageCost(pricing, size || '1024x1024')
    } catch (err) {
      console.error('[workspace] loadProPricing failed:', err)
      proPricing.value = null
      proSingleImageCost.value = 0
    }
  }

  /** 智能模式预计总消耗 */
  /** 简单模式套图结构配置的总图片数（从 imageGroups 中统计所有 slots） */
  const totalSmartSlots = computed(() => {
    const groups = smartModeConfig.value?.imageGroups || []
    return groups.reduce((sum: number, g: any) => sum + (g.slots?.length || 0), 0)
  })

  const estimatedCost = computed(() =>
    singleImageCost.value * totalSmartSlots.value,
  )

  /** 专业模式预计总消耗 */
  const proEstimatedCost = computed(() =>
    proSingleImageCost.value * proTaskCount.value,
  )

  const canGenerate = computed(
    () => productImages.value.length > 0 && !isGenerating.value,
  )

  const currentConfig = computed<GenerationConfig>(() => ({
    mode: mode.value,
    productImages: productImages.value,
    referenceImage: referenceImage.value,
    sceneStyle: mode.value === 'smart' ? sceneStyle.value : null,
    proConfig: proConfig.value,
  }))

  function setMode(m: GenerationMode) {
    if (mode.value === m) return
    // 切换模式时清理旧模式的生成状态
    stopPolling()
    isGenerating.value = false
    batchId.value = null
    generatedImages.value = []
    mode.value = m
  }

  function addProductImages(images: ProductImage[]) {
    if (productImages.value.length + images.length > 10) {
      return false
    }
    productImages.value.push(...images)
    return true
  }

  function removeProductImage(id: string) {
    productImages.value = productImages.value.filter((img) => img.id !== id)
  }

  function setReferenceImage(img: ReferenceImage | null) {
    referenceImage.value = img
  }

  function updateReferenceStrength(strength: number) {
    if (referenceImage.value) {
      referenceImage.value.strength = strength
    }
  }

  function setSceneStyle(style: SceneStyle | null) {
    sceneStyle.value = style
  }

  function updateProConfig(partial: Partial<ProConfig>) {
    Object.assign(proConfig.value, partial)
  }

  function updateLighting(lighting: LightingStyle) {
    proConfig.value.lighting = lighting
  }

  function updateCameraAngle(angle: CameraAngle) {
    proConfig.value.cameraAngle = angle
  }

  function updateAspectRatio(ratio: AspectRatio) {
    proConfig.value.aspectRatio = ratio
  }

  // 专业模式状态设置(供 ProMode.vue 调用以同步全局 UI)
  function setProGenerating(value: boolean) {
    isProGenerating.value = value
  }

  function setProBatchId(id: string | null) {
    proBatchId.value = id
  }

  /** 停止批次进度订阅（SSE 连接 / 降级轮询 / 兜底超时一并清理） */
  function stopPolling() {
    batchFinished = true
    if (trackingTimer) {
      clearTimeout(trackingTimer)
      trackingTimer = null
    }
    generationSse.stop()
    fetchedImageTaskIds.clear()
  }

  async function fetchTaskImage(taskId: string): Promise<void> {
    try {
      const task = await getTaskStatus(taskId)
      if (task.image_url) {
        generatedImages.value = generatedImages.value.map(img =>
          img.id === taskId ? { ...img, url: task.image_url || '' } : img
        )
      } else {
        // 后端返回成功但无 image_url，标记为失败
        console.warn(`[图片获取] task=${taskId} 返回成功但无 image_url`)
        generatedImages.value = generatedImages.value.map(img =>
          img.id === taskId ? { ...img, status: 'failed' as const, errorMsg: '图片数据获取失败' } : img
        )
      }
    } catch (err) {
      console.error(`[图片获取] task=${taskId} 失败:`, err)
      // 标记为失败，让用户看到明确状态
      generatedImages.value = generatedImages.value.map(img =>
        img.id === taskId ? { ...img, status: 'failed' as const, errorMsg: '图片加载失败，请重试' } : img
      )
      fetchedImageTaskIds.delete(taskId)
    }
  }

  // ===== 批次进度 SSE 订阅（SubTask 8.4） =====
  /** 远程任务形状：SSE 批次聚合事件与降级轮询 GET 归一化后的公共字段 */
  interface GenTaskLike {
    task_id: string
    batch_id?: string
    status: string
    prompt_used?: string | null
    image_url?: string | null
    has_image?: boolean
    error_msg?: string | null
  }

  /**
   * 任务状态 → UI 状态：
   * 轮询 GET 为原始语义（pending/processing/success/failed），
   * SSE 事件为统一语义（queued/running/completed/failed），两种形状都归一到 UI 三态
   */
  function genStatusToUi(status: string | undefined): 'success' | 'failed' | 'processing' {
    if (status === 'success' || status === 'completed') return 'success'
    if (status === 'failed') return 'failed'
    return 'processing'
  }

  /**
   * 应用一次批次任务状态刷新（SSE 事件与降级轮询同源），返回是否全部完成。
   * 批次聚合进度（如 3/8 张完成）仍由前端计算：本函数即原轮询响应的处理逻辑，
   * 仅把"每次状态刷新"的来源从轮询响应换成 SSE 事件。
   */
  async function applyGenerationTasks(tasks: GenTaskLike[]): Promise<boolean> {
    if (!tasks.length) return false

    generatedImages.value = tasks.map((task) => {
      const existing = generatedImages.value.find(img => img.id === task.task_id)
      return {
        id: task.task_id,
        taskId: task.task_id,
        batchId: task.batch_id || existing?.batchId || batchId.value || '',
        url: task.image_url || existing?.url || '',
        prompt: task.prompt_used || existing?.prompt || '',
        status: genStatusToUi(task.status),
        errorMsg: task.error_msg || undefined,
        favorited: false,
      }
    })

    // 后端已剥离 base64 数据 URI，对成功但缺图的任务单独获取图片
    const imageFetches: Promise<void>[] = []
    for (const task of tasks) {
      if (genStatusToUi(task.status) === 'success' && !task.image_url && task.has_image) {
        const tid = task.task_id
        if (!fetchedImageTaskIds.has(tid)) {
          fetchedImageTaskIds.add(tid)
          imageFetches.push(fetchTaskImage(tid))
        }
      }
    }
    // 等待所有图片获取完成后再判定是否全部完成
    if (imageFetches.length > 0) {
      await Promise.allSettled(imageFetches)
    }

    // 全部完成判定（与原轮询一致）：失败任务直接算完成，成功任务必须有实际图片 URL
    return tasks.every((task) => {
      const ui = genStatusToUi(task.status)
      if (ui === 'failed') return true
      if (ui === 'success') {
        const local = generatedImages.value.find(img => img.id === task.task_id)
        return !!local?.url
      }
      return false
    })
  }

  /** 降级轮询：批次 GET 响应 → 统一 TaskStatus（SSE 连续失败时由 useTaskSse 调用，2s 间隔） */
  async function pollBatchStatus(bid: string): Promise<TaskStatus> {
    const result = await getBatchStatus(bid)
    const tasks: GenTaskLike[] = result.tasks.map(t => ({
      task_id: t.task_id,
      batch_id: t.batch_id || bid,
      status: t.status,
      prompt_used: t.prompt_used,
      image_url: t.image_url,
      has_image: t.has_image,
      error_msg: t.error_msg,
    }))
    const allDone = tasks.length > 0 && tasks.every(t => genStatusToUi(t.status) !== 'processing')
    return {
      status: allDone ? 'completed' : 'running',
      step: '',
      pct: 0,
      result: { batch_id: bid, tasks },
      error: null,
    }
  }

  function clearTrackingTimer() {
    if (trackingTimer) {
      clearTimeout(trackingTimer)
      trackingTimer = null
    }
  }

  /** 结束本次批次跟踪（幂等） */
  function finishGeneration() {
    if (batchFinished) return
    batchFinished = true
    clearTrackingTimer()
    generationSse.stop()
    isGenerating.value = false
  }

  /** 批次进度订阅：单图任务用 task_id、批次用 batch_id（后端对两种 id 都发事件），这里订阅批次 */
  const generationSse = useTaskSse({
    taskId: batchSseTaskId,
    pollFn: pollBatchStatus,
    onCompleted: async (result) => {
      const tasks = (result as { tasks?: GenTaskLike[] } | null)?.tasks || []
      await applyGenerationTasks(tasks)
      finishGeneration()
    },
    onFailed: (err) => {
      console.warn('[workspace] 批次任务失败事件:', err)
      finishGeneration()
    },
  })

  // 每次状态刷新（SSE progress / 降级轮询响应）→ 更新批次 UI
  watch(() => generationSse.result, async (result) => {
    if (batchFinished) return
    const tasks = (result as { tasks?: GenTaskLike[] } | null)?.tasks
    if (!tasks || tasks.length === 0) return
    const allDone = await applyGenerationTasks(tasks)
    if (allDone) finishGeneration()
  })

  /**
   * 开始跟踪批次进度：订阅 task-events:{batch_id}（SSE 失败自动降级为 pollBatchStatus 轮询）。
   * 重试/重新生成沿用同一入口（新批次产生新 batch_id，订阅自动重建）。
   */
  function startPolling(bid: string) {
    stopPolling()
    batchFinished = false
    batchSseTaskId.value = bid
    generationSse.start()

    // 兜底超时：SSE 与轮询都拿不到终态时强制结束（与原轮询 15 分钟上限行为一致）
    trackingTimer = setTimeout(() => {
      if (batchFinished) return
      generatedImages.value = generatedImages.value.map(img => ({
        ...img,
        status: img.status === 'processing' ? 'failed' as const : img.status,
        errorMsg: img.status === 'processing' ? '生成超时，请重试' : img.errorMsg,
      }))
      finishGeneration()
    }, MAX_TRACKING_DURATION)
  }

  // ===== 批量生成（Task 6）状态：提交 / manifest / SSE 进度 / 失败重试 =====
  /** 批量任务 ID（batch_task_id）。与单图生成批次的 batchId 相互独立 */
  const batchTaskId = ref<string | null>(null)
  /** 批量任务状态：idle | submitting | running | completed | failed（running 后为后端批次状态透传） */
  const batchStatus = ref<string>('idle')
  /** manifest 明细项（当前页） */
  const batchItems = ref<BatchManifestItem[]>([])
  /** manifest 各状态计数 */
  const batchCounts = ref<Record<string, number>>({})
  const batchTotalItems = ref(0)
  /** 后端预检锁定的灵感币总数 */
  const batchCoinsLocked = ref(0)
  /** 后端返回的单张单价 */
  const batchUnitCost = ref(0)
  /** 提交响应中的 warnings */
  const batchWarnings = ref<string[]>([])
  /** 批次进度百分比（SSE 事件优先，manifest 计数兜底） */
  const batchPct = ref(0)
  /** 批量操作错误信息（提交 400 预检失败 / 重试 400 等） */
  const batchError = ref('')
  const isBatchSubmitting = ref(false)
  const isBatchTracking = ref(false)
  let batchTrackingTimer: ReturnType<typeof setTimeout> | null = null
  let batchManifestRefreshTimer: ReturnType<typeof setTimeout> | null = null
  let batchTrackingFinished = true

  const failedBatchItems = computed(() =>
    batchItems.value.filter((item) => item.status === 'failed'),
  )

  /** manifest 分页参数：明细表一次取 100 条足够展示 */
  const BATCH_MANIFEST_PAGE_SIZE = 100

  /** 应用一次 manifest 数据到批量 UI 状态，并判定是否终态 */
  function applyBatchManifest(data: BatchManifest) {
    batchItems.value = data.items || []
    batchCounts.value = data.counts || {}
    if (data.batch) {
      batchTotalItems.value = data.batch.total_items ?? batchTotalItems.value
      batchStatus.value = data.batch.status || batchStatus.value
      batchCoinsLocked.value = data.batch.coins_locked ?? batchCoinsLocked.value
      if (data.batch.total_items > 0) {
        batchPct.value = Math.round(
          ((data.batch.succeeded_items ?? 0) + (data.batch.failed_items ?? 0)) / data.batch.total_items * 100,
        )
      }
    }
    if (batchTrackingFinished) return
    const st = data.batch?.status
    if (st === 'completed' || st === 'failed') finishBatchTracking()
  }

  /** 拉取批量任务 manifest 并刷新 UI（无任务时返回 null） */
  async function fetchBatchManifest(): Promise<BatchManifest | null> {
    if (!batchTaskId.value) return null
    try {
      const data = await getBatchManifest(batchTaskId.value, { page: 1, page_size: BATCH_MANIFEST_PAGE_SIZE })
      applyBatchManifest(data)
      return data
    } catch (err) {
      console.error('[workspace] 批量 manifest 拉取失败:', err)
      return null
    }
  }

  /** 降级轮询：manifest GET → 统一 TaskStatus（批量 SSE 连续失败时由 useTaskSse 调用） */
  async function pollBatchManifest(taskId: string): Promise<TaskStatus> {
    const data = await getBatchManifest(taskId, { page: 1, page_size: BATCH_MANIFEST_PAGE_SIZE })
    applyBatchManifest(data)
    const st = data.batch?.status
    return {
      status: st === 'completed' ? 'completed' : st === 'failed' ? 'failed' : 'running',
      step: '',
      pct: batchPct.value,
      result: data,
      error: null,
    }
  }

  function clearBatchTrackingTimer() {
    if (batchTrackingTimer) {
      clearTimeout(batchTrackingTimer)
      batchTrackingTimer = null
    }
  }

  /** 结束本次批量跟踪（幂等，不清空展示数据） */
  function finishBatchTracking() {
    if (batchTrackingFinished) return
    batchTrackingFinished = true
    clearBatchTrackingTimer()
    batchSse.stop()
    isBatchTracking.value = false
  }

  /** 停止批量订阅与防抖刷新（提交新一轮 / 重置时调用） */
  function stopBatchTracking() {
    batchTrackingFinished = true
    clearBatchTrackingTimer()
    if (batchManifestRefreshTimer) {
      clearTimeout(batchManifestRefreshTimer)
      batchManifestRefreshTimer = null
    }
    batchSse.stop()
    isBatchTracking.value = false
  }

  /** 批量进度订阅：复用任务 SSE 通道，SSE 连续失败自动降级为 manifest 轮询 */
  const batchSse = useTaskSse({
    taskId: batchSseTaskId,
    pollFn: pollBatchManifest,
    onCompleted: () => finishBatchTracking(),
    onFailed: () => finishBatchTracking(),
  })

  // SSE 进度事件只携带摘要（step/pct/succeeded/failed/batch_status），
  // 明细以 manifest 为准：更新快照字段后防抖 300ms 拉取一次 manifest
  watch(() => batchSse.raw, (raw) => {
    if (batchTrackingFinished || !raw || batchSse.source === 'poll') return
    const payload = raw as Record<string, any>
    if (typeof payload.pct === 'number') batchPct.value = payload.pct
    if (payload.batch_status) batchStatus.value = payload.batch_status
    if (batchManifestRefreshTimer) clearTimeout(batchManifestRefreshTimer)
    batchManifestRefreshTimer = setTimeout(() => { fetchBatchManifest() }, 300)
  })

  /** 开始跟踪批量任务进度（订阅 SSE + 降级轮询 + 兜底超时） */
  function startBatchTracking(taskId: string) {
    stopBatchTracking()
    batchTrackingFinished = false
    batchTaskId.value = taskId
    batchSseTaskId.value = taskId
    isBatchTracking.value = true
    batchSse.start()
    // 兜底超时：与单图批次一致的 15 分钟上限
    batchTrackingTimer = setTimeout(() => {
      finishBatchTracking()
      fetchBatchManifest()
    }, MAX_TRACKING_DURATION)
  }

  /**
   * 提交批量生成任务。后端预检失败（400）时抛出 ApiError，
   * err.data 内含失败原因（由调用方展示）。
   */
  async function submitBatch(payload: BatchSubmitPayload): Promise<BatchSubmitResult> {
    isBatchSubmitting.value = true
    batchError.value = ''
    batchStatus.value = 'submitting'
    // 新一轮提交前清理上一轮的订阅与展示数据
    stopBatchTracking()
    batchItems.value = []
    batchCounts.value = {}
    batchWarnings.value = []
    batchPct.value = 0
    try {
      const result = await submitBatchTask(payload)
      batchTaskId.value = result.batch_task_id
      batchTotalItems.value = result.total_items
      batchCoinsLocked.value = result.coins_locked
      batchUnitCost.value = result.unit_cost
      batchWarnings.value = result.warnings || []
      batchStatus.value = 'running'
      startBatchTracking(result.batch_task_id)
      await fetchBatchManifest()
      return result
    } catch (err: any) {
      batchStatus.value = 'idle'
      batchError.value = getErrorMessage(err, '批量任务提交失败')
      throw err
    } finally {
      isBatchSubmitting.value = false
    }
  }

  /** 重试批量任务中的失败项，成功后重建进度订阅并刷新 manifest */
  async function retryBatchFailed(): Promise<boolean> {
    if (!batchTaskId.value) return false
    batchError.value = ''
    try {
      await retryBatchTask(batchTaskId.value)
      // 重试后失败项回到 running，重建进度订阅
      startBatchTracking(batchTaskId.value)
      await fetchBatchManifest()
      return true
    } catch (err: any) {
      // 后端 400：completed 无失败项或 running 中不允许重试
      batchError.value = getErrorMessage(err, '重试失败，请稍后再试')
      return false
    }
  }

  async function runGeneration() {
    isGenerating.value = true
    batchId.value = `batch-${Date.now()}`
    // 新一轮提交前清空上一轮的合规阻断提示
    complianceBlocks.value = []

    try {
      const smartConfig = getSmartModeConfig()
      if (!smartConfig) {
        isGenerating.value = false
        generatedImages.value = [{
          id: `gi-${Date.now()}`,
          taskId: `task-config-${Date.now()}`,
          batchId: '',
          url: '',
          prompt: '',
          status: 'failed' as const,
          errorMsg: '生成配置未就绪，请刷新页面后重试',
          favorited: false,
        }]
        return
      }

      const productImagesBase64 = await Promise.all(
        productImages.value.map(async (img) => {
          return await imageUrlToBase64(img.url)
        })
      )

      const result = await smartGenerate({
        product_images: productImagesBase64,
        reference_image: referenceImage.value
          ? await imageUrlToBase64(referenceImage.value.url)
          : null,
        reference_text: smartConfig.referenceText || null,
        platform: smartConfig.platform,
        region: smartConfig.region,
        target_language: smartConfig.targetLanguage,
        size: smartConfig.size,
        product_info: smartConfig.productInfo,
        image_groups: smartConfig.imageGroups,
      })

      batchId.value = result.batch_id

      // 初始化任务列表（后端已返回 batch_id + 任务列表，状态为 pending）
      generatedImages.value = result.tasks.map((task: GenerationTask) => ({
        id: task.task_id,
        taskId: task.task_id,
        batchId: task.batch_id,
        url: task.image_url || '',
        prompt: task.prompt_used || '',
        status: 'processing' as const,
        errorMsg: task.error_msg || undefined,
        favorited: false,
      }))

      // 开始跟踪批次进度（SSE 订阅 + 降级轮询）
      startPolling(result.batch_id)
    } catch (err: any) {
      console.error('[runGeneration] 提交失败:', err)
      stopPolling()
      isGenerating.value = false
      // 合规阻断：提交被 400 拒绝且响应 data 内含 blocks 列表时，结构化展示阻断原因
      const blocks = err?.data?.blocks ?? err?.details?.blocks
      if (Array.isArray(blocks) && blocks.length > 0) {
        complianceBlocks.value = blocks
      }
      const errorMsg = getErrorMessage(err, '生成失败，请稍后重试')
      generatedImages.value = [{
        id: `gi-${Date.now()}`,
        taskId: `task-error-${Date.now()}`,
        batchId: batchId.value || '',
        url: '',
        prompt: '',
        status: 'failed' as const,
        errorMsg: errorMsg,
        favorited: false,
      }]
    }
  }

  async function retryTaskAction(taskId: string) {
    // 找到对应的本地图片记录
    const img = generatedImages.value.find((g) => g.id === taskId)
    if (!img) return

    const bid = img.batchId
    if (!bid) {
      console.error('[retryTask] 缺少 batchId，无法重试')
      return
    }

    // 即时 UI 反馈：将状态设为 processing
    img.status = 'processing' as const
    img.errorMsg = undefined

    try {
      isGenerating.value = true
      await retryTask(taskId)
      // 重新订阅批次进度，全部任务完成后自动停止
      startPolling(bid)
    } catch (err: any) {
      console.error('[retryTask] 重试提交失败:', err)
      img.status = 'failed' as const
      // 后端返回"仅失败的任务可以重试"(code=4001) 说明任务实际已成功，前端误判为失败
      if (err?.code === 4001 && err?.message?.includes('仅失败')) {
        img.errorMsg = '该任务可能已成功生成，请刷新页面查看'
      } else {
        img.errorMsg = getErrorMessage(err, '重试失败，请稍后再试')
      }
      isGenerating.value = false
    }
  }

  function reset() {
    stopPolling()
    mode.value = 'smart'
    productImages.value = []
    referenceImage.value = null
    sceneStyle.value = null
    proConfig.value = {
      rawPrompt: '',
      polishedPrompt: '',
      zhTags: [],
      lighting: 'studio-soft',
      cameraAngle: 'eye-level',
      aspectRatio: '1:1',
      promptHistory: [],
    }
    generatedImages.value = []
    isGenerating.value = false
    batchId.value = null
    // 重置专业模式状态
    isProGenerating.value = false
    proBatchId.value = null
    // 重置智能模式英文卖点校验与合规阻断提示
    smartEnPointsInvalid.value = false
    complianceBlocks.value = []
    // 重置批量生成状态
    stopBatchTracking()
    batchTaskId.value = null
    batchStatus.value = 'idle'
    batchItems.value = []
    batchCounts.value = {}
    batchTotalItems.value = 0
    batchCoinsLocked.value = 0
    batchUnitCost.value = 0
    batchWarnings.value = []
    batchPct.value = 0
    batchError.value = ''
    isBatchSubmitting.value = false
  }

  function loadConfig(config: GenerationConfig) {
    mode.value = config.mode
    referenceImage.value = config.referenceImage
    sceneStyle.value = config.sceneStyle
    proConfig.value = { ...config.proConfig }
    productImages.value = []
    generatedImages.value = []
  }

  return {
    mode,
    productImages,
    referenceImage,
    sceneStyle,
    proConfig,
    generatedImages,
    isGenerating,
    batchId,
    // 专业模式状态
    isProGenerating,
    proBatchId,
    setProGenerating,
    setProBatchId,
    estimatedCost,
    totalSmartSlots,
    canGenerate,
    currentConfig,
    setMode,
    addProductImages,
    removeProductImage,
    setReferenceImage,
    updateReferenceStrength,
    setSceneStyle,
    updateProConfig,
    updateLighting,
    updateCameraAngle,
    updateAspectRatio,
    runGeneration,
    retryTask: retryTaskAction,
    setSmartModeConfig,
    smartModeConfig,
    smartEnPointsInvalid,
    setSmartEnPointsInvalid,
    complianceBlocks,
    reset,
    loadConfig,
    // 功能定价
    currentPricing,
    singleImageCost,
    proPricing,
    proSingleImageCost,
    proTaskCount,
    proEstimatedCost,
    loadPricing,
    loadProPricing,
    recomputeCost,
    // 批量生成（Task 6）
    batchTaskId,
    batchStatus,
    batchItems,
    batchCounts,
    batchTotalItems,
    batchCoinsLocked,
    batchUnitCost,
    batchWarnings,
    batchPct,
    batchError,
    isBatchSubmitting,
    isBatchTracking,
    failedBatchItems,
    submitBatch,
    fetchBatchManifest,
    retryBatchFailed,
  }
})