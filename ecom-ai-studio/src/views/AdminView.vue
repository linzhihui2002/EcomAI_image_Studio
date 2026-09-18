<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  getAdminStats,
  getAllPricingPlans,
  createPricingPlan,
  updatePricingPlan,
  togglePricingPlanActive,
  deletePricingPlan,
  getTeamConsumptions,
  getAdminRedemptionCodes,
  generateRedemptionCode,
  deleteRedemptionCode,
  getAdminAnnouncements,
  createAnnouncement,
  updateAnnouncement,
  toggleAnnouncementActive,
  deleteAnnouncement,
  getFeaturePricingList,
  createFeaturePricing,
  updateFeaturePricing,
  toggleFeaturePricingActive,
  deleteFeaturePricing as deleteFeaturePricingApi,
  getFeatureKeyOptions,
} from '@/api/admin'
import type { FeatureKeyOption } from '@/api/admin'
import { clearFeaturePricingCache } from '@/api/featurePricing'
import { getErrorMessage } from '@/lib/error'
import type {
  AdminStats,
  PricingPlan,
  TeamConsumption,
  RedemptionCode,
  Announcement,
  FeaturePricingAdmin,
  FeaturePricingConfig,
  PricingType,
} from '@/types'
import {
  Users,
  Zap,
  Activity,
  TrendingUp,
  AlertTriangle,
  AlertCircle,
  Clock,
  Shield,
  Coins,
  Plus,
  Pencil,
  Trash2,
  X,
  Check,
  Ban,
  Building2,
  DollarSign,
  Sparkles,
  Hash,
  Search,
  ChevronDown,
  ArrowUpDown,
  Key,
  Ticket,
  Copy,
  Calendar,
  Megaphone,
  Tag,
} from 'lucide-vue-next'

type AdminTab = 'dashboard' | 'pricing' | 'feature_pricing' | 'consumption' | 'redemption' | 'announcement'

const activeTab = ref<AdminTab>('dashboard')

const tabs: { key: AdminTab; label: string; icon: any }[] = [
  { key: 'dashboard', label: '监控仪表盘', icon: Activity },
  { key: 'pricing', label: '定价管理', icon: DollarSign },
  { key: 'feature_pricing', label: '功能定价', icon: Tag },
  { key: 'consumption', label: '团队消耗', icon: Building2 },
  { key: 'redemption', label: '兑换码管理', icon: Ticket },
  { key: 'announcement', label: '公告管理', icon: Megaphone },
]

// 统一的删除确认状态
const pendingDelete = ref<{ type: 'plan' | 'code' | 'announcement' | 'feature_pricing'; id: number | string; label: string } | null>(null)
const deleteLoading = ref(false)

async function executeDelete() {
  if (!pendingDelete.value) return
  const { type, id } = pendingDelete.value
  deleteLoading.value = true
  try {
    if (type === 'plan') {
      await deletePricingPlan(id as number)
      await fetchPricingPlans()
    } else if (type === 'code') {
      await deleteRedemptionCode(id as string)
      await fetchRedemptionCodes(codeFilter.value === 'all' ? undefined : codeFilter.value)
    } else if (type === 'announcement') {
      await deleteAnnouncement(id as string)
      await fetchAnnouncements()
    } else if (type === 'feature_pricing') {
      await deleteFeaturePricingApi(id as number)
      clearFeaturePricingCache()
      await fetchFeaturePricing()
    }
    pendingDelete.value = null
  } catch (err) {
    const msg = getErrorMessage(err, '删除失败，请稍后重试')
    if (type === 'feature_pricing') {
      featurePricingError.value = msg
    } else {
      alert(msg)
    }
    console.error('删除操作失败:', msg)
  } finally {
    deleteLoading.value = false
  }
}

const stats = ref<AdminStats>({
  onlineUsers: 0,
  todayPoints: 0,
  qwenSuccessRate: 0,
  gptSuccessRate: 0,
  modelHealth: {
    qwen: { status: 'green', latency: 0, lastCheck: '' },
    gpt: { status: 'green', latency: 0, lastCheck: '' },
  },
  hourlyRequests: [],
  failureTrend: [],
})

const dashboardLoading = ref(false)

async function fetchDashboardStats() {
  try {
    dashboardLoading.value = true
    const data = await getAdminStats()
    stats.value = data
  } catch (err) {
    console.error('获取仪表盘数据失败:', getErrorMessage(err))
  } finally {
    dashboardLoading.value = false
  }
}

let interval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  fetchDashboardStats()
  fetchPricingPlans()
  fetchFeaturePricing()
  fetchTeamConsumptions()
  fetchRedemptionCodes()
  fetchAnnouncements()
  interval = setInterval(() => {
    fetchDashboardStats()
  }, 30000)
})

onUnmounted(() => {
  if (interval) clearInterval(interval)
})

const maxQwenRequest = computed(() => Math.max(...stats.value.hourlyRequests.map((h) => h.qwen), 1))
const maxGptRequest = computed(() => Math.max(...stats.value.hourlyRequests.map((h) => h.gpt), 1))
const maxFailure = computed(() => Math.max(...stats.value.failureTrend.map((h) => h.count), 1))

// ========== 定价管理 ==========
const pricingPlans = ref<PricingPlan[]>([])
const pricingLoading = ref(false)

async function fetchPricingPlans() {
  try {
    pricingLoading.value = true
    pricingPlans.value = await getAllPricingPlans()
  } catch (err) {
    console.error('获取定价方案失败:', getErrorMessage(err))
  } finally {
    pricingLoading.value = false
  }
}

const showPricingModal = ref(false)
const editingPlan = ref<PricingPlan | null>(null)
const pricingForm = ref({
  name: '',
  price: 0,
  coins: 0,
  bonusCoins: 0,
})

function openNewPlan() {
  editingPlan.value = null
  pricingForm.value = { name: '', price: 0, coins: 0, bonusCoins: 0 }
  showPricingModal.value = true
}

function openEditPlan(plan: PricingPlan) {
  editingPlan.value = plan
  pricingForm.value = {
    name: plan.name,
    price: plan.price,
    coins: plan.coins,
    bonusCoins: plan.bonusCoins,
  }
  showPricingModal.value = true
}

async function savePlan() {
  if (!pricingForm.value.name || pricingForm.value.price <= 0 || pricingForm.value.coins <= 0) return

  try {
    if (editingPlan.value) {
      await updatePricingPlan(editingPlan.value.id, {
        name: pricingForm.value.name,
        price: pricingForm.value.price,
        coins: pricingForm.value.coins,
        bonusCoins: pricingForm.value.bonusCoins,
      })
    } else {
      await createPricingPlan({
        name: pricingForm.value.name,
        price: pricingForm.value.price,
        coins: pricingForm.value.coins,
        bonusCoins: pricingForm.value.bonusCoins,
      })
    }
    showPricingModal.value = false
    await fetchPricingPlans()
  } catch (err) {
    console.error('保存定价方案失败:', getErrorMessage(err))
  }
}

async function togglePlanActive(planId: number) {
  try {
    await togglePricingPlanActive(planId)
    await fetchPricingPlans()
  } catch (err) {
    alert(getErrorMessage(err, '切换定价方案状态失败，请稍后重试'))
    console.error('切换定价方案状态失败:', getErrorMessage(err))
  }
}

async function deletePlan(planId: number) {
  pendingDelete.value = { type: 'plan', id: planId, label: '定价方案' }
}

// ========== 团队消耗 ==========
const teamConsumptions = ref<TeamConsumption[]>([])
const consumptionLoading = ref(false)

async function fetchTeamConsumptions(sortBy?: string, order?: string) {
  try {
    consumptionLoading.value = true
    teamConsumptions.value = await getTeamConsumptions(sortBy, order)
  } catch (err) {
    console.error('获取团队消耗数据失败:', getErrorMessage(err))
  } finally {
    consumptionLoading.value = false
  }
}

const consumptionSortField = ref<keyof TeamConsumption>('totalCoinsConsumed')
const consumptionSortOrder = ref<'asc' | 'desc'>('desc')

async function sortConsumptions(field: keyof TeamConsumption) {
  if (consumptionSortField.value === field) {
    consumptionSortOrder.value = consumptionSortOrder.value === 'desc' ? 'asc' : 'desc'
  } else {
    consumptionSortField.value = field
    consumptionSortOrder.value = 'desc'
  }
  await fetchTeamConsumptions(consumptionSortField.value, consumptionSortOrder.value)
}

const sortedConsumptions = computed(() => {
  return teamConsumptions.value
})

function formatNumber(n: number): string {
  return Number(n ?? 0).toLocaleString()
}

function formatPrice(n: number): string {
  const num = Number(n ?? 0)
  return num % 1 === 0 ? `¥${num}` : `¥${num.toFixed(1)}`
}

// ========== 兑换码管理 ==========
const redemptionCodes = ref<RedemptionCode[]>([])
const redemptionLoading = ref(false)
const redemptionError = ref<string | null>(null)

async function fetchRedemptionCodes(status?: string) {
  try {
    redemptionLoading.value = true
    redemptionError.value = null
    redemptionCodes.value = await getAdminRedemptionCodes(status)
  } catch (err) {
    const msg = getErrorMessage(err, '加载兑换码失败，请稍后重试')
    redemptionError.value = msg
    console.error('[AdminView] 获取兑换码失败:', err instanceof Error ? err.message : String(err))
  } finally {
    redemptionLoading.value = false
  }
}

const showGenerateModal = ref(false)
const generateForm = ref({
  coins: 100,
  expiresDays: 30,
  remark: '',
  maxUses: 1,
  maxUsesPerUser: 1,
})

const codeFilter = ref<'all' | 'unused' | 'used'>('all')

const filteredCodes = computed(() => {
  return redemptionCodes.value
})

const codeStats = computed(() => {
  const all = redemptionCodes.value
  const unused = all.filter((c) => !c.isUsed).length
  const used = all.filter((c) => c.isUsed).length
  const totalCoins = all.reduce((s, c) => s + c.coins, 0)
  const usedCoins = all.filter((c) => c.isUsed).reduce((s, c) => s + c.coins, 0)
  const remainingUses = all.reduce((s, c) => s + (c.remainingUses ?? 0), 0)
  return { total: all.length, unused, used, totalCoins, usedCoins, remainingUses }
})

async function generateCodes() {
  if (generateForm.value.coins <= 0 || generateForm.value.expiresDays <= 0) return
  if (generateForm.value.maxUses < 1 || generateForm.value.maxUsesPerUser < 1) return
  if (generateForm.value.maxUsesPerUser > generateForm.value.maxUses) return
  try {
    await generateRedemptionCode({
      coins: generateForm.value.coins,
      expiresDays: generateForm.value.expiresDays,
      remark: generateForm.value.remark,
      maxUses: generateForm.value.maxUses,
      maxUsesPerUser: generateForm.value.maxUsesPerUser,
    })
    showGenerateModal.value = false
    generateForm.value = { coins: 100, expiresDays: 30, remark: '', maxUses: 1, maxUsesPerUser: 1 }
    await fetchRedemptionCodes(codeFilter.value === 'all' ? undefined : codeFilter.value)
  } catch (err) {
    console.error('生成兑换码失败:', getErrorMessage(err))
  }
}

function copyCode(code: string) {
  navigator.clipboard.writeText(code).catch(() => {})
}

function onMaxUsesChange() {
  if (generateForm.value.maxUsesPerUser > generateForm.value.maxUses) {
    generateForm.value.maxUsesPerUser = generateForm.value.maxUses
  }
}

async function deleteCode(id: string) {
  pendingDelete.value = { type: 'code', id, label: '兑换码' }
}

// 筛选变化时重新请求后端数据
watch(codeFilter, (newFilter) => {
  fetchRedemptionCodes(newFilter === 'all' ? undefined : newFilter)
})

function isExpired(expiresAt: string): boolean {
  if (!expiresAt) return false
  return new Date(expiresAt) < new Date()
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '—'
  // 兼容 ISO 格式 (2026-12-31T23:59:59) 和 MySQL DATETIME 格式 (2026-12-31 23:59:59)
  const datePart = dateStr.includes('T') ? dateStr.split('T')[0] : dateStr.split(' ')[0]
  // 验证是否为有效的 YYYY-MM-DD 格式
  if (/^\d{4}-\d{2}-\d{2}$/.test(datePart)) {
    return datePart
  }
  // 最后尝试 Date 解析
  try {
    const d = new Date(dateStr)
    if (!isNaN(d.getTime())) {
      return d.toISOString().split('T')[0]
    }
  } catch { /* fall through */ }
  return '—'
}

// ========== 公告管理 ==========
const announcements = ref<Announcement[]>([])
const announcementLoading = ref(false)

async function fetchAnnouncements() {
  try {
    announcementLoading.value = true
    announcements.value = await getAdminAnnouncements()
  } catch (err) {
    console.error('获取公告失败:', getErrorMessage(err))
  } finally {
    announcementLoading.value = false
  }
}

const showAnnouncementModal = ref(false)
const editingAnnouncement = ref<Announcement | null>(null)
const announcementForm = ref({
  title: '',
  content: '',
  type: 'info' as Announcement['type'],
  isPinned: false,
  expiresAt: '',
})

function openNewAnnouncement() {
  editingAnnouncement.value = null
  announcementForm.value = { title: '', content: '', type: 'info', isPinned: false, expiresAt: '' }
  showAnnouncementModal.value = true
}

function openEditAnnouncement(ann: Announcement) {
  editingAnnouncement.value = ann
  announcementForm.value = {
    title: ann.title,
    content: ann.content,
    type: ann.type,
    isPinned: ann.isPinned,
    expiresAt: ann.expiresAt ? ann.expiresAt.split('T')[0] : '',
  }
  showAnnouncementModal.value = true
}

async function saveAnnouncement() {
  if (!announcementForm.value.title || !announcementForm.value.content) return

  try {
    const payload = {
      title: announcementForm.value.title,
      content: announcementForm.value.content,
      type: announcementForm.value.type,
      isPinned: announcementForm.value.isPinned,
      expiresAt: announcementForm.value.expiresAt
        ? new Date(announcementForm.value.expiresAt).toISOString()
        : null,
    }

    if (editingAnnouncement.value) {
      await updateAnnouncement(editingAnnouncement.value.id, payload)
    } else {
      await createAnnouncement(payload)
    }

    showAnnouncementModal.value = false
    await fetchAnnouncements()
  } catch (err) {
    alert(getErrorMessage(err, '保存公告失败，请稍后重试'))
    console.error('保存公告失败:', getErrorMessage(err))
  }
}

async function handleToggleAnnouncementActive(id: string) {
  try {
    await toggleAnnouncementActive(id)
    await fetchAnnouncements()
  } catch (err) {
    alert(getErrorMessage(err, '切换公告状态失败，请稍后重试'))
    console.error('切换公告状态失败:', getErrorMessage(err))
  }
}

async function handleDeleteAnnouncement(id: string) {
  pendingDelete.value = { type: 'announcement', id, label: '公告' }
}

// ========== 功能定价管理 ==========
const featurePricingList = ref<FeaturePricingAdmin[]>([])
const featurePricingLoading = ref(false)
const featurePricingError = ref('')

async function fetchFeaturePricing() {
  try {
    featurePricingLoading.value = true
    featurePricingError.value = ''
    featurePricingList.value = await getFeaturePricingList()
  } catch (err) {
    featurePricingError.value = getErrorMessage(err, '加载功能定价失败，请稍后重试')
    console.error('[AdminView] 获取功能定价失败:', err instanceof Error ? err.message : String(err))
  } finally {
    featurePricingLoading.value = false
  }
}

const featurePricingModalOpen = ref(false)
const featurePricingEditing = ref<FeaturePricingAdmin | null>(null)
const fpFeatureKey = ref('')
const fpDisplayName = ref('')
const fpCategory = ref<string>('ai_product_image')
const fpPricingType = ref<PricingType>('per_use')
const fpDescription = ref('')
const fpPerUseCoins = ref(0)
const fpTier1KCoins = ref(0)
const fpTier2KCoins = ref(0)
const fpTier4KCoins = ref(0)
const fpFormError = ref('')
const featureKeyOptions = ref<FeatureKeyOption[]>([])

const FEATURE_PRICING_CATEGORY_LABELS: Record<string, string> = {
  ai_product_image: 'AI 商品图',
  ai_toolbox: 'AI 工具箱',
}

const featurePricingByCategory = computed(() => {
  const order = ['ai_product_image', 'ai_toolbox']
  const groups: { category: string; label: string; items: FeaturePricingAdmin[] }[] = []
  for (const cat of order) {
    const items = featurePricingList.value
      .filter((p) => p.category === cat)
      .sort((a, b) => a.sortOrder - b.sortOrder)
    if (items.length > 0) {
      groups.push({
        category: cat,
        label: FEATURE_PRICING_CATEGORY_LABELS[cat] ?? cat,
        items,
      })
    }
  }
  // 兜底：展示未识别类目下的条目，避免数据丢失
  const known = new Set(order)
  const others = featurePricingList.value
    .filter((p) => !known.has(p.category))
    .sort((a, b) => a.sortOrder - b.sortOrder)
  if (others.length > 0) {
    groups.push({ category: '__other__', label: '其他', items: others })
  }
  return groups
})

const featurePricingConfigPreview = computed(() => {
  if (fpPricingType.value === 'per_use') {
    return `${fpPerUseCoins.value || 0} 币/次`
  }
  return `1K: ${fpTier1KCoins.value || 0}币 / 2K: ${fpTier2KCoins.value || 0}币 / 4K: ${fpTier4KCoins.value || 0}币`
})

const availableFeatureKeyOptions = computed(() => {
  const configured = new Set(featurePricingList.value.map((p) => p.featureKey))
  return featureKeyOptions.value.filter((o) => !configured.has(o.featureKey))
})

const selectedFeatureKeyDescription = computed(() => {
  if (!fpFeatureKey.value) return ''
  const opt = featureKeyOptions.value.find((o) => o.featureKey === fpFeatureKey.value)
  return opt?.description ?? ''
})

function formatFeaturePricingConfig(item: FeaturePricingAdmin): string {
  if (item.pricingType === 'per_use') {
    return `${item.config?.coins ?? 0} 币/次`
  }
  const tiers = item.config?.tiers ?? []
  if (tiers.length === 0) return '未配置档位'
  return tiers.map((t) => `${t.tier}: ${t.coins}币`).join(' / ')
}

async function openCreateFeaturePricing() {
  featurePricingEditing.value = null
  fpFeatureKey.value = ''
  fpDisplayName.value = ''
  fpCategory.value = 'ai_product_image'
  fpPricingType.value = 'per_use'
  fpDescription.value = ''
  fpPerUseCoins.value = 0
  fpTier1KCoins.value = 0
  fpTier2KCoins.value = 0
  fpTier4KCoins.value = 0
  fpFormError.value = ''
  featurePricingModalOpen.value = true

  if (featureKeyOptions.value.length === 0) {
    try {
      featureKeyOptions.value = await getFeatureKeyOptions()
    } catch {
      featureKeyOptions.value = []
    }
  }
}

function openEditFeaturePricing(item: FeaturePricingAdmin) {
  featurePricingEditing.value = item
  fpFeatureKey.value = item.featureKey
  fpDisplayName.value = item.displayName
  fpCategory.value = item.category || 'ai_product_image'
  fpPricingType.value = item.pricingType
  fpDescription.value = item.description ?? ''
  if (item.pricingType === 'per_use') {
    fpPerUseCoins.value = item.config?.coins ?? 0
  } else {
    const tiers = item.config?.tiers ?? []
    fpTier1KCoins.value = tiers.find((t) => t.tier === '1K')?.coins ?? 0
    fpTier2KCoins.value = tiers.find((t) => t.tier === '2K')?.coins ?? 0
    fpTier4KCoins.value = tiers.find((t) => t.tier === '4K')?.coins ?? 0
  }
  fpFormError.value = ''
  featurePricingModalOpen.value = true
}

function onFeatureKeySelected() {
  const opt = featureKeyOptions.value.find((o) => o.featureKey === fpFeatureKey.value)
  if (opt) {
    fpDisplayName.value = opt.displayName
    fpCategory.value = opt.category
    fpPricingType.value = opt.pricingType
  }
}

async function saveFeaturePricing() {
  fpFormError.value = ''
  if (!fpFeatureKey.value.trim()) {
    fpFormError.value = '请选择功能标识'
    return
  }
  if (!fpDisplayName.value.trim()) {
    fpFormError.value = '请输入显示名称'
    return
  }

  let config: FeaturePricingConfig
  if (fpPricingType.value === 'per_use') {
    if (fpPerUseCoins.value <= 0) {
      fpFormError.value = '单次消耗必须大于 0'
      return
    }
    config = { coins: fpPerUseCoins.value }
  } else {
    if (fpTier1KCoins.value <= 0 || fpTier2KCoins.value <= 0 || fpTier4KCoins.value <= 0) {
      fpFormError.value = '各分辨率档位消耗必须大于 0'
      return
    }
    config = {
      tiers: [
        { tier: '1K', max_dimension: 1024, coins: fpTier1KCoins.value },
        { tier: '2K', max_dimension: 2048, coins: fpTier2KCoins.value },
        { tier: '4K', max_dimension: 4096, coins: fpTier4KCoins.value },
      ],
    }
  }

  try {
    if (featurePricingEditing.value) {
      await updateFeaturePricing(featurePricingEditing.value.id, {
        displayName: fpDisplayName.value,
        category: fpCategory.value,
        pricingType: fpPricingType.value,
        config,
        description: fpDescription.value || undefined,
      })
    } else {
      await createFeaturePricing({
        featureKey: fpFeatureKey.value,
        displayName: fpDisplayName.value,
        category: fpCategory.value,
        pricingType: fpPricingType.value,
        config,
        description: fpDescription.value || undefined,
      })
    }
    clearFeaturePricingCache()
    featurePricingModalOpen.value = false
    await fetchFeaturePricing()
  } catch (err) {
    fpFormError.value = getErrorMessage(err, '保存功能定价失败，请稍后重试')
    console.error('保存功能定价失败:', getErrorMessage(err))
  }
}

async function toggleFeaturePricing(item: FeaturePricingAdmin) {
  try {
    await toggleFeaturePricingActive(item.id)
    clearFeaturePricingCache()
    await fetchFeaturePricing()
  } catch (err) {
    featurePricingError.value = getErrorMessage(err, '切换功能定价状态失败，请稍后重试')
    console.error('切换功能定价状态失败:', getErrorMessage(err))
  }
}

async function deleteFeaturePricing(item: FeaturePricingAdmin) {
  pendingDelete.value = { type: 'feature_pricing', id: item.id, label: '功能定价' }
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <!-- 头部 -->
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-slate-900">
        <Shield class="w-5 h-5 inline mr-2 text-brand-purple" />
        管理后台
      </h2>
      <p class="text-sm text-slate-500 mt-1">系统管理与运营配置</p>
    </div>

    <!-- Tab 切换 -->
    <div class="flex items-center gap-2 mb-6">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="activeTab = tab.key"
        :class="[
          'flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200',
          activeTab === tab.key
            ? 'bg-brand-gradient-subtle text-brand-purple'
            : 'bg-slate-100 text-slate-500 hover:text-slate-700',
        ]"
      >
        <component :is="tab.icon" class="w-4 h-4" />
        {{ tab.label }}
      </button>
    </div>

    <!-- ==================== 监控仪表盘 ==================== -->
    <div v-if="activeTab === 'dashboard'" class="space-y-6 animate-fade-in">
      <!-- Loading 状态 -->
      <div v-if="dashboardLoading && stats.onlineUsers === 0" class="text-center py-16 text-slate-400">
        <Activity class="w-12 h-12 mx-auto mb-3 opacity-50 animate-pulse" />
        <p class="font-medium text-slate-500">加载监控数据中...</p>
      </div>

      <template v-else>
      <!-- 顶部三卡片 -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div class="glass-card p-6">
          <div class="flex items-center justify-between mb-4">
            <span class="text-sm text-slate-500">实时在线人数</span>
            <Users class="w-5 h-5 text-brand-cyan" />
          </div>
          <p class="text-3xl font-display font-bold text-slate-900">
            {{ stats.onlineUsers }}
          </p>
          <p class="text-xs text-slate-400 mt-1">当前活跃 session 数</p>
        </div>

        <div class="glass-card p-6">
          <div class="flex items-center justify-between mb-4">
            <span class="text-sm text-slate-500">今日消耗算力</span>
            <Zap class="w-5 h-5 text-amber-500" />
          </div>
          <p class="text-3xl font-display font-bold text-slate-900">
            {{ stats.todayPoints.toLocaleString() }}
          </p>
          <p class="text-xs text-slate-400 mt-1">累计灵感币消耗</p>
        </div>

        <div class="glass-card p-6">
          <div class="flex items-center justify-between mb-4">
            <span class="text-sm text-slate-500">近1h API成功率</span>
            <TrendingUp class="w-5 h-5 text-green-500" />
          </div>
          <div class="flex items-baseline gap-2">
            <p class="text-2xl font-display font-bold text-slate-900">
              {{ Number(stats.qwenSuccessRate).toFixed(1) }}%
            </p>
            <span class="text-lg font-display text-slate-400">/</span>
            <p class="text-2xl font-display font-bold text-brand-purple">
              {{ Number(stats.gptSuccessRate).toFixed(1) }}%
            </p>
          </div>
          <p class="text-xs text-slate-400 mt-1">千问 / GPT-Image-2</p>
        </div>
      </div>

      <!-- 图表区域 -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- 双模型调用对比 -->
        <div class="glass-card p-6">
          <h3 class="text-sm font-semibold text-slate-700 mb-4">
            双模型调用对比（24h）
          </h3>
          <div class="h-48 flex items-end gap-1">
            <div
              v-for="(h, i) in stats.hourlyRequests"
              :key="i"
              class="flex-1 flex flex-col items-center gap-1"
            >
              <div class="w-full flex flex-col items-center gap-0.5">
                <div
                  class="w-full rounded-t-sm bg-brand-purple/70"
                  :style="{ height: `${(h.qwen / maxQwenRequest) * 100}%` }"
                  :title="`千问: ${h.qwen}`"
                />
                <div
                  class="w-full rounded-t-sm bg-brand-cyan/70"
                  :style="{ height: `${(h.gpt / maxGptRequest) * 100}%` }"
                  :title="`GPT: ${h.gpt}`"
                />
              </div>
              <span
                v-if="i % 4 === 0"
                class="text-[9px] text-slate-400 mt-1"
              >
                {{ h.hour }}
              </span>
            </div>
          </div>
          <div class="flex items-center gap-6 mt-4 justify-center">
            <div class="flex items-center gap-2">
              <div class="w-3 h-3 rounded-sm bg-brand-purple/70" />
              <span class="text-xs text-slate-500">通义千问</span>
            </div>
            <div class="flex items-center gap-2">
              <div class="w-3 h-3 rounded-sm bg-brand-cyan/70" />
              <span class="text-xs text-slate-500">GPT-Image-2</span>
            </div>
          </div>
        </div>

        <!-- 失败任务趋势 -->
        <div class="glass-card p-6">
          <h3 class="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            <AlertTriangle class="w-4 h-4 text-amber-500" />
            失败任务趋势（24h）
          </h3>
          <div class="h-48 flex items-end gap-1">
            <div
              v-for="(h, i) in stats.failureTrend"
              :key="i"
              class="flex-1 flex flex-col items-center gap-1"
            >
              <div
                class="w-full rounded-t-sm transition-all"
                :class="h.count > maxFailure * 0.7 ? 'bg-red-400' : 'bg-amber-400/60'"
                :style="{ height: `${maxFailure > 0 ? (h.count / maxFailure) * 100 : 0}%` }"
                :title="`${h.hour}: ${h.count}`"
              />
              <span
                v-if="i % 4 === 0"
                class="text-[9px] text-slate-400 mt-1"
              >
                {{ h.hour }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 模型健康度 -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="glass-card p-6">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-sm font-semibold text-slate-700">通义千问</h3>
            <span
              :class="[
                'flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium',
                stats.modelHealth.qwen.status === 'green'
                  ? 'bg-green-100 text-green-700 border border-green-200'
                  : 'bg-red-100 text-red-700 border border-red-200',
              ]"
            >
              <span
                class="w-2 h-2 rounded-full"
                :class="
                  stats.modelHealth.qwen.status === 'green'
                    ? 'bg-green-500'
                    : 'bg-red-500'
                "
              />
              {{ stats.modelHealth.qwen.status === 'green' ? '正常' : '异常' }}
            </span>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <p class="text-xs text-slate-500 mb-1">平均延迟</p>
              <p class="text-2xl font-display font-bold text-slate-900">
                {{ stats.modelHealth.qwen.latency }}
                <span class="text-sm font-normal text-slate-400">ms</span>
              </p>
            </div>
            <div>
              <p class="text-xs text-slate-500 mb-1">最后检查</p>
              <div class="flex items-center gap-1.5">
                <Clock class="w-3.5 h-3.5 text-slate-400" />
                <p class="text-sm text-slate-600">
                  {{ stats.modelHealth.qwen.lastCheck?.split('T')[1]?.slice(0, 5) || '—' }}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div class="glass-card p-6">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-sm font-semibold text-slate-700">GPT-Image-2</h3>
            <span
              :class="[
                'flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium',
                stats.modelHealth.gpt.status === 'green'
                  ? 'bg-green-100 text-green-700 border border-green-200'
                  : 'bg-red-100 text-red-700 border border-red-200',
              ]"
            >
              <span
                class="w-2 h-2 rounded-full"
                :class="
                  stats.modelHealth.gpt.status === 'green'
                    ? 'bg-green-500'
                    : 'bg-red-500'
                "
              />
              {{ stats.modelHealth.gpt.status === 'green' ? '正常' : '异常' }}
            </span>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <p class="text-xs text-slate-500 mb-1">平均延迟</p>
              <p class="text-2xl font-display font-bold text-slate-900">
                {{ stats.modelHealth.gpt.latency }}
                <span class="text-sm font-normal text-slate-400">ms</span>
              </p>
            </div>
            <div>
              <p class="text-xs text-slate-500 mb-1">最后检查</p>
              <div class="flex items-center gap-1.5">
                <Clock class="w-3.5 h-3.5 text-slate-400" />
                <p class="text-sm text-slate-600">
                  {{ stats.modelHealth.gpt.lastCheck?.split('T')[1]?.slice(0, 5) || '—' }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
      </template>
    </div>

    <!-- ==================== 定价管理 ==================== -->
    <div v-if="activeTab === 'pricing'" class="animate-fade-in">
      <div class="flex items-center justify-between mb-5">
        <div>
          <h3 class="text-base font-semibold text-slate-900 flex items-center gap-2">
            <DollarSign class="w-4 h-4 text-brand-purple" />
            灵感币定价方案
          </h3>
          <p class="text-sm text-slate-500 mt-0.5">管理平台的充值定价策略</p>
        </div>
        <button @click="openNewPlan" class="btn-primary text-sm">
          <Plus class="w-4 h-4" />
          新增方案
        </button>
      </div>

      <!-- Loading 状态 -->
      <div v-if="pricingLoading" class="text-center py-16 text-slate-400">
        <Coins class="w-12 h-12 mx-auto mb-3 opacity-50 animate-pulse" />
        <p class="font-medium text-slate-500">加载定价方案中...</p>
      </div>

      <template v-else>

      <div v-if="pricingPlans.length === 0" class="text-center py-16 text-slate-400">
        <Coins class="w-12 h-12 mx-auto mb-3 opacity-50" />
        <p class="font-medium text-slate-500 mb-1">暂无定价方案</p>
        <p class="text-sm">点击「新增方案」创建第一个定价</p>
      </div>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="plan in pricingPlans"
          :key="plan.id"
          :class="[
            'glass-card p-5 relative transition-all duration-200 group',
            !plan.isActive && 'opacity-60 grayscale',
          ]"
        >
          <div
            v-if="!plan.isActive"
            class="absolute top-3 right-3 px-2 py-0.5 rounded-full bg-slate-200 text-[10px] font-medium text-slate-500"
          >
            已下架
          </div>

          <div class="flex items-start justify-between mb-4">
            <div>
              <h4 class="font-semibold text-slate-900 text-lg">{{ plan.name }}</h4>
            </div>
            <div
              :class="[
                'w-10 h-10 rounded-xl flex items-center justify-center',
                plan.isActive
                  ? 'bg-brand-gradient-subtle'
                  : 'bg-slate-100',
              ]"
            >
              <Coins
                :class="[
                  'w-5 h-5',
                  plan.isActive ? 'text-brand-purple' : 'text-slate-400',
                ]"
              />
            </div>
          </div>

          <div class="mb-4">
            <p class="text-3xl font-display font-bold text-slate-900">
              {{ formatPrice(plan.price) }}
            </p>
            <p class="text-sm text-slate-500 mt-1">
              可得
              <span class="font-semibold text-brand-purple">{{ Number(plan.coins).toLocaleString() }}</span>
              灵感币
              <span v-if="plan.bonusCoins > 0" class="text-amber-500">
                + 赠 {{ plan.bonusCoins }}
              </span>
            </p>
          </div>

          <div class="flex items-center gap-1 text-xs text-slate-400 mb-4">
            <Sparkles class="w-3 h-3" />
            约 {{ (Number(plan.price) / Number(plan.coins)).toFixed(2) }} 元/币
          </div>

          <div class="flex items-center gap-2 pt-3 border-t border-slate-100">
            <button
              @click="togglePlanActive(plan.id)"
              :class="[
                'flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                plan.isActive
                  ? 'bg-amber-50 text-amber-600 hover:bg-amber-100'
                  : 'bg-green-50 text-green-600 hover:bg-green-100',
              ]"
              :title="plan.isActive ? '下架' : '上架'"
            >
              <Ban v-if="plan.isActive" class="w-3.5 h-3.5" />
              <Check v-else class="w-3.5 h-3.5" />
              {{ plan.isActive ? '下架' : '上架' }}
            </button>
            <button
              @click="openEditPlan(plan)"
              class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors"
            >
              <Pencil class="w-3.5 h-3.5" />
              编辑
            </button>
            <button
              @click="deletePlan(plan.id)"
              class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-red-400 hover:bg-red-50 hover:text-red-500 transition-colors ml-auto"
            >
              <Trash2 class="w-3.5 h-3.5" />
              删除
            </button>
          </div>
        </div>
      </div>
      </template>
    </div>

    <!-- ==================== 功能定价 ==================== -->
    <div v-if="activeTab === 'feature_pricing'" class="animate-fade-in">
      <div class="flex items-center justify-between mb-5">
        <div>
          <h3 class="text-base font-semibold text-slate-900 flex items-center gap-2">
            <Tag class="w-4 h-4 text-brand-purple" />
            功能定价
          </h3>
          <p class="text-sm text-slate-500 mt-0.5">管理各 AI 功能的灵感币消耗规则</p>
        </div>
        <button @click="openCreateFeaturePricing" class="btn-primary text-sm">
          <Plus class="w-4 h-4" />
          新增定价
        </button>
      </div>

      <!-- Loading 状态 -->
      <div v-if="featurePricingLoading" class="text-center py-16 text-slate-400">
        <Tag class="w-12 h-12 mx-auto mb-3 opacity-50 animate-pulse" />
        <p class="font-medium text-slate-500">加载功能定价中...</p>
      </div>

      <template v-else>
        <!-- 错误提示 -->
        <div
          v-if="featurePricingError"
          class="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 flex items-center gap-2"
        >
          <AlertCircle class="w-4 h-4 text-red-500 flex-shrink-0" />
          <p class="text-sm text-red-600">{{ featurePricingError }}</p>
          <button
            @click="featurePricingError = ''; fetchFeaturePricing()"
            class="ml-auto text-xs text-red-500 hover:text-red-700 underline flex-shrink-0"
          >
            重试
          </button>
        </div>

        <!-- 空状态 -->
        <div
          v-if="featurePricingList.length === 0 && !featurePricingError"
          class="text-center py-16 text-slate-400"
        >
          <Tag class="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p class="font-medium text-slate-500 mb-1">暂无功能定价</p>
          <p class="text-sm">点击「新增定价」创建第一个功能定价</p>
        </div>

        <!-- 按类目分组展示 -->
        <div v-else class="space-y-6">
          <div v-for="group in featurePricingByCategory" :key="group.category">
            <h4 class="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <span class="w-1 h-4 rounded-full bg-brand-purple"></span>
              {{ group.label }}
              <span class="text-xs font-normal text-slate-400">({{ group.items.length }})</span>
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div
                v-for="item in group.items"
                :key="item.id"
                :class="[
                  'glass-card p-5 relative transition-all duration-200 group',
                  !item.isActive && 'opacity-60 grayscale',
                ]"
              >
                <div
                  v-if="!item.isActive"
                  class="absolute top-3 right-3 px-2 py-0.5 rounded-full bg-slate-200 text-[10px] font-medium text-slate-500"
                >
                  已停用
                </div>

                <div class="flex items-start justify-between mb-3">
                  <div class="min-w-0">
                    <h4 class="font-semibold text-slate-900 truncate">{{ item.displayName }}</h4>
                    <code class="text-xs text-slate-400 font-mono">{{ item.featureKey }}</code>
                  </div>
                  <div
                    class="w-9 h-9 rounded-xl bg-brand-gradient-subtle flex items-center justify-center flex-shrink-0 ml-2"
                  >
                    <Tag class="w-4 h-4 text-brand-purple" />
                  </div>
                </div>

                <div class="flex items-center gap-2 mb-3">
                  <span
                    :class="[
                      'px-2 py-0.5 rounded-full text-[10px] font-medium border',
                      item.pricingType === 'per_image_resolution'
                        ? 'bg-blue-50 text-blue-700 border-blue-200'
                        : 'bg-purple-50 text-purple-700 border-purple-200',
                    ]"
                  >
                    {{ item.pricingType === 'per_image_resolution' ? '按分辨率' : '按次' }}
                  </span>
                </div>

                <p class="text-sm text-slate-600 mb-3">{{ formatFeaturePricingConfig(item) }}</p>

                <p v-if="item.description" class="text-xs text-slate-400 mb-3 line-clamp-2">
                  {{ item.description }}
                </p>

                <div class="flex items-center gap-2 pt-3 border-t border-slate-100">
                  <button
                    @click="toggleFeaturePricing(item)"
                    :class="[
                      'flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                      item.isActive
                        ? 'bg-amber-50 text-amber-600 hover:bg-amber-100'
                        : 'bg-green-50 text-green-600 hover:bg-green-100',
                    ]"
                    :title="item.isActive ? '停用' : '启用'"
                  >
                    <Ban v-if="item.isActive" class="w-3.5 h-3.5" />
                    <Check v-else class="w-3.5 h-3.5" />
                    {{ item.isActive ? '停用' : '启用' }}
                  </button>
                  <button
                    @click="openEditFeaturePricing(item)"
                    class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors"
                  >
                    <Pencil class="w-3.5 h-3.5" />
                    编辑
                  </button>
                  <button
                    @click="deleteFeaturePricing(item)"
                    class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-red-400 hover:bg-red-50 hover:text-red-500 transition-colors ml-auto"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                    删除
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ==================== 团队消耗 ==================== -->
    <div v-if="activeTab === 'consumption'" class="animate-fade-in">
      <div class="mb-5">
        <h3 class="text-base font-semibold text-slate-900 flex items-center gap-2">
          <Building2 class="w-4 h-4 text-brand-purple" />
          团队灵感币消耗总览
        </h3>
        <p class="text-sm text-slate-500 mt-0.5">查看各团队在不同时间维度的算力消耗</p>
      </div>

      <!-- Loading 状态 -->
      <div v-if="consumptionLoading" class="text-center py-16 text-slate-400">
        <Building2 class="w-12 h-12 mx-auto mb-3 opacity-50 animate-pulse" />
        <p class="font-medium text-slate-500">加载团队消耗数据中...</p>
      </div>

      <template v-else>

      <!-- 汇总卡片 -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">团队总数</p>
          <p class="text-2xl font-display font-bold text-slate-900">
            {{ teamConsumptions.length }}
          </p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">总累计消耗</p>
          <p class="text-2xl font-display font-bold text-slate-900">
            {{ formatNumber(teamConsumptions.reduce((s, t) => s + t.totalCoinsConsumed, 0)) }}
          </p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">今日总消耗</p>
          <p class="text-2xl font-display font-bold text-amber-600">
            {{ formatNumber(teamConsumptions.reduce((s, t) => s + t.todayCoinsConsumed, 0)) }}
          </p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">本月总消耗</p>
          <p class="text-2xl font-display font-bold text-brand-purple">
            {{ formatNumber(teamConsumptions.reduce((s, t) => s + t.monthlyCoinsConsumed, 0)) }}
          </p>
        </div>
      </div>

      <!-- 团队消耗表格 -->
      <div class="glass-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead>
              <tr class="border-b border-slate-100">
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">
                  团队
                </th>
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">
                  类目
                </th>
                <th class="text-center text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">
                  成员
                </th>
                <th
                  @click="sortConsumptions('todayCoinsConsumed')"
                  class="text-right text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5 cursor-pointer hover:text-slate-700 select-none"
                >
                  <div class="flex items-center justify-end gap-1">
                    今日消耗
                    <ArrowUpDown class="w-3 h-3" />
                  </div>
                </th>
                <th
                  @click="sortConsumptions('weeklyCoinsConsumed')"
                  class="text-right text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5 cursor-pointer hover:text-slate-700 select-none"
                >
                  <div class="flex items-center justify-end gap-1">
                    本周消耗
                    <ArrowUpDown class="w-3 h-3" />
                  </div>
                </th>
                <th
                  @click="sortConsumptions('monthlyCoinsConsumed')"
                  class="text-right text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5 cursor-pointer hover:text-slate-700 select-none"
                >
                  <div class="flex items-center justify-end gap-1">
                    本月消耗
                    <ArrowUpDown class="w-3 h-3" />
                  </div>
                </th>
                <th
                  @click="sortConsumptions('totalCoinsConsumed')"
                  class="text-right text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5 cursor-pointer hover:text-slate-700 select-none"
                >
                  <div class="flex items-center justify-end gap-1">
                    累计消耗
                    <ArrowUpDown class="w-3 h-3" />
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="team in sortedConsumptions"
                :key="team.teamId"
                class="border-b border-slate-50 hover:bg-slate-50/50 transition-colors"
              >
                <td class="px-5 py-3.5">
                  <div class="flex items-center gap-3">
                    <div
                      class="w-9 h-9 rounded-lg bg-brand-gradient-subtle flex items-center justify-center flex-shrink-0"
                    >
                      <Building2 class="w-4 h-4 text-brand-purple" />
                    </div>
                    <div>
                      <p class="text-sm font-medium text-slate-900">{{ team.teamName }}</p>
                    </div>
                  </div>
                </td>
                <td class="px-5 py-3.5">
                  <span class="px-2 py-0.5 rounded-md bg-slate-100 text-xs text-slate-600">
                    {{ team.category }}
                  </span>
                </td>
                <td class="px-5 py-3.5 text-center">
                  <span class="text-sm text-slate-600">{{ team.memberCount }} 人</span>
                </td>
                <td class="px-5 py-3.5 text-right">
                  <span class="text-sm font-medium text-amber-600">
                    {{ formatNumber(team.todayCoinsConsumed) }}
                  </span>
                </td>
                <td class="px-5 py-3.5 text-right">
                  <span class="text-sm text-slate-700">
                    {{ formatNumber(team.weeklyCoinsConsumed) }}
                  </span>
                </td>
                <td class="px-5 py-3.5 text-right">
                  <span class="text-sm text-slate-700">
                    {{ formatNumber(team.monthlyCoinsConsumed) }}
                  </span>
                </td>
                <td class="px-5 py-3.5 text-right">
                  <span class="text-sm font-semibold text-slate-900">
                    {{ formatNumber(team.totalCoinsConsumed) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="teamConsumptions.length === 0" class="text-center py-16 text-slate-400">
          <Building2 class="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p class="font-medium text-slate-500">暂无团队消耗数据</p>
        </div>
      </div>
      </template>
    </div>

    <!-- ==================== 兑换码管理 ==================== -->
    <div v-if="activeTab === 'redemption'" class="animate-fade-in">
      <div class="flex items-center justify-between mb-5">
        <div>
          <h3 class="text-base font-semibold text-slate-900 flex items-center gap-2">
            <Ticket class="w-4 h-4 text-brand-purple" />
            兑换码管理
          </h3>
          <p class="text-sm text-slate-500 mt-0.5">生成和管理灵感币兑换码</p>
        </div>
        <button @click="showGenerateModal = true" class="btn-primary text-sm">
          <Plus class="w-4 h-4" />
          生成兑换码
        </button>
      </div>

      <!-- Loading 状态 -->
      <div v-if="redemptionLoading" class="text-center py-16 text-slate-400">
        <Ticket class="w-12 h-12 mx-auto mb-3 opacity-50 animate-pulse" />
        <p class="font-medium text-slate-500">加载兑换码数据中...</p>
      </div>

      <!-- 加载错误提示 -->
      <div v-if="redemptionError && !redemptionLoading" class="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 flex items-center gap-2">
        <AlertCircle class="w-4 h-4 text-red-500 flex-shrink-0" />
        <p class="text-sm text-red-600">{{ redemptionError }}</p>
        <button @click="fetchRedemptionCodes(codeFilter === 'all' ? undefined : codeFilter)" 
          class="ml-auto text-xs text-red-500 hover:text-red-700 underline flex-shrink-0">
          重试
        </button>
      </div>

      <template v-else>

      <!-- 统计卡片 -->
      <div class="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-6">
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">总数量</p>
          <p class="text-xl font-display font-bold text-slate-900">{{ codeStats.total }}</p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">剩余可用次数</p>
          <p class="text-xl font-display font-bold text-green-600">{{ codeStats.remainingUses }}</p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">已使用</p>
          <p class="text-xl font-display font-bold text-slate-400">{{ codeStats.used }}</p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">发放总额</p>
          <p class="text-xl font-display font-bold text-brand-purple">{{ formatNumber(codeStats.totalCoins) }}</p>
        </div>
        <div class="glass-card p-4 col-span-2 sm:col-span-1">
          <p class="text-xs text-slate-500 mb-1">已消耗</p>
          <p class="text-xl font-display font-bold text-amber-600">{{ formatNumber(codeStats.usedCoins) }}</p>
        </div>
      </div>

      <!-- 筛选栏 -->
      <div class="flex items-center gap-2 mb-4">
        <button
          v-for="f in [{ key: 'all', label: '全部' }, { key: 'unused', label: '未使用' }, { key: 'used', label: '已使用' }]"
          :key="f.key"
          @click="codeFilter = f.key as typeof codeFilter.value"
          :class="[
            'px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200',
            codeFilter === f.key
              ? 'bg-brand-gradient-subtle text-brand-purple'
              : 'bg-slate-100 text-slate-500 hover:text-slate-700',
          ]"
        >
          {{ f.label }}
        </button>
      </div>

      <!-- 兑换码列表 -->
      <div v-if="filteredCodes.length === 0" class="text-center py-16 text-slate-400">
        <Key class="w-12 h-12 mx-auto mb-3 opacity-50" />
        <p class="font-medium text-slate-500">暂无兑换码</p>
        <p class="text-sm mt-1">点击「生成兑换码」创建新的兑换码</p>
      </div>

      <div v-else class="glass-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead>
              <tr class="border-b border-slate-100">
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">兑换码</th>
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">面额</th>
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">有效期至</th>
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">使用次数</th>
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">状态</th>
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">使用人</th>
                <th class="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">备注</th>
                <th class="text-right text-xs font-semibold text-slate-500 uppercase tracking-wider px-5 py-3.5">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="code in filteredCodes"
                :key="code.id"
                class="border-b border-slate-50 hover:bg-slate-50/50 transition-colors"
              >
                <td class="px-5 py-3.5">
                  <div class="flex items-center gap-2">
                    <code class="px-2.5 py-1 rounded-lg bg-slate-100 text-sm font-mono font-semibold text-brand-purple tracking-wide select-all">
                      {{ code.code }}
                    </code>
                    <button
                      @click="copyCode(code.code)"
                      title="复制"
                      class="p-1 rounded hover:bg-slate-200 text-slate-400 hover:text-slate-600 transition-colors"
                    >
                      <Copy class="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
                <td class="px-5 py-3.5">
                  <span class="font-semibold text-amber-600">{{ code.coins }}</span>
                  <span class="text-xs text-slate-400 ml-0.5">币</span>
                </td>
                <td class="px-5 py-3.5">
                  <div class="flex items-center gap-1.5">
                    <Calendar class="w-3.5 h-3.5 text-slate-400" />
                    <span
                      :class="[
                        'text-sm',
                        isExpired(code.expiresAt) && !code.isUsed ? 'text-red-500 line-through' : 'text-slate-600',
                      ]"
                    >
                      {{ formatDate(code.expiresAt) }}
                    </span>
                  </div>
                </td>
                <td class="px-5 py-3.5">
                  <div class="flex items-center gap-2">
                    <div class="flex-1 min-w-[80px]">
                      <div class="flex items-center justify-between text-xs mb-1">
                        <span class="text-slate-600">{{ code.useCount }}/{{ code.maxUses }}</span>
                        <span class="text-slate-400">单账号限{{ code.maxUsesPerUser }}次</span>
                      </div>
                      <div class="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                        <div
                          :class="[
                            'h-full rounded-full transition-all duration-300',
                            code.useCount >= code.maxUses
                              ? 'bg-red-400'
                              : code.useCount / code.maxUses > 0.7
                                ? 'bg-amber-400'
                                : 'bg-green-400',
                          ]"
                          :style="{ width: Math.min(100, (code.useCount / code.maxUses) * 100) + '%' }"
                        ></div>
                      </div>
                    </div>
                  </div>
                </td>
                <td class="px-5 py-3.5">
                  <span
                    v-if="code.isUsed"
                    class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-slate-100 text-xs font-medium text-slate-500"
                  >
                    已使用
                  </span>
                  <span
                    v-else-if="isExpired(code.expiresAt)"
                    class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-red-50 text-xs font-medium text-red-500 border border-red-200"
                  >
                    已过期
                  </span>
                  <span
                    v-else
                    class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-green-50 text-xs font-medium text-green-600 border border-green-200"
                  >
                    可用
                  </span>
                </td>
                <td class="px-5 py-3.5">
                  <span v-if="code.usedBy" class="text-sm text-slate-600">{{ code.usedBy }}</span>
                  <span v-else class="text-sm text-slate-300">—</span>
                </td>
                <td class="px-5 py-3.5">
                  <span v-if="code.remark" class="text-xs text-slate-500 max-w-[120px] truncate block">{{ code.remark }}</span>
                  <span v-else class="text-xs text-slate-300">—</span>
                </td>
                <td class="px-5 py-3.5 text-right">
                  <button
                    @click="deleteCode(code.id)"
                    class="px-2 py-1 rounded-lg text-xs text-red-400 hover:bg-red-50 hover:text-red-500 transition-colors"
                  >
                    <Trash2 class="w-3.5 h-3.5 inline mr-0.5" />
                    删除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      </template>
    </div>

    <!-- ==================== 公告管理 ==================== -->
    <div v-if="activeTab === 'announcement'" class="animate-fade-in">
      <div class="flex items-center justify-between mb-5">
        <div>
          <h3 class="text-base font-semibold text-slate-900 flex items-center gap-2">
            <Megaphone class="w-4 h-4 text-brand-purple" />
            公告管理
          </h3>
          <p class="text-sm text-slate-500 mt-0.5">发布和管理系统公告，所有用户可见</p>
        </div>
        <button @click="openNewAnnouncement" class="btn-primary text-sm">
          <Plus class="w-4 h-4" />
          发布公告
        </button>
      </div>

      <!-- Loading 状态 -->
      <div v-if="announcementLoading" class="text-center py-16 text-slate-400">
        <Megaphone class="w-12 h-12 mx-auto mb-3 opacity-50 animate-pulse" />
        <p class="font-medium text-slate-500">加载公告数据中...</p>
      </div>

      <template v-else>

      <!-- 统计卡片 -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">总公告数</p>
          <p class="text-xl font-display font-bold text-slate-900">{{ announcements.length }}</p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">已发布</p>
          <p class="text-xl font-display font-bold text-green-600">{{ announcements.filter((a) => a.isActive).length }}</p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">已置顶</p>
          <p class="text-xl font-display font-bold text-amber-600">{{ announcements.filter((a) => a.isPinned).length }}</p>
        </div>
        <div class="glass-card p-4">
          <p class="text-xs text-slate-500 mb-1">已停用</p>
          <p class="text-xl font-display font-bold text-slate-400">{{ announcements.filter((a) => !a.isActive).length }}</p>
        </div>
      </div>

      <!-- 公告列表 -->
      <div v-if="announcements.length === 0" class="text-center py-16 text-slate-400">
        <Megaphone class="w-12 h-12 mx-auto mb-3 opacity-50" />
        <p class="font-medium text-slate-500">暂无公告</p>
        <p class="text-sm mt-1">点击「发布公告」创建第一条公告</p>
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="ann in announcements"
          :key="ann.id"
          :class="[
            'glass-card p-5 transition-all duration-200 group',
            !ann.isActive && 'opacity-60 grayscale',
          ]"
        >
          <div class="flex items-start justify-between mb-3">
            <div class="flex items-start gap-3 flex-1">
              <div
                :class="[
                  'w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0',
                  ann.type === 'info' && 'bg-blue-50',
                  ann.type === 'warning' && 'bg-amber-50',
                  ann.type === 'success' && 'bg-green-50',
                  ann.type === 'important' && 'bg-red-50',
                ]"
              >
                <Megaphone
                  :class="[
                    'w-5 h-5',
                    ann.type === 'info' && 'text-blue-600',
                    ann.type === 'warning' && 'text-amber-600',
                    ann.type === 'success' && 'text-green-600',
                    ann.type === 'important' && 'text-red-600',
                  ]"
                />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <h4 class="font-semibold text-slate-900">{{ ann.title }}</h4>
                  <span
                    v-if="ann.isPinned"
                    class="px-2 py-0.5 rounded-full bg-amber-100 text-[10px] font-medium text-amber-700"
                  >
                    置顶
                  </span>
                  <span
                    :class="[
                      'px-2 py-0.5 rounded-full text-[10px] font-medium',
                      ann.type === 'info' && 'bg-blue-100 text-blue-700',
                      ann.type === 'warning' && 'bg-amber-100 text-amber-700',
                      ann.type === 'success' && 'bg-green-100 text-green-700',
                      ann.type === 'important' && 'bg-red-100 text-red-700',
                    ]"
                  >
                    {{ ann.type === 'info' ? '信息' : ann.type === 'warning' ? '警告' : ann.type === 'success' ? '成功' : '重要' }}
                  </span>
                  <span
                    v-if="!ann.isActive"
                    class="px-2 py-0.5 rounded-full bg-slate-200 text-[10px] font-medium text-slate-500"
                  >
                    已停用
                  </span>
                </div>
                <p class="text-sm text-slate-600 line-clamp-2">{{ ann.content }}</p>
              </div>
            </div>
          </div>

          <div class="flex items-center justify-between pt-3 border-t border-slate-100">
            <div class="flex items-center gap-4 text-xs text-slate-400">
              <span>发布于 {{ formatDate(ann.createdAt) }}</span>
              <span v-if="ann.expiresAt" class="text-amber-500">
                有效期至 {{ formatDate(ann.expiresAt) }}
              </span>
            </div>
            <div class="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click="handleToggleAnnouncementActive(ann.id)"
                :class="[
                  'flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  ann.isActive
                    ? 'bg-amber-50 text-amber-600 hover:bg-amber-100'
                    : 'bg-green-50 text-green-600 hover:bg-green-100',
                ]"
                :title="ann.isActive ? '停用' : '启用'"
              >
                <Ban v-if="ann.isActive" class="w-3.5 h-3.5" />
                <Check v-else class="w-3.5 h-3.5" />
                {{ ann.isActive ? '停用' : '启用' }}
              </button>
              <button
                @click="openEditAnnouncement(ann)"
                class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors"
              >
                <Pencil class="w-3.5 h-3.5" />
                编辑
              </button>
              <button
                @click="handleDeleteAnnouncement(ann.id)"
                class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-red-400 hover:bg-red-50 hover:text-red-500 transition-colors"
              >
                <Trash2 class="w-3.5 h-3.5" />
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
      </template>
    </div>

    <!-- ==================== 定价弹窗 ==================== -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showPricingModal"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showPricingModal = false"
        >
          <div class="bg-white rounded-2xl w-full max-w-md mx-4 p-6 shadow-2xl animate-scale-in">
            <div class="flex items-center justify-between mb-5">
              <h3 class="text-lg font-semibold text-slate-900">
                {{ editingPlan ? '编辑定价方案' : '新增定价方案' }}
              </h3>
              <button
                @click="showPricingModal = false"
                class="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X class="w-5 h-5" />
              </button>
            </div>

            <div class="space-y-4">
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  方案名称
                </label>
                <input
                  v-model="pricingForm.name"
                  type="text"
                  placeholder="例如：入门包、进阶包"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
              </div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                    价格（元）
                  </label>
                  <input
                    v-model.number="pricingForm.price"
                    type="number"
                    min="0"
                    step="0.01"
                    placeholder="29.90"
                    class="glass-input w-full px-4 py-2.5 text-sm"
                  />
                </div>
                <div>
                  <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                    灵感币数量
                  </label>
                  <input
                    v-model.number="pricingForm.coins"
                    type="number"
                    min="0"
                    step="1"
                    placeholder="100"
                    class="glass-input w-full px-4 py-2.5 text-sm"
                  />
                </div>
              </div>
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  赠送灵感币
                </label>
                <input
                  v-model.number="pricingForm.bonusCoins"
                  type="number"
                  min="0"
                  step="1"
                  placeholder="0"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
                <p class="text-xs text-slate-400 mt-1">额外赠送的灵感币数量，填 0 表示无赠送</p>
              </div>

              <div
                v-if="pricingForm.price > 0 && pricingForm.coins > 0"
                class="p-3 rounded-xl bg-brand-gradient-subtle"
              >
                <p class="text-xs text-slate-500 mb-1">预览</p>
                <p class="text-sm font-medium text-slate-800">
                  {{ formatPrice(pricingForm.price) }} =
                  <span class="text-brand-purple font-semibold">{{ pricingForm.coins.toLocaleString() }}</span>
                  灵感币
                  <span v-if="pricingForm.bonusCoins > 0" class="text-amber-500">
                    + 赠 {{ pricingForm.bonusCoins.toLocaleString() }}
                  </span>
                </p>
                <p class="text-xs text-slate-400 mt-1">
                  约 {{ (Number(pricingForm.price) / Number(pricingForm.coins)).toFixed(2) }} 元/币
                </p>
              </div>
            </div>

            <div class="flex gap-3 mt-6">
              <button @click="showPricingModal = false" class="btn-secondary flex-1">
                取消
              </button>
              <button
                @click="savePlan"
                :disabled="!pricingForm.name || pricingForm.price <= 0 || pricingForm.coins <= 0"
                class="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {{ editingPlan ? '保存修改' : '创建方案' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ==================== 生成兑换码弹窗 ==================== -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showGenerateModal"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showGenerateModal = false"
        >
          <div class="bg-white rounded-2xl w-full max-w-md mx-4 p-6 shadow-2xl animate-scale-in">
            <div class="flex items-center justify-between mb-5">
              <h3 class="text-lg font-semibold text-slate-900">生成兑换码</h3>
              <button
                @click="showGenerateModal = false"
                class="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X class="w-5 h-5" />
              </button>
            </div>

            <div class="space-y-4">
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  灵感币额度
                </label>
                <input
                  v-model.number="generateForm.coins"
                  type="number"
                  min="1"
                  step="1"
                  placeholder="100"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
              </div>
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  有效期（天）
                </label>
                <input
                  v-model.number="generateForm.expiresDays"
                  type="number"
                  min="1"
                  step="1"
                  placeholder="30"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
                <p class="text-xs text-slate-400 mt-1">从生成之日起计算有效期</p>
              </div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                    总使用次数
                  </label>
                  <input
                    v-model.number="generateForm.maxUses"
                    type="number"
                    min="1"
                    step="1"
                    placeholder="1"
                    class="glass-input w-full px-4 py-2.5 text-sm"
                    @change="onMaxUsesChange"
                  />
                </div>
                <div>
                  <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                    单账号限用次数
                  </label>
                  <input
                    v-model.number="generateForm.maxUsesPerUser"
                    type="number"
                    min="1"
                    :max="generateForm.maxUses"
                    step="1"
                    placeholder="1"
                    class="glass-input w-full px-4 py-2.5 text-sm"
                  />
                </div>
              </div>
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  备注（可选）
                </label>
                <input
                  v-model="generateForm.remark"
                  type="text"
                  placeholder="例如：新用户礼包、活动奖励"
                  maxlength="50"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
              </div>

              <div class="p-3 rounded-xl bg-brand-gradient-subtle space-y-1.5">
                <p class="text-xs text-slate-500">预览</p>
                <p class="text-sm font-medium text-slate-800">
                  兑换码面额：<span class="font-bold text-brand-purple">{{ generateForm.coins || 0 }} 灵感币</span>
                </p>
                <p class="text-xs text-slate-500">
                  有效期 {{ generateForm.expiresDays || 0 }} 天 ·
                  限使用 {{ generateForm.maxUses || 1 }} 次，每账号限 {{ generateForm.maxUsesPerUser || 1 }} 次
                </p>
              </div>
            </div>

            <div class="flex gap-3 mt-6">
              <button @click="showGenerateModal = false" class="btn-secondary flex-1">
                取消
              </button>
              <button
                @click="generateCodes"
                :disabled="generateForm.coins <= 0 || generateForm.expiresDays <= 0 || generateForm.maxUses < 1 || generateForm.maxUsesPerUser < 1 || generateForm.maxUsesPerUser > generateForm.maxUses"
                class="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                生成
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ==================== 发布/编辑公告弹窗 ==================== -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showAnnouncementModal"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showAnnouncementModal = false"
        >
          <div class="bg-white rounded-2xl w-full max-w-lg mx-4 p-6 shadow-2xl animate-scale-in max-h-[90vh] overflow-y-auto">
            <div class="flex items-center justify-between mb-5">
              <h3 class="text-lg font-semibold text-slate-900">
                {{ editingAnnouncement ? '编辑公告' : '发布公告' }}
              </h3>
              <button
                @click="showAnnouncementModal = false"
                class="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X class="w-5 h-5" />
              </button>
            </div>

            <div class="space-y-4">
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  公告标题 *
                </label>
                <input
                  v-model="announcementForm.title"
                  type="text"
                  placeholder="请输入公告标题（支持 emoji）"
                  maxlength="100"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
              </div>

              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  公告内容 *
                </label>
                <textarea
                  v-model="announcementForm.content"
                  placeholder="请输入公告详细内容..."
                  rows="5"
                  maxlength="1000"
                  class="glass-input w-full px-4 py-2.5 text-sm resize-none"
                ></textarea>
                <p class="text-xs text-slate-400 mt-1">{{ announcementForm.content.length }} / 1000</p>
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                    公告类型
                  </label>
                  <select
                    v-model="announcementForm.type"
                    class="glass-input w-full px-4 py-2.5 text-sm"
                  >
                    <option value="info">ℹ️ 信息通知</option>
                    <option value="warning">⚠️ 警告提醒</option>
                    <option value="success">✅ 成功/活动</option>
                    <option value="important">📢 重要公告</option>
                  </select>
                </div>
                <div>
                  <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                    有效期至（可选）
                  </label>
                  <input
                    v-model="announcementForm.expiresAt"
                    type="date"
                    class="glass-input w-full px-4 py-2.5 text-sm"
                  />
                  <p class="text-xs text-slate-400 mt-1">留空表示长期有效</p>
                </div>
              </div>

              <div class="flex items-center gap-3 pt-2">
                <label class="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    v-model="announcementForm.isPinned"
                    class="w-4 h-4 rounded border-slate-300 text-brand-purple focus:ring-brand-purple"
                  />
                  <span class="text-sm text-slate-700">置顶显示</span>
                </label>
                <span class="text-xs text-slate-400">置顶的公告会优先展示给用户</span>
              </div>

              <div v-if="announcementForm.title && announcementForm.content" class="p-3 rounded-xl bg-brand-gradient-subtle space-y-2">
                <p class="text-xs text-slate-500">预览</p>
                <div :class="['p-3 rounded-lg', announcementForm.type === 'info' ? 'bg-blue-50' : announcementForm.type === 'warning' ? 'bg-amber-50' : announcementForm.type === 'success' ? 'bg-green-50' : 'bg-red-50']">
                  <p :class="['font-medium text-sm', announcementForm.type === 'info' ? 'text-blue-700' : announcementForm.type === 'warning' ? 'text-amber-700' : announcementForm.type === 'success' ? 'text-green-700' : 'text-red-700']">
                    {{ announcementForm.title }}
                  </p>
                  <p class="text-xs text-slate-600 mt-1 line-clamp-2">{{ announcementForm.content }}</p>
                </div>
              </div>
            </div>

            <div class="flex gap-3 mt-6">
              <button @click="showAnnouncementModal = false" class="btn-secondary flex-1">
                取消
              </button>
              <button
                @click="saveAnnouncement"
                :disabled="!announcementForm.title || !announcementForm.content"
                class="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {{ editingAnnouncement ? '保存修改' : '发布公告' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ==================== 功能定价弹窗 ==================== -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="featurePricingModalOpen"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="featurePricingModalOpen = false"
        >
          <div class="bg-white rounded-2xl w-full max-w-lg mx-4 p-6 shadow-2xl animate-scale-in max-h-[90vh] overflow-y-auto">
            <div class="flex items-center justify-between mb-5">
              <h3 class="text-lg font-semibold text-slate-900">
                {{ featurePricingEditing ? '编辑功能定价' : '新增功能定价' }}
              </h3>
              <button
                @click="featurePricingModalOpen = false"
                class="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X class="w-5 h-5" />
              </button>
            </div>

            <div class="space-y-4">
              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  功能标识 (feature_key) *
                </label>
                <!-- 新建模式：下拉选择 -->
                <select
                  v-if="!featurePricingEditing"
                  v-model="fpFeatureKey"
                  @change="onFeatureKeySelected"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                  :disabled="availableFeatureKeyOptions.length === 0"
                >
                  <option value="" disabled>
                    {{ availableFeatureKeyOptions.length === 0 ? '所有功能已配置定价' : '请选择功能标识...' }}
                  </option>
                  <option
                    v-for="opt in availableFeatureKeyOptions"
                    :key="opt.featureKey"
                    :value="opt.featureKey"
                  >
                    {{ opt.featureKey }} — {{ opt.displayName }}
                  </option>
                </select>
                <!-- 编辑模式：只读文本 -->
                <input
                  v-else
                  :value="fpFeatureKey"
                  type="text"
                  disabled
                  class="glass-input w-full px-4 py-2.5 text-sm disabled:bg-slate-50 disabled:text-slate-400"
                />
                <p class="text-xs text-slate-400 mt-1">
                  {{ availableFeatureKeyOptions.length === 0 && !featurePricingEditing
                    ? '所有功能已配置定价，请使用编辑功能修改现有定价'
                    : (selectedFeatureKeyDescription || '创建后不可修改，请从可用功能中选择') }}
                </p>
              </div>

              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  显示名称 *
                </label>
                <input
                  v-model="fpDisplayName"
                  type="text"
                  placeholder="例如：智能商品图、AI 模特"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                    类目
                  </label>
                  <select v-model="fpCategory" class="glass-input w-full px-4 py-2.5 text-sm">
                    <option value="ai_product_image">AI 商品图</option>
                    <option value="ai_toolbox">AI 工具箱</option>
                  </select>
                </div>
                <div>
                  <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                    计费方式
                  </label>
                  <select v-model="fpPricingType" class="glass-input w-full px-4 py-2.5 text-sm">
                    <option value="per_use">按次计费</option>
                    <option value="per_image_resolution">按分辨率计费</option>
                  </select>
                </div>
              </div>

              <!-- 按次计费 -->
              <div v-if="fpPricingType === 'per_use'">
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  单次消耗（灵感币）*
                </label>
                <input
                  v-model.number="fpPerUseCoins"
                  type="number"
                  min="1"
                  step="1"
                  placeholder="5"
                  class="glass-input w-full px-4 py-2.5 text-sm"
                />
              </div>

              <!-- 按分辨率计费 -->
              <div v-else class="space-y-2">
                <label class="text-sm font-medium text-slate-700 block">
                  分辨率档位消耗（灵感币）*
                </label>
                <div class="grid grid-cols-3 gap-3">
                  <div>
                    <label class="text-xs text-slate-500 mb-1 block">1K (1024px)</label>
                    <input
                      v-model.number="fpTier1KCoins"
                      type="number"
                      min="1"
                      step="1"
                      placeholder="5"
                      class="glass-input w-full px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label class="text-xs text-slate-500 mb-1 block">2K (2048px)</label>
                    <input
                      v-model.number="fpTier2KCoins"
                      type="number"
                      min="1"
                      step="1"
                      placeholder="10"
                      class="glass-input w-full px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label class="text-xs text-slate-500 mb-1 block">4K (4096px)</label>
                    <input
                      v-model.number="fpTier4KCoins"
                      type="number"
                      min="1"
                      step="1"
                      placeholder="15"
                      class="glass-input w-full px-3 py-2 text-sm"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label class="text-sm font-medium text-slate-700 mb-1.5 block">
                  描述（可选）
                </label>
                <textarea
                  v-model="fpDescription"
                  placeholder="该功能的简要说明"
                  rows="2"
                  maxlength="200"
                  class="glass-input w-full px-4 py-2.5 text-sm resize-none"
                ></textarea>
              </div>

              <!-- 表单错误 -->
              <div
                v-if="fpFormError"
                class="p-3 rounded-lg bg-red-50 border border-red-200 flex items-center gap-2"
              >
                <AlertCircle class="w-4 h-4 text-red-500 flex-shrink-0" />
                <p class="text-sm text-red-600">{{ fpFormError }}</p>
              </div>

              <!-- 预览 -->
              <div v-if="fpDisplayName" class="p-3 rounded-xl bg-brand-gradient-subtle">
                <p class="text-xs text-slate-500 mb-1">预览</p>
                <p class="text-sm font-medium text-slate-800">
                  {{ fpDisplayName }}
                  <span class="text-xs text-slate-500">({{ fpFeatureKey || '—' }})</span>
                </p>
                <p class="text-xs text-slate-600 mt-1">{{ featurePricingConfigPreview }}</p>
              </div>
            </div>

            <div class="flex gap-3 mt-6">
              <button @click="featurePricingModalOpen = false" class="btn-secondary flex-1">
                取消
              </button>
              <button @click="saveFeaturePricing" class="btn-primary flex-1">
                {{ featurePricingEditing ? '保存修改' : '创建' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 统一的删除确认弹窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="pendingDelete"
          class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm"
          @click.self="pendingDelete = null"
        >
          <div class="bg-white rounded-2xl shadow-2xl p-6 max-w-md w-full mx-4">
            <div class="flex items-center gap-3 mb-4">
              <div class="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                <AlertTriangle class="w-5 h-5 text-red-500" />
              </div>
              <h3 class="text-lg font-semibold text-slate-800">确认删除</h3>
            </div>
            <p class="text-slate-600 mb-6">
              <template v-if="pendingDelete.type === 'feature_pricing'">
                删除后该功能将无法正常计费，确定要删除吗？此操作无法撤销。
              </template>
              <template v-else>
                确定要删除该{{ pendingDelete.label }}吗？此操作无法撤销。
              </template>
            </p>
            <div class="flex gap-3 justify-end">
              <button
                @click="pendingDelete = null"
                class="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
                :disabled="deleteLoading"
              >
                取消
              </button>
              <button
                @click="executeDelete"
                class="px-4 py-2 text-sm font-medium text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                :disabled="deleteLoading"
              >
                <span v-if="deleteLoading" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
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
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>