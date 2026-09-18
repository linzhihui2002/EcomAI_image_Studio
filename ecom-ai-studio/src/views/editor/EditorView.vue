<script setup lang="ts">
/**
 * AI 图片编辑器页面（/editor?imageId=xxx）
 *
 * 三栏布局：左侧工具栏 | 中间画布区 | 右侧（页签："图层"面板 + "AI 助手"对话面板）
 * - 工具执行：POST execute → useTaskSse 订阅进度（SSE 失败自动降级 pollFn 轮询）
 *   → completed 后按 result.image_url 更新目标图层（执行前已 pushSnapshot，可整体撤销）
 * - AI 助手：指令 → agentPlan → 计划卡片确认执行 → agentExecute → SSE 进度
 *   → final_image_url 替换背景图层；面板用 v-show 切换保证任务进度不中断
 * - 笔刷选区：mask 工具或 AI 助手计划激活笔刷模式，画布涂抹 → Enter/按钮生成蒙版
 * - 撤销/重做：Ctrl+Z / Ctrl+Y（输入框内不拦截）
 * - 前后对比：原图 vs 当前画布导出（预览分辨率导出，速度优先）
 * - 保存到历史：确保文档已保存 → 原图分辨率导出 → POST save-history
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  CheckCircle2,
  Columns2,
  Download,
  Layers,
  Loader2,
  PenTool,
  Redo2,
  Save,
  Sparkles,
  Undo2,
  Upload,
  XCircle,
} from 'lucide-vue-next'
import { getErrorMessage } from '@/lib/error'
import { useEditorStore } from '@/stores/editor'
import {
  executeEditorTool,
  fetchEditorTaskStatus,
  fetchEditorTools,
  saveEditorDocumentHistory,
  type EditorLayer,
  type EditorTaskResult,
} from '@/api/editor'
import { useTaskSse } from '@/composables/useTaskSse'
import EditorToolbar from '@/components/editor/EditorToolbar.vue'
import EditorCanvas from '@/components/editor/EditorCanvas.vue'
import EditorLayerPanel from '@/components/editor/EditorLayerPanel.vue'
import EditorPropertyPanel from '@/components/editor/EditorPropertyPanel.vue'
import EditorCompareOverlay from '@/components/editor/EditorCompareOverlay.vue'
import EditorAgentPanel from '@/components/editor/EditorAgentPanel.vue'

const route = useRoute()
const store = useEditorStore()

const canvasRef = ref<InstanceType<typeof EditorCanvas> | null>(null)
const imageLoading = ref(false)
const toolRunning = ref(false)
const executingLayerId = ref<string | null>(null)
const savingHistory = ref(false)
const downloading = ref(false)
const compareCurrentUrl = ref('')
/** 顶栏「上传」按钮触发的隐藏文件选择框 */
const uploadInputRef = ref<HTMLInputElement | null>(null)

// ===== 右侧页签（图层 / AI 助手） =====
// v-show 切换：两个面板均保持挂载，AI 助手中的 SSE 订阅与任务进度不因切页中断
const rightTab = ref<'layers' | 'agent'>('layers')

// ===== Toast 提示 =====

const toast = reactive<{ visible: boolean; type: 'info' | 'success' | 'error'; text: string }>({
  visible: false,
  type: 'info',
  text: '',
})
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(text: string, type: 'info' | 'success' | 'error' = 'info') {
  toast.visible = true
  toast.type = type
  toast.text = text
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.visible = false
  }, 3000)
}

// ===== 初始化 =====

/**
 * imageId → 图片 URL 规则（与项目既有取图方式一致）：
 * - 完整地址（/api/v1/images/...、data URI、http[s]）直接使用
 * - 其余视为本服务图片文件名（即 source_image_id），补全为 /api/v1/images/<filename>
 */
function normalizeImageUrl(imageId: string): string | null {
  if (!imageId) return null
  if (
    imageId.startsWith('/api/v1/images/') ||
    imageId.startsWith('data:image/') ||
    imageId.startsWith('http://') ||
    imageId.startsWith('https://')
  ) {
    return imageId
  }
  return `/api/v1/images/${imageId}`
}

async function loadTools() {
  if (store.toolsLoaded) return
  try {
    store.tools = await fetchEditorTools()
    store.toolsLoaded = true
  } catch (err) {
    console.error('[editor] 工具注册表加载失败', err)
    showToast(getErrorMessage(err, '编辑工具加载失败'), 'error')
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown)
  void loadTools()

  const raw = route.query.imageId
  const imageId = typeof raw === 'string' ? raw : Array.isArray(raw) ? String(raw[0] ?? '') : ''
  const url = normalizeImageUrl(imageId)
  if (url) {
    imageLoading.value = true
    try {
      await store.loadFromImage({ url, imageId: imageId || undefined })
    } catch (err) {
      console.error('[editor] 背景图加载失败', err)
      showToast(getErrorMessage(err, '图片加载失败'), 'error')
    } finally {
      imageLoading.value = false
    }
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  store.reset()
})

// ===== 撤销 / 重做快捷键 =====

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable
}

function handleKeydown(e: KeyboardEvent) {
  if (!(e.ctrlKey || e.metaKey)) return
  const key = e.key.toLowerCase()
  if (key === 'z' && !e.shiftKey) {
    if (isTypingTarget(e.target)) return
    e.preventDefault()
    store.undo()
  } else if (key === 'y' || (key === 'z' && e.shiftKey)) {
    if (isTypingTarget(e.target)) return
    e.preventDefault()
    store.redo()
  }
}

// ===== 工具执行（SSE + 降级轮询） =====

const taskId = ref('')
const taskTracker = useTaskSse({
  taskId,
  // SSE 连续失败自动降级为轮询（2s 间隔），pollFn 复用既有 GET 端点
  pollFn: (id) => fetchEditorTaskStatus(id),
  onCompleted: handleToolCompleted,
  onFailed: handleToolFailed,
})

async function handleApplyTool() {
  const toolName = store.activeTool
  const toolDef = store.activeToolDef
  if (!toolName || !toolDef || toolRunning.value) return

  // 目标图层：选中的图片图层，否则背景图层
  const selected = store.selectedLayer
  const target = selected && selected.type === 'image' && selected.url ? selected : store.backgroundLayer
  if (!target || !target.url) {
    showToast('请先选择一个图片图层', 'error')
    return
  }

  // 必填参数校验（蒙版参数缺失时尝试用当前涂抹笔迹自动生成）
  const params: Record<string, number | string | boolean> = { ...store.toolParams }
  for (const [key, rule] of Object.entries(toolDef.params_schema)) {
    if (!rule.required || (params[key] !== undefined && params[key] !== '')) continue
    if (key === 'mask_data_uri' && store.hasMaskStrokes) {
      const uri = await store.confirmMaskSelection()
      if (uri) {
        params.mask_data_uri = uri
        continue
      }
    }
    showToast(`请填写参数：${rule.label ?? key}`, 'error')
    return
  }

  toolRunning.value = true
  executingLayerId.value = target.id
  // 执行前压栈：结果应用（图层被替换）后可整体撤销
  store.pushSnapshot()

  try {
    const res = await executeEditorTool(toolName, target.url, params)
    taskId.value = res.task_id
    taskTracker.start()
  } catch (err) {
    toolRunning.value = false
    executingLayerId.value = null
    showToast(getErrorMessage(err, '任务提交失败'), 'error')
  }
}

function handleToolCompleted(result: unknown) {
  toolRunning.value = false
  const layerId = executingLayerId.value
  executingLayerId.value = null
  const r = result as EditorTaskResult | null
  if (!layerId || !r || !r.image_url) {
    showToast('任务完成但未返回结果图', 'error')
    return
  }

  if (layerId === store.backgroundLayerId) {
    // 背景层替换：同步自然尺寸与预览尺寸（坐标体系沿用会话固定的 previewScale）
    void store.replaceBackgroundImage(r.image_url, r.width, r.height)
  } else {
    const patch: Partial<EditorLayer> = { url: r.image_url }
    if (r.width && r.height) {
      // 原图像素 → 预览坐标
      const scale = store.exportScale
      patch.width = Math.round(r.width / scale)
      patch.height = Math.round(r.height / scale)
    }
    store.updateLayer(layerId, patch)
  }
  showToast('处理完成', 'success')
}

function handleToolFailed(error: string) {
  toolRunning.value = false
  executingLayerId.value = null
  showToast(error || '处理失败', 'error')
}

// ===== 笔刷选区确认（画布 Enter） =====

/** 画布笔刷模式下按 Enter：生成蒙版并按当前入口提示下一步 */
async function handleConfirmMask() {
  if (!store.isMaskBrushMode) return
  if (!store.hasMaskStrokes) {
    showToast('请先在画布上按住鼠标涂抹选区', 'error')
    return
  }
  try {
    const uri = await store.confirmMaskSelection()
    if (!uri) {
      showToast('选区蒙版生成失败', 'error')
      return
    }
    showToast('选区蒙版已生成', 'success')
  } catch (err) {
    console.error('[editor] 蒙版生成失败', err)
    showToast(getErrorMessage(err, '蒙版生成失败'), 'error')
  }
}

// ===== 上传本地图片（顶栏按钮 / 画布空状态按钮共用同一文件选择框） =====

function handleUploadClick() {
  uploadInputRef.value?.click()
}

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // 置空以便重复选择同一文件
  input.value = ''
  if (!file) return
  try {
    const result = await store.applyUploadedFile(file)
    showToast(result === 'background' ? '图片已作为底图加载' : '图片已添加为图层', 'success')
  } catch (err) {
    console.error('[editor] 图片上传失败', err)
    showToast(getErrorMessage(err, '图片上传失败'), 'error')
  }
}

// ===== 下载当前画布（原图分辨率导出） =====

async function handleDownload() {
  if (downloading.value) return
  if (!store.hasImageContent) {
    showToast('画布为空，无法下载', 'error')
    return
  }
  downloading.value = true
  try {
    // 不传倍率 = 按 store.exportScale 导出原图分辨率
    const url = await canvasRef.value?.exportScene()
    if (!url) {
      showToast('画布导出失败', 'error')
      return
    }
    const a = document.createElement('a')
    a.href = url
    a.download = `ecomai-editor-${Date.now()}.png`
    a.click()
    showToast('已开始下载', 'success')
  } catch (err) {
    console.error('[editor] 画布下载失败', err)
    showToast(getErrorMessage(err, '画布导出失败'), 'error')
  } finally {
    downloading.value = false
  }
}

// ===== 前后对比 =====

async function toggleCompare() {
  if (store.compareMode) {
    store.compareMode = false
    compareCurrentUrl.value = ''
    return
  }
  if (!store.hasImageContent) {
    showToast('画布为空，无法对比', 'error')
    return
  }
  if (!store.sourceImage) {
    showToast('原图不可用，无法对比', 'error')
    return
  }
  // 预览分辨率导出（对比仅示意，导出原图分辨率走保存到历史）
  const url = await canvasRef.value?.exportScene(1)
  if (!url) {
    showToast('画布导出失败', 'error')
    return
  }
  compareCurrentUrl.value = url
  store.compareMode = true
}

// ===== 保存到历史 =====

async function handleSaveHistory() {
  if (savingHistory.value) return
  if (!store.hasImageContent) {
    showToast('画布为空，无法保存', 'error')
    return
  }
  savingHistory.value = true
  try {
    // 确保 documentId 已存在（跳过防抖立即保存）
    await store.flushAutosave()
    if (store.documentId === null) {
      throw new Error('文档保存失败，请稍后重试')
    }
    // 原图分辨率导出（预览缩放不影响清晰度）
    const dataUrl = await canvasRef.value?.exportScene()
    if (!dataUrl) {
      throw new Error('画布导出失败')
    }
    const res = await saveEditorDocumentHistory(store.documentId, dataUrl)
    showToast(`已保存到历史记录（编号 ${res.history_id}）`, 'success')
  } catch (err) {
    console.error('[editor] 保存到历史失败', err)
    showToast(getErrorMessage(err, '保存到历史失败'), 'error')
  } finally {
    savingHistory.value = false
  }
}

// ===== 展示辅助 =====

const saveStateText = computed(() => {
  switch (store.saveState) {
    case 'dirty':
      return '待保存'
    case 'saving':
      return '保存中...'
    case 'saved':
      return '已自动保存'
    case 'error':
      return store.saveError || '保存失败'
    default:
      return '未编辑'
  }
})

const saveStateClass = computed(() => {
  switch (store.saveState) {
    case 'saved':
      return 'text-emerald-500'
    case 'error':
      return 'text-red-500'
    default:
      return 'text-slate-400'
  }
})
</script>

<template>
  <div class="h-full flex flex-col bg-surface-light">
    <!-- 顶栏 -->
    <div class="h-14 shrink-0 bg-white/80 backdrop-blur-xl border-b border-slate-200 flex items-center gap-3 px-4">
      <div class="w-8 h-8 rounded-xl bg-brand-gradient flex items-center justify-center shrink-0">
        <PenTool class="w-4 h-4 text-white" />
      </div>
      <div class="min-w-0">
        <input
          type="text"
          class="glass-input px-2.5 py-1 text-sm font-medium text-slate-800 w-48"
          placeholder="未命名设计"
          :value="store.documentTitle"
          @change="store.setTitle(($event.target as HTMLInputElement).value)"
        />
      </div>
      <span class="text-xs shrink-0" :class="saveStateClass">{{ saveStateText }}</span>

      <div class="flex-1" />

      <!-- 撤销 / 重做 -->
      <button
        type="button"
        class="p-2 rounded-xl text-slate-500 hover:bg-slate-100 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title="撤销（Ctrl+Z）"
        :disabled="!store.canUndo"
        @click="store.undo()"
      >
        <Undo2 class="w-4 h-4" />
      </button>
      <button
        type="button"
        class="p-2 rounded-xl text-slate-500 hover:bg-slate-100 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title="重做（Ctrl+Y）"
        :disabled="!store.canRedo"
        @click="store.redo()"
      >
        <Redo2 class="w-4 h-4" />
      </button>

      <!-- 上传本地图片（作为底图或新增图层） -->
      <button
        type="button"
        class="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200 bg-white border border-slate-200 text-slate-600 hover:border-slate-300"
        @click="handleUploadClick"
      >
        <Upload class="w-4 h-4" />
        上传
      </button>
      <input
        ref="uploadInputRef"
        type="file"
        accept="image/*"
        class="hidden"
        @change="handleFileChange"
      />

      <!-- 下载当前画布（原图分辨率） -->
      <button
        type="button"
        class="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200 bg-white border border-slate-200 text-slate-600 hover:border-slate-300 disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="downloading"
        @click="handleDownload"
      >
        <Loader2 v-if="downloading" class="w-4 h-4 animate-spin" />
        <Download v-else class="w-4 h-4" />
        {{ downloading ? '下载中...' : '下载' }}
      </button>

      <!-- 前后对比 -->
      <button
        type="button"
        class="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200"
        :class="store.compareMode
          ? 'bg-brand-gradient text-white shadow-glow'
          : 'bg-white border border-slate-200 text-slate-600 hover:border-slate-300'"
        @click="toggleCompare"
      >
        <Columns2 class="w-4 h-4" />
        前后对比
      </button>

      <!-- 保存到历史 -->
      <button
        type="button"
        class="btn-primary px-4 py-2 text-sm flex items-center gap-1.5"
        :disabled="savingHistory"
        @click="handleSaveHistory"
      >
        <Loader2 v-if="savingHistory" class="w-4 h-4 animate-spin" />
        <Save v-else class="w-4 h-4" />
        {{ savingHistory ? '保存中...' : '保存到历史' }}
      </button>
    </div>

    <!-- 主体三栏 -->
    <div class="flex-1 flex min-h-0">
      <EditorToolbar />

      <!-- 中间画布区 -->
      <div class="relative flex-1 min-w-0">
        <EditorCanvas
          ref="canvasRef"
          @confirm-mask="handleConfirmMask"
          @upload-request="handleUploadClick"
        />

        <!-- 前后对比覆盖层 -->
        <EditorCompareOverlay
          v-if="store.compareMode && compareCurrentUrl && store.sourceImage"
          :original-url="store.sourceImage.url"
          :current-url="compareCurrentUrl"
        />

        <!-- 工具执行进度 -->
        <div
          v-if="toolRunning"
          class="absolute top-4 left-1/2 -translate-x-1/2 z-30 w-72 bg-white/95 backdrop-blur-xl rounded-2xl shadow-card-hover border border-slate-100 px-4 py-3"
        >
          <div class="flex items-center gap-2 mb-2">
            <Loader2 class="w-4 h-4 text-brand-purple animate-spin shrink-0" />
            <p class="text-xs text-slate-600 truncate">
              {{ taskTracker.step || '任务排队中...' }}
            </p>
            <span class="ml-auto text-xs font-semibold text-brand-purple shrink-0">
              {{ Math.round(taskTracker.pct) }}%
            </span>
          </div>
          <div class="h-1.5 rounded-full bg-slate-100 overflow-hidden">
            <div
              class="h-full rounded-full bg-brand-gradient transition-all duration-300"
              :style="{ width: Math.min(100, Math.max(2, taskTracker.pct)) + '%' }"
            />
          </div>
          <p v-if="taskTracker.source === 'poll'" class="mt-1.5 text-[10px] text-slate-300">
            实时通道不可用，已切换为轮询
          </p>
        </div>

        <!-- 背景图加载中 -->
        <div
          v-if="imageLoading"
          class="absolute inset-0 z-30 bg-white/60 backdrop-blur-sm flex flex-col items-center justify-center"
        >
          <Loader2 class="w-8 h-8 text-brand-purple animate-spin" />
          <p class="mt-3 text-sm text-slate-500">正在加载图片...</p>
        </div>
      </div>

      <!-- 右侧：页签（图层 | AI 助手） -->
      <aside class="w-72 shrink-0 h-full bg-white/80 backdrop-blur-xl border-l border-slate-200 flex flex-col">
        <!-- 页签切换 -->
        <div class="flex items-center gap-1 px-3 pt-2.5 pb-1 shrink-0">
          <button
            type="button"
            class="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-xl text-xs font-medium transition-all duration-200"
            :class="rightTab === 'layers'
              ? 'bg-brand-gradient text-white shadow-glow'
              : 'text-slate-500 hover:bg-slate-100'"
            @click="rightTab = 'layers'"
          >
            <Layers class="w-3.5 h-3.5" />
            图层
          </button>
          <button
            type="button"
            class="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-xl text-xs font-medium transition-all duration-200"
            :class="rightTab === 'agent'
              ? 'bg-brand-gradient text-white shadow-glow'
              : 'text-slate-500 hover:bg-slate-100'"
            @click="rightTab = 'agent'"
          >
            <Sparkles class="w-3.5 h-3.5" />
            AI 助手
          </button>
        </div>

        <!-- 图层面板 + 属性面板（保持挂载，切页不丢状态） -->
        <div v-show="rightTab === 'layers'" class="flex-1 min-h-0 flex flex-col">
          <EditorLayerPanel class="h-[42%] shrink-0" @error="showToast($event, 'error')" />
          <EditorPropertyPanel class="flex-1 min-h-0" :tool-running="toolRunning" @apply="handleApplyTool" />
        </div>

        <!-- AI 助手对话面板 -->
        <EditorAgentPanel v-show="rightTab === 'agent'" class="flex-1 min-h-0" />
      </aside>
    </div>

    <!-- Toast -->
    <transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 translate-y-2"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="opacity-0 translate-y-2"
    >
      <div
        v-if="toast.visible"
        class="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl shadow-card-hover border text-sm bg-white"
        :class="toast.type === 'error' ? 'border-red-100 text-red-500' : toast.type === 'success' ? 'border-emerald-100 text-emerald-600' : 'border-slate-100 text-slate-600'"
      >
        <XCircle v-if="toast.type === 'error'" class="w-4 h-4 shrink-0" />
        <CheckCircle2 v-else-if="toast.type === 'success'" class="w-4 h-4 shrink-0" />
        <span>{{ toast.text }}</span>
      </div>
    </transition>
  </div>
</template>
