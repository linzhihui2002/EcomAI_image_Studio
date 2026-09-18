<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Upload,
  ScanText,
  Loader2,
  RefreshCw,
  AlertCircle,
  ImageOff,
  Copy,
  Check,
} from 'lucide-vue-next'
import { reversePrompt } from '@/api/toolbox'
import { getErrorMessage } from '@/lib/error'
import ToolCostBadge from '@/components/common/ToolCostBadge.vue'
import WalletCostPanel from '@/components/common/WalletCostPanel.vue'
import { useAuthStore } from '@/stores/auth'

const FEATURE_KEY = 'toolbox.prompt_reverse'
const auth = useAuthStore()
const walletCostRef = ref<InstanceType<typeof WalletCostPanel> | null>(null)
const insufficientBalance = ref(false)

// ===== 状态 =====
const originalImage = ref<string>('')      // 上传的图片 base64 data URL
const fileName = ref<string>('')
const promptCn = ref<string>('')       // 反推结果 - 中文
const promptEn = ref<string>('')       // 反推结果 - 英文
const isProcessing = ref(false)
const errorMsg = ref<string>('')
const isDragOver = ref(false)
const isCopiedCn = ref(false)          // 中文复制状态
const isCopiedEn = ref(false)          // 英文复制状态

// ===== 计算属性 =====
const hasResult = computed(() => !!promptCn.value || !!promptEn.value)

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

async function handleFile(file: File) {
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
    originalImage.value = base64
    fileName.value = file.name
    // 切换图片后清空旧结果
    promptCn.value = ''
    promptEn.value = ''
  } catch {
    errorMsg.value = '图片读取失败，请重试'
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    handleFile(input.files[0])
  }
  // 重置 input value 以便重复选择同一文件
  input.value = ''
}

function onDrop(event: DragEvent) {
  isDragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleFile(file)
}

function onDragOver() {
  isDragOver.value = true
}

function onDragLeave() {
  isDragOver.value = false
}

function resetAll() {
  originalImage.value = ''
  fileName.value = ''
  promptCn.value = ''
  promptEn.value = ''
  errorMsg.value = ''
  isCopiedCn.value = false
  isCopiedEn.value = false
}

// ===== 业务逻辑 =====
async function startReverse() {
  if (isProcessing.value) return
  errorMsg.value = ''
  insufficientBalance.value = false
  if (!originalImage.value) {
    errorMsg.value = '请上传图片'
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
  promptCn.value = ''
  promptEn.value = ''
  try {
    const res = await reversePrompt({ image: originalImage.value })
    promptCn.value = res.prompt_cn
    promptEn.value = res.prompt_en

    // 同步本地余额（后端已扣款；失败时忽略，后端为权威源）
    if (cost > 0) {
      try { auth.deductPoints(cost) } catch { /* ignore */ }
    }
  } catch (err) {
    errorMsg.value = getErrorMessage(err, '反推提示词失败')
  } finally {
    isProcessing.value = false
  }
}

async function copyPromptCn() {
  if (!promptCn.value) return
  try {
    await navigator.clipboard.writeText(promptCn.value)
    isCopiedCn.value = true
    setTimeout(() => {
      isCopiedCn.value = false
    }, 2000)
  } catch {
    errorMsg.value = '复制失败，请手动选择文本复制'
  }
}

async function copyPromptEn() {
  if (!promptEn.value) return
  try {
    await navigator.clipboard.writeText(promptEn.value)
    isCopiedEn.value = true
    setTimeout(() => {
      isCopiedEn.value = false
    }, 2000)
  } catch {
    errorMsg.value = '复制失败，请手动选择文本复制'
  }
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <!-- 页面标题 -->
    <div>
      <h1 class="text-2xl font-display font-bold text-slate-900 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <ScanText class="w-5 h-5 text-white" />
        </div>
        反推提示词
        <ToolCostBadge :feature-key="FEATURE_KEY" />
      </h1>
      <p class="text-slate-500 mt-1 text-sm">上传图片，AI 自动反推图片的提示词，便于复用于文生图</p>
    </div>

    <!-- 主容器 -->
    <div class="glass-card p-6 space-y-5">
      <!-- 图片上传区 / 缩略图预览 -->
      <div v-if="!originalImage && !isProcessing" class="space-y-2">
        <label class="text-sm font-medium text-slate-700 flex items-center gap-1.5">
          <ImageOff class="w-4 h-4 text-emerald-500" />
          图片
          <span class="text-red-500 text-xs">*</span>
        </label>
        <label
          for="prompt-reverse-upload"
          class="block cursor-pointer group"
          @drop.prevent="onDrop"
          @dragover.prevent="onDragOver"
          @dragleave.prevent="onDragLeave"
        >
          <div
            :class="[
              'flex flex-col items-center justify-center py-16 px-6 rounded-2xl border-2 border-dashed transition-all duration-200',
              isDragOver
                ? 'border-emerald-500 bg-emerald-50'
                : 'border-emerald-300 bg-gradient-to-br from-emerald-50/50 to-teal-50/50 group-hover:border-emerald-500 group-hover:bg-emerald-50',
            ]"
          >
            <div class="w-20 h-20 rounded-3xl bg-white shadow-sm flex items-center justify-center mb-4">
              <Upload class="w-9 h-9 text-emerald-500" />
            </div>
            <h3 class="text-lg font-semibold text-slate-700 mb-1">点击或拖拽上传图片</h3>
            <p class="text-sm text-slate-400 text-center max-w-xs">支持 JPG、PNG、WebP 格式，单张最大 20MB</p>
          </div>
          <input
            id="prompt-reverse-upload"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            class="hidden"
            @change="onFileChange"
          />
        </label>
      </div>

      <!-- 处理中状态 -->
      <div v-else-if="isProcessing" class="flex flex-col items-center justify-center py-16">
        <div class="relative w-24 h-24 mb-6">
          <svg class="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="42" fill="none" stroke="#E5E7EB" stroke-width="8" />
            <circle
              cx="50" cy="50" r="42" fill="none" stroke="url(#promptReverseGradient)"
              stroke-width="8" stroke-linecap="round"
              stroke-dasharray="180 264"
              class="animate-spin"
              style="transform-origin: center; animation-duration: 1.5s;"
            />
            <defs>
              <linearGradient id="promptReverseGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#10B981" />
                <stop offset="100%" stop-color="#06B6D4" />
              </linearGradient>
            </defs>
          </svg>
          <div class="absolute inset-0 flex items-center justify-center">
            <Loader2 class="w-8 h-8 text-emerald-500 animate-spin" />
          </div>
        </div>
        <h3 class="text-lg font-semibold text-slate-700 mb-2">正在反推提示词...</h3>
        <p class="text-sm text-slate-400">AI 正在分析图片内容并生成提示词，请稍候</p>
      </div>

      <!-- 结果展示区 -->
      <div v-else class="space-y-4">
        <!-- 原图预览 -->
        <div class="space-y-2">
          <div class="flex items-center gap-2 text-sm font-medium text-slate-600">
            <ImageOff class="w-4 h-4 text-slate-400" />
            原图
          </div>
          <div class="rounded-xl overflow-hidden bg-slate-50 border border-slate-200 min-h-[200px] flex items-center justify-center p-3">
            <img
              v-if="originalImage"
              :src="originalImage"
              alt="原图"
              class="max-h-[300px] w-auto max-w-full object-contain rounded-lg"
            />
          </div>
        </div>

        <!-- 反推结果 -->
        <div v-if="hasResult" class="space-y-4">
          <!-- 中文提示词 -->
          <div class="space-y-2">
            <div class="flex items-center gap-2 text-sm font-medium text-emerald-600">
              <ScanText class="w-4 h-4" />
              中文提示词
              <span class="text-[10px] text-emerald-500 bg-emerald-50 px-1.5 py-0.5 rounded">可复用</span>
            </div>
            <div class="relative">
              <textarea
                readonly
                :value="promptCn"
                class="w-full px-4 py-3 rounded-xl border border-slate-200 bg-slate-50 text-slate-700 text-sm font-mono whitespace-pre-wrap min-h-[100px] resize-y outline-none"
              />
              <button
                v-if="promptCn"
                @click="copyPromptCn"
                class="absolute top-2 right-2 btn-secondary flex items-center gap-1.5 text-xs px-2.5 py-1.5"
                :title="isCopiedCn ? '已复制' : '复制中文提示词'"
              >
                <Check v-if="isCopiedCn" class="w-3.5 h-3.5 text-emerald-500" />
                <Copy v-else class="w-3.5 h-3.5" />
                {{ isCopiedCn ? '已复制' : '复制' }}
              </button>
            </div>
          </div>

          <!-- 英文提示词 -->
          <div class="space-y-2">
            <div class="flex items-center gap-2 text-sm font-medium text-blue-600">
              <ScanText class="w-4 h-4" />
              英文提示词
              <span class="text-[10px] text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">SD/MJ</span>
            </div>
            <div class="relative">
              <textarea
                readonly
                :value="promptEn"
                class="w-full px-4 py-3 rounded-xl border border-slate-200 bg-slate-50 text-slate-700 text-sm font-mono whitespace-pre-wrap min-h-[100px] resize-y outline-none"
              />
              <button
                v-if="promptEn"
                @click="copyPromptEn"
                class="absolute top-2 right-2 btn-secondary flex items-center gap-1.5 text-xs px-2.5 py-1.5"
                :title="isCopiedEn ? '已复制' : '复制英文提示词'"
              >
                <Check v-if="isCopiedEn" class="w-3.5 h-3.5 text-emerald-500" />
                <Copy v-else class="w-3.5 h-3.5" />
                {{ isCopiedEn ? '已复制' : '复制' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 钱包选择与消耗展示 -->
        <WalletCostPanel
          ref="walletCostRef"
          :feature-key="FEATURE_KEY"
        />

        <!-- 操作按钮组 -->
        <div class="flex flex-wrap gap-3">
          <button
            @click="startReverse"
            :disabled="isProcessing"
            class="btn-primary flex items-center justify-center gap-2"
          >
            <Loader2 v-if="isProcessing" class="w-4 h-4 animate-spin" />
            <ScanText v-else class="w-4 h-4" />
            {{ hasResult ? '重新反推' : '反推提示词' }}
          </button>
          <button
            @click="resetAll"
            class="btn-secondary flex items-center gap-2"
          >
            <RefreshCw class="w-4 h-4" />
            更换图片
          </button>
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
