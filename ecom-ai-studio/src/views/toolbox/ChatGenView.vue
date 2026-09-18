<script setup lang="ts">
import { ref, nextTick, computed } from 'vue'
import {
  Send,
  Upload,
  X,
  Download,
  MessageSquare,
  Loader2,
  Bot,
  User,
  Sparkles,
  ImagePlus,
  Maximize2,
} from 'lucide-vue-next'
import { chatGenerate } from '@/api/toolbox'
import { getErrorMessage } from '@/lib/error'
import ToolCostBadge from '@/components/common/ToolCostBadge.vue'
import WalletCostPanel from '@/components/common/WalletCostPanel.vue'
import { useAuthStore } from '@/stores/auth'

const FEATURE_KEY = 'toolbox.chat_gen'
const auth = useAuthStore()
const walletCostRef = ref<InstanceType<typeof WalletCostPanel> | null>(null)
const insufficientBalance = ref(false)

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  images?: string[]
  error?: boolean
}

const MAX_REFERENCE_IMAGES = 3

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const referenceImages = ref<string[]>([])
const isSending = ref(false)
const errorMessage = ref('')
const lightboxImage = ref<string | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)

const isEmpty = computed(() => messages.value.length === 0)
const canSend = computed(() => inputText.value.trim().length > 0 && !isSending.value)
const canUploadMore = computed(() => referenceImages.value.length < MAX_REFERENCE_IMAGES)

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function handleReferenceUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  errorMessage.value = ''
  const remaining = MAX_REFERENCE_IMAGES - referenceImages.value.length
  const filesToProcess = Array.from(input.files).slice(0, remaining)

  for (const file of filesToProcess) {
    if (!file.type.startsWith('image/')) {
      errorMessage.value = '仅支持上传图片格式文件'
      continue
    }
    try {
      const base64 = await fileToBase64(file)
      referenceImages.value.push(base64)
    } catch {
      errorMessage.value = '图片读取失败，请重试'
    }
  }

  // 重置 input，允许再次选择相同文件
  input.value = ''
}

function removeReferenceImage(index: number) {
  referenceImages.value.splice(index, 1)
}

async function scrollToBottom() {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isSending.value) return

  errorMessage.value = ''
  insufficientBalance.value = false

  // 余额校验
	const cost = walletCostRef.value?.cost ?? 0
	if (cost > 0 && auth.selectedWalletBalance < cost) {
    errorMessage.value = `灵感币余额不足，预计消耗 ${cost}，当前余额 ${auth.selectedWalletBalance}，请先充值`
    insufficientBalance.value = true
    return
  }

  // 追加用户消息
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  await scrollToBottom()

  // 发送请求
  isSending.value = true
  try {
    const result = await chatGenerate({
      messages: messages.value
        .filter(m => !m.error)
        .map(m => ({ role: m.role, content: m.content })),
      reference_images:
        referenceImages.value.length > 0 ? referenceImages.value : undefined,
    })

    messages.value.push({
      role: 'assistant',
      content: result.reply,
      images: result.images,
    })

    // 同步本地余额（后端已扣款；失败时忽略，后端为权威源）
    if (cost > 0) {
      try { auth.deductPoints(cost) } catch { /* ignore */ }
    }
  } catch (err) {
    const msg = getErrorMessage(err, '发送失败')
    messages.value.push({
      role: 'assistant',
      content: msg,
      error: true,
    })
    errorMessage.value = msg
  } finally {
    isSending.value = false
    await scrollToBottom()
  }
}

function downloadImage(src: string, index: number) {
  const a = document.createElement('a')
  a.href = src
  a.download = `chat-gen-${Date.now()}-${index + 1}.png`
  a.click()
}

function openLightbox(src: string) {
  lightboxImage.value = src
}

function closeLightbox() {
  lightboxImage.value = null
}

function dismissError() {
  errorMessage.value = ''
}
</script>

<template>
  <div class="p-6 max-w-5xl mx-auto space-y-6">
    <!-- 页面标题 -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-display font-bold text-slate-900 flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
            <MessageSquare class="w-5 h-5 text-white" />
          </div>
          对话式生图
          <ToolCostBadge :feature-key="FEATURE_KEY" />
        </h1>
        <p class="text-slate-500 mt-1 text-sm">与 AI 对话生成图片，支持多轮交互与参考图</p>
      </div>
    </div>

    <!-- 顶部错误提示 -->
    <div
      v-if="errorMessage"
      class="glass-card p-3 flex items-center justify-between border-red-200 bg-red-50/80"
    >
      <div class="flex items-center gap-2">
        <span class="text-sm text-red-600">{{ errorMessage }}</span>
        <router-link
          v-if="insufficientBalance"
          to="/purchase"
          class="inline-flex items-center gap-1 text-emerald-600 hover:text-emerald-700 font-medium underline text-sm"
        >
          去充值
        </router-link>
      </div>
      <button @click="dismissError" class="text-red-400 hover:text-red-600 transition-colors">
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- 对话主容器 -->
    <div
      class="glass-card flex flex-col overflow-hidden"
      :style="{ height: 'calc(100vh - 220px)', minHeight: '60vh' }"
    >
      <!-- 消息列表区 -->
      <div
        ref="messagesContainer"
        class="flex-1 overflow-y-auto p-6 space-y-4"
      >
        <!-- 空状态 -->
        <div
          v-if="isEmpty"
          class="h-full flex flex-col items-center justify-center text-center py-10"
        >
          <div class="w-20 h-20 rounded-3xl bg-gradient-to-br from-emerald-50 to-teal-50 border border-emerald-200 flex items-center justify-center mb-4">
            <Sparkles class="w-10 h-10 text-emerald-500" />
          </div>
          <h3 class="text-lg font-semibold text-slate-700 mb-2">开始与 AI 对话生成图片</h3>
          <p class="text-sm text-slate-400 max-w-md">
            描述你想要的图片，AI 会自动判断需求并生成。如需基于参考图生成，可上传 1-3 张参考图。
          </p>
          <div class="mt-6 grid grid-cols-1 md:grid-cols-2 gap-2 max-w-lg w-full">
            <div class="text-left p-3 rounded-xl bg-white/60 border border-slate-200">
              <p class="text-xs font-medium text-emerald-600 mb-1">示例 1</p>
              <p class="text-xs text-slate-500">"帮我生成一张夏日海滩的产品图"</p>
            </div>
            <div class="text-left p-3 rounded-xl bg-white/60 border border-slate-200">
              <p class="text-xs font-medium text-emerald-600 mb-1">示例 2</p>
              <p class="text-xs text-slate-500">"基于参考图，生成白色背景版本"</p>
            </div>
          </div>
        </div>

        <!-- 消息气泡 -->
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          :class="['flex gap-3', msg.role === 'user' ? 'justify-end' : 'justify-start']"
        >
          <!-- AI 头像 -->
          <div
            v-if="msg.role === 'assistant'"
            class="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center flex-shrink-0"
          >
            <Bot class="w-4 h-4 text-white" />
          </div>

          <!-- 气泡内容 -->
          <div
            :class="[
              'max-w-[75%] rounded-2xl px-4 py-3',
              msg.role === 'user'
                ? 'bg-emerald-500/10 border border-emerald-500/20'
                : msg.error
                  ? 'bg-red-50 border border-red-200'
                  : 'bg-white/5 border border-white/10',
            ]"
          >
            <!-- 文本内容 -->
            <p
              v-if="msg.content"
              :class="[
                'text-sm whitespace-pre-wrap break-words',
                msg.error ? 'text-red-600' : 'text-slate-700',
              ]"
            >
              {{ msg.content }}
            </p>

            <!-- 图片内容 -->
            <div
              v-if="msg.images && msg.images.length > 0"
              class="mt-3 space-y-2"
            >
              <div
                v-for="(img, imgIdx) in msg.images"
                :key="imgIdx"
                class="relative group rounded-xl overflow-hidden border border-slate-200 inline-block"
              >
                <img
                  :src="img"
                  alt="生成图片"
                  class="w-full max-w-sm block cursor-zoom-in"
                  @click="openLightbox(img)"
                />
                <div class="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    @click="openLightbox(img)"
                    class="p-1.5 rounded-lg bg-black/50 text-white hover:bg-black/70 transition-colors"
                    title="放大"
                  >
                    <Maximize2 class="w-3.5 h-3.5" />
                  </button>
                  <button
                    @click="downloadImage(img, imgIdx)"
                    class="p-1.5 rounded-lg bg-black/50 text-white hover:bg-black/70 transition-colors"
                    title="下载"
                  >
                    <Download class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- 用户头像 -->
          <div
            v-if="msg.role === 'user'"
            class="w-8 h-8 rounded-lg bg-slate-200 flex items-center justify-center flex-shrink-0"
          >
            <User class="w-4 h-4 text-slate-600" />
          </div>
        </div>

        <!-- Typing indicator -->
        <div v-if="isSending" class="flex gap-3 justify-start">
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center flex-shrink-0">
            <Bot class="w-4 h-4 text-white" />
          </div>
          <div class="bg-white/5 border border-white/10 rounded-2xl px-4 py-3">
            <div class="flex items-center gap-2">
              <Loader2 class="w-4 h-4 text-emerald-500 animate-spin" />
              <span class="text-sm text-slate-500">AI 正在思考...</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="border-t border-slate-100 p-4 space-y-3 bg-white/40">
        <!-- 参考图缩略图 -->
        <div v-if="referenceImages.length > 0" class="flex items-center gap-2 flex-wrap">
          <div
            v-for="(img, idx) in referenceImages"
            :key="idx"
            class="relative w-14 h-14 rounded-lg overflow-hidden border border-slate-200 group"
          >
            <img :src="img" :alt="`参考图 ${idx + 1}`" class="w-full h-full object-cover" />
            <button
              @click="removeReferenceImage(idx)"
              class="absolute top-0 right-0 p-0.5 bg-black/60 text-white rounded-bl-lg opacity-0 group-hover:opacity-100 transition-opacity"
              title="删除参考图"
            >
              <X class="w-3 h-3" />
            </button>
          </div>
        </div>

        <!-- 钱包选择与消耗展示 -->
        <WalletCostPanel
          ref="walletCostRef"
          :feature-key="FEATURE_KEY"
        />

        <!-- 输入框 + 按钮 -->
        <div class="flex items-end gap-2">
          <!-- 上传参考图按钮 -->
          <label
            :class="[
              'p-2.5 rounded-xl transition-all border flex items-center justify-center',
              canUploadMore
                ? 'bg-white border-slate-200 text-slate-500 hover:border-emerald-300 hover:text-emerald-600 cursor-pointer'
                : 'bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed',
            ]"
            :title="`上传参考图（最多 ${MAX_REFERENCE_IMAGES} 张）`"
          >
            <Upload class="w-5 h-5" />
            <input
              v-if="canUploadMore"
              type="file"
              accept="image/*"
              multiple
              class="hidden"
              @change="handleReferenceUpload"
            />
          </label>

          <!-- 文本输入 -->
          <textarea
            v-model="inputText"
            @keydown="handleKeydown"
            placeholder="输入消息描述你想要的图片... (Enter 发送，Shift+Enter 换行)"
            rows="2"
            :disabled="isSending"
            class="flex-1 resize-none bg-white border border-slate-200 rounded-xl px-4 py-2.5 text-sm text-slate-700 placeholder-slate-400 focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500/50 outline-none transition-all disabled:opacity-60"
          />

          <!-- 发送按钮 -->
          <button
            @click="sendMessage"
            :disabled="!canSend"
            class="btn-primary px-5 py-2.5 flex items-center gap-2 self-stretch"
          >
            <Loader2 v-if="isSending" class="w-4 h-4 animate-spin" />
            <Send v-else class="w-4 h-4" />
            {{ isSending ? '发送中' : '发送' }}
          </button>
        </div>

        <!-- 底部提示 -->
        <div class="flex items-center justify-between text-xs text-slate-400">
          <span class="flex items-center gap-1">
            <ImagePlus class="w-3 h-3" />
            参考图 {{ referenceImages.length }}/{{ MAX_REFERENCE_IMAGES }}
          </span>
          <span>支持多轮对话，AI 会保留上下文</span>
        </div>
      </div>
    </div>

    <!-- 图片放大弹窗 -->
    <div
      v-if="lightboxImage"
      @click="closeLightbox"
      class="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6"
    >
      <div class="relative max-w-4xl max-h-full" @click.stop>
        <img
          :src="lightboxImage"
          alt="放大图片"
          class="max-w-full max-h-[85vh] rounded-lg shadow-2xl"
        />
        <div class="absolute top-3 right-3 flex gap-2">
          <button
            @click="downloadImage(lightboxImage, 0)"
            class="p-2 rounded-lg bg-white/20 text-white hover:bg-white/30 backdrop-blur transition-colors"
            title="下载"
          >
            <Download class="w-5 h-5" />
          </button>
          <button
            @click="closeLightbox"
            class="p-2 rounded-lg bg-white/20 text-white hover:bg-white/30 backdrop-blur transition-colors"
            title="关闭"
          >
            <X class="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>
