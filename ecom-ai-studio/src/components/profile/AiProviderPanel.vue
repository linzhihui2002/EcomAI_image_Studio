<script setup lang="ts">
/**
 * 模型服务商配置（BYOK）面板
 *
 * 结构：
 *   - 顶部总开关「优先使用我自己的模型额度」
 *   - 3 个分类分区：生图模型 / 多模态视觉模型 / 文本模型（顺序即号池尝试顺序）
 *   - 每个分区内为条目卡片（启用状态、优先级、最近测试结果、上移/下移/测试/编辑/删除）
 *   - 新增 / 编辑共用弹窗；删除走二次确认
 */
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import type { Component } from 'vue'
import {
  Plus, Pencil, Trash2, ArrowUp, ArrowDown, Loader2, Server,
  ShieldCheck, AlertTriangle, AlertCircle, Check, X, Zap,
  Image as ImageIcon, Eye, EyeOff, FileText,
} from 'lucide-vue-next'
import {
  fetchAiProviders,
  createAiProvider,
  updateAiProvider,
  deleteAiProvider,
  moveAiProvider,
  testAiProvider,
  updateAiProviderSettings,
} from '@/api/aiProvider'
import type {
  AiProvider,
  AiProviderCategory,
  AiProviderMoveDirection,
} from '@/api/aiProvider'
import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'

// ==================== 分类定义（顺序即展示顺序） ====================

interface CategoryMeta {
  key: AiProviderCategory
  title: string
  desc: string
  icon: Component
}

const CATEGORIES: CategoryMeta[] = [
  {
    key: 'image_gen',
    title: '生图模型',
    desc: '文生图、图生图、批量套图、编辑器改图等生图场景',
    icon: ImageIcon,
  },
  {
    key: 'multimodal',
    title: '多模态视觉模型',
    desc: '商品图分析、合规审查、反推提示词、计划分析等视觉理解场景',
    icon: Eye,
  },
  {
    key: 'llm',
    title: '文本模型',
    desc: '文案生成、专业模式方案优化、编辑器 Agent 规划等文本场景',
    icon: FileText,
  },
]

function categoryTitle(key: AiProviderCategory): string {
  return CATEGORIES.find((c) => c.key === key)?.title ?? ''
}

// ==================== 列表与总开关 ====================

const loading = ref(false)
const loadError = ref('')
const providers = ref<AiProvider[]>([])
const useOwnProvider = ref(false)
const savingToggle = ref(false)

/** 正在执行（启停/移动/删除）的条目 ID 集合，用于禁用按钮 */
const busyIds = ref<number[]>([])
/** 正在测试的条目 ID */
const testingId = ref<number | null>(null)

const feedback = ref<{ type: 'success' | 'error'; text: string } | null>(null)
let feedbackTimer: ReturnType<typeof setTimeout> | null = null

function showFeedback(type: 'success' | 'error', text: string) {
  feedback.value = { type, text }
  if (feedbackTimer) clearTimeout(feedbackTimer)
  feedbackTimer = setTimeout(() => {
    feedback.value = null
    feedbackTimer = null
  }, 4000)
}

onUnmounted(() => {
  if (feedbackTimer) clearTimeout(feedbackTimer)
})

const grouped = computed<Record<AiProviderCategory, AiProvider[]>>(() => {
  const map: Record<AiProviderCategory, AiProvider[]> = {
    image_gen: [],
    multimodal: [],
    llm: [],
  }
  for (const item of providers.value) {
    if (map[item.category]) map[item.category].push(item)
  }
  return map
})

function isBusy(id: number): boolean {
  return busyIds.value.includes(id)
}

function markBusy(id: number) {
  if (!busyIds.value.includes(id)) busyIds.value = [...busyIds.value, id]
}

function unmarkBusy(id: number) {
  busyIds.value = busyIds.value.filter((item) => item !== id)
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchAiProviders()
    providers.value = res.items
    useOwnProvider.value = res.useOwnProvider
  } catch (err) {
    loadError.value = getErrorMessage(err, ERROR_DEFAULTS.LOAD_FAILED)
  } finally {
    loading.value = false
  }
}

/** 静默刷新列表（不显示整页 loading，用于增删改/移动/测试后的同步） */
async function refreshSilently() {
  try {
    const res = await fetchAiProviders()
    providers.value = res.items
    useOwnProvider.value = res.useOwnProvider
  } catch (err) {
    showFeedback('error', getErrorMessage(err, ERROR_DEFAULTS.LOAD_FAILED))
  }
}

onMounted(load)

// ==================== 总开关 ====================

async function handleToggleOwnProvider() {
  if (savingToggle.value) return
  savingToggle.value = true
  try {
    useOwnProvider.value = await updateAiProviderSettings(!useOwnProvider.value)
    showFeedback(
      'success',
      useOwnProvider.value ? '已开启：优先使用你自己的模型额度' : '已关闭：全部使用平台通道',
    )
  } catch (err) {
    showFeedback('error', getErrorMessage(err, ERROR_DEFAULTS.SAVE_FAILED))
  } finally {
    savingToggle.value = false
  }
}

// ==================== 条目操作 ====================

async function handleToggleEnabled(item: AiProvider) {
  if (isBusy(item.id)) return
  markBusy(item.id)
  try {
    const updated = await updateAiProvider(item.id, { isEnabled: !item.isEnabled })
    const index = providers.value.findIndex((p) => p.id === updated.id)
    if (index >= 0) providers.value[index] = updated
  } catch (err) {
    showFeedback('error', getErrorMessage(err, ERROR_DEFAULTS.SAVE_FAILED))
  } finally {
    unmarkBusy(item.id)
  }
}

async function handleMove(item: AiProvider, direction: AiProviderMoveDirection) {
  if (isBusy(item.id)) return
  markBusy(item.id)
  try {
    await moveAiProvider(item.id, direction)
    await refreshSilently()
  } catch (err) {
    showFeedback('error', getErrorMessage(err, '调整顺序失败，请稍后重试'))
  } finally {
    unmarkBusy(item.id)
  }
}

async function handleTest(item: AiProvider) {
  if (testingId.value !== null) return
  testingId.value = item.id
  try {
    const result = await testAiProvider(item.id)
    await refreshSilently()
    if (result.ok) {
      showFeedback('success', `「${item.name}」连通性测试通过`)
    } else {
      showFeedback(
        'error',
        `「${item.name}」测试失败：${result.error || '未知错误'}`,
      )
    }
  } catch (err) {
    showFeedback('error', getErrorMessage(err, '测试失败，请稍后重试'))
  } finally {
    testingId.value = null
  }
}

// ==================== 删除（二次确认） ====================

const pendingDelete = ref<{ id: number; label: string } | null>(null)
const deleteLoading = ref(false)

function requestDelete(item: AiProvider) {
  pendingDelete.value = { id: item.id, label: item.name }
}

async function executeDelete() {
  if (!pendingDelete.value) return
  const target = pendingDelete.value
  deleteLoading.value = true
  try {
    await deleteAiProvider(target.id)
    pendingDelete.value = null
    await refreshSilently()
    showFeedback('success', '配置已删除')
  } catch (err) {
    pendingDelete.value = null
    showFeedback('error', getErrorMessage(err, ERROR_DEFAULTS.DELETE_FAILED))
  } finally {
    deleteLoading.value = false
  }
}

// ==================== 新增 / 编辑弹窗 ====================

const modalOpen = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const modalCategory = ref<AiProviderCategory>('image_gen')
const editingId = ref<number | null>(null)
/** 编辑时展示的当前 Key 掩码（不回填明文） */
const editingKeyMasked = ref('')
const formError = ref('')
const saving = ref(false)
/** API Key 明文显示开关（text + CSS 掩码方案，见模板说明） */
const showApiKey = ref(false)

const form = reactive({
  name: '',
  apiBase: '',
  apiKey: '',
  modelName: '',
})

const modalTitle = computed(() =>
  modalMode.value === 'create' ? '添加模型服务商配置' : '编辑模型服务商配置',
)

function openCreate(category: AiProviderCategory) {
  modalMode.value = 'create'
  modalCategory.value = category
  editingId.value = null
  editingKeyMasked.value = ''
  form.name = ''
  form.apiBase = ''
  form.apiKey = ''
  form.modelName = ''
  formError.value = ''
  showApiKey.value = false
  modalOpen.value = true
}

function openEdit(item: AiProvider) {
  modalMode.value = 'edit'
  modalCategory.value = item.category
  editingId.value = item.id
  editingKeyMasked.value = item.apiKeyMasked
  form.name = item.name
  form.apiBase = item.apiBase
  form.apiKey = ''
  form.modelName = item.modelName
  formError.value = ''
  showApiKey.value = false
  modalOpen.value = true
}

function closeModal() {
  if (saving.value) return
  modalOpen.value = false
  formError.value = ''
}

async function submitModal() {
  formError.value = ''

  const name = form.name.trim()
  const apiBase = form.apiBase.trim()
  const apiKey = form.apiKey.trim()
  const modelName = form.modelName.trim()

  if (!name) {
    formError.value = '请填写备注名'
    return
  }
  if (!apiBase) {
    formError.value = '请填写 API Base'
    return
  }
  if (!/^https?:\/\//i.test(apiBase)) {
    formError.value = 'API Base 需以 http:// 或 https:// 开头'
    return
  }
  if (!modelName) {
    formError.value = '请填写模型名'
    return
  }
  if (modalMode.value === 'create' && !apiKey) {
    formError.value = '请填写 API Key'
    return
  }

  saving.value = true
  try {
    if (modalMode.value === 'create') {
      await createAiProvider({ category: modalCategory.value, name, apiBase, apiKey, modelName })
      showFeedback('success', '配置已添加')
    } else if (editingId.value !== null) {
      // apiKey 留空传空串，后端理解为「不修改」
      await updateAiProvider(editingId.value, { name, apiBase, apiKey, modelName })
      showFeedback('success', '配置已更新')
    }
    modalOpen.value = false
    formError.value = ''
    await refreshSilently()
  } catch (err) {
    formError.value = getErrorMessage(err, ERROR_DEFAULTS.SAVE_FAILED)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="space-y-5">
    <!-- 反馈提示 -->
    <Transition name="fade">
      <div
        v-if="feedback"
        class="p-3 rounded-xl text-sm animate-fade-in border"
        :class="
          feedback.type === 'success'
            ? 'bg-green-50 border-green-200 text-green-700'
            : 'bg-red-50 border-red-200 text-red-600'
        "
      >
        {{ feedback.text }}
      </div>
    </Transition>

    <!-- ==================== 总开关 ==================== -->
    <div class="glass-card p-5 rounded-2xl">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0">
          <h3 class="text-base font-semibold text-slate-900">优先使用我自己的模型额度</h3>
          <p class="text-xs text-slate-500 mt-1 leading-relaxed">
            开启后，下方已配置的分类将使用你自己的 API 额度调用模型，平台不再扣除灵感币；未配置的分类仍使用平台通道。
          </p>
        </div>
        <button
          type="button"
          role="switch"
          :aria-checked="useOwnProvider"
          :disabled="savingToggle"
          aria-label="优先使用我自己的模型额度"
          class="relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :class="useOwnProvider ? 'bg-brand-purple' : 'bg-slate-200'"
          @click="handleToggleOwnProvider"
        >
          <span
            class="absolute left-0 h-5 w-5 rounded-full bg-white shadow transition-transform"
            :class="useOwnProvider ? 'translate-x-[22px]' : 'translate-x-0.5'"
          />
          <Loader2
            v-if="savingToggle"
            class="absolute right-1.5 w-3 h-3 text-white/80 animate-spin"
          />
        </button>
      </div>
    </div>

    <!-- ==================== 加载 / 错误 ==================== -->
    <div v-if="loading" class="glass-card p-10 rounded-2xl flex flex-col items-center justify-center">
      <Loader2 class="w-6 h-6 text-brand-purple animate-spin mb-3" />
      <p class="text-sm text-slate-500">正在加载配置...</p>
    </div>

    <div v-else-if="loadError" class="glass-card p-6 rounded-2xl text-center">
      <AlertCircle class="w-8 h-8 text-red-400 mx-auto mb-2" />
      <p class="text-sm text-slate-600 mb-4">{{ loadError }}</p>
      <button class="btn-secondary px-4 py-2 text-sm" @click="load">重新加载</button>
    </div>

    <!-- ==================== 分类分区 ==================== -->
    <template v-else>
      <div v-for="cat in CATEGORIES" :key="cat.key" class="glass-card p-5 rounded-2xl">
        <!-- 分区标题 -->
        <div class="flex items-start gap-3 mb-4">
          <div
            class="w-9 h-9 rounded-lg bg-brand-gradient-subtle flex items-center justify-center flex-shrink-0"
          >
            <component :is="cat.icon" class="w-5 h-5 text-brand-purple" />
          </div>
          <div class="min-w-0">
            <h3 class="text-base font-semibold text-slate-900">{{ cat.title }}</h3>
            <p class="text-xs text-slate-500 mt-0.5 leading-relaxed">{{ cat.desc }}</p>
          </div>
        </div>

        <!-- 空状态 -->
        <div
          v-if="grouped[cat.key].length === 0"
          class="flex flex-col items-center justify-center py-8 rounded-xl border border-dashed border-slate-200 bg-slate-50/60"
        >
          <Server class="w-8 h-8 text-slate-300 mb-2" />
          <p class="text-sm text-slate-400">还没有配置，添加后即可使用你自己的额度</p>
        </div>

        <!-- 条目列表 -->
        <div v-else class="space-y-3">
          <div
            v-for="(item, index) in grouped[cat.key]"
            :key="item.id"
            class="rounded-xl border border-slate-200 bg-white p-4"
          >
            <div class="flex items-start gap-3">
              <div class="flex-1 min-w-0">
                <!-- 名称 + 状态徽标 + 优先级 -->
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-sm font-semibold text-slate-900 break-all">{{ item.name }}</span>
                  <span
                    class="inline-flex items-center px-2 py-0.5 rounded-full border text-xs font-medium"
                    :class="
                      item.isEnabled
                        ? 'bg-green-50 border-green-200 text-green-600'
                        : 'bg-slate-100 border-slate-200 text-slate-500'
                    "
                  >
                    {{ item.isEnabled ? '启用' : '已停用' }}
                  </span>
                  <span class="text-xs text-slate-400 font-mono">#{{ index + 1 }}</span>
                </div>

                <!-- 详情 -->
                <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  <span>
                    模型名：<span class="font-mono text-slate-700">{{ item.modelName }}</span>
                  </span>
                  <span class="break-all">
                    API Base：<span class="font-mono text-slate-700">{{ item.apiBase }}</span>
                  </span>
                  <span>
                    API Key：<span class="font-mono text-slate-700">{{ item.apiKeyMasked }}</span>
                  </span>
                </div>

                <!-- 最近状态 -->
                <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                  <span
                    v-if="item.lastTestOk === true"
                    class="inline-flex items-center gap-1 text-green-600"
                  >
                    <Check class="w-3.5 h-3.5" />
                    测试通过 · {{ item.lastTestAt || '-' }}
                  </span>
                  <span
                    v-else-if="item.lastTestOk === false"
                    class="inline-flex items-center gap-1 text-red-500"
                  >
                    <AlertCircle class="w-3.5 h-3.5" />
                    测试失败：{{ item.lastTestError || '未知错误' }}
                  </span>
                  <span
                    v-if="item.failureCount > 0"
                    class="inline-flex items-center gap-1 text-amber-600"
                  >
                    <AlertTriangle class="w-3.5 h-3.5" />
                    累计失败 {{ item.failureCount }} 次
                  </span>
                </div>
              </div>

              <!-- 操作区 -->
              <div class="flex items-center gap-0.5 flex-shrink-0">
                <button
                  type="button"
                  role="switch"
                  :aria-checked="item.isEnabled"
                  :disabled="isBusy(item.id)"
                  :title="item.isEnabled ? '停用该配置' : '启用该配置'"
                  :aria-label="item.isEnabled ? '停用该配置' : '启用该配置'"
                  class="relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  :class="item.isEnabled ? 'bg-brand-purple' : 'bg-slate-200'"
                  @click="handleToggleEnabled(item)"
                >
                  <span
                    class="absolute left-0 h-4 w-4 rounded-full bg-white shadow transition-transform"
                    :class="item.isEnabled ? 'translate-x-[20px]' : 'translate-x-0.5'"
                  />
                </button>

                <button
                  type="button"
                  :disabled="index === 0 || isBusy(item.id)"
                  title="上移"
                  aria-label="上移"
                  class="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  @click="handleMove(item, 'up')"
                >
                  <ArrowUp class="w-4 h-4" />
                </button>

                <button
                  type="button"
                  :disabled="index === grouped[cat.key].length - 1 || isBusy(item.id)"
                  title="下移"
                  aria-label="下移"
                  class="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  @click="handleMove(item, 'down')"
                >
                  <ArrowDown class="w-4 h-4" />
                </button>

                <button
                  type="button"
                  :disabled="testingId !== null || isBusy(item.id)"
                  title="测试连通性"
                  aria-label="测试连通性"
                  class="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  @click="handleTest(item)"
                >
                  <Loader2 v-if="testingId === item.id" class="w-4 h-4 animate-spin" />
                  <Zap v-else class="w-4 h-4" />
                </button>

                <button
                  type="button"
                  :disabled="isBusy(item.id)"
                  title="编辑"
                  aria-label="编辑"
                  class="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  @click="openEdit(item)"
                >
                  <Pencil class="w-4 h-4" />
                </button>

                <button
                  type="button"
                  :disabled="isBusy(item.id)"
                  title="删除"
                  aria-label="删除"
                  class="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  @click="requestDelete(item)"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 添加配置 -->
        <div class="mt-4 flex justify-end">
          <button
            class="btn-secondary inline-flex items-center gap-1.5 px-3.5 py-2 text-sm"
            @click="openCreate(cat.key)"
          >
            <Plus class="w-4 h-4" />
            添加配置
          </button>
        </div>
      </div>
    </template>

    <!-- ==================== 新增 / 编辑弹窗 ==================== -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="modalOpen"
          class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm px-4"
          @click.self="closeModal"
        >
          <div class="bg-white rounded-2xl shadow-2xl p-6 max-w-lg w-full max-h-[90vh] overflow-y-auto">
            <div class="flex items-center justify-between mb-5">
              <h3 class="text-lg font-semibold text-slate-900">{{ modalTitle }}</h3>
              <button
                type="button"
                class="p-1.5 rounded-lg hover:bg-slate-100 transition-colors"
                aria-label="关闭"
                @click="closeModal"
              >
                <X class="w-4 h-4 text-slate-500" />
              </button>
            </div>

            <p class="text-xs text-slate-500 mb-5">
              所属分类：<span class="text-slate-700 font-medium">{{ categoryTitle(modalCategory) }}</span>
            </p>

            <div class="space-y-4">
              <div>
                <label class="block text-sm text-slate-600 mb-1.5">备注名</label>
                <input
                  v-model="form.name"
                  type="text"
                  name="provider-label"
                  autocomplete="off"
                  placeholder="例如：我的主号 / 备用号"
                  class="w-full px-4 py-2.5 text-sm rounded-xl border border-slate-200 bg-white focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 transition-all outline-none"
                />
              </div>

              <div>
                <label class="block text-sm text-slate-600 mb-1.5">API Base</label>
                <input
                  v-model="form.apiBase"
                  type="text"
                  name="provider-api-base"
                  autocomplete="off"
                  placeholder="https://api.example.com/v1"
                  class="w-full px-4 py-2.5 text-sm font-mono rounded-xl border border-slate-200 bg-white focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 transition-all outline-none"
                />
              </div>

              <div>
                <div class="flex items-center justify-between mb-1.5">
                  <label class="block text-sm text-slate-600">API Key</label>
                  <button
                    type="button"
                    class="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                    :aria-label="showApiKey ? '隐藏 API Key' : '显示 API Key'"
                    @click="showApiKey = !showApiKey"
                  >
                    <EyeOff v-if="showApiKey" class="w-4 h-4" />
                    <Eye v-else class="w-4 h-4" />
                  </button>
                </div>
                <!-- 刻意不用 type="password"：密码管理器会把含 password 输入框的表单当成登录表单，
                     导致聚焦时弹出凭证下拉、提交后弹出"保存密码"。改用 text + CSS 圆点掩码。 -->
                <input
                  v-model="form.apiKey"
                  type="text"
                  name="provider-api-key"
                  autocomplete="off"
                  spellcheck="false"
                  autocapitalize="off"
                  :placeholder="modalMode === 'edit' ? '留空表示不修改' : '请输入模型服务商签发的 API Key'"
                  :class="[
                    'w-full px-4 py-2.5 text-sm font-mono rounded-xl border border-slate-200 bg-white focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 transition-all outline-none',
                    showApiKey ? '' : 'api-key-masked',
                  ]"
                />
                <p v-if="modalMode === 'edit'" class="text-xs text-slate-400 mt-1">
                  当前 Key：<span class="font-mono">{{ editingKeyMasked }}</span>
                </p>
              </div>

              <div>
                <label class="block text-sm text-slate-600 mb-1.5">模型名</label>
                <input
                  v-model="form.modelName"
                  type="text"
                  name="provider-model-name"
                  autocomplete="off"
                  placeholder="例如：gpt-image-1 / qwen-vl-max"
                  class="w-full px-4 py-2.5 text-sm font-mono rounded-xl border border-slate-200 bg-white focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 transition-all outline-none"
                />
              </div>
            </div>

            <div class="mt-4 flex items-start gap-2 p-3 rounded-xl bg-slate-50 text-xs text-slate-500">
              <ShieldCheck class="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
              <span>请手动填写模型服务商签发的 API Key（勿填网站账号密码，二者凭证互不通用）。Key 将加密存储，仅用于调用你填写的模型服务，页面不会回显完整 Key。</span>
            </div>

            <div
              v-if="formError"
              class="mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 animate-fade-in"
            >
              {{ formError }}
            </div>

            <div class="mt-6 flex gap-3 justify-end">
              <button
                type="button"
                class="px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                :disabled="saving"
                @click="closeModal"
              >
                取消
              </button>
              <button
                type="button"
                class="btn-primary inline-flex items-center gap-2 px-5 py-2.5 text-sm"
                :disabled="saving"
                @click="submitModal"
              >
                <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
                <span>{{ saving ? '保存中...' : '保存' }}</span>
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ==================== 删除二次确认 ==================== -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="pendingDelete"
          class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm px-4"
          @click.self="pendingDelete = null"
        >
          <div class="bg-white rounded-2xl shadow-2xl p-6 max-w-md w-full">
            <div class="flex items-center gap-3 mb-4">
              <div class="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                <AlertTriangle class="w-5 h-5 text-red-500" />
              </div>
              <h3 class="text-lg font-semibold text-slate-800">确认删除</h3>
            </div>
            <p class="text-sm text-slate-600 mb-6">
              确定要删除「{{ pendingDelete.label }}」吗？删除后该配置将不再参与模型调用，此操作无法撤销。
            </p>
            <div class="flex gap-3 justify-end">
              <button
                type="button"
                class="px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
                :disabled="deleteLoading"
                @click="pendingDelete = null"
              >
                取消
              </button>
              <button
                type="button"
                class="px-4 py-2 text-sm font-medium text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
                :disabled="deleteLoading"
                @click="executeDelete"
              >
                <Loader2 v-if="deleteLoading" class="w-4 h-4 animate-spin" />
                {{ deleteLoading ? '删除中...' : '确认删除' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* API Key 视觉掩码：保持 type="text" 以避开浏览器密码管理器，
   同时用 CSS 圆点达到与密码框相同的遮蔽效果（Chrome/Edge/Safari/Firefox 均支持） */
.api-key-masked {
  -webkit-text-security: disc;
}
</style>
