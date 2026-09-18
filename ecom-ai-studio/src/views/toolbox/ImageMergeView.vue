<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { Upload, X, Download, Layers, Loader2, Image as ImageIcon, AlertCircle, CheckCircle, AlertTriangle } from 'lucide-vue-next'
import { mergeImages, getMergeStatus } from '@/api/toolbox'
import { getErrorMessage } from '@/lib/error'
import type { MergeTaskStatus } from '@/api/toolbox'
import { useTaskSse, type TaskStatus } from '@/composables/useTaskSse'
import ToolCostBadge from '@/components/common/ToolCostBadge.vue'
import WalletCostPanel from '@/components/common/WalletCostPanel.vue'
import { useAuthStore } from '@/stores/auth'

const FEATURE_KEY = 'toolbox.image_merge'
const auth = useAuthStore()
const walletCostRef = ref<InstanceType<typeof WalletCostPanel> | null>(null)
const insufficientBalance = ref(false)

interface UploadedImage {
  id: string
  name: string
  dataUrl: string
}

const images = ref<UploadedImage[]>([])
const resultImage = ref<string>('')
const verificationResult = ref<{ passed: boolean; issues: string[] } | null>(null)
const isProcessing = ref(false)
const progressText = ref<string>('')
const errorMsg = ref<string>('')
const validationMsg = ref<string>('')

// ===== 任务进度跟踪（SSE 实时订阅，GET 轮询作为降级通道） =====
/** 当前任务的单次消耗，供完成后同步本地余额 */
const taskCost = ref(0)
/** 当前合并任务的 Redis 任务 ID */
const mergeTaskId = ref('')
/** 与原轮询 maxPolls=150 × 2s 对齐的总超时 */
const TASK_TIMEOUT_MS = 5 * 60 * 1000
/** 连续 404 计数（降级轮询时沿用原"连续 3 次 404 提前终止"逻辑） */
let consecutive404 = 0
let timeoutTimer: ReturnType<typeof setTimeout> | null = null

/** GET 端点状态（progress 文案）→ 通用任务状态（step 文案）适配 */
function mergeStatusToTask(s: MergeTaskStatus): TaskStatus {
  return {
    status: s.status === 'completed' ? 'completed' : s.status === 'failed' ? 'failed' : 'running',
    step: s.progress || '',
    pct: 0,
    result: s.result ?? null,
    error: s.error ?? null,
  }
}

/** 降级轮询函数：复用既有 GET 请求，保持原有错误语义 */
async function pollMergeStatus(taskId: string): Promise<TaskStatus> {
  try {
    const s: MergeTaskStatus = await getMergeStatus(taskId)
    consecutive404 = 0 // 成功获取，重置计数
    return mergeStatusToTask(s)
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
          error: '合并任务不存在或已过期，请重新提交',
        }
      }
    }
    console.warn('[ImageMerge] 轮询失败:', pollErr)
    // 非致命错误：返回运行中状态，等待下一次轮询
    return { status: 'running', step: '', pct: 0, result: null, error: null }
  }
}

const mergeTask = useTaskSse({
  taskId: mergeTaskId,
  pollFn: pollMergeStatus,
  onCompleted: handleMergeCompleted,
  onFailed: handleMergeFailed,
})

// SSE 推送的步骤文案 → 进度展示（与原轮询更新 progressText 的赋值逻辑一致）
watch(() => mergeTask.step, (step) => {
  if (step) progressText.value = step
})

function handleMergeCompleted(result: any) {
  clearTaskTimeout()
  if (result?.image) {
    resultImage.value = result.image
    verificationResult.value = result.verification ?? null
    // 同步本地余额（后端已扣款；失败时忽略，后端为权威源）
    if (taskCost.value > 0) {
      try { auth.deductPoints(taskCost.value) } catch { /* ignore */ }
    }
  } else {
    errorMsg.value = '合并完成但结果为空，请重试'
  }
  isProcessing.value = false
}

function handleMergeFailed(error: string) {
  clearTaskTimeout()
  errorMsg.value = error || '合并失败，请重试'
  isProcessing.value = false
}

function armTaskTimeout() {
  clearTaskTimeout()
  timeoutTimer = setTimeout(() => {
    if (!isProcessing.value) return
    mergeTask.stop()
    errorMsg.value = '合并处理超时，请稍后重试'
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

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function handleImageUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  errorMsg.value = ''
  validationMsg.value = ''

  const remaining = 10 - images.value.length
  if (remaining <= 0) {
    validationMsg.value = '请上传 2-10 张图片进行合并'
    input.value = ''
    return
  }

  const filesToProcess = Array.from(input.files).slice(0, remaining)

  for (const file of filesToProcess) {
    if (!file.type.startsWith('image/')) continue
    try {
      const dataUrl = await fileToBase64(file)
      images.value.push({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
        name: file.name,
        dataUrl,
      })
    } catch {
      errorMsg.value = `图片 ${file.name} 读取失败`
    }
  }

  input.value = ''

  if (images.value.length < 2 || images.value.length > 10) {
    validationMsg.value = '请上传 2-10 张图片进行合并'
  } else {
    validationMsg.value = ''
  }

  resultImage.value = ''
  verificationResult.value = null
}

function removeImage(id: string) {
  images.value = images.value.filter(img => img.id !== id)
  resultImage.value = ''
  verificationResult.value = null
  if (images.value.length < 2 || images.value.length > 10) {
    validationMsg.value = '请上传 2-10 张图片进行合并'
  } else {
    validationMsg.value = ''
  }
}

function clearAll() {
  images.value = []
  resultImage.value = ''
  verificationResult.value = null
  validationMsg.value = ''
  errorMsg.value = ''
}

async function startMerge() {
  errorMsg.value = ''
  validationMsg.value = ''
  insufficientBalance.value = false

  if (images.value.length < 2 || images.value.length > 10) {
    validationMsg.value = '请上传 2-10 张图片进行合并'
    return
  }

  // 余额校验
	const cost = walletCostRef.value?.cost ?? 0
	if (cost > 0 && auth.selectedWalletBalance < cost) {
    errorMsg.value = `灵感币余额不足，预计消耗 ${cost}，当前余额 ${auth.selectedWalletBalance}，请先充值`
    insufficientBalance.value = true
    return
  }

  isProcessing.value = true
  resultImage.value = ''
  verificationResult.value = null
  progressText.value = '正在提交合并任务...'

  try {
    // 提交异步任务
    const asyncResult = await mergeImages({
      images: images.value.map(img => img.dataUrl),
    })

    const taskId = asyncResult.task_id
    if (!taskId || typeof taskId !== 'string' || taskId.trim() === '') {
      console.error('[ImageMerge] 响应中未获取到有效 task_id，完整响应:', JSON.stringify(asyncResult).substring(0, 500))
      errorMsg.value = '任务提交失败，未获取到有效的任务 ID，请重试'
      isProcessing.value = false
      return
    }

    // 订阅任务进度（SSE 优先，连续错误自动降级为 pollMergeStatus 轮询）
    taskCost.value = cost
    consecutive404 = 0
    progressText.value = '正在分析产品特征...'
    mergeTaskId.value = taskId
    armTaskTimeout()
    mergeTask.start()
  } catch (err) {
    clearTaskTimeout()
    errorMsg.value = getErrorMessage(err, '合并失败')
    isProcessing.value = false
  }
}

function downloadResult() {
  if (!resultImage.value) return
  const a = document.createElement('a')
  a.href = resultImage.value
  a.download = `merged-${Date.now()}.png`
  a.click()
}

const progressSteps: { key: string; label: string }[] = [
  { key: '分析', label: '分析产品特征' },
  { key: '生成', label: 'AI 生成合并图片' },
  { key: '校验', label: '校验产品一致性' },
  { key: '完成', label: '处理完成' },
]
function findLastProgressKey(): string | undefined {
  for (let i = progressSteps.length - 1; i >= 0; i--) {
    const s = progressSteps[i]
    if (progressText.value.includes(s.key)) return s.key
  }
  return undefined
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <!-- 页面标题 -->
    <div>
      <h1 class="text-2xl font-display font-bold text-slate-900 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <Layers class="w-5 h-5 text-white" />
        </div>
        图片合并
        <ToolCostBadge :feature-key="FEATURE_KEY" />
      </h1>
      <p class="text-slate-500 mt-1 text-sm">上传 2-10 张产品图，AI 智能合并为一张综合展示图，严格保证产品细节一致</p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- 左侧：上传与配置 -->
      <div class="glass-card p-6 space-y-5">
        <!-- 上传区 -->
        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
              <ImageIcon class="w-4 h-4 text-emerald-500" />
              上传图片
              <span class="text-xs font-normal text-slate-400">（{{ images.length }}/10）</span>
            </h3>
            <button
              v-if="images.length > 0"
              @click="clearAll"
              class="text-xs text-slate-400 hover:text-red-500 transition-colors"
            >
              清空全部
            </button>
          </div>

          <!-- 上传按钮 -->
          <label
            v-if="images.length < 10"
            class="block cursor-pointer group"
          >
            <div class="border-2 border-dashed border-emerald-300 rounded-xl py-8 px-4 flex flex-col items-center justify-center bg-emerald-50/40 hover:bg-emerald-50 hover:border-emerald-500 transition-all">
              <Upload class="w-8 h-8 text-emerald-400 group-hover:text-emerald-500 mb-2" />
              <p class="text-sm font-medium text-emerald-600">点击上传图片</p>
              <p class="text-xs text-slate-400 mt-1">支持 JPG / PNG / WebP，最多 10 张</p>
            </div>
            <input
              type="file"
              accept="image/*"
              multiple
              class="hidden"
              @change="handleImageUpload"
            />
          </label>

          <!-- 缩略图列表 -->
          <div v-if="images.length > 0" class="grid grid-cols-3 gap-2 mt-3">
            <div
              v-for="(img, idx) in images"
              :key="img.id"
              class="relative group aspect-square rounded-lg overflow-hidden border border-slate-200 bg-slate-50"
            >
              <img :src="img.dataUrl" :alt="img.name" class="w-full h-full object-cover" />
              <div class="absolute top-1 left-1 w-5 h-5 rounded-full bg-emerald-500 text-white text-[10px] font-bold flex items-center justify-center">
                {{ idx + 1 }}
              </div>
              <button
                @click="removeImage(img.id)"
                class="absolute top-1 right-1 w-5 h-5 rounded-full bg-white/90 text-slate-500 hover:bg-red-500 hover:text-white flex items-center justify-center transition-colors shadow-sm"
                title="删除"
              >
                <X class="w-3 h-3" />
              </button>
              <div class="absolute bottom-0 inset-x-0 bg-black/40 text-white text-[10px] px-1 py-0.5 truncate">
                {{ img.name }}
              </div>
            </div>
          </div>

          <!-- 数量校验提示 -->
          <p v-if="validationMsg" class="mt-3 text-xs text-amber-600 flex items-center gap-1.5">
            <AlertCircle class="w-3.5 h-3.5" />
            {{ validationMsg }}
          </p>
        </div>

        <!-- 钱包选择与消耗展示 -->
        <WalletCostPanel
          ref="walletCostRef"
          :feature-key="FEATURE_KEY"
        />

        <!-- 操作按钮 -->
        <div class="flex gap-3 pt-2">
          <button
            @click="startMerge"
            :disabled="isProcessing"
            class="btn-primary flex-1 py-2.5 flex items-center justify-center gap-2"
          >
            <Loader2 v-if="isProcessing" class="w-4 h-4 animate-spin" />
            <Layers v-else class="w-4 h-4" />
            {{ isProcessing ? '合并中...' : '开始合并' }}
          </button>
          <button
            v-if="resultImage && !isProcessing"
            @click="downloadResult"
            class="btn-secondary px-5 py-2.5 flex items-center gap-2"
          >
            <Download class="w-4 h-4" />
            下载
          </button>
        </div>

        <!-- 错误提示 -->
        <p v-if="errorMsg" class="text-sm text-red-500 flex items-center gap-1.5">
          <AlertCircle class="w-4 h-4" />
          <span>{{ errorMsg }}</span>
          <router-link
            v-if="insufficientBalance"
            to="/purchase"
            class="inline-flex items-center gap-1 ml-2 text-emerald-600 hover:text-emerald-700 font-medium underline"
          >
            去充值
          </router-link>
        </p>
      </div>

      <!-- 右侧：结果展示 -->
      <div class="glass-card p-6">
        <h3 class="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
          <ImageIcon class="w-4 h-4 text-emerald-500" />
          合并结果
        </h3>

        <!-- 空状态 -->
        <div
          v-if="!isProcessing && !resultImage"
          class="flex flex-col items-center justify-center py-16 text-center"
        >
          <div class="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mb-3">
            <Layers class="w-8 h-8 text-slate-300" />
          </div>
          <p class="text-sm text-slate-400">上传图片并点击"开始合并"后，结果将在此显示</p>
          <p class="text-xs text-slate-300 mt-1">AI 将智能分析产品特征并生成综合展示图</p>
        </div>

        <!-- 处理中 -->
        <div
          v-else-if="isProcessing"
          class="flex flex-col items-center justify-center py-12"
        >
          <div class="relative w-20 h-20 mb-6">
            <svg class="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="#E5E7EB" stroke-width="8" />
              <circle
                cx="50" cy="50" r="42" fill="none"
                stroke="url(#mergeGradient)"
                stroke-width="8" stroke-linecap="round"
                stroke-dasharray="180 264"
                class="animate-spin"
                style="transform-origin: center; animation-duration: 1.5s;"
              />
              <defs>
                <linearGradient id="mergeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
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
                <CheckCircle v-if="progressText.includes(step.key) && step.key !== progressSteps.find(s => progressText.includes(s.key))?.key" class="w-3 h-3" />
                <Loader2 v-else-if="progressText.includes(step.key) && step.key === findLastProgressKey()" class="w-3 h-3 animate-spin" />
                <span v-else>{{ progressSteps.indexOf(step) + 1 }}</span>
              </div>
              <span class="text-xs font-medium" :class="progressText.includes(step.key) ? 'text-slate-700' : 'text-slate-400'">
                {{ step.label }}
              </span>
            </div>
          </div>

          <p class="text-sm text-slate-500">{{ progressText }}</p>
        </div>

        <!-- 结果展示 -->
        <div v-else class="space-y-4">
          <!-- 一致性校验结果 -->
          <div
            v-if="verificationResult"
            class="flex items-start gap-2 p-3 rounded-lg text-sm"
            :class="verificationResult.passed ? 'bg-emerald-50 border border-emerald-200' : 'bg-amber-50 border border-amber-200'"
          >
            <CheckCircle v-if="verificationResult.passed" class="w-4 h-4 text-emerald-500 flex-shrink-0 mt-0.5" />
            <AlertTriangle v-else class="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
            <div>
              <p class="font-semibold" :class="verificationResult.passed ? 'text-emerald-700' : 'text-amber-700'">
                {{ verificationResult.passed ? '产品特征一致性校验通过' : '产品特征一致性校验 - 存在偏差' }}
              </p>
              <ul v-if="!verificationResult.passed && verificationResult.issues.length > 0" class="mt-1 space-y-0.5">
                <li v-for="(issue, idx) in verificationResult.issues" :key="idx" class="text-amber-600 text-xs">
                  {{ issue }}
                </li>
              </ul>
            </div>
          </div>

          <!-- 合并图片 -->
          <div class="relative bg-[repeating-conic-gradient(#f1f5f9_0%_25%,#fff_0%_50%)] bg-[length:20px_20px] rounded-xl overflow-hidden flex items-center justify-center p-4">
            <img
              :src="resultImage"
              alt="合并结果"
              class="max-w-full max-h-[480px] rounded-lg shadow-lg object-contain"
            />
          </div>
          <div class="flex justify-end">
            <button
              @click="downloadResult"
              class="btn-primary px-5 py-2 flex items-center gap-2 text-sm"
            >
              <Download class="w-4 h-4" />
              下载合并图
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>