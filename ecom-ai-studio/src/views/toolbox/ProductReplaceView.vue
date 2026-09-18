<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { Upload, Download, Replace, Loader2, RefreshCw, AlertCircle, ImageOff } from 'lucide-vue-next'
import { replaceProduct, getProductReplaceStatus } from '@/api/toolbox'
import { getErrorMessage } from '@/lib/error'
import type { ProductReplaceTaskStatus } from '@/api/toolbox'
import { useTaskSse, type TaskStatus } from '@/composables/useTaskSse'
import ToolCostBadge from '@/components/common/ToolCostBadge.vue'
import WalletCostPanel from '@/components/common/WalletCostPanel.vue'
import { useAuthStore } from '@/stores/auth'

const FEATURE_KEY = 'toolbox.product_replace'
const auth = useAuthStore()
const walletCostRef = ref<InstanceType<typeof WalletCostPanel> | null>(null)
const insufficientBalance = ref(false)

// ===== 状态 =====
const productImage = ref<string>('')       // 商品图
const referenceImage = ref<string>('')     // 参考图
const productFileName = ref<string>('')
const referenceFileName = ref<string>('')
const prompt = ref<string>('')             // 可选提示词
const resultImage = ref<string>('')        // 结果图
const isProcessing = ref(false)
const progressText = ref<string>('')
const errorMsg = ref<string>('')
const isProductDragOver = ref(false)
const isReferenceDragOver = ref(false)

// ===== 任务进度跟踪（SSE 实时订阅，GET 轮询作为降级通道） =====
/** 当前任务的单次消耗，供完成后同步本地余额 */
const taskCost = ref(0)
/** 当前替换任务的 Redis 任务 ID */
const replaceTaskId = ref('')
/** 与原轮询 maxPolls=150 × 2s 对齐的总超时 */
const TASK_TIMEOUT_MS = 5 * 60 * 1000
/** 连续 404 计数（降级轮询时沿用原"连续 3 次 404 提前终止"逻辑） */
let consecutive404 = 0
let timeoutTimer: ReturnType<typeof setTimeout> | null = null

/** GET 端点状态（progress 文案）→ 通用任务状态（step 文案）适配 */
function replaceStatusToTask(s: ProductReplaceTaskStatus): TaskStatus {
  return {
    status: s.status === 'completed' ? 'completed' : s.status === 'failed' ? 'failed' : 'running',
    step: s.progress || '',
    pct: 0,
    result: s.result ?? null,
    error: s.error ?? null,
  }
}

/** 降级轮询函数：复用既有 GET 请求，保持原有错误语义 */
async function pollReplaceStatus(taskId: string): Promise<TaskStatus> {
  try {
    const s: ProductReplaceTaskStatus = await getProductReplaceStatus(taskId)
    consecutive404 = 0
    return replaceStatusToTask(s)
  } catch (pollErr: any) {
    // 检测 404 致命错误：连续 3 次返回 404 则以失败终态终止
    if (pollErr?.code === 404 || pollErr?.message?.includes('不存在')) {
      consecutive404++
      if (consecutive404 >= 3) {
        return {
          status: 'failed',
          step: '',
          pct: 0,
          result: null,
          error: '替换任务不存在或已过期，请重新提交',
        }
      }
    }
    console.warn('[ProductReplace] 轮询失败:', pollErr)
    // 非致命错误：返回运行中状态，等待下一次轮询
    return { status: 'running', step: '', pct: 0, result: null, error: null }
  }
}

const replaceTask = useTaskSse({
  taskId: replaceTaskId,
  pollFn: pollReplaceStatus,
  onCompleted: handleReplaceCompleted,
  onFailed: handleReplaceFailed,
})

// SSE 推送的步骤文案 → 进度展示（与原轮询更新 progressText 的赋值逻辑一致）
watch(() => replaceTask.step, (step) => {
  if (step) progressText.value = step
})

function handleReplaceCompleted(result: any) {
  clearTaskTimeout()
  if (result?.image) {
    resultImage.value = result.image
    // 同步本地余额（后端已扣款；失败时忽略，后端为权威源）
    if (taskCost.value > 0) {
      try { auth.deductPoints(taskCost.value) } catch { /* ignore */ }
    }
  } else {
    errorMsg.value = '替换完成但结果为空，请重试'
  }
  isProcessing.value = false
}

function handleReplaceFailed(error: string) {
  clearTaskTimeout()
  errorMsg.value = error || '产品替换失败，请重试'
  isProcessing.value = false
}

function armTaskTimeout() {
  clearTaskTimeout()
  timeoutTimer = setTimeout(() => {
    if (!isProcessing.value) return
    replaceTask.stop()
    errorMsg.value = '替换处理超时，请稍后重试'
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

// ===== 工具函数 =====
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
    const base64 = await fileToBase64(file)
    productImage.value = base64
    productFileName.value = file.name
    resultImage.value = ''
  } catch {
    errorMsg.value = '图片读取失败，请重试'
  }
}

async function handleReferenceFile(file: File) {
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
    const base64 = await fileToBase64(file)
    referenceImage.value = base64
    referenceFileName.value = file.name
    resultImage.value = ''
  } catch {
    errorMsg.value = '图片读取失败，请重试'
  }
}

function onProductFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    handleProductFile(input.files[0])
  }
  // 重置 input value 以便重复选择同一文件
  input.value = ''
}

function onReferenceFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    handleReferenceFile(input.files[0])
  }
  input.value = ''
}

function onProductDrop(event: DragEvent) {
  isProductDragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleProductFile(file)
}

function onReferenceDrop(event: DragEvent) {
  isReferenceDragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleReferenceFile(file)
}

function onProductDragOver() {
  isProductDragOver.value = true
}

function onProductDragLeave() {
  isProductDragOver.value = false
}

function onReferenceDragOver() {
  isReferenceDragOver.value = true
}

function onReferenceDragLeave() {
  isReferenceDragOver.value = false
}

function resetAll() {
  productImage.value = ''
  referenceImage.value = ''
  productFileName.value = ''
  referenceFileName.value = ''
  prompt.value = ''
  resultImage.value = ''
  errorMsg.value = ''
}

// ===== 业务逻辑 =====
	async function startReplace() {
	  if (!productImage.value) {
	    errorMsg.value = '请上传商品图'
	    return
	  }
	  if (!referenceImage.value) {
	    errorMsg.value = '请上传参考图'
	    return
	  }
	  if (isProcessing.value) return

	  errorMsg.value = ''
	  insufficientBalance.value = false

	  // 余额校验
	  const cost = walletCostRef.value?.cost ?? 0
	  if (cost > 0 && auth.selectedWalletBalance < cost) {
	    errorMsg.value = `灵感币余额不足，预计消耗 ${cost}，当前余额 ${auth.selectedWalletBalance}，请先充值`
	    insufficientBalance.value = true
	    return
	  }

	  isProcessing.value = true
	  resultImage.value = ''
	  progressText.value = '正在提交替换任务...'

	  try {
	    const asyncResult = await replaceProduct({
	      product_image: productImage.value,
	      reference_image: referenceImage.value,
	      ...(prompt.value.trim() ? { prompt: prompt.value.trim() } : {}),
	    })

	    const taskId = asyncResult.task_id
	    if (!taskId || typeof taskId !== 'string' || taskId.trim() === '') {
	      console.error('[ProductReplace] 响应中未获取到有效 task_id，完整响应:', JSON.stringify(asyncResult).substring(0, 500))
	      errorMsg.value = '任务提交失败，未获取到有效的任务 ID，请重试'
	      isProcessing.value = false
	      return
	    }

	    // 订阅任务进度（SSE 优先，连续错误自动降级为 pollReplaceStatus 轮询）
	    taskCost.value = cost
	    consecutive404 = 0
	    progressText.value = '正在分析商品图与参考图...'
	    replaceTaskId.value = taskId
	    armTaskTimeout()
	    replaceTask.start()
	  } catch (err) {
	    clearTaskTimeout()
	    errorMsg.value = getErrorMessage(err, '产品替换失败')
	    isProcessing.value = false
	  }
	}

function downloadResult() {
  if (!resultImage.value) return
  const a = document.createElement('a')
  a.href = resultImage.value
  const baseName = productFileName.value ? productFileName.value.replace(/\.[^.]+$/, '') : 'image'
  a.download = `${baseName}-replaced-${Date.now()}.png`
  a.click()
}

const progressSteps = [
  { key: '分析', label: '分析商品图与参考图' },
  { key: '生成', label: 'AI 生成替换图片' },
  { key: '完成', label: '处理完成' },
]

const lastActiveStepKey = computed(() => {
  for (let i = progressSteps.length - 1; i >= 0; i--) {
    if (progressText.value.includes(progressSteps[i].key)) {
      return progressSteps[i].key
    }
  }
  return undefined
})
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <!-- 页面标题 -->
    <div>
      <h1 class="text-2xl font-display font-bold text-slate-900 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <Replace class="w-5 h-5 text-white" />
        </div>
        产品替换
        <ToolCostBadge :feature-key="FEATURE_KEY" />
      </h1>
      <p class="text-slate-500 mt-1 text-sm">上传商品图和参考图，AI 智能替换参考图中的商品</p>
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
            for="product-replace-upload"
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
              id="product-replace-upload"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              class="hidden"
              @change="onProductFileChange"
            />
          </label>
        </div>

        <!-- 参考图 -->
        <div class="space-y-2">
          <div class="flex items-center gap-2 text-sm font-medium text-slate-600">
            <ImageOff class="w-4 h-4 text-slate-400" />
            参考图 <span class="text-red-500">*</span>
          </div>
          <label
            for="reference-replace-upload"
            class="block cursor-pointer group"
            @drop.prevent="onReferenceDrop"
            @dragover.prevent="onReferenceDragOver"
            @dragleave.prevent="onReferenceDragLeave"
          >
            <!-- 已上传：缩略图预览 -->
            <div
              v-if="referenceImage"
              class="rounded-xl overflow-hidden bg-slate-50 border border-slate-200 min-h-[280px] flex items-center justify-center p-3 relative"
            >
              <img
                :src="referenceImage"
                alt="参考图"
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
                isReferenceDragOver
                  ? 'border-emerald-500 bg-emerald-50'
                  : 'border-emerald-300 bg-gradient-to-br from-emerald-50/50 to-teal-50/50 group-hover:border-emerald-500 group-hover:bg-emerald-50',
              ]"
            >
              <div class="w-16 h-16 rounded-2xl bg-white shadow-sm flex items-center justify-center mb-3">
                <Upload class="w-7 h-7 text-emerald-500" />
              </div>
              <h3 class="text-base font-semibold text-slate-700 mb-1">点击或拖拽上传参考图</h3>
              <p class="text-xs text-slate-400 text-center max-w-xs">支持 JPG、PNG、WebP，单张最大 20MB</p>
            </div>
            <input
              id="reference-replace-upload"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              class="hidden"
              @change="onReferenceFileChange"
            />
          </label>
        </div>
      </div>

      <!-- 提示词输入框（两图齐备时显示） -->
      <div v-if="productImage && referenceImage" class="space-y-2">
        <label class="flex items-center gap-2 text-sm font-medium text-slate-600">
          提示词 <span class="text-xs text-slate-400 font-normal">（选填）</span>
        </label>
        <textarea
          v-model="prompt"
          rows="3"
          placeholder="选填，描述替换要求，如：将商品放在木质桌面上，自然光"
          class="w-full px-4 py-3 rounded-xl border border-slate-200 bg-white/60 text-sm text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-400 resize-none transition-colors"
        ></textarea>
      </div>

      <!-- 处理中状态 -->
      <div
        v-if="isProcessing"
        class="flex flex-col items-center justify-center py-12"
      >
        <div class="relative w-20 h-20 mb-6">
          <svg class="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="42" fill="none" stroke="#E5E7EB" stroke-width="8" />
            <circle
              cx="50" cy="50" r="42" fill="none"
              stroke="url(#productReplaceProgressGradient)"
              stroke-width="8" stroke-linecap="round"
              stroke-dasharray="180 264"
              class="animate-spin"
              style="transform-origin: center; animation-duration: 1.5s;"
            />
            <defs>
              <linearGradient id="productReplaceProgressGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#10B981" />
                <stop offset="100%" stop-color="#06B6D4" />
              </linearGradient>
            </defs>
          </svg>
          <div class="absolute inset-0 flex items-center justify-center">
            <Loader2 class="w-7 h-7 text-emerald-500 animate-spin" />
          </div>
        </div>

        <!-- 进度步骤 -->
        <div class="w-full max-w-xs space-y-2 mb-4">
          <div
            v-for="step in progressSteps"
            :key="step.key"
            class="flex items-center gap-2 transition-all duration-300"
            :class="progressText.includes(step.key) ? 'opacity-100' : 'opacity-30'"
          >
            <div
              class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0"
              :class="progressText.includes(step.key) ? 'bg-emerald-500 text-white' : 'bg-slate-200 text-slate-400'"
            >
              <span v-if="progressText.includes(step.key) && step.key !== lastActiveStepKey">✓</span>
              <Loader2 v-else-if="progressText.includes(step.key) && step.key === lastActiveStepKey" class="w-3 h-3 animate-spin" />
              <span v-else>{{ progressSteps.indexOf(step) + 1 }}</span>
            </div>
            <span class="text-xs font-medium" :class="progressText.includes(step.key) ? 'text-slate-700' : 'text-slate-400'">
              {{ step.label }}
            </span>
          </div>
        </div>

        <p class="text-sm text-slate-500">{{ progressText }}</p>
      </div>

      <!-- 钱包选择与消耗展示 -->
      <WalletCostPanel
        ref="walletCostRef"
        :feature-key="FEATURE_KEY"
      />

      <!-- 操作按钮组 -->
      <div v-if="!isProcessing" class="flex flex-wrap gap-3">
        <button
          @click="startReplace"
          class="btn-primary flex items-center justify-center gap-2"
        >
          <Replace class="w-4 h-4" />
          开始替换
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
          v-if="productImage || referenceImage || resultImage"
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
          <Replace class="w-4 h-4" />
          替换结果
        </div>
        <div class="rounded-xl overflow-hidden bg-slate-50 border border-slate-200 min-h-[280px] flex items-center justify-center p-3">
          <img
            :src="resultImage"
            alt="替换结果"
            class="max-h-[420px] w-auto max-w-full object-contain rounded-lg"
          />
        </div>
      </div>

      <!-- 错误提示（内联） -->
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
  </div>
</template>

<style scoped>
</style>
