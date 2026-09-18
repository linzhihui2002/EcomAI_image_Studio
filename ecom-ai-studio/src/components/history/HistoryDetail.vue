<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { X, Download, Share2, UserCheck, ChevronDown, Users, Heart, PenLine } from 'lucide-vue-next'
import { fetchHistoryDetail, shareToTeam, unshareFromTeam } from '@/api/history'
import { addHistoryFavorite } from '@/api/favorites'
import { getMyTeams } from '@/api/team'
import { SUB_CATEGORY_LABELS } from '@/types'
import type { HistoryRecordDetail, Team } from '@/types'
import { getErrorMessage } from '@/lib/error'

const props = defineProps<{
  recordId: number
}>()

const emit = defineEmits<{
  close: []
}>()

const router = useRouter()

// 跳转到编辑器，携带图片 URL 作为 imageId
function handleEdit(url: string) {
  router.push({ path: '/editor', query: { imageId: url } })
}

const loading = ref<boolean>(true)
const error = ref<string | null>(null)
const detail = ref<HistoryRecordDetail | null>(null)
const shareLoading = ref<boolean>(false)
const shareError = ref<string | null>(null)
const teams = ref<Team[]>([])
const showTeamSelector = ref<boolean>(false)
const favLoading = ref<boolean>(false)
const favorited = ref<boolean>(false)
const favError = ref<string | null>(null)

// 图片加载失败追踪 (key: "input-0", "output-0" 等)
const imgErrors = reactive<Set<string>>(new Set())

function handleImgError(key: string) {
  imgErrors.add(key)
}

onMounted(async () => {
  try {
    const [detailRes, teamsRes] = await Promise.all([
      fetchHistoryDetail(props.recordId),
      getMyTeams().catch(() => ({ data: { teams: [] } })),
    ])
    detail.value = detailRes.data
    teams.value = teamsRes.data?.teams || []
  } catch (err: unknown) {
    error.value = getErrorMessage(err, '加载历史记录详情失败')
  } finally {
    loading.value = false
  }
})

const IMAGE_KEY_PATTERNS = [
  'product_images',
  'images',
  'image',
  'product_image',
  'reference_image',
  'person_image',
  'model_image',
]

function isImageValue(value: unknown): value is string {
  return typeof value === 'string' && (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('data:') || value.startsWith('blob:') || value.startsWith('/api/v1/images/'))
}

function isImageArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => isImageValue(item))
}

const inputImages = computed<string[]>(() => {
  if (!detail.value) return []
  const data = detail.value.input_data
  if (!data || typeof data !== 'object') return []

  const images: string[] = []
  for (const key of IMAGE_KEY_PATTERNS) {
    const val = data[key]
    if (val === undefined || val === null) continue
    if (isImageValue(val)) {
      images.push(val)
    } else if (isImageArray(val)) {
      images.push(...val)
    }
  }
  return images
})

/** 字段中文标签（找不到时回退原始键名） */
const FIELD_LABELS: Record<string, string> = {
  platform: '平台',
  region: '地区',
  target_language: '目标语言',
  size: '尺寸',
  reference_text: '参考文案',
  product_info: '商品信息',
  image_groups: '图片分组',
  batch_id: '批次ID',
  error: '错误信息',
}

const PRODUCT_INFO_LABELS: Record<string, string> = {
  product_name: '商品名称',
  target_audience: '目标人群',
  selling_points: '卖点',
  usage_scenario: '使用场景',
  product_category: '商品类目',
  selling_points_en: '英文卖点',
}

const IMAGE_TYPE_LABELS: Record<string, string> = {
  main_image: '主图',
  sub_image: '副图',
  white_bg: '白底图',
  scene: '场景图',
  selling_point: '卖点图',
  checklist: '清单图',
  material: '材质图',
  size_chart: '尺寸图',
  other: '其他',
}

interface DisplayRow {
  label: string
  value: string
}

interface DisplayField {
  key: string
  label: string
  kind: 'text' | 'kv' | 'list'
  value?: string
  rows?: DisplayRow[]
  items?: { title: string; text?: string; rows?: DisplayRow[] }[]
}

/** 标量/嵌套值 → 紧凑可读文本（对象优先取 name/desc 语义） */
function formatScalar(val: unknown): string {
  if (val === null || val === undefined) return ''
  if (typeof val === 'boolean') return val ? '是' : '否'
  if (Array.isArray(val)) {
    return val.map((item) => formatScalar(item)).filter(Boolean).join('、')
  }
  if (typeof val === 'object') {
    const rec = val as Record<string, unknown>
    const name = rec.name ?? rec.title ?? rec.label
    const desc = rec.desc ?? rec.description
    if (name && desc) return `${name}（${desc}）`
    if (name) return String(name)
    return Object.entries(rec)
      .filter(([, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => `${k}: ${formatScalar(v)}`)
      .join('、')
  }
  return String(val)
}

/** 对象 → 可读行（按 labels 映射中文标签） */
function buildRows(obj: Record<string, unknown>, labels: Record<string, string>): DisplayRow[] {
  const rows: DisplayRow[] = []
  for (const [key, val] of Object.entries(obj)) {
    if (val === undefined || val === null || val === '') continue
    rows.push({ label: labels[key] || key, value: formatScalar(val) })
  }
  return rows
}

/** 单字段 → 展示结构（text / kv / list），避免直接输出 raw JSON */
function buildField(key: string, val: unknown, labels: Record<string, string>): DisplayField {
  const label = labels[key] || key
  const nestedLabels = key === 'product_info' ? PRODUCT_INFO_LABELS : labels

  if (Array.isArray(val)) {
    const items = val.map((item, i) => {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const rec = item as Record<string, unknown>
        const title = String(rec.slot_name ?? rec.name ?? rec.key ?? rec.title ?? `第 ${i + 1} 项`)
        return { title, rows: buildRows(rec, nestedLabels) }
      }
      return { title: `第 ${i + 1} 项`, text: formatScalar(item) }
    })
    return { key, label, kind: 'list', items }
  }

  if (val && typeof val === 'object') {
    return { key, label, kind: 'kv', rows: buildRows(val as Record<string, unknown>, nestedLabels) }
  }

  return { key, label, kind: 'text', value: formatScalar(val) }
}

/** 生成任务项（简单/专业模式：output_data.tasks） */
interface HistoryTaskItem {
  taskId: string
  label: string
  status: string
  url: string | null
  prompt: string
  error: string | null
}

const outputTasks = computed<HistoryTaskItem[]>(() => {
  if (!detail.value) return []
  const data = detail.value.output_data
  if (!data || typeof data !== 'object') return []
  const tasks = data.tasks
  if (!Array.isArray(tasks)) return []

  return tasks
    .filter((task: any) => task && typeof task === 'object')
    .map((task: any, i: number) => {
      const url = task.image_url || task.result_url || ''
      return {
        taskId: String(task.task_id || `task-${i}`),
        label: task.slot_name || IMAGE_TYPE_LABELS[task.image_type] || `图片 ${i + 1}`,
        status: String(task.status || ''),
        url: isImageValue(url) ? url : null,
        prompt: typeof task.prompt_used === 'string' ? task.prompt_used : '',
        error: task.error_msg || task.error_message || null,
      }
    })
})

const expandedPrompts = reactive<Set<string>>(new Set())

function togglePrompt(taskId: string) {
  if (expandedPrompts.has(taskId)) {
    expandedPrompts.delete(taskId)
  } else {
    expandedPrompts.add(taskId)
  }
}

const inputFields = computed<DisplayField[]>(() => {
  if (!detail.value) return []
  const data = detail.value.input_data
  if (!data || typeof data !== 'object') return []

  const fields: DisplayField[] = []
  for (const [key, val] of Object.entries(data)) {
    if (IMAGE_KEY_PATTERNS.includes(key)) continue
    if (val === undefined || val === null) continue
    fields.push(buildField(key, val, FIELD_LABELS))
  }
  return fields
})

const outputImages = computed<{ url: string }[]>(() => {
  if (!detail.value) return []
  const data = detail.value.output_data
  if (!data || typeof data !== 'object') return []

  const images: { url: string }[] = []

  // Direct image keys
  const directKeys = ['image', 'images', 'merged_image', 'result_image']
  for (const key of directKeys) {
    const val = data[key]
    if (val === undefined || val === null) continue
    if (isImageValue(val)) {
      images.push({ url: val })
    } else if (isImageArray(val)) {
      images.push(...val.map((url) => ({ url })))
    }
  }

  // Tasks array with image_url or result_url（有任务画廊时由画廊渲染，避免重复）
  const tasks = data.tasks
  if (Array.isArray(tasks) && outputTasks.value.length === 0) {
    for (const task of tasks) {
      if (task && typeof task === 'object') {
        const url = task.image_url || task.result_url
        if (isImageValue(url)) {
          images.push({ url })
        }
      }
    }
  }

  return images
})

// 生图计划分析：从 output_data.images 提取方案数据
const isPlanAnalysis = computed(() => detail.value?.sub_category === 'plan_analysis')

interface PlanImageItem {
  index: number
  title: string
  plan: string
  reason: string
  prompt_cn: string
  prompt_en: string
  backup_prompt_cn: string
  backup_prompt_en: string
}

const planAnalysisImages = computed<PlanImageItem[]>(() => {
  if (!isPlanAnalysis.value || !detail.value) return []
  const data = detail.value.output_data
  if (!data || typeof data !== 'object') return []
  const images = data.images
  if (!Array.isArray(images)) return []
  return images.filter((img: any) => img && typeof img === 'object')
})

// plan_analysis 的 images 是方案对象数组（非图片 URL），不应被跳过
const imageKeys = computed(() => {
  const base = new Set(['image', 'merged_image', 'result_image', 'tasks'])
  if (!isPlanAnalysis.value) {
    base.add('images')
  }
  return base
})

const outputFields = computed<DisplayField[]>(() => {
  if (!detail.value) return []
  const data = detail.value.output_data
  if (!data || typeof data !== 'object') return []

  const fields: DisplayField[] = []
  for (const [key, val] of Object.entries(data)) {
    if (imageKeys.value.has(key)) continue
    if (val === undefined || val === null) continue
    fields.push(buildField(key, val, FIELD_LABELS))
  }
  return fields
})

async function handleShare(teamId: string) {
  shareError.value = null
  shareLoading.value = true
  showTeamSelector.value = false
  try {
    await shareToTeam(props.recordId, teamId)
    if (detail.value) {
      detail.value.shared_to_team = true
      detail.value.shared_team_id = teamId
    }
  } catch (err: unknown) {
    shareError.value = getErrorMessage(err, '分享失败，请稍后重试')
  } finally {
    shareLoading.value = false
  }
}

async function handleUnshare() {
  shareError.value = null
  shareLoading.value = true
  try {
    await unshareFromTeam(props.recordId)
    if (detail.value) {
      detail.value.shared_to_team = false
      detail.value.shared_team_id = null
    }
  } catch (err: unknown) {
    shareError.value = getErrorMessage(err, '取消分享失败，请稍后重试')
  } finally {
    shareLoading.value = false
  }
}

function handleDownload(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = 'ecomai-history.jpg'
  a.click()
}

async function handleFavorite() {
  if (favLoading.value || favorited.value) return
  favLoading.value = true
  favError.value = null
  try {
    await addHistoryFavorite(props.recordId)
    favorited.value = true
  } catch (err: unknown) {
    const msg = getErrorMessage(err, '收藏失败，请稍后重试')
    // 409 / 已收藏 也标记为已收藏
    if (msg.includes('已收藏') || (err as any)?.code === 2006) {
      favorited.value = true
    } else {
      favError.value = msg
    }
  } finally {
    favLoading.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="emit('close')">
      <!-- Modal -->
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto m-4">
        <!-- Close button -->
        <div class="sticky top-0 bg-white border-b border-slate-100 px-6 py-4 flex items-center justify-between z-10">
          <h3 class="text-lg font-semibold text-slate-900">{{ detail?.title }}</h3>
          <button @click="emit('close')" class="p-2 rounded-lg hover:bg-slate-100 text-slate-400">
            <X class="w-5 h-5" />
          </button>
        </div>

        <!-- Loading -->
        <div v-if="loading" class="p-8 text-center">
          <svg class="animate-spin w-8 h-8 mx-auto text-brand-purple" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p class="mt-3 text-sm text-slate-400">加载中...</p>
        </div>

        <!-- Error -->
        <div v-else-if="error" class="p-8 text-center">
          <p class="text-red-500">{{ error }}</p>
        </div>

        <!-- Content -->
        <div v-else-if="detail" class="p-6 space-y-6">
          <!-- Meta info -->
          <div class="flex items-center gap-3 text-sm text-slate-500">
            <span class="px-2 py-0.5 rounded-full bg-brand-purple/10 text-brand-purple text-xs">
              {{ SUB_CATEGORY_LABELS[detail.sub_category] }}
            </span>
            <span>{{ detail.created_at }}</span>
          </div>

          <!-- Input section -->
          <div>
            <h4 class="text-sm font-medium text-slate-700 mb-3">输入内容</h4>
            <!-- Show input images if any -->
            <div v-if="inputImages.length > 0" class="grid grid-cols-3 gap-2 mb-3">
              <template v-for="(img, i) in inputImages" :key="i">
                <img
                  v-if="!imgErrors.has(`input-${i}`)"
                  :src="img"
                  class="w-full aspect-square object-cover rounded-lg canvas-checkerboard"
                  @error="handleImgError(`input-${i}`)"
                />
                <div v-else class="w-full aspect-square rounded-lg bg-slate-100 flex items-center justify-center">
                  <X class="w-6 h-6 text-slate-300" />
                </div>
              </template>
            </div>
            <!-- Show input fields（键值 / 列表可读化，不输出 raw JSON） -->
            <div v-if="inputFields.length > 0" class="space-y-2">
              <div v-for="field in inputFields" :key="field.key" class="text-sm">
                <template v-if="field.kind === 'text'">
                  <span class="text-slate-400">{{ field.label }}：</span>
                  <span class="text-slate-700 break-words">{{ field.value }}</span>
                </template>
                <template v-else-if="field.kind === 'kv'">
                  <div class="text-slate-400 mb-1">{{ field.label }}</div>
                  <div class="rounded-lg bg-slate-50 p-2 space-y-1">
                    <div v-for="row in (field.rows || [])" :key="row.label" class="flex gap-2 text-xs">
                      <span class="text-slate-400 w-20 shrink-0">{{ row.label }}</span>
                      <span class="text-slate-700 break-words">{{ row.value }}</span>
                    </div>
                  </div>
                </template>
                <template v-else>
                  <div class="text-slate-400 mb-1">{{ field.label }}（{{ (field.items || []).length }}）</div>
                  <div class="space-y-1">
                    <div v-for="(item, i) in (field.items || [])" :key="i" class="rounded-lg bg-slate-50 p-2 text-xs space-y-1">
                      <div class="font-medium text-slate-600">{{ item.title }}</div>
                      <div v-if="item.text" class="text-slate-700 break-words">{{ item.text }}</div>
                      <div v-for="row in (item.rows || [])" :key="row.label" class="flex gap-2">
                        <span class="text-slate-400 w-20 shrink-0">{{ row.label }}</span>
                        <span class="text-slate-700 break-words">{{ row.value }}</span>
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>

          <!-- Output section -->
          <div>
            <h4 class="text-sm font-medium text-slate-700 mb-3">输出结果</h4>
            <!-- 任务画廊（简单/专业模式）：按图展示 + 每张图的提示词可折叠 -->
            <div v-if="outputTasks.length > 0">
              <div class="grid grid-cols-2 gap-3">
                <div
                  v-for="task in outputTasks"
                  :key="task.taskId"
                  class="rounded-xl border border-slate-200 overflow-hidden"
                >
                  <div class="relative">
                    <img
                      v-if="task.url && !imgErrors.has(`task-${task.taskId}`)"
                      :src="task.url"
                      class="w-full rounded-t-xl canvas-checkerboard"
                      @error="handleImgError(`task-${task.taskId}`)"
                    />
                    <div v-else-if="task.url" class="w-full aspect-square bg-slate-100 flex items-center justify-center">
                      <X class="w-8 h-8 text-slate-300" />
                    </div>
                    <div v-else class="w-full aspect-square bg-slate-100 flex flex-col items-center justify-center gap-1 px-2 text-center">
                      <X class="w-6 h-6 text-slate-300" />
                      <span class="text-xs text-red-400 break-words">{{ task.error || '生成失败' }}</span>
                    </div>
                    <button
                      v-if="task.url && !imgErrors.has(`task-${task.taskId}`)"
                      @click="task.url && handleEdit(task.url)"
                      title="编辑"
                      class="absolute bottom-2 left-2 p-2 bg-white/90 rounded-lg shadow hover:bg-white"
                    >
                      <PenLine class="w-4 h-4 text-slate-600" />
                    </button>
                    <button
                      v-if="task.url && !imgErrors.has(`task-${task.taskId}`)"
                      @click="task.url && handleDownload(task.url)"
                      title="下载"
                      class="absolute bottom-2 right-2 p-2 bg-white/90 rounded-lg shadow hover:bg-white"
                    >
                      <Download class="w-4 h-4 text-slate-600" />
                    </button>
                  </div>
                  <div class="px-2 py-1.5 flex items-center justify-between gap-2 text-xs">
                    <span class="text-slate-500 truncate" :title="task.label">{{ task.label }}</span>
                    <span v-if="!task.url" class="shrink-0 text-red-400">生成失败</span>
                  </div>
                  <!-- 提示词折叠 -->
                  <div v-if="task.prompt" class="border-t border-slate-100">
                    <button
                      @click="togglePrompt(task.taskId)"
                      class="w-full flex items-center gap-1 px-2 py-1.5 text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors"
                    >
                      <ChevronDown
                        :class="[
                          'w-3 h-3 transition-transform duration-200',
                          expandedPrompts.has(task.taskId) && 'rotate-180',
                        ]"
                      />
                      <span>提示词</span>
                    </button>
                    <div v-if="expandedPrompts.has(task.taskId)" class="px-2 pb-2">
                      <p class="text-xs text-slate-500 leading-relaxed break-words bg-slate-50 rounded p-2">
                        {{ task.prompt }}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- Show output images -->
            <div v-if="outputImages.length > 0" class="grid grid-cols-2 gap-3">
              <div v-for="(img, i) in outputImages" :key="i" class="relative">
                <img
                  v-if="!imgErrors.has(`output-${i}`)"
                  :src="img.url"
                  class="w-full rounded-lg canvas-checkerboard"
                  @error="handleImgError(`output-${i}`)"
                />
                <div v-else class="w-full aspect-square rounded-lg bg-slate-100 flex items-center justify-center">
                  <X class="w-8 h-8 text-slate-300" />
                </div>
                <!-- 编辑按钮：跳转到编辑器 -->
                <button v-if="!imgErrors.has(`output-${i}`)" @click="handleEdit(img.url)" title="编辑" class="absolute bottom-2 left-2 p-2 bg-white/90 rounded-lg shadow hover:bg-white">
                  <PenLine class="w-4 h-4 text-slate-600" />
                </button>
                <button v-if="!imgErrors.has(`output-${i}`)" @click="handleDownload(img.url)" class="absolute bottom-2 right-2 p-2 bg-white/90 rounded-lg shadow hover:bg-white">
                  <Download class="w-4 h-4 text-slate-600" />
                </button>
              </div>
            </div>
            <!-- Plan Analysis: 生图计划方案展示 -->
            <div v-if="isPlanAnalysis && planAnalysisImages.length > 0" class="space-y-4 mt-3">
              <h5 class="text-sm font-medium text-slate-600">生图方案（{{ planAnalysisImages.length }} 张）</h5>
              <div
                v-for="img in planAnalysisImages"
                :key="`plan-img-${img.index}`"
                class="rounded-xl border border-slate-200 bg-slate-50/50 p-4 space-y-2"
              >
                <div class="flex items-center gap-2">
                  <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-emerald-500 text-white text-xs font-bold">
                    {{ img.index }}
                  </span>
                  <span class="text-sm font-semibold text-slate-700">{{ img.title }}</span>
                </div>
                <div v-if="img.plan" class="text-xs text-slate-600">
                  <span class="font-medium">方案：</span>{{ img.plan }}
                </div>
                <div v-if="img.reason" class="text-xs text-slate-500">
                  <span class="font-medium">原因：</span>{{ img.reason }}
                </div>
                <div v-if="img.prompt_cn" class="text-xs">
                  <span class="font-medium text-slate-500">中文提示词：</span>
                  <span class="text-slate-700">{{ img.prompt_cn }}</span>
                </div>
                <div v-if="img.prompt_en" class="text-xs">
                  <span class="font-medium text-slate-500">英文提示词：</span>
                  <span class="text-slate-700">{{ img.prompt_en }}</span>
                </div>
                <div v-if="img.backup_prompt_cn" class="text-xs">
                  <span class="font-medium text-amber-600">备用中文：</span>
                  <span class="text-slate-600">{{ img.backup_prompt_cn }}</span>
                </div>
                <div v-if="img.backup_prompt_en" class="text-xs">
                  <span class="font-medium text-amber-600">备用英文：</span>
                  <span class="text-slate-600">{{ img.backup_prompt_en }}</span>
                </div>
              </div>
            </div>
            <!-- Show output fields（键值 / 列表可读化，不输出 raw JSON） -->
            <div v-if="outputFields.length > 0" class="space-y-2 mt-3">
              <div v-for="field in outputFields" :key="field.key" class="text-sm">
                <template v-if="field.kind === 'text'">
                  <span class="text-slate-400">{{ field.label }}：</span>
                  <span :class="field.key === 'error' ? 'text-red-500' : 'text-slate-700'" class="break-words">{{ field.value }}</span>
                </template>
                <template v-else-if="field.kind === 'kv'">
                  <div class="text-slate-400 mb-1">{{ field.label }}</div>
                  <div class="rounded-lg bg-slate-50 p-2 space-y-1">
                    <div v-for="row in (field.rows || [])" :key="row.label" class="flex gap-2 text-xs">
                      <span class="text-slate-400 w-20 shrink-0">{{ row.label }}</span>
                      <span class="text-slate-700 break-words">{{ row.value }}</span>
                    </div>
                  </div>
                </template>
                <template v-else>
                  <div class="text-slate-400 mb-1">{{ field.label }}（{{ (field.items || []).length }}）</div>
                  <div class="space-y-1">
                    <div v-for="(item, i) in (field.items || [])" :key="i" class="rounded-lg bg-slate-50 p-2 text-xs space-y-1">
                      <div class="font-medium text-slate-600">{{ item.title }}</div>
                      <div v-if="item.text" class="text-slate-700 break-words">{{ item.text }}</div>
                      <div v-for="row in (item.rows || [])" :key="row.label" class="flex gap-2">
                        <span class="text-slate-400 w-20 shrink-0">{{ row.label }}</span>
                        <span class="text-slate-700 break-words">{{ row.value }}</span>
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>

          <!-- Share button -->
          <div class="pt-4 border-t border-slate-100">
            <div v-if="favError" class="text-xs text-red-500 mb-2">{{ favError }}</div>
            <div v-if="shareError" class="text-xs text-red-500 mb-2">{{ shareError }}</div>
            <div class="flex items-center gap-2 flex-wrap">
              <!-- 收藏按钮 -->
              <button
                @click="handleFavorite"
                :disabled="favLoading || favorited"
                class="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                :class="{ 'text-red-500 border-red-200 bg-red-50': favorited }"
              >
                <Heart class="w-4 h-4" :class="{ 'fill-current': favorited }" />
                {{ favorited ? '已收藏' : (favLoading ? '收藏中...' : '收藏') }}
              </button>
              <!-- Not shared yet -->
              <template v-if="!detail.shared_to_team">
                <div v-if="teams.length === 0" class="relative inline-block">
                  <button disabled
                    class="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-400 cursor-not-allowed">
                    <Share2 class="w-4 h-4" />
                    请先加入团队
                  </button>
                </div>
                <div v-else class="relative inline-block">
                  <button @click="showTeamSelector = !showTeamSelector" :disabled="shareLoading"
                    class="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50">
                    <Share2 class="w-4 h-4" />
                    {{ shareLoading ? '分享中...' : '分享到团队' }}
                    <ChevronDown class="w-3.5 h-3.5" />
                  </button>
                  <!-- Team selector dropdown -->
                  <div v-if="showTeamSelector"
                    class="absolute bottom-full left-0 mb-1 w-56 bg-white rounded-xl border border-slate-200 shadow-lg py-1 z-10">
                    <div class="px-3 py-1.5 text-xs text-slate-400 font-medium">选择团队</div>
                    <button
                      v-for="team in teams"
                      :key="team.id"
                      @click="handleShare(team.id)"
                      class="w-full text-left px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                    >
                      <Users class="w-4 h-4 text-slate-400" />
                      {{ team.name }}
                    </button>
                  </div>
                </div>
              </template>
              <!-- Already shared -->
              <button v-else @click="handleUnshare" :disabled="shareLoading"
                class="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-purple/10 text-brand-purple text-sm hover:bg-brand-purple/20 disabled:opacity-50">
                <UserCheck class="w-4 h-4" />
                已分享 - 点击取消分享
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>