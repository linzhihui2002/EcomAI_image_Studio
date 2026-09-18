<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Type, Download, Loader2, Sparkles, AlertCircle, ImageIcon, RefreshCw, SlidersHorizontal } from 'lucide-vue-next'
import { textToImage } from '@/api/toolbox'
import { getErrorMessage } from '@/lib/error'
import { validateAndCorrectSize, SIZE_LIMITS } from '@/lib/utils'
import ToolCostBadge from '@/components/common/ToolCostBadge.vue'
import WalletCostPanel from '@/components/common/WalletCostPanel.vue'
import { useAuthStore } from '@/stores/auth'

const FEATURE_KEY = 'toolbox.text_to_image'
const auth = useAuthStore()
const walletCostRef = ref<InstanceType<typeof WalletCostPanel> | null>(null)
const insufficientBalance = ref(false)

// ===== 类型与常量 =====
interface SizeOption {
  value: string
  label: string
  desc: string
}

const SIZE_OPTIONS: SizeOption[] = [
  { value: '1024x1024', label: '1024 × 1024', desc: '正方形' },
  { value: '1536x1024', label: '1536 × 1024', desc: '横图' },
  { value: '1024x1536', label: '1024 × 1536', desc: '竖图' },
  { value: '2048x2048', label: '2048 × 2048', desc: '2K 正方形' },
  { value: 'custom', label: '自定义', desc: '自由输入宽高' },
]

interface QualityOption {
  value: string
  label: string
  desc: string
}

const QUALITY_OPTIONS: QualityOption[] = [
  { value: 'auto', label: '自动', desc: '由模型自动选择' },
  { value: 'low', label: '低', desc: '生成速度快' },
  { value: 'medium', label: '中', desc: '均衡速度与质量' },
  { value: 'high', label: '高', desc: '最佳画质' },
]

// ===== 状态 =====
const prompt = ref<string>('')
const selectedSize = ref<string>('1024x1024')
const selectedQuality = ref<string>('auto')
const customWidth = ref<string>('')
const customHeight = ref<string>('')
const resultImage = ref<string>('')
const isProcessing = ref(false)
const errorMsg = ref<string>('')
const promptError = ref<string>('')
const sizeWarning = ref<string>('')

// ===== 计算属性 =====
const hasResult = computed(() => !!resultImage.value)
const currentSize = computed(() => SIZE_OPTIONS.find(s => s.value === selectedSize.value))
const isCustom = computed(() => selectedSize.value === 'custom')

const customSizeResult = computed(() => {
  if (!isCustom.value) return null
  if (!customWidth.value || !customHeight.value) return null
  const w = parseInt(customWidth.value, 10)
  const h = parseInt(customHeight.value, 10)
  if (!w || !h || w <= 0 || h <= 0) return null
  return validateAndCorrectSize(w, h)
})

const effectiveSize = computed(() => {
  if (isCustom.value && customSizeResult.value) {
    const r = customSizeResult.value
    return `${r.width}x${r.height}`
  }
  return selectedSize.value
})

// ===== 自定义尺寸校验 =====
watch([customWidth, customHeight], ([w, h]) => {
  if (!isCustom.value) return
  if (!w || !h) {
    sizeWarning.value = ''
    return
  }
  const result = customSizeResult.value
  if (result?.corrected) {
    sizeWarning.value = result.reason || '输入值已自动调整以符合规则'
  } else {
    sizeWarning.value = ''
  }
})

watch(selectedSize, () => {
  sizeWarning.value = ''
})

// ===== 业务逻辑 =====
function validatePrompt(): boolean {
  if (!prompt.value.trim()) {
    promptError.value = '请输入图片描述'
    return false
  }
  promptError.value = ''
  return true
}

function onPromptInput() {
  if (promptError.value && prompt.value.trim()) {
    promptError.value = ''
  }
}

async function startGenerate() {
  if (isProcessing.value) return
  errorMsg.value = ''
  insufficientBalance.value = false
  if (!validatePrompt()) return

  // 余额校验
	const cost = walletCostRef.value?.cost ?? 0
	if (cost > 0 && auth.selectedWalletBalance < cost) {
    errorMsg.value = `灵感币余额不足，预计消耗 ${cost}，当前余额 ${auth.selectedWalletBalance}，请先充值`
    insufficientBalance.value = true
    return
  }

  isProcessing.value = true
  resultImage.value = ''
  try {
    const res = await textToImage({
      prompt: prompt.value.trim(),
      size: effectiveSize.value,
      quality: selectedQuality.value,
    })
    resultImage.value = res.image

    // 同步本地余额（后端已扣款；失败时忽略，后端为权威源）
    if (cost > 0) {
      try { auth.deductPoints(cost) } catch { /* ignore */ }
    }
  } catch (err) {
    errorMsg.value = getErrorMessage(err, '生成失败')
  } finally {
    isProcessing.value = false
  }
}

function downloadResult() {
  if (!resultImage.value) return
  const a = document.createElement('a')
  a.href = resultImage.value
  a.download = `text-to-image-${Date.now()}.png`
  a.click()
}

function resetAll() {
  prompt.value = ''
  selectedSize.value = '1024x1024'
  selectedQuality.value = 'auto'
  customWidth.value = ''
  customHeight.value = ''
  resultImage.value = ''
  errorMsg.value = ''
  promptError.value = ''
  sizeWarning.value = ''
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <!-- 页面标题 -->
    <div>
      <h1 class="text-2xl font-display font-bold text-slate-900 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <Sparkles class="w-5 h-5 text-white" />
        </div>
        文生图
        <ToolCostBadge :feature-key="FEATURE_KEY" />
      </h1>
      <p class="text-slate-500 mt-1 text-sm">输入文字描述，AI 自动生成高质量商品图，支持多种尺寸输出</p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-6">
      <!-- 左侧：参数面板 -->
      <div class="glass-card p-5 space-y-5 h-fit">
        <!-- 提示词输入 -->
        <div class="space-y-2">
          <label class="text-sm font-medium text-slate-700 flex items-center gap-1.5">
            <Type class="w-4 h-4 text-emerald-500" />
            图片描述
            <span class="text-red-500 text-xs">*</span>
          </label>
          <textarea
            v-model="prompt"
            @input="onPromptInput"
            rows="6"
            placeholder="例如：一只白色运动鞋放在浅灰色背景上，柔和的影棚光，高细节，商业摄影风格"
            :class="[
              'w-full px-3 py-2.5 text-sm rounded-xl border bg-white/80 backdrop-blur-xl resize-y transition-all duration-200 focus:outline-none focus:ring-2',
              promptError
                ? 'border-red-300 focus:ring-red-500/20 focus:border-red-500/50'
                : 'border-slate-200 focus:ring-emerald-500/20 focus:border-emerald-500/50',
            ]"
          />
          <p v-if="promptError" class="text-xs text-red-500 flex items-center gap-1">
            <AlertCircle class="w-3.5 h-3.5" />
            {{ promptError }}
          </p>
          <p v-else class="text-[11px] text-slate-400">详细描述画面内容、风格、光线，可获得更精准的结果</p>
        </div>

        <!-- 尺寸选择 -->
        <div class="space-y-2">
          <label class="text-sm font-medium text-slate-700 flex items-center gap-1.5">
            <ImageIcon class="w-4 h-4 text-emerald-500" />
            输出尺寸
          </label>
          <div class="space-y-2">
            <label
              v-for="opt in SIZE_OPTIONS"
              :key="opt.value"
              :class="[
                'flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-all',
                selectedSize === opt.value
                  ? 'border-emerald-300 bg-emerald-50'
                  : 'border-slate-200 bg-white hover:border-slate-300',
              ]"
            >
              <input
                type="radio"
                :value="opt.value"
                v-model="selectedSize"
                class="text-emerald-500 focus:ring-emerald-500"
              />
              <div class="flex-1">
                <p
                  :class="[
                    'text-sm font-medium',
                    selectedSize === opt.value ? 'text-emerald-700' : 'text-slate-700',
                  ]"
                >
                  {{ opt.label }}
                </p>
                <p class="text-[11px] text-slate-400">{{ opt.desc }}</p>
              </div>
            </label>
          </div>

          <!-- 自定义尺寸输入 -->
          <Transition name="fade">
            <div v-if="isCustom" class="mt-2 space-y-2 animate-fade-in">
              <div class="flex items-center gap-2">
                <input
                  v-model="customWidth"
                  type="number"
                  min="16"
                  max="3840"
                  step="16"
                  placeholder="宽"
                  class="flex-1 px-3 py-2.5 text-sm text-center rounded-xl border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500/50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                />
                <span class="text-slate-400 font-medium text-sm select-none">×</span>
                <input
                  v-model="customHeight"
                  type="number"
                  min="16"
                  max="3840"
                  step="16"
                  placeholder="高"
                  class="flex-1 px-3 py-2.5 text-sm text-center rounded-xl border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500/50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                />
              </div>
              <p class="text-[10px] text-slate-400">宽 × 高，需为 16 的倍数，最大不超过 3840</p>

              <!-- 有效尺寸预览 & 校验提示 -->
              <div
                v-if="customSizeResult"
                class="rounded-lg p-2.5 space-y-1.5"
                :class="sizeWarning ? 'bg-amber-50 border border-amber-200' : 'bg-slate-50 border border-slate-100'"
              >
                <div class="flex items-center justify-between">
                  <span class="text-[10px] text-slate-500">有效输出尺寸</span>
                  <span class="text-xs font-semibold tabular-nums" :class="sizeWarning ? 'text-amber-600' : 'text-slate-800'">
                    {{ customSizeResult.width }} × {{ customSizeResult.height }}
                  </span>
                </div>
                <div class="flex items-center gap-2 text-[10px]" :class="sizeWarning ? 'text-amber-600' : 'text-slate-400'">
                  <AlertCircle v-if="sizeWarning" class="w-3 h-3 flex-shrink-0" />
                  <span>{{ sizeWarning || `${(customSizeResult.width * customSizeResult.height / 10000).toFixed(1)} 万像素 · 符合约束规则` }}</span>
                </div>
              </div>
            </div>
          </Transition>
        </div>

        <!-- 画质选择 -->
        <div class="space-y-2">
          <label class="text-sm font-medium text-slate-700 flex items-center gap-1.5">
            <SlidersHorizontal class="w-4 h-4 text-emerald-500" />
            画质
          </label>
          <div class="space-y-2">
            <label
              v-for="opt in QUALITY_OPTIONS"
              :key="opt.value"
              :class="[
                'flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-all',
                selectedQuality === opt.value
                  ? 'border-emerald-300 bg-emerald-50'
                  : 'border-slate-200 bg-white hover:border-slate-300',
              ]"
            >
              <input
                type="radio"
                :value="opt.value"
                v-model="selectedQuality"
                class="text-emerald-500 focus:ring-emerald-500"
              />
              <div class="flex-1">
                <p
                  :class="[
                    'text-sm font-medium',
                    selectedQuality === opt.value ? 'text-emerald-700' : 'text-slate-700',
                  ]"
                >
                  {{ opt.label }}
                </p>
                <p class="text-[11px] text-slate-400">{{ opt.desc }}</p>
              </div>
            </label>
          </div>
        </div>

        <!-- 钱包选择与消耗展示 -->
        <WalletCostPanel
          ref="walletCostRef"
          :feature-key="FEATURE_KEY"
        />

        <!-- 生成按钮 -->
        <button
          @click="startGenerate"
          :disabled="isProcessing"
          class="btn-primary w-full flex items-center justify-center gap-2"
        >
          <Loader2 v-if="isProcessing" class="w-4 h-4 animate-spin" />
          <Sparkles v-else class="w-4 h-4" />
          {{ isProcessing ? '生成中...' : '生成图片' }}
        </button>

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

      <!-- 右侧：结果展示 -->
      <div class="glass-card p-6 min-h-[520px] flex flex-col">
        <!-- 空状态 -->
        <div v-if="!hasResult && !isProcessing" class="flex-1 flex flex-col items-center justify-center py-16">
          <div class="w-24 h-24 rounded-3xl bg-gradient-to-br from-emerald-50 to-teal-50 border-2 border-dashed border-emerald-200 flex items-center justify-center mb-4">
            <Sparkles class="w-10 h-10 text-emerald-400" />
          </div>
          <h3 class="text-lg font-semibold text-slate-700 mb-2">输入描述后生成图片</h3>
          <p class="text-sm text-slate-400 text-center max-w-sm">
            在左侧填写图片描述并选择尺寸，点击「生成图片」按钮即可
          </p>
        </div>

        <!-- 生成中状态 -->
        <div v-else-if="isProcessing" class="flex-1 flex flex-col items-center justify-center py-16">
          <div class="relative w-24 h-24 mb-6">
            <svg class="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="#E5E7EB" stroke-width="8" />
              <circle
                cx="50" cy="50" r="42" fill="none" stroke="url(#textToImageGradient)"
                stroke-width="8" stroke-linecap="round"
                stroke-dasharray="180 264"
                class="animate-spin"
                style="transform-origin: center; animation-duration: 1.5s;"
              />
              <defs>
                <linearGradient id="textToImageGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stop-color="#10B981" />
                  <stop offset="100%" stop-color="#06B6D4" />
                </linearGradient>
              </defs>
            </svg>
            <div class="absolute inset-0 flex items-center justify-center">
              <Loader2 class="w-8 h-8 text-emerald-500 animate-spin" />
            </div>
          </div>
          <h3 class="text-lg font-semibold text-slate-700 mb-2">正在生成图片...</h3>
          <p class="text-sm text-slate-400">AI 正在根据您的描述创作图片，请稍候</p>
        </div>

        <!-- 结果展示 -->
        <div v-else class="flex-1 flex flex-col space-y-4">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 text-sm font-medium text-emerald-600">
              <ImageIcon class="w-4 h-4" />
              生成结果
              <span class="text-[10px] text-emerald-500 bg-emerald-50 px-1.5 py-0.5 rounded">
                {{ effectiveSize }}
              </span>
            </div>
            <button
              @click="resetAll"
              class="text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1 transition-colors"
            >
              <RefreshCw class="w-3.5 h-3.5" />
              重新生成
            </button>
          </div>

          <div
            class="flex-1 rounded-xl overflow-hidden bg-slate-50 border border-slate-200 min-h-[360px] flex items-center justify-center p-4"
          >
            <img
              v-if="resultImage"
              :src="resultImage"
              alt="生成结果"
              class="max-h-[480px] w-auto max-w-full object-contain rounded-lg shadow-lg"
            />
          </div>

          <!-- 描述回显 -->
          <div v-if="prompt" class="p-3 rounded-xl bg-slate-50 border border-slate-200">
            <p class="text-[11px] text-slate-400 mb-1">提示词</p>
            <p class="text-sm text-slate-600 line-clamp-3">{{ prompt }}</p>
          </div>

          <!-- 下载按钮 -->
          <div class="flex justify-end">
            <button
              @click="downloadResult"
              class="btn-secondary flex items-center gap-2"
            >
              <Download class="w-4 h-4" />
              下载图片
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>
