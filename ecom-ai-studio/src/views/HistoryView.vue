<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { fetchHistory, deleteHistory, fetchHistoryDetail, fetchTeamHistory } from '@/api/history'
import { addHistoryFavorite } from '@/api/favorites'
import { getMyTeams } from '@/api/team'
import { useAuthStore } from '@/stores/auth'
import type { HistoryRecordItem, HistoryCategory, HistorySubCategory, Team } from '@/types'
import { CATEGORY_LABELS, SUB_CATEGORY_LABELS } from '@/types'
import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'
import { Clock, Trash2, Eye, X, Heart, Users } from 'lucide-vue-next'
import HistoryDetail from '@/components/history/HistoryDetail.vue'

const auth = useAuthStore()
const loading = ref(false)
const error = ref<string | null>(null)
const actionError = ref<string | null>(null)
const records = ref<HistoryRecordItem[]>([])
const currentPage = ref(1)
const pageSize = ref(20)
const totalPages = ref(0)
const selectedCategory = ref<HistoryCategory | null>(null)
const selectedSubCategory = ref<HistorySubCategory | null>(null)
const detailRecordId = ref<number | null>(null)

// 图片加载失败追踪
const imgErrors = reactive<Set<number>>(new Set())

function handleImgError(id: number) {
  imgErrors.add(id)
}

// 模式切换：我的历史 / 团队历史
const historyMode = ref<'mine' | 'team'>('mine')
const teams = ref<Team[]>([])
const selectedTeamId = ref<string | null>(null)
// 正在收藏中的记录ID，防止重复点击
const favoritingIds = ref<Set<number>>(new Set())
// 已收藏的记录ID（点击成功后加入）
const favoritedIds = ref<Set<number>>(new Set())

const mainCategories: { value: HistoryCategory | null; label: string }[] = [
  { value: null, label: '全部' },
  { value: 'ai_product_image', label: 'AI商品图' },
  { value: 'ai_toolbox', label: 'AI工具箱' },
]

const aiProductImageSubs: { value: HistorySubCategory | null; label: string }[] = [
  { value: null, label: '全部' },
  { value: 'smart_mode', label: '简单模式' },
  { value: 'pro_mode', label: '专业模式' },
]

const aiToolboxSubs: { value: HistorySubCategory | null; label: string }[] = [
  { value: null, label: '全部' },
  { value: 'plan_analysis', label: '生图计划分析' },
  { value: 'image_merge', label: '图片合并' },
  { value: 'text_to_image', label: '文生图' },
  { value: 'chat_gen', label: '对话式生图' },
  { value: 'product_replace', label: '产品替换' },
  { value: 'ai_model', label: 'AI模特' },
  { value: 'model_product', label: '模特商品图' },
  { value: 'prompt_reverse', label: '反推提示词' },
  { value: 'editor', label: '图片编辑器' },
]

const subCategories = computed(() => {
  if (selectedCategory.value === 'ai_product_image') return aiProductImageSubs
  if (selectedCategory.value === 'ai_toolbox') return aiToolboxSubs
  return []
})

function selectCategory(value: HistoryCategory | null) {
  selectedCategory.value = value
  selectedSubCategory.value = null
  currentPage.value = 1
  loadHistory()
}

function selectSubCategory(value: HistorySubCategory | null) {
  selectedSubCategory.value = value
  currentPage.value = 1
  loadHistory()
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function loadTeams() {
  try {
    const res = await getMyTeams()
    teams.value = res.data?.teams || []
  } catch (e: any) {
    // 静默失败，团队加载失败不影响我的历史
    teams.value = []
  }
}

function switchMode(mode: 'mine' | 'team') {
  historyMode.value = mode
  currentPage.value = 1
  selectedCategory.value = null
  selectedSubCategory.value = null
  if (mode === 'team') {
    // 自动选中第一个团队（若有）
    if (teams.value.length > 0 && !selectedTeamId.value) {
      selectedTeamId.value = teams.value[0].id
    }
    loadHistory()
  } else {
    records.value = []
    loadHistory()
  }
}

function selectTeam(teamId: string) {
  selectedTeamId.value = teamId
  currentPage.value = 1
  loadHistory()
}

async function handleFavorite(id: number) {
  if (favoritingIds.value.has(id) || favoritedIds.value.has(id)) return
  favoritingIds.value.add(id)
  try {
    await addHistoryFavorite(id)
    favoritedIds.value.add(id)
  } catch (e: any) {
    // 409 表示已收藏，也标记为已收藏
    const msg = getErrorMessage(e, '')
    if (msg.includes('已收藏') || (e as any)?.code === 2006) {
      favoritedIds.value.add(id)
    } else {
      actionError.value = getErrorMessage(e, '收藏失败，请稍后重试')
    }
  } finally {
    favoritingIds.value.delete(id)
  }
}

async function loadHistory() {
  loading.value = true
  error.value = null
  try {
    let res
    if (historyMode.value === 'mine') {
      res = await fetchHistory({
        category: selectedCategory.value ?? undefined,
        sub_category: selectedSubCategory.value ?? undefined,
        page: currentPage.value,
        page_size: pageSize.value,
      })
    } else {
      // 团队历史模式
      if (!selectedTeamId.value) {
        records.value = []
        totalPages.value = 0
        return
      }
      res = await fetchTeamHistory(Number(selectedTeamId.value), {
        page: currentPage.value,
        page_size: pageSize.value,
      })
    }
    records.value = res.data
    totalPages.value = res.pagination.totalPages
  } catch (e: any) {
    error.value = getErrorMessage(e, ERROR_DEFAULTS.LOAD_FAILED)
    records.value = []
  } finally {
    loading.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await deleteHistory(id)
    records.value = records.value.filter((r) => r.id !== id)
  } catch (e: any) {
    actionError.value = getErrorMessage(e, '删除失败，请稍后重试')
  }
}

function handleViewDetail(id: number) {
  detailRecordId.value = id
}

onMounted(() => {
  loadTeams()
  loadHistory()
})
</script>

<template>
  <div class="p-6 max-w-6xl mx-auto">
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-semibold text-slate-900">
        <Clock class="w-5 h-5 inline mr-2 text-brand-purple" />
        历史记录
      </h2>
      <p class="text-sm text-slate-500">
        {{ totalPages > 0 ? `第 ${currentPage} / ${totalPages} 页` : '' }}
      </p>
    </div>

    <!-- Action error inline alert -->
    <Transition name="fade">
      <div
        v-if="actionError"
        class="mb-4 px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 flex items-center justify-between"
      >
        <span>{{ actionError }}</span>
        <button @click="actionError = null" class="text-red-400 hover:text-red-600 ml-4">
          <X class="w-4 h-4" />
        </button>
      </div>
    </Transition>

    <!-- 模式切换 -->
    <div class="flex gap-2 mb-4">
      <button
        @click="switchMode('mine')"
        :class="historyMode === 'mine' ? 'bg-brand-purple text-white' : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'"
        class="px-4 py-1.5 rounded-full text-sm font-medium transition-colors"
      >我的历史</button>
      <button
        @click="switchMode('team')"
        :class="historyMode === 'team' ? 'bg-brand-purple text-white' : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'"
        class="px-4 py-1.5 rounded-full text-sm font-medium transition-colors"
      >团队历史</button>
    </div>

    <!-- 团队选择器（仅团队历史模式显示） -->
    <div v-if="historyMode === 'team'" class="flex items-center gap-2 mb-4">
      <Users class="w-4 h-4 text-slate-400" />
      <select
        v-model="selectedTeamId"
        @change="selectTeam(($event.target as HTMLSelectElement).value)"
        class="px-3 py-1.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:border-brand-purple/50"
      >
        <option v-for="team in teams" :key="team.id" :value="team.id">{{ team.name }}</option>
      </select>
    </div>

    <!-- Category filter tabs（仅我的历史模式显示） -->
    <div v-if="historyMode === 'mine'" class="flex flex-col gap-3 mb-6">
      <!-- Level 1: Main category -->
      <div class="flex gap-2">
        <button
          v-for="cat in mainCategories"
          :key="cat.label"
          @click="selectCategory(cat.value)"
          :class="
            selectedCategory === cat.value
              ? 'bg-brand-purple text-white'
              : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
          "
          class="px-4 py-1.5 rounded-full text-sm font-medium transition-colors"
        >
          {{ cat.label }}
        </button>
      </div>

      <!-- Level 2: Sub category (only when a main category is selected) -->
      <div v-if="subCategories.length > 0" class="flex gap-2">
        <button
          v-for="sub in subCategories"
          :key="sub.label"
          @click="selectSubCategory(sub.value)"
          :class="
            selectedSubCategory === sub.value
              ? 'bg-brand-purple/10 text-brand-purple'
              : 'text-slate-500 hover:text-slate-700'
          "
          class="px-3 py-1 rounded-full text-xs font-medium transition-colors"
        >
          {{ sub.label }}
        </button>
      </div>
    </div>

    <!-- Empty State (team mode: no teams joined) -->
    <div v-if="historyMode === 'team' && teams.length === 0" class="text-center py-20 text-slate-400">
      <Users class="w-10 h-10 mx-auto mb-3 opacity-50" />
      <p>请先加入团队</p>
      <p class="text-sm mt-1">加入团队后可查看团队成员分享的历史记录</p>
    </div>

    <!-- Loading State -->
    <div v-else-if="loading" class="text-center py-20">
      <svg class="animate-spin w-8 h-8 mx-auto text-brand-purple" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25" />
        <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" class="opacity-75" />
      </svg>
      <p class="mt-3 text-sm text-slate-400">加载中...</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="text-center py-20">
      <p class="text-red-500 mb-3">{{ error }}</p>
      <button @click="loadHistory" class="btn-secondary text-sm px-4 py-2">重试</button>
    </div>

    <!-- Empty State -->
    <div v-else-if="records.length === 0 && historyMode === 'mine' && (selectedCategory || selectedSubCategory)" class="text-center py-20 text-slate-400">
      <Clock class="w-10 h-10 mx-auto mb-3 opacity-50" />
      <p>当前筛选条件下暂无历史记录</p>
      <p class="text-sm mt-1">尝试选择其他标签或返回"全部"查看</p>
    </div>

    <!-- Empty State (no filter) -->
    <div v-else-if="records.length === 0" class="text-center py-20 text-slate-400">
      <Clock class="w-10 h-10 mx-auto mb-3 opacity-50" />
      <p>暂无历史记录</p>
      <p class="text-sm mt-1">在工作台生成图片后可以查看记录</p>
    </div>

    <!-- Grid -->
    <div v-else class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
      <div
        v-for="item in records"
        :key="item.id"
        class="glass-card overflow-hidden group animate-fade-in"
      >
        <div class="relative aspect-square canvas-checkerboard">
          <img
            v-if="item.thumbnail_url && !imgErrors.has(item.id)"
            :src="item.thumbnail_url"
            :alt="item.title"
            class="w-full h-full object-cover"
            loading="lazy"
            @error="handleImgError(item.id)"
          />
          <div v-else class="w-full h-full flex items-center justify-center bg-slate-100">
            <Clock class="w-8 h-8 text-slate-300" />
          </div>
          <div class="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
        </div>

        <div class="p-2">
          <p class="text-sm font-medium text-slate-800 truncate" :title="item.title">
            {{ item.title }}
          </p>
          <div class="flex items-center gap-2 mt-1">
            <span class="px-2 py-0.5 rounded-full text-xs bg-brand-purple/10 text-brand-purple">
              {{ SUB_CATEGORY_LABELS[item.sub_category] || item.sub_category }}
            </span>
            <span class="text-xs text-slate-400">{{ formatDate(item.created_at) }}</span>
          </div>
          <!-- 团队历史模式下显示记录来源所有者（自己则不显示） -->
          <div
            v-if="historyMode === 'team' && item.user_id !== Number(auth.user?.id)"
            class="flex items-center gap-1 mt-1 text-xs text-slate-400"
          >
            <Users class="w-3 h-3" />
            <span>来自：用户{{ item.user_id }}</span>
          </div>
        </div>

        <div class="flex items-center justify-center gap-1 p-2 border-t border-slate-100">
          <button
            @click="handleViewDetail(item.id)"
            class="p-2 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
            title="查看详情"
          >
            <Eye class="w-4 h-4" />
          </button>
          <button
            @click="handleFavorite(item.id)"
            :disabled="favoritingIds.has(item.id) || favoritedIds.has(item.id)"
            :class="favoritedIds.has(item.id) ? 'text-red-500' : 'text-slate-400 hover:text-red-500 hover:bg-red-50'"
            class="p-2 rounded-lg transition-colors disabled:opacity-50"
            :title="favoritedIds.has(item.id) ? '已收藏' : '收藏'"
          >
            <Heart class="w-4 h-4" :class="{ 'fill-current': favoritedIds.has(item.id) }" />
          </button>
          <button
            v-if="historyMode === 'mine'"
            @click="handleDelete(item.id)"
            class="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
            title="删除"
          >
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="totalPages > 1" class="flex justify-center items-center gap-2 mt-6">
      <button
        :disabled="currentPage <= 1"
        @click="currentPage--; loadHistory()"
        class="px-3 py-1.5 rounded-lg text-sm border border-slate-200 disabled:opacity-40"
      >
        上一页
      </button>
      <span class="text-sm text-slate-500">第 {{ currentPage }} / {{ totalPages }} 页</span>
      <button
        :disabled="currentPage >= totalPages"
        @click="currentPage++; loadHistory()"
        class="px-3 py-1.5 rounded-lg text-sm border border-slate-200 disabled:opacity-40"
      >
        下一页
      </button>
    </div>

    <!-- HistoryDetail modal -->
    <HistoryDetail
      v-if="detailRecordId !== null"
      :record-id="detailRecordId"
      @close="detailRecordId = null"
    />
  </div>
</template>

<style scoped>
.fade-enter-active {
  transition: opacity 0.3s ease;
}
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>