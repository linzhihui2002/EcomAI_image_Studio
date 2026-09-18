<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Upload,
  X,
  FileText,
  ClipboardList,
  Loader2,
  Camera,
  Sparkles,
  Image as ImageIcon,
  AlertCircle,
  Lightbulb,
  Copy,
  Check,
} from 'lucide-vue-next'
import { analyzePlan, getPlanAnalysisStatus, type PlanAnalysisResult, type PlanAnalysisRequest } from '@/api/toolbox'
import { getErrorMessage } from '@/lib/error'
import ToolCostBadge from '@/components/common/ToolCostBadge.vue'
import WalletCostPanel from '@/components/common/WalletCostPanel.vue'
import { useAuthStore } from '@/stores/auth'

const FEATURE_KEY = 'toolbox.plan_analysis'
const auth = useAuthStore()
const walletCostRef = ref<InstanceType<typeof WalletCostPanel> | null>(null)
const insufficientBalance = ref(false)

interface UploadedImage {
  id: string
  name: string
  dataUrl: string
}

interface UploadedFile {
  name: string
  content?: string           // 纯文本文件的内容（txt/md/json）
  dataUrl?: string           // 二进制文件的 base64 data URL（PDF/DOC/PPT/XLS/图片等）
  isBinary: boolean          // 是否为需要 MinerU 解析的二进制文件
}

/** 纯文本文件扩展名 */
const TEXT_EXTENSIONS = ['txt', 'md', 'markdown', 'json']

/** 判断文件是否为纯文本类型（可直接读取内容） */
function isTextFile(file: File): boolean {
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  return TEXT_EXTENSIONS.includes(ext) || file.type.startsWith('text/')
}

const images = ref<UploadedImage[]>([])
const descFile = ref<UploadedFile | null>(null)
const promptText = ref<string>('')
const result = ref<PlanAnalysisResult | null>(null)
const isProcessing = ref(false)
const errorMsg = ref<string>('')
const validationMsg = ref<string>('')

const planSummary = computed(() => result.value?.plan?.summary || '')
const planImages = computed(() => result.value?.plan?.images || [])
const rawText = computed(() => result.value?.plan?.raw_text || '')

const copiedField = ref<string>('')

async function copyText(text: string, fieldKey: string) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = fieldKey
    setTimeout(() => { copiedField.value = '' }, 2000)
  } catch {
    errorMsg.value = '复制失败，请手动选择文本复制'
  }
}

const hasResult = computed(() => result.value !== null)

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function fileToText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsText(file)
  })
}

async function handleImageUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  errorMsg.value = ''
  validationMsg.value = ''

  const filesToProcess = Array.from(input.files)

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
  result.value = null

  if (images.value.length === 0) {
    validationMsg.value = '请至少上传一张商品图'
  } else {
    validationMsg.value = ''
  }
}

function removeImage(id: string) {
  images.value = images.value.filter(img => img.id !== id)
  result.value = null
  if (images.value.length === 0) {
    validationMsg.value = '请至少上传一张商品图'
  }
}

function clearImages() {
  images.value = []
  result.value = null
  validationMsg.value = '请至少上传一张商品图'
}

async function handleFileUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  errorMsg.value = ''
  const file = input.files[0]

  // 支持的文件类型：纯文本（txt/md/json）+ 二进制文档（PDF/DOC/PPT/XLS/图片）
  const isText = isTextFile(file)
  const isBinary = /\.(pdf|doc|docx|ppt|pptx|xls|xlsx)$/i.test(file.name)
    || /^(application\/(pdf|vnd\.ms-word|vnd\.openxmlformats-officedocument\.wordprocessingml\.document|vnd\.ms-powerpoint|vnd\.openxmlformats-officedocument\.presentationml\.presentation|vnd\.ms-excel|vnd\.openxmlformats-officedocument\.spreadsheetml\.sheet)|image\/(png|jpe?g|gif|bmp|webp))/.test(file.type)

  if (!isText && !isBinary) {
    errorMsg.value = '不支持的文件格式，请上传 .txt / .md / .json 或 PDF/DOC/PPT/XLS/图片等文档'
    input.value = ''
    return
  }

  try {
    if (isText) {
      // 纯文本文件：直接读取内容
      const content = await fileToText(file)
      descFile.value = {
        name: file.name,
        content,
        isBinary: false,
      }
    } else {
      // 二进制文件：转为 base64，由后端通过 MinerU 解析
      const dataUrl = await fileToBase64(file)
      descFile.value = {
        name: file.name,
        dataUrl,
        isBinary: true,
      }
    }
    result.value = null
  } catch {
    errorMsg.value = `文件 ${file.name} 读取失败`
  }

  input.value = ''
}

function removeFile() {
  descFile.value = null
  result.value = null
}

async function startAnalysis() {
  errorMsg.value = ''
  validationMsg.value = ''
  insufficientBalance.value = false

  if (images.value.length === 0) {
    validationMsg.value = '请至少上传一张商品图'
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
  result.value = null

  try {
    const payload: Record<string, unknown> = {
      images: images.value.map(img => img.dataUrl),
    }

    if (descFile.value) {
      if (descFile.value.isBinary && descFile.value.dataUrl) {
        payload.file_data = descFile.value.dataUrl
        payload.file_name = descFile.value.name
      } else if (descFile.value.content !== undefined) {
        payload.file_content = descFile.value.content
      }
    }

    if (promptText.value.trim()) {
      payload.prompt = promptText.value.trim()
    }

    // 1. 提交异步任务
    const asyncResult = await analyzePlan(payload as unknown as PlanAnalysisRequest)
    const taskId = asyncResult.task_id
    console.log('[PlanAnalysis] 异步任务已创建:', taskId)

    // 同步本地余额（后端已扣款）
    if (cost > 0) {
      try { auth.deductPoints(cost) } catch { /* ignore */ }
    }

    // 2. 轮询任务状态
    const POLL_INTERVAL_MS = 2000
    const MAX_POLLS = 300  // 最多轮询 10 分钟（匹配后端重试窗口）
    let pollCount = 0

    while (pollCount < MAX_POLLS) {
      await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS))
      pollCount++

      try {
        const status = await getPlanAnalysisStatus(taskId)
        console.log(`[PlanAnalysis] 轮询 #${pollCount}: status=${status.status}`)

        if (status.status === 'completed') {
          if (status.result_json) {
            result.value = { plan: status.result_json } as PlanAnalysisResult
            console.log('[PlanAnalysis] 分析完成:', JSON.stringify(status.result_json).substring(0, 500))
          } else {
            errorMsg.value = '分析完成但结果为空，请重试'
          }
          return
        }

        if (status.status === 'failed') {
          errorMsg.value = status.error_message || '分析失败，请稍后重试'
          return
        }
        // status === 'processing' → 继续轮询
      } catch (pollErr) {
        console.warn('[PlanAnalysis] 轮询请求失败，继续重试:', pollErr)
        // 继续轮询，不中断
      }
    }

    // 超时
    errorMsg.value = '分析超时，请稍后重试'
  } catch (err) {
    const msg = getErrorMessage(err, '分析失败')
    if (msg.includes('MinerU') || msg.includes('文档解析') || msg.includes('文档下载')) {
      if (msg.includes('SSL') || msg.includes('CDN') || msg.includes('下载失败')) {
        errorMsg.value = `文档下载失败：${msg}\n\n建议：\n1. 网络环境可能不稳定，请稍后重试\n2. 如持续失败，可尝试切换网络环境\n3. 或联系技术支持`
      } else {
        errorMsg.value = `文档解析失败：${msg}\n\n建议：\n1. 确认文件格式正确（支持 PDF/DOC/PPT/XLS/图片）\n2. 检查文件是否损坏或受密码保护\n3. 稍后重试`
      }
    } else {
      errorMsg.value = msg
    }
  } finally {
    isProcessing.value = false
  }
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <!-- 页面标题 -->
    <div>
      <h1 class="text-2xl font-display font-bold text-slate-900 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <ClipboardList class="w-5 h-5 text-white" />
        </div>
        生图计划分析
        <ToolCostBadge :feature-key="FEATURE_KEY" />
      </h1>
      <p class="text-slate-500 mt-1 text-sm">上传商品图，AI 自动分析并生成生图方案：数据摘要、逐图方案与原因、中英文提示词、备用提示词，均可直接复制使用</p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- 左侧：上传与配置 -->
      <div class="glass-card p-6 space-y-5">
        <!-- 商品图上传 -->
        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
              <ImageIcon class="w-4 h-4 text-emerald-500" />
              商品图
              <span class="text-xs font-normal text-rose-500">*必填</span>
              <span class="text-xs font-normal text-slate-400">（{{ images.length }} 张）</span>
            </h3>
            <button
              v-if="images.length > 0"
              @click="clearImages"
              class="text-xs text-slate-400 hover:text-red-500 transition-colors"
            >
              清空全部
            </button>
          </div>

          <label class="block cursor-pointer group">
            <div class="border-2 border-dashed border-emerald-300 rounded-xl py-6 px-4 flex flex-col items-center justify-center bg-emerald-50/40 hover:bg-emerald-50 hover:border-emerald-500 transition-all">
              <Upload class="w-7 h-7 text-emerald-400 group-hover:text-emerald-500 mb-2" />
              <p class="text-sm font-medium text-emerald-600">点击上传商品图</p>
              <p class="text-xs text-slate-400 mt-1">支持 JPG / PNG / WebP，可多张</p>
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

          <!-- 必填校验提示 -->
          <p v-if="validationMsg" class="mt-3 text-xs text-amber-600 flex items-center gap-1.5">
            <AlertCircle class="w-3.5 h-3.5" />
            {{ validationMsg }}
          </p>
        </div>

        <!-- 产品说明文件（可选） -->
        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
              <FileText class="w-4 h-4 text-emerald-500" />
              产品说明文件
              <span class="text-xs font-normal text-slate-400">（可选）</span>
            </h3>
            <button
              v-if="descFile"
              @click="removeFile"
              class="text-xs text-slate-400 hover:text-red-500 transition-colors"
            >
              移除
            </button>
          </div>

          <label v-if="!descFile" class="block cursor-pointer group">
            <div class="border-2 border-dashed border-slate-300 rounded-xl py-5 px-4 flex flex-col items-center justify-center bg-slate-50/40 hover:bg-slate-50 hover:border-slate-400 transition-all">
              <FileText class="w-6 h-6 text-slate-400 group-hover:text-slate-500 mb-1.5" />
              <p class="text-sm font-medium text-slate-600">点击上传说明文件</p>
              <p class="text-xs text-slate-400 mt-1">支持 .txt / .md / .json（直接读取）或 PDF/DOC/PPT/XLS/图片（AI 解析）</p>
            </div>
            <input
              type="file"
              accept=".txt,.md,.markdown,.json,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,image/png,image/jpeg,image/jpg,image/gif,image/bmp,image/webp,text/plain,text/markdown,application/pdf"
              class="hidden"
              @change="handleFileUpload"
            />
          </label>

          <!-- 已上传文件展示 -->
          <div v-else class="flex items-center gap-3 p-3 rounded-xl bg-emerald-50 border border-emerald-200">
            <div class="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" :class="descFile.isBinary ? 'bg-blue-100' : 'bg-emerald-100'">
              <FileText class="w-4.5 h-4.5" :class="descFile.isBinary ? 'text-blue-600' : 'text-emerald-600'" />
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-slate-700 truncate">{{ descFile.name }}</p>
              <p class="text-[10px] text-slate-400">
                <template v-if="descFile.isBinary">二进制文件 · AI 智能解析</template>
                <template v-else>{{ descFile.content?.length || 0 }} 字符</template>
              </p>
            </div>
            <button
              @click="removeFile"
              class="p-1.5 rounded-lg hover:bg-white/60 text-slate-400 hover:text-red-500 transition-colors"
              title="移除文件"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
        </div>

        <!-- 提示词（可选） -->
        <div>
          <h3 class="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
            <Lightbulb class="w-4 h-4 text-emerald-500" />
            提示词
            <span class="text-xs font-normal text-slate-400">（可选）</span>
          </h3>
          <textarea
            v-model="promptText"
            rows="4"
            maxlength="1000"
            placeholder="可输入自定义提示词，描述期望的场景、风格、角度等偏好，AI 将据此优化生图计划"
            class="w-full rounded-xl border border-slate-300 bg-white/60 px-3 py-2.5 text-sm text-slate-700 placeholder-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 focus:outline-none resize-none transition-colors"
          ></textarea>
          <div class="flex justify-between mt-1.5">
            <p class="text-xs text-slate-400">AI 将结合图片与提示词综合分析</p>
            <p class="text-xs text-slate-400">{{ promptText.length }} / 1000</p>
          </div>
        </div>

        <!-- 钱包选择与消耗展示 -->
        <WalletCostPanel
          ref="walletCostRef"
          :feature-key="FEATURE_KEY"
        />

        <!-- 操作按钮 -->
        <div class="pt-2">
          <button
            @click="startAnalysis"
            :disabled="isProcessing"
            class="btn-primary w-full py-2.5 flex items-center justify-center gap-2"
          >
            <Loader2 v-if="isProcessing" class="w-4 h-4 animate-spin" />
            <ClipboardList v-else class="w-4 h-4" />
            {{ isProcessing ? '分析中...' : '开始分析' }}
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

      <!-- 右侧：分析结果 -->
      <div class="glass-card p-6">
        <h3 class="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-1.5">
          <Sparkles class="w-4 h-4 text-emerald-500" />
          分析结果
        </h3>

        <!-- 空状态 -->
        <div
          v-if="!isProcessing && !hasResult"
          class="flex flex-col items-center justify-center py-16 text-center"
        >
          <div class="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center mb-3">
            <ClipboardList class="w-8 h-8 text-slate-300" />
          </div>
          <p class="text-sm text-slate-400">上传商品图并点击"开始分析"后，结构化生图计划将在此显示</p>
        </div>

        <!-- 处理中 -->
        <div
          v-else-if="isProcessing"
          class="flex flex-col items-center justify-center py-16"
        >
          <div class="relative w-20 h-20 mb-4">
            <svg class="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="#E5E7EB" stroke-width="8" />
              <circle
                cx="50" cy="50" r="42" fill="none"
                stroke="url(#planGradient)"
                stroke-width="8" stroke-linecap="round"
                stroke-dasharray="180 264"
                class="animate-spin"
                style="transform-origin: center; animation-duration: 1.5s;"
              />
              <defs>
                <linearGradient id="planGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stop-color="#10B981" />
                  <stop offset="100%" stop-color="#06B6D4" />
                </linearGradient>
              </defs>
            </svg>
            <div class="absolute inset-0 flex items-center justify-center">
              <Loader2 class="w-7 h-7 text-emerald-500 animate-spin" />
            </div>
          </div>
          <h3 class="text-base font-semibold text-slate-700 mb-1">正在分析生图计划...</h3>
          <p class="text-xs text-slate-400">AI 多模态分析中，请稍候</p>
        </div>

        <!-- 结果展示 -->
        <div v-else class="space-y-4">
          <!-- 1. 数据摘要 -->
          <section v-if="planSummary" class="rounded-xl border border-slate-200 bg-white/60 p-4">
            <h4 class="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
              <Lightbulb class="w-4 h-4 text-emerald-500" />
              数据摘要
            </h4>
            <p class="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">{{ planSummary }}</p>
          </section>

          <!-- 2/3/4. 逐图方案、提示词、备用提示词 -->
          <section
            v-for="img in planImages"
            :key="`img-${img.index}`"
            class="rounded-xl border border-slate-200 bg-white/60 p-4 space-y-3"
          >
            <!-- 图片标题 -->
            <div class="flex items-center gap-2">
              <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-emerald-500 text-white text-xs font-bold">
                {{ img.index }}
              </span>
              <h4 class="text-sm font-semibold text-slate-700">{{ img.title }}</h4>
            </div>

            <!-- 方案 -->
            <div v-if="img.plan" class="flex items-start gap-2 p-2.5 rounded-lg bg-emerald-50/60 border border-emerald-100">
              <Camera class="w-3.5 h-3.5 text-emerald-500 flex-shrink-0 mt-0.5" />
              <div class="text-xs text-slate-700 leading-relaxed">
                <span class="font-medium text-slate-800">方案：</span>{{ img.plan }}
              </div>
            </div>

            <!-- 原因 -->
            <div v-if="img.reason" class="flex items-start gap-2 p-2.5 rounded-lg bg-blue-50/40 border border-blue-100">
              <Lightbulb class="w-3.5 h-3.5 text-blue-500 flex-shrink-0 mt-0.5" />
              <div class="text-xs text-slate-700 leading-relaxed">
                <span class="font-medium text-slate-800">原因：</span>{{ img.reason }}
              </div>
            </div>

            <!-- 中文提示词 -->
            <div v-if="img.prompt_cn" class="space-y-1">
              <div class="flex items-center justify-between">
                <span class="text-xs font-medium text-slate-600">中文提示词</span>
                <button
                  @click="copyText(img.prompt_cn, `prompt_cn_${img.index}`)"
                  class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors"
                  :class="copiedField === `prompt_cn_${img.index}` ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'"
                >
                  <Check v-if="copiedField === `prompt_cn_${img.index}`" class="w-3 h-3" />
                  <Copy v-else class="w-3 h-3" />
                  {{ copiedField === `prompt_cn_${img.index}` ? '已复制' : '复制' }}
                </button>
              </div>
              <textarea
                readonly
                :value="img.prompt_cn"
                class="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 text-xs font-mono whitespace-pre-wrap min-h-[80px] resize-y outline-none"
              ></textarea>
            </div>

            <!-- 英文提示词 -->
            <div v-if="img.prompt_en" class="space-y-1">
              <div class="flex items-center justify-between">
                <span class="text-xs font-medium text-slate-600">英文提示词</span>
                <button
                  @click="copyText(img.prompt_en, `prompt_en_${img.index}`)"
                  class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors"
                  :class="copiedField === `prompt_en_${img.index}` ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'"
                >
                  <Check v-if="copiedField === `prompt_en_${img.index}`" class="w-3 h-3" />
                  <Copy v-else class="w-3 h-3" />
                  {{ copiedField === `prompt_en_${img.index}` ? '已复制' : '复制' }}
                </button>
              </div>
              <textarea
                readonly
                :value="img.prompt_en"
                class="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 text-xs font-mono whitespace-pre-wrap min-h-[80px] resize-y outline-none"
              ></textarea>
            </div>

            <!-- 备用中文提示词 -->
            <div v-if="img.backup_prompt_cn" class="space-y-1 pt-2 border-t border-dashed border-slate-200">
              <div class="flex items-center justify-between">
                <span class="text-xs font-medium text-amber-600">备用中文提示词</span>
                <button
                  @click="copyText(img.backup_prompt_cn, `backup_cn_${img.index}`)"
                  class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors"
                  :class="copiedField === `backup_cn_${img.index}` ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-50 text-amber-600 hover:bg-amber-100'"
                >
                  <Check v-if="copiedField === `backup_cn_${img.index}`" class="w-3 h-3" />
                  <Copy v-else class="w-3 h-3" />
                  {{ copiedField === `backup_cn_${img.index}` ? '已复制' : '复制' }}
                </button>
              </div>
              <textarea
                readonly
                :value="img.backup_prompt_cn"
                class="w-full px-3 py-2 rounded-lg border border-amber-100 bg-amber-50/30 text-slate-700 text-xs font-mono whitespace-pre-wrap min-h-[80px] resize-y outline-none"
              ></textarea>
            </div>

            <!-- 备用英文提示词 -->
            <div v-if="img.backup_prompt_en" class="space-y-1">
              <div class="flex items-center justify-between">
                <span class="text-xs font-medium text-amber-600">备用英文提示词</span>
                <button
                  @click="copyText(img.backup_prompt_en, `backup_en_${img.index}`)"
                  class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors"
                  :class="copiedField === `backup_en_${img.index}` ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-50 text-amber-600 hover:bg-amber-100'"
                >
                  <Check v-if="copiedField === `backup_en_${img.index}`" class="w-3 h-3" />
                  <Copy v-else class="w-3 h-3" />
                  {{ copiedField === `backup_en_${img.index}` ? '已复制' : '复制' }}
                </button>
              </div>
              <textarea
                readonly
                :value="img.backup_prompt_en"
                class="w-full px-3 py-2 rounded-lg border border-amber-100 bg-amber-50/30 text-slate-700 text-xs font-mono whitespace-pre-wrap min-h-[80px] resize-y outline-none"
              ></textarea>
            </div>
          </section>

          <!-- raw_text 兜底展示（JSON 解析失败时） -->
          <section v-if="!planSummary && planImages.length === 0 && rawText" class="rounded-xl border border-amber-200 bg-amber-50/40 p-4">
            <h4 class="text-sm font-semibold text-amber-700 mb-3 flex items-center gap-1.5">
              <AlertCircle class="w-4 h-4" />
              AI 返回内容（格式异常，未能解析为结构化数据）
            </h4>
            <textarea
              readonly
              :value="rawText"
              class="w-full px-3 py-2 rounded-lg border border-amber-200 bg-white/60 text-slate-700 text-xs font-mono whitespace-pre-wrap min-h-[120px] resize-y outline-none"
            ></textarea>
          </section>

          <!-- 空结果兜底 -->
          <div
            v-if="!planSummary && planImages.length === 0 && !rawText"
            class="py-10 text-center text-sm text-slate-400"
          >
            分析结果为空，请尝试更换图片或补充说明文件后重试
          </div>
        </div>
      </div>
    </div>
  </div>
</template>


