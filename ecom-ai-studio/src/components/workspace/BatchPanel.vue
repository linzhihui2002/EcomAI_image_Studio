<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { getTemplateOptions, type TemplateSite } from '@/api/template'
import { toCompliancePlatform } from '@/api/compliance'
import { imageUrlToBase64 } from '@/lib/utils'
import { getErrorMessage } from '@/lib/error'
import {
  TIKTOK_SHOWCASE,
  BATCH_IMAGE_TYPES,
  DEFAULT_BATCH_SITES,
  siteCodeToMarket,
  makeBatchProductId,
  estimateBatchItems,
  REVIEW_RISK_STYLES,
  BATCH_ITEM_STATUS_STYLES,
} from '@/lib/batch'
import type { BatchProductInput, BatchManifestItem } from '@/api/batch'
import {
  Layers,
  ChevronDown,
  X,
  Sparkles,
  AlertCircle,
  RefreshCw,
  ShieldAlert,
  Globe,
  Coins,
} from 'lucide-vue-next'

const workspace = useWorkspaceStore()

// ===== 面板折叠 =====
const expanded = ref(false)

// ===== 批量模式开关（关闭时隐藏提交配置区，进行中的批次进度仍展示） =====
const batchModeOn = ref(true)

// ===== 站点多选（来自模板引擎选项，挂载时拉取，失败降级内置列表） =====
const siteOptions = ref<TemplateSite[]>(DEFAULT_BATCH_SITES)
const selectedSites = ref<string[]>([])

function toggleSite(code: string) {
  const idx = selectedSites.value.indexOf(code)
  if (idx >= 0) selectedSites.value.splice(idx, 1)
  else selectedSites.value.push(code)
}

// ===== 图组选择：自定义图型多选 / TikTok 展示图组预设 =====
const useTiktokPreset = ref(false)
const selectedTypes = ref<string[]>(['main', 'scene', 'detail'])

/** TikTok 预设选中后图型固定 main+scene+detail */
const effectiveTypes = computed(() =>
  useTiktokPreset.value ? BATCH_IMAGE_TYPES.map((t) => t.code) : selectedTypes.value,
)

function toggleType(code: string) {
  if (useTiktokPreset.value) return
  const idx = selectedTypes.value.indexOf(code)
  if (idx >= 0) selectedTypes.value.splice(idx, 1)
  else selectedTypes.value.push(code)
}

function selectGroup(preset: boolean) {
  useTiktokPreset.value = preset
}

// ===== 风格锁定提示 =====
const styleLockHint = ref('')

// ===== 预估展示 =====
/** 总张数 = 商品数 × 站点数 × 图型数 */
const estimatedItems = computed(() =>
  estimateBatchItems(workspace.productImages.length, selectedSites.value.length, effectiveTypes.value.length),
)
/** 本地单价估算（定价未加载时为 0，实际以后端预检锁定为准） */
const estimatedCoins = computed(() => workspace.singleImageCost * estimatedItems.value)

const canSubmit = computed(() =>
  workspace.productImages.length > 0 &&
  selectedSites.value.length > 0 &&
  effectiveTypes.value.length > 0 &&
  !workspace.isBatchSubmitting,
)

// ===== 提交确认弹层 =====
const showConfirm = ref(false)
const submitErrorMsg = ref('')

function requestSubmit() {
  submitErrorMsg.value = ''
  if (!canSubmit.value) return
  showConfirm.value = true
}

/** 预检失败（400）data 内原因的宽容归一化 */
function normalizePrecheckReasons(data: any): string[] {
  if (!data) return []
  if (typeof data === 'string') return [data]
  if (Array.isArray(data)) {
    return data.map((item: any) =>
      typeof item === 'string' ? item : item?.reason || item?.message || item?.detail || JSON.stringify(item),
    )
  }
  if (typeof data === 'object') {
    return Object.values(data).map((v: any) =>
      typeof v === 'string' ? v : Array.isArray(v) ? v.join('；') : JSON.stringify(v),
    )
  }
  return []
}

async function confirmSubmit() {
  showConfirm.value = false
  submitErrorMsg.value = ''
  try {
    const products: BatchProductInput[] = await Promise.all(
      workspace.productImages.map(async (img, idx) => ({
        product_id: makeBatchProductId(idx + 1, img.name),
        product_name: img.name.replace(/\.[^.]+$/, ''),
        product_image: await imageUrlToBase64(img.url),
        selling_points: workspace.smartModeConfig?.productInfo?.selling_points || undefined,
        selling_points_en: workspace.smartModeConfig?.sellingPointsEn,
      })),
    )
    await workspace.submitBatch({
      products,
      sites: selectedSites.value.map(siteCodeToMarket),
      image_types: effectiveTypes.value,
      // 平台需为后端规则键（amazon/temu/...），展示名经映射转换，未知平台回退 amazon
      platform: toCompliancePlatform(workspace.smartModeConfig?.platform || 'Amazon') || 'amazon',
      size: workspace.smartModeConfig?.size || '1024x1024',
      image_group: useTiktokPreset.value ? TIKTOK_SHOWCASE : undefined,
      style_lock_hint: styleLockHint.value.trim() || undefined,
    })
    expanded.value = true
  } catch (err: any) {
    const reasons = normalizePrecheckReasons(err?.data)
    submitErrorMsg.value = reasons.length
      ? `预检未通过：${reasons.join('；')}`
      : getErrorMessage(err, '批量任务提交失败，请稍后重试')
  }
}

// ===== 批次状态展示 =====
const BATCH_STATUS_LABELS: Record<string, string> = {
  idle: '未开始',
  submitting: '提交中...',
  planned: '排队中',
  queued: '排队中',
  running: '生成中',
  processing: '生成中',
  completed: '已完成',
  failed: '失败',
  partial: '部分完成',
}

function batchStatusLabel(status: string): string {
  return BATCH_STATUS_LABELS[status] || status
}

/** 展示进度条：SSE pct 优先，缺省时用 (succeeded+failed)/total 兜底 */
const displayPct = computed(() => {
  if (workspace.batchPct > 0) return Math.min(100, workspace.batchPct)
  const total = workspace.batchTotalItems
  if (!total) return 0
  const done = (workspace.batchCounts.completed || 0) + (workspace.batchCounts.failed || 0)
  return Math.min(100, Math.round((done / total) * 100))
})

// ===== 审查徽标（Task 9.3）：悬浮 / 点击展示 issues 与 fixSuggestions =====
const reviewOpenKey = ref('')

function riskStyle(review: BatchManifestItem['review']) {
  const level = review?.riskLevel || 'unknown'
  return REVIEW_RISK_STYLES[level] || REVIEW_RISK_STYLES.unknown
}

function itemStatusStyle(status: string) {
  return BATCH_ITEM_STATUS_STYLES[status] || BATCH_ITEM_STATUS_STYLES.planned
}

function toggleReview(key: string) {
  reviewOpenKey.value = reviewOpenKey.value === key ? '' : key
}

// ===== 重试 =====
const isRetrying = ref(false)
const canRetry = computed(() => workspace.failedBatchItems.length > 0 && !isRetrying.value)

async function handleRetry() {
  if (!canRetry.value) return
  isRetrying.value = true
  try {
    await workspace.retryBatchFailed()
  } finally {
    isRetrying.value = false
  }
}

// ===== 挂载：拉取站点选项 =====
onMounted(async () => {
  try {
    const options = await getTemplateOptions()
    if (options?.sites?.length) {
      siteOptions.value = options.sites
      selectedSites.value = selectedSites.value.filter((c) => options.sites.some((s) => s.code === c))
    }
  } catch (err) {
    console.warn('[BatchPanel] 站点选项加载失败，已降级为默认列表:', err)
  }
})
</script>

<template>
  <div class="border-t border-slate-200 bg-white flex-shrink-0">
    <!-- 折叠栏（始终展示） -->
    <button
      class="w-full flex items-center justify-between px-4 py-2 hover:bg-slate-50 transition-colors"
      @click="expanded = !expanded"
    >
      <span class="flex items-center gap-2 text-xs font-semibold text-slate-700">
        <Layers class="w-4 h-4 text-brand-purple" />
        批量生成
        <span
          v-if="workspace.failedBatchItems.length > 0"
          class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-red-100 text-red-600"
        >{{ workspace.failedBatchItems.length }} 项失败</span>
        <span
          v-else-if="workspace.isBatchTracking"
          class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-600"
        >进行中</span>
      </span>
      <ChevronDown :class="['w-4 h-4 text-slate-400 transition-transform duration-200', expanded && 'rotate-180']" />
    </button>

    <div v-if="expanded" class="px-4 pb-4 max-h-[45vh] overflow-y-auto">
      <!-- 批量模式开关 -->
      <div class="flex items-center justify-between py-2">
        <span class="text-xs font-medium text-slate-700">批量模式</span>
        <button
          role="switch"
          :aria-checked="batchModeOn"
          :class="[
            'relative w-9 h-5 rounded-full transition-colors duration-200',
            batchModeOn ? 'bg-brand-purple' : 'bg-slate-200',
          ]"
          @click="batchModeOn = !batchModeOn"
        >
          <span
            :class="['absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200']"
            :style="{ transform: batchModeOn ? 'translateX(16px)' : 'translateX(0)' }"
          />
        </button>
      </div>

      <!-- 提交区 -->
      <div v-if="batchModeOn" class="space-y-3 pt-1">
        <!-- 商品列表（取 store 的 productImages，每张为一个商品） -->
        <div>
          <label class="text-xs font-medium text-slate-700 mb-1.5 block">
            商品（{{ workspace.productImages.length }} 张上传图各为一个商品）
          </label>
          <div v-if="workspace.productImages.length === 0" class="rounded-lg border border-dashed border-slate-200 px-3 py-3 text-center text-[11px] text-slate-400">
            请先在左侧上传商品图
          </div>
          <div v-else class="flex flex-wrap gap-2">
            <div
              v-for="(img, idx) in workspace.productImages"
              :key="img.id"
              class="relative w-14 h-14 rounded-lg overflow-hidden border border-slate-200 bg-slate-100 group"
              :title="`${makeBatchProductId(idx + 1, img.name)} · ${img.name}`"
            >
              <img :src="img.url" :alt="img.name" class="w-full h-full object-cover" loading="lazy" />
              <span class="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-black/60 text-white text-[9px] font-bold flex items-center justify-center">
                {{ idx + 1 }}
              </span>
              <button
                class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center text-white"
                @click="workspace.removeProductImage(img.id)"
              >
                <X class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>

        <!-- 站点多选 -->
        <div>
          <label class="text-xs font-medium text-slate-700 mb-1.5 block">目标站点（可多选）</label>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="site in siteOptions"
              :key="site.code"
              :class="[
                'px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all duration-200 border',
                selectedSites.includes(site.code)
                  ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-sm'
                  : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50',
              ]"
              @click="toggleSite(site.code)"
            >
              {{ site.name }}
            </button>
          </div>
        </div>

        <!-- 图组选择 -->
        <div>
          <label class="text-xs font-medium text-slate-700 mb-1.5 block">图组</label>
          <div class="grid grid-cols-2 gap-2">
            <button
              :class="[
                'px-2.5 py-2 rounded-lg text-[11px] font-medium transition-all duration-200 border text-left',
                !useTiktokPreset
                  ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-sm'
                  : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300',
              ]"
              @click="selectGroup(false)"
            >
              自定义图型
              <span class="block text-[10px] font-normal mt-0.5 opacity-80">勾选下方图片类型</span>
            </button>
            <button
              :class="[
                'px-2.5 py-2 rounded-lg text-[11px] font-medium transition-all duration-200 border text-left',
                useTiktokPreset
                  ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-sm'
                  : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300',
              ]"
              @click="selectGroup(true)"
            >
              TikTok 展示图组
              <span class="block text-[10px] font-normal mt-0.5 opacity-80">主图 1:1 · 场景 1:1 · 细节 9:16</span>
            </button>
          </div>

          <!-- 自定义图型勾选（TikTok 预设时固定并禁用） -->
          <div class="flex flex-wrap gap-1.5 mt-2">
            <button
              v-for="t in BATCH_IMAGE_TYPES"
              :key="t.code"
              :disabled="useTiktokPreset"
              :class="[
                'px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all duration-200 border',
                (useTiktokPreset ? effectiveTypes : selectedTypes).includes(t.code)
                  ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-sm'
                  : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300',
                useTiktokPreset && 'opacity-70 cursor-not-allowed',
              ]"
              :title="useTiktokPreset ? 'TikTok 图组已固定包含全部图型' : `输出比例 ${t.ratio}`"
              @click="toggleType(t.code)"
            >
              {{ t.name }}
            </button>
          </div>
          <p v-if="useTiktokPreset" class="mt-1.5 text-[10px] text-slate-400 flex items-center gap-1">
            <AlertCircle class="w-3 h-3 flex-shrink-0" />
            TikTok 图组固定生成 主图(1:1) + 场景图(1:1) + 细节图(9:16)
          </p>
        </div>

        <!-- 风格锁定提示 -->
        <div>
          <label class="text-xs font-medium text-slate-700 mb-1.5 block">
            风格锁定提示
            <span class="text-slate-400 font-normal">（可选）</span>
          </label>
          <input
            v-model="styleLockHint"
            placeholder="如：保持与首图一致的色调与光影"
            class="w-full px-2.5 py-2 rounded-lg border border-slate-200 text-xs text-slate-700 placeholder:text-slate-300 focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 outline-none transition-all"
          />
        </div>

        <!-- 预估展示 -->
        <div class="rounded-lg bg-slate-50 border border-slate-100 px-3 py-2.5 flex items-center justify-between">
          <span class="text-[11px] text-slate-500">
            预估 <span class="font-semibold text-slate-800">{{ estimatedItems }}</span> 张
            <span class="text-slate-300 mx-1">=</span>
            {{ workspace.productImages.length }} 商品 × {{ selectedSites.length }} 站点 × {{ effectiveTypes.length }} 图型
          </span>
          <span class="flex items-center gap-1 text-[11px] text-slate-500 flex-shrink-0">
            <Coins class="w-3.5 h-3.5 text-amber-500" />
            约 {{ estimatedCoins }} 灵感币
          </span>
        </div>

        <!-- 提交错误（预检 400 原因） -->
        <div v-if="submitErrorMsg" class="flex items-start gap-2 p-2.5 rounded-lg bg-red-50 border border-red-200 text-[11px] text-red-600">
          <AlertCircle class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span>{{ submitErrorMsg }}</span>
        </div>
        <div v-else-if="workspace.batchError" class="flex items-start gap-2 p-2.5 rounded-lg bg-red-50 border border-red-200 text-[11px] text-red-600">
          <AlertCircle class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span>{{ workspace.batchError }}</span>
        </div>

        <button
          :disabled="!canSubmit"
          :class="[
            'w-full py-2.5 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all duration-200',
            canSubmit
              ? 'btn-primary text-white hover:shadow-glow hover:-translate-y-0.5'
              : 'bg-slate-100 text-slate-400 cursor-not-allowed',
          ]"
          @click="requestSubmit"
        >
          <Sparkles class="w-3.5 h-3.5" />
          {{ workspace.isBatchSubmitting ? '提交中...' : '提交批量任务' }}
        </button>
      </div>

      <!-- 进度区（提交后展示） -->
      <div v-if="workspace.batchTaskId" class="mt-4 pt-3 border-t border-slate-100 space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold text-slate-700">
            批次进度
            <span
              :class="[
                'ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-medium',
                workspace.batchStatus === 'completed' ? 'bg-emerald-100 text-emerald-600'
                  : workspace.batchStatus === 'failed' ? 'bg-red-100 text-red-600'
                  : 'bg-blue-100 text-blue-600',
              ]"
            >{{ batchStatusLabel(workspace.batchStatus) }}</span>
          </span>
          <span class="flex items-center gap-1 text-[11px] text-slate-500">
            <Coins class="w-3.5 h-3.5 text-amber-500" />
            已锁定 {{ workspace.batchCoinsLocked }} 灵感币
          </span>
        </div>

        <!-- 进度条 -->
        <div class="h-1.5 rounded-full bg-slate-100 overflow-hidden">
          <div
            class="h-full rounded-full bg-gradient-to-r from-brand-purple to-cyan-400 transition-all duration-500"
            :style="{ width: displayPct + '%' }"
          />
        </div>
        <div class="flex items-center justify-between text-[11px] text-slate-500">
          <span>{{ displayPct }}%</span>
          <span>
            成功 {{ workspace.batchCounts.completed || 0 }} ·
            失败 {{ workspace.batchCounts.failed || 0 }} ·
            共 {{ workspace.batchTotalItems }}
          </span>
        </div>

        <!-- 提交 warnings -->
        <div v-if="workspace.batchWarnings.length" class="rounded-lg bg-amber-50 border border-amber-200/60 px-2.5 py-2 space-y-1">
          <p v-for="(w, i) in workspace.batchWarnings" :key="i" class="text-[10px] text-amber-600 flex items-start gap-1">
            <AlertCircle class="w-3 h-3 flex-shrink-0 mt-0.5" />
            <span>{{ w }}</span>
          </p>
        </div>

        <!-- manifest 明细表 -->
        <div class="rounded-lg border border-slate-200 overflow-hidden">
          <div class="grid grid-cols-[1fr_auto_auto] gap-2 px-2.5 py-1.5 bg-slate-50 border-b border-slate-100 text-[10px] font-semibold text-slate-500">
            <span>商品 / 站点 / 图型</span>
            <span>状态</span>
            <span>审查</span>
          </div>
          <div class="divide-y divide-slate-50 max-h-56 overflow-y-auto">
            <div v-if="workspace.batchItems.length === 0" class="px-2.5 py-4 text-center text-[11px] text-slate-400">
              暂无明细数据
            </div>
            <div
              v-for="item in workspace.batchItems"
              :key="item.item_key"
              class="grid grid-cols-[1fr_auto_auto] gap-2 px-2.5 py-2 items-center text-[11px]"
            >
              <div class="min-w-0">
                <p class="text-slate-700 truncate" :title="item.product_id">{{ item.product_id }}</p>
                <p class="text-[10px] text-slate-400 truncate">
                  <Globe class="w-2.5 h-2.5 inline-block -mt-0.5 mr-0.5" />{{ item.site }} · {{ item.image_type }}
                  <template v-if="item.error"> · <span class="text-red-500" :title="item.error">{{ item.error }}</span></template>
                </p>
              </div>
              <span
                :class="['px-1.5 py-0.5 rounded border text-[10px] font-medium flex-shrink-0', itemStatusStyle(item.status).cls]"
              >{{ itemStatusStyle(item.status).label }}</span>
              <!-- 审查徽标：悬浮或点击展示 issues 与 fixSuggestions -->
              <span class="relative flex-shrink-0 group">
                <button
                  :class="['px-1.5 py-0.5 rounded border text-[10px] font-medium', riskStyle(item.review).cls]"
                  @click="toggleReview(item.item_key)"
                >
                  <ShieldAlert class="w-2.5 h-2.5 inline-block -mt-0.5 mr-0.5" />{{ riskStyle(item.review).label }}
                </button>
                <!-- 悬浮详情 -->
                <span class="hidden group-hover:block absolute right-0 top-full mt-1 z-20 w-64 rounded-lg bg-slate-800 text-white text-[10px] p-2.5 shadow-xl text-left">
                  <template v-if="item.review?.issues?.length">
                    <p class="font-semibold text-white/90 border-b border-white/10 pb-1 mb-1">问题</p>
                    <p v-for="(issue, i) in item.review.issues" :key="i" class="text-white/70 leading-relaxed">
                      {{ issue.rule }}：{{ issue.detail }}
                    </p>
                  </template>
                  <template v-if="item.review?.fixSuggestions?.length">
                    <p class="font-semibold text-white/90 border-b border-white/10 pb-1 mb-1 mt-1.5">修复建议</p>
                    <p v-for="(fix, i) in item.review.fixSuggestions" :key="i" class="text-white/70 leading-relaxed">· {{ fix }}</p>
                  </template>
                  <p v-if="!item.review?.issues?.length && !item.review?.fixSuggestions?.length" class="text-white/70">
                    暂无审查详情
                  </p>
                </span>
              </span>
            </div>
          </div>
        </div>

        <!-- 点击徽标展开的审查详情（触屏/键盘可达） -->
        <div
          v-for="item in workspace.batchItems.filter((it) => reviewOpenKey === it.item_key)"
          :key="`detail-${item.item_key}`"
          class="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2.5 space-y-1.5"
        >
          <p class="text-[11px] font-semibold text-slate-700">审查详情 · {{ item.product_id }}</p>
          <p v-for="(issue, i) in item.review?.issues || []" :key="`i-${i}`" class="text-[10px] text-slate-600">
            {{ issue.rule }}：{{ issue.detail }}
          </p>
          <p v-for="(fix, i) in item.review?.fixSuggestions || []" :key="`f-${i}`" class="text-[10px] text-brand-purple">
            建议：{{ fix }}
          </p>
          <p v-if="!item.review?.issues?.length && !item.review?.fixSuggestions?.length" class="text-[10px] text-slate-400">
            暂无审查详情
          </p>
        </div>

        <!-- 重试按钮：failed>0 时可用 -->
        <button
          :disabled="!canRetry"
          :class="[
            'w-full py-2 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all duration-200',
            canRetry
              ? 'border border-brand-purple text-brand-purple hover:bg-brand-gradient-subtle'
              : 'border border-slate-200 text-slate-300 cursor-not-allowed',
          ]"
          :title="canRetry ? `重试 ${workspace.failedBatchItems.length} 个失败项` : '无失败项可重试'"
          @click="handleRetry"
        >
          <RefreshCw :class="['w-3.5 h-3.5', isRetrying && 'animate-spin']" />
          {{ isRetrying ? '重试中...' : `重试失败项（${workspace.failedBatchItems.length}）` }}
        </button>
      </div>
    </div>

    <!-- 提交确认弹层：明确锁定灵感币 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showConfirm"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-6"
          @click="showConfirm = false"
        >
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-5 space-y-4" @click.stop>
            <h3 class="text-sm font-semibold text-slate-900">确认提交批量任务</h3>
            <div class="space-y-1.5 text-xs text-slate-600">
              <p>商品 <span class="font-semibold text-slate-800">{{ workspace.productImages.length }}</span> 个 ×
                站点 <span class="font-semibold text-slate-800">{{ selectedSites.length }}</span> 个 ×
                图型 <span class="font-semibold text-slate-800">{{ effectiveTypes.length }}</span> 个
              </p>
              <p>共生成 <span class="font-semibold text-brand-purple">{{ estimatedItems }}</span> 张图片</p>
              <p class="flex items-center gap-1">
                <Coins class="w-3.5 h-3.5 text-amber-500" />
                预估消耗
                <span class="font-semibold text-amber-600">{{ estimatedCoins || estimatedItems }}</span> 灵感币
                <span class="text-[10px] text-slate-400">（以后端预检锁定为准）</span>
              </p>
            </div>
            <div class="flex gap-2">
              <button
                class="flex-1 py-2 rounded-xl text-xs font-medium border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
                @click="showConfirm = false"
              >取消</button>
              <button
                class="flex-1 py-2 rounded-xl text-xs font-semibold btn-primary text-white hover:shadow-glow transition-all"
                @click="confirmSubmit"
              >确认提交</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: all 0.25s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
