<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { Upload, Download, ShoppingBag, Loader2, RefreshCw, AlertCircle, ImageOff, X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { generateModelProduct, getModelProductStatus } from '@/api/toolbox'
import type { ModelProductTaskStatus } from '@/api/toolbox'
import { getErrorMessage } from '@/lib/error'
import { useTaskSse, type TaskStatus } from '@/composables/useTaskSse'
import ToolCostBadge from '@/components/common/ToolCostBadge.vue'
import WalletCostPanel from '@/components/common/WalletCostPanel.vue'
import { useAuthStore } from '@/stores/auth'

const FEATURE_KEY = 'toolbox.model_product'
const auth = useAuthStore()
const walletCostRef = ref<InstanceType<typeof WalletCostPanel> | null>(null)
const insufficientBalance = ref(false)
/** 当前任务的单次消耗，供完成后同步本地余额 */
const taskCost = ref(0)

// ===== 状态变量 =====
const productImage = ref<string>('')
const modelImage = ref<string>('')
const productFileName = ref<string>('')
const modelFileName = ref<string>('')
const uploadProgress = ref<number>(0)
const a0Prompt = ref<string>('')
const selectedResolution = ref<string>('1024x1024')
const customWidth = ref<number>(1024)
const customHeight = ref<number>(1024)
const selectedRatio = ref<string>('1:1')
const isProcessing = ref(false)
const taskId = ref<string>('')
const taskStatus = ref<ModelProductTaskStatus | null>(null)
const resultImage = ref<string>('')
const errorMsg = ref<string>('')
const isProductDragOver = ref(false)
const isModelDragOver = ref(false)
const showPreview = ref(false)
const previewScale = ref(1)
const previewPosition = ref({ x: 0, y: 0 })

// ===== 任务进度跟踪（SSE 实时订阅，GET 轮询作为降级通道） =====
/** 与原轮询 maxPolls=120 × 2s 对齐的总超时 */
const TASK_TIMEOUT_MS = 4 * 60 * 1000
let timeoutTimer: ReturnType<typeof setTimeout> | null = null

/** GET 端点状态（progress 文案）→ 通用任务状态（step 文案）适配 */
function modelProductStatusToTask(s: ModelProductTaskStatus): TaskStatus {
  return {
    status: s.status === 'completed' ? 'completed' : s.status === 'failed' ? 'failed' : 'running',
    step: s.progress || '',
    pct: 0,
    result: s.result ?? null,
    error: s.error ?? null,
  }
}

/** 降级轮询函数：复用既有 GET 请求，保持原"查询失败即终止"的语义 */
async function pollModelProductStatus(id: string): Promise<TaskStatus> {
  try {
    const s = await getModelProductStatus(id)
    return modelProductStatusToTask(s)
  } catch (err) {
    console.warn('[ModelProduct] 轮询失败:', err)
    // 与原轮询一致：查询失败以失败终态终止并提示错误
    return {
      status: 'failed',
      step: '',
      pct: 0,
      result: null,
      error: getErrorMessage(err, '查询任务状态失败'),
    }
  }
}

const modelProductTask = useTaskSse({
  taskId,
  pollFn: pollModelProductStatus,
  onCompleted: handleTaskCompleted,
  onFailed: handleTaskFailed,
})

// SSE 推送的步骤/状态 → taskStatus（模板进度文案沿用 taskStatus.progress 展示）
watch(() => [modelProductTask.status, modelProductTask.step] as const, ([st, sp]) => {
  if (!taskId.value) return
  taskStatus.value = {
    task_id: taskId.value,
    status: st === 'completed' || st === 'failed' ? st : 'processing',
    progress: sp || taskStatus.value?.progress || '',
  }
})

function handleTaskCompleted(result: any) {
  clearTaskTimeout()
  resultImage.value = result?.image || ''
  // 同步本地余额（后端已扣款；失败时忽略，后端为权威源）
  if (taskCost.value > 0) {
    try { auth.deductPoints(taskCost.value) } catch { /* ignore */ }
  }
  isProcessing.value = false
}

function handleTaskFailed(error: string) {
  clearTaskTimeout()
  errorMsg.value = error || '任务处理失败'
  isProcessing.value = false
}

function armTaskTimeout() {
  clearTaskTimeout()
  timeoutTimer = setTimeout(() => {
    if (!isProcessing.value) return
    modelProductTask.stop()
    errorMsg.value = '任务处理超时，请重试'
    isProcessing.value = false
  }, TASK_TIMEOUT_MS)
}

function clearTaskTimeout() {
  if (timeoutTimer) {
    clearTimeout(timeoutTimer)
    timeoutTimer = null
  }
}

// 组件卸载时清理超时定时器（SSE 连接由 useTaskSse 自动关闭）
onUnmounted(() => {
  clearTaskTimeout()
})

// ===== 分辨率选项 =====
const resolutions = [
  { value: '1024x1024', label: '1K' },
  { value: '2048x2048', label: '2K' },
  { value: '3840x2160', label: '4K' },
  { value: 'custom', label: '自定义' },
]

const ratios = [
  { value: '1:1', label: '1:1 正方形' },
  { value: '4:3', label: '4:3 横向' },
  { value: '3:4', label: '3:4 纵向' },
  { value: '16:9', label: '16:9 宽屏' },
  { value: '9:16', label: '9:16 竖屏' },
]

// ===== 比例与分辨率联动 =====
const ratioPixelMap: Record<string, Record<string, { width: number; height: number }>> = {
  '1:1': {
    '1024x1024': { width: 1024, height: 1024 },
    '2048x2048': { width: 2048, height: 2048 },
    '3840x2160': { width: 2160, height: 2160 },
  },
  '4:3': {
    '1024x1024': { width: 1024, height: 768 },
    '2048x2048': { width: 2048, height: 1536 },
    '3840x2160': { width: 2880, height: 2160 },
  },
  '3:4': {
    '1024x1024': { width: 768, height: 1024 },
    '2048x2048': { width: 1536, height: 2048 },
    '3840x2160': { width: 1616, height: 2160 },
  },
  '16:9': {
    '1024x1024': { width: 1024, height: 576 },
    '2048x2048': { width: 2048, height: 1152 },
    '3840x2160': { width: 3840, height: 2160 },
  },
  '9:16': {
    '1024x1024': { width: 576, height: 1024 },
    '2048x2048': { width: 1152, height: 2048 },
    '3840x2160': { width: 2160, height: 3840 },
  },
}

function onRatioChange(ratio: string) {
  selectedRatio.value = ratio
  selectedResolution.value = '1024x1024'
}

function onResolutionChange(res: string) {
  selectedResolution.value = res
  if (res !== 'custom') {
    const mapped = ratioPixelMap[selectedRatio.value]?.[res]
    if (mapped) {
      customWidth.value = mapped.width
      customHeight.value = mapped.height
    }
  }
}

// ===== 计算属性 =====
const resolvedSize = computed(() => {
  if (selectedResolution.value === 'custom') {
    return { width: customWidth.value, height: customHeight.value }
  }
  return ratioPixelMap[selectedRatio.value]?.[selectedResolution.value] || { width: 1024, height: 1024 }
})

const sizeInfo = computed(() => {
  const s = resolvedSize.value
  const totalPixels = s.width * s.height
  const mega = (totalPixels / 1_000_000).toFixed(1)
  return `${s.width} × ${s.height}（${mega}M 像素, ${selectedRatio.value}）`
})

const showBothUploaded = computed(() => productImage.value && modelImage.value)

// ===== 文件上传处理 =====
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function isAcceptedImage(file: File): boolean {
  return ['image/jpeg', 'image/png', 'image/webp'].includes(file.type)
}

function simulateUploadProgress(file: File) {
  uploadProgress.value = 0
  if (file.size <= 2 * 1024 * 1024) {
    uploadProgress.value = 100
    return
  }
  let progress = 0
  const interval = window.setInterval(() => {
    const increment = Math.floor(Math.random() * 11) + 10
    progress = Math.min(progress + increment, 95)
    uploadProgress.value = progress
    if (progress >= 95) {
      clearInterval(interval)
    }
  }, 100)
  setTimeout(() => {
    clearInterval(interval)
    uploadProgress.value = 100
  }, 1500)
}

async function handleProductFile(file: File) {
  errorMsg.value = ''
  if (!isAcceptedImage(file)) {
    errorMsg.value = '图片格式不支持，请使用 JPG、PNG 或 WebP 格式'
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    errorMsg.value = '图片大小超出限制，请压缩后重试（最大 20MB）'
    return
  }
  try {
    simulateUploadProgress(file)
    const base64 = await fileToBase64(file)
    productImage.value = base64
    productFileName.value = file.name
    resultImage.value = ''
    uploadProgress.value = 100
  } catch {
    errorMsg.value = '图片读取失败，请重试'
    uploadProgress.value = 0
  }
}

async function handleModelFile(file: File) {
  errorMsg.value = ''
  if (!isAcceptedImage(file)) {
    errorMsg.value = '图片格式不支持，请使用 JPG、PNG 或 WebP 格式'
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    errorMsg.value = '图片大小超出限制，请压缩后重试（最大 20MB）'
    return
  }
  try {
    simulateUploadProgress(file)
    const base64 = await fileToBase64(file)
    modelImage.value = base64
    modelFileName.value = file.name
    resultImage.value = ''
    uploadProgress.value = 100
  } catch {
    errorMsg.value = '图片读取失败，请重试'
    uploadProgress.value = 0
  }
}

function onProductFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    handleProductFile(input.files[0])
  }
  input.value = ''
}

function onModelFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    handleModelFile(input.files[0])
  }
  input.value = ''
}

function onProductDrop(event: DragEvent) {
  isProductDragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleProductFile(file)
}

function onModelDrop(event: DragEvent) {
  isModelDragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleModelFile(file)
}

function onProductDragOver() { isProductDragOver.value = true }
function onProductDragLeave() { isProductDragOver.value = false }
function onModelDragOver() { isModelDragOver.value = true }
function onModelDragLeave() { isModelDragOver.value = false }

function resetAll() {
  productImage.value = ''
  modelImage.value = ''
  productFileName.value = ''
  modelFileName.value = ''
  a0Prompt.value = ''
  resultImage.value = ''
  errorMsg.value = ''
  uploadProgress.value = 0
  taskId.value = ''
  taskStatus.value = null
  selectedResolution.value = '1024x1024'
  selectedRatio.value = '1:1'
  customWidth.value = 1024
  customHeight.value = 1024
}

// ===== 异步生成逻辑 =====
async function startGenerate() {
  if (!productImage.value) { errorMsg.value = '请上传商品图'; return }
  if (!modelImage.value) { errorMsg.value = '请上传模特图'; return }
  if (!a0Prompt.value.trim()) { errorMsg.value = '请输入提示词'; return }
  if (isProcessing.value) return

  // 自定义尺寸 16 倍数校验
  if (selectedResolution.value === 'custom') {
    if (customWidth.value % 16 !== 0 || customHeight.value % 16 !== 0) {
      errorMsg.value = '自定义尺寸的宽和高必须为 16 的倍数'
      return
    }
  }

  errorMsg.value = ''
  insufficientBalance.value = false

  // 余额校验
	const cost = walletCostRef.value?.cost ?? 0
	if (cost > 0 && auth.selectedWalletBalance < cost) {
    errorMsg.value = `灵感币余额不足，预计消耗 ${cost}，当前余额 ${auth.selectedWalletBalance}，请先充值`
    insufficientBalance.value = true
    return
  }
  taskCost.value = cost

  isProcessing.value = true
  resultImage.value = ''

  try {
    const res = await generateModelProduct({
      product_image: productImage.value,
      model_image: modelImage.value,
      prompt: a0Prompt.value.trim(),
      resolution: resolvedSize.value ? `${resolvedSize.value.width}x${resolvedSize.value.height}` : '1024x1024',
    })
    taskId.value = res.task_id
    taskStatus.value = { task_id: res.task_id, status: 'processing', progress: '正在初始化...' }
    // 订阅任务进度（SSE 优先，连续错误自动降级为 pollModelProductStatus 轮询）
    armTaskTimeout()
    modelProductTask.start()
  } catch (err) {
    errorMsg.value = getErrorMessage(err, '任务提交失败')
    isProcessing.value = false
  }
}

// ===== 下载 =====
function downloadResult() {
  if (!resultImage.value) return
  const a = document.createElement('a')
  a.href = resultImage.value
  const baseName = productFileName.value ? productFileName.value.replace(/\.[^.]+$/, '') : 'image'
  a.download = `${baseName}-model-product-${Date.now()}.png`
  a.click()
}

// ===== 预览模态框 =====
function openPreview() {
  showPreview.value = true
  previewScale.value = 1
  previewPosition.value = { x: 0, y: 0 }
}

function closePreview() {
  showPreview.value = false
}

function onPreviewWheel(event: WheelEvent) {
  event.preventDefault()
  const delta = event.deltaY > 0 ? -0.1 : 0.1
  previewScale.value = Math.max(0.5, Math.min(3.0, previewScale.value + delta))
}

// ===== 预览拖拽 =====
let isDragging = false
let dragStart = { x: 0, y: 0 }
let posStart = { x: 0, y: 0 }

function onPreviewMouseDown(event: MouseEvent) {
  isDragging = true
  dragStart = { x: event.clientX, y: event.clientY }
  posStart = { ...previewPosition.value }
  event.preventDefault()
}

function onPreviewMouseMove(event: MouseEvent) {
  if (!isDragging) return
  previewPosition.value = {
    x: posStart.x + (event.clientX - dragStart.x),
    y: posStart.y + (event.clientY - dragStart.y),
  }
}

function onPreviewMouseUp() {
  isDragging = false
}

// ===== clean up =====
// 任务进度订阅（SSE/降级轮询）与超时定时器的清理见文件头部 onUnmounted
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <!-- 页面标题 -->
    <div>
      <h1 class="text-2xl font-display font-bold text-slate-900 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <ShoppingBag class="w-5 h-5 text-white" />
        </div>
        模特商品图
        <ToolCostBadge :feature-key="FEATURE_KEY" />
      </h1>
      <p class="text-slate-500 mt-1 text-sm">上传商品图和模特图，AI 生成模特自然使用商品的图片</p>
    </div>

    <!-- 主容器 -->
    <div class="glass-card p-6 space-y-5">
      <!-- 双图上传区 -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- 商品图 -->
        <div class="space-y-2">
          <div class="flex items-center gap-2 text-sm font-medium text-slate-600">
            <ImageOff class="w-4 h-4 text-slate-400" />
            商品图 <span class="text-red-500">*</span>
          </div>
          <label
            for="model-product-upload"
            class="block cursor-pointer group"
            @drop.prevent="onProductDrop"
            @dragover.prevent="onProductDragOver"
            @dragleave.prevent="onProductDragLeave"
          >
            <!-- 已上传：缩略图预览 -->
            <div
              v-if="productImage"
              class="rounded-xl overflow-hidden bg-slate-50 border border-slate-200 min-h-[280px] flex items-center justify-center p-3 relative"
            >
              <img
                :src="productImage"
                alt="商品图"
                class="max-h-[280px] w-auto max-w-full object-contain rounded-lg"
              />
              <div class="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-all duration-200 flex items-center justify-center">
                <div class="opacity-0 group-hover:opacity-100 transition-opacity duration-200 text-white text-sm flex items-center gap-2">
                  <RefreshCw class="w-4 h-4" />
                  点击重新上传
                </div>
              </div>
            </div>
            <!-- 未上传：上传区 -->
            <div
              v-else
              :class="[
                'flex flex-col items-center justify-center py-16 px-6 rounded-2xl border-2 border-dashed transition-all duration-200 min-h-[280px]',
                isProductDragOver
                  ? 'border-emerald-500 bg-emerald-50'
                  : 'border-emerald-300 bg-gradient-to-br from-emerald-50/50 to-teal-50/50 group-hover:border-emerald-500 group-hover:bg-emerald-50',
              ]"
            >
              <div class="w-16 h-16 rounded-2xl bg-white shadow-sm flex items-center justify-center mb-3">
                <Upload class="w-7 h-7 text-emerald-500" />
              </div>
              <h3 class="text-base font-semibold text-slate-700 mb-1">点击或拖拽上传商品图</h3>
              <p class="text-xs text-slate-400 text-center max-w-xs">支持 JPG、PNG、WebP，单张最大 20MB</p>
            </div>
            <input
              id="model-product-upload"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              class="hidden"
              @change="onProductFileChange"
            />
          </label>
          <!-- 上传进度条 -->
          <div v-if="uploadProgress > 0 && uploadProgress < 100 && productImage" class="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden">
            <div
              class="h-full bg-gradient-to-r from-emerald-500 to-teal-500 rounded-full transition-all duration-300"
              :style="{ width: uploadProgress + '%' }"
            ></div>
          </div>
        </div>

        <!-- 模特图 -->
        <div class="space-y-2">
          <div class="flex items-center gap-2 text-sm font-medium text-slate-600">
            <ImageOff class="w-4 h-4 text-slate-400" />
            模特图 <span class="text-red-500">*</span>
          </div>
          <label
            for="model-image-upload"
            class="block cursor-pointer group"
            @drop.prevent="onModelDrop"
            @dragover.prevent="onModelDragOver"
            @dragleave.prevent="onModelDragLeave"
          >
            <!-- 已上传：缩略图预览 -->
            <div
              v-if="modelImage"
              class="rounded-xl overflow-hidden bg-slate-50 border border-slate-200 min-h-[280px] flex items-center justify-center p-3 relative"
            >
              <img
                :src="modelImage"
                alt="模特图"
                class="max-h-[280px] w-auto max-w-full object-contain rounded-lg"
              />
              <div class="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-all duration-200 flex items-center justify-center">
                <div class="opacity-0 group-hover:opacity-100 transition-opacity duration-200 text-white text-sm flex items-center gap-2">
                  <RefreshCw class="w-4 h-4" />
                  点击重新上传
                </div>
              </div>
            </div>
            <!-- 未上传：上传区 -->
            <div
              v-else
              :class="[
                'flex flex-col items-center justify-center py-16 px-6 rounded-2xl border-2 border-dashed transition-all duration-200 min-h-[280px]',
                isModelDragOver
                  ? 'border-emerald-500 bg-emerald-50'
                  : 'border-emerald-300 bg-gradient-to-br from-emerald-50/50 to-teal-50/50 group-hover:border-emerald-500 group-hover:bg-emerald-50',
              ]"
            >
              <div class="w-16 h-16 rounded-2xl bg-white shadow-sm flex items-center justify-center mb-3">
                <Upload class="w-7 h-7 text-emerald-500" />
              </div>
              <h3 class="text-base font-semibold text-slate-700 mb-1">点击或拖拽上传模特图</h3>
              <p class="text-xs text-slate-400 text-center max-w-xs">支持 JPG、PNG、WebP，单张最大 20MB</p>
            </div>
            <input
              id="model-image-upload"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              class="hidden"
              @change="onModelFileChange"
            />
          </label>
          <!-- 上传进度条 -->
          <div v-if="uploadProgress > 0 && uploadProgress < 100 && modelImage" class="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden">
            <div
              class="h-full bg-gradient-to-r from-emerald-500 to-teal-500 rounded-full transition-all duration-300"
              :style="{ width: uploadProgress + '%' }"
            ></div>
          </div>
        </div>
      </div>

      <!-- 分辨率与尺寸设置区（两图上传后显示） -->
      <div v-if="showBothUploaded" class="space-y-4 pt-2 border-t border-slate-100">
        <h3 class="text-sm font-semibold text-slate-700">分辨率与尺寸设置</h3>

        <!-- 比例选择 -->
        <div class="space-y-2">
          <label class="text-xs font-medium text-slate-500">比例</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="ratio in ratios"
              :key="ratio.value"
              @click="onRatioChange(ratio.value)"
              :class="[
                'px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 border',
                selectedRatio === ratio.value
                  ? 'bg-emerald-500 text-white border-emerald-500 shadow-sm'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-emerald-300 hover:text-emerald-600',
              ]"
            >
              {{ ratio.label }}
            </button>
          </div>
        </div>

        <!-- 分辨率选择 -->
        <div class="space-y-2">
          <label class="text-xs font-medium text-slate-500">分辨率</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="res in resolutions"
              :key="res.value"
              @click="onResolutionChange(res.value)"
              :class="[
                'px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 border',
                selectedResolution === res.value
                  ? 'bg-emerald-500 text-white border-emerald-500 shadow-sm'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-emerald-300 hover:text-emerald-600',
              ]"
            >
              {{ res.label }}
            </button>
          </div>
        </div>

        <!-- 自定义尺寸输入 -->
        <div v-if="selectedResolution === 'custom'" class="flex items-center gap-3">
          <div class="flex items-center gap-2">
            <label class="text-xs font-medium text-slate-500">宽</label>
            <input
              v-model.number="customWidth"
              type="number"
              min="64"
              max="3840"
              step="16"
              class="w-24 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-400"
            />
          </div>
          <span class="text-slate-400 text-lg">×</span>
          <div class="flex items-center gap-2">
            <label class="text-xs font-medium text-slate-500">高</label>
            <input
              v-model.number="customHeight"
              type="number"
              min="64"
              max="3840"
              step="16"
              class="w-24 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-400"
            />
          </div>
        </div>

        <!-- 尺寸信息 -->
        <div class="text-xs text-slate-400 bg-slate-50 rounded-lg px-3 py-2">
          最终尺寸：{{ sizeInfo }}
        </div>
      </div>

      <!-- 提示词输入区（两图上传后显示） -->
      <div v-if="showBothUploaded" class="space-y-2 pt-2 border-t border-slate-100">
        <label class="flex items-center gap-2 text-sm font-medium text-slate-600">
          提示词 A0 <span class="text-red-500">*</span>
          <span class="text-xs text-slate-400 font-normal">（支持模糊描述）</span>
        </label>
        <textarea
          v-model="a0Prompt"
          rows="3"
          placeholder="描述模特使用商品的方式，如：模特手持商品，自然站立，微笑"
          class="w-full px-4 py-3 rounded-xl border border-slate-200 bg-white/60 text-sm text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-400 resize-none transition-colors"
        ></textarea>
      </div>

      <!-- 处理中状态 -->
      <div v-if="isProcessing" class="flex flex-col items-center justify-center py-12">
        <div class="relative w-24 h-24 mb-6">
          <svg class="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="42" fill="none" stroke="#E5E7EB" stroke-width="8" />
            <circle
              cx="50" cy="50" r="42" fill="none" stroke="url(#modelProductGradient)"
              stroke-width="8" stroke-linecap="round"
              stroke-dasharray="180 264"
              class="animate-spin"
              style="transform-origin: center; animation-duration: 1.5s;"
            />
            <defs>
              <linearGradient id="modelProductGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#10B981" />
                <stop offset="100%" stop-color="#06B6D4" />
              </linearGradient>
            </defs>
          </svg>
          <div class="absolute inset-0 flex items-center justify-center">
            <Loader2 class="w-8 h-8 text-emerald-500 animate-spin" />
          </div>
        </div>
        <h3 class="text-lg font-semibold text-slate-700 mb-2">正在生成中...</h3>
        <p class="text-sm text-slate-400">{{ taskStatus?.progress || 'AI 正在生成模特使用商品的图片，请稍候' }}</p>
      </div>

      <!-- 钱包选择与消耗展示 -->
      <WalletCostPanel
        ref="walletCostRef"
        :feature-key="FEATURE_KEY"
      />

      <!-- 操作按钮组 -->
      <div v-if="!isProcessing" class="flex flex-wrap gap-3">
        <button
          @click="startGenerate"
          class="btn-primary flex items-center justify-center gap-2"
        >
          <ShoppingBag class="w-4 h-4" />
          生成图片
        </button>
        <button
          v-if="resultImage"
          @click="downloadResult"
          class="btn-secondary flex items-center gap-2"
        >
          <Download class="w-4 h-4" />
          下载结果
        </button>
        <button
          v-if="productImage || modelImage || resultImage"
          @click="resetAll"
          class="btn-secondary flex items-center gap-2"
        >
          <RefreshCw class="w-4 h-4" />
          更换图片
        </button>
      </div>

      <!-- 结果展示区 -->
      <div v-if="resultImage && !isProcessing" class="space-y-2">
        <div class="flex items-center gap-2 text-sm font-medium text-emerald-600">
          <ShoppingBag class="w-4 h-4" />
          生成结果
        </div>
        <div
          class="rounded-xl overflow-hidden bg-slate-50 border border-slate-200 min-h-[280px] flex items-center justify-center p-3 cursor-pointer group relative"
          @click="openPreview"
        >
          <img
            :src="resultImage"
            alt="生成结果"
            class="max-h-[420px] w-auto max-w-full object-contain rounded-lg group-hover:scale-[1.02] transition-transform duration-200"
          />
          <div class="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-all duration-200 flex items-center justify-center">
            <div class="opacity-0 group-hover:opacity-100 transition-opacity duration-200 text-white text-sm flex items-center gap-2 bg-black/50 px-3 py-1.5 rounded-full">
              <ZoomIn class="w-4 h-4" />
              点击放大预览
            </div>
          </div>
        </div>
      </div>

      <!-- 错误提示 -->
      <div
        v-if="errorMsg"
        class="flex items-start gap-2 p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm"
      >
        <AlertCircle class="w-4 h-4 flex-shrink-0 mt-0.5" />
        <div class="flex-1">
          <span>{{ errorMsg }}</span>
          <router-link
            v-if="insufficientBalance"
            to="/purchase"
            class="inline-flex items-center gap-1 ml-2 text-emerald-600 hover:text-emerald-700 font-medium underline"
          >
            去充值
          </router-link>
        </div>
      </div>
    </div>

    <!-- 预览模态框 -->
    <Teleport to="body">
      <div
        v-if="showPreview"
        class="fixed inset-0 bg-black/80 z-50 flex items-center justify-center"
        @click.self="closePreview"
        @wheel.prevent="onPreviewWheel"
        @mousemove="onPreviewMouseMove"
        @mouseup="onPreviewMouseUp"
        @mouseleave="onPreviewMouseUp"
      >
        <!-- 工具栏 -->
        <div class="absolute top-4 right-4 flex items-center gap-3 z-10">
          <span class="text-white/80 text-sm bg-white/10 px-3 py-1.5 rounded-full backdrop-blur-sm">
            {{ Math.round(previewScale * 100) }}%
          </span>
          <button
            @click="downloadResult"
            class="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
            title="下载"
          >
            <Download class="w-5 h-5" />
          </button>
          <button
            @click="closePreview"
            class="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
            title="关闭"
          >
            <X class="w-5 h-5" />
          </button>
        </div>

        <!-- 图片 -->
        <img
          :src="resultImage"
          alt="预览"
          :style="{
            transform: `translate(${previewPosition.x}px, ${previewPosition.y}px) scale(${previewScale})`,
            cursor: isDragging ? 'grabbing' : 'grab',
            maxWidth: '90vw',
            maxHeight: '90vh',
            transition: isDragging ? 'none' : 'transform 0.1s ease-out',
          }"
          class="object-contain select-none"
          @mousedown="onPreviewMouseDown"
          @dragstart.prevent
        />
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
</style>