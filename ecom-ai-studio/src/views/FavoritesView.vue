<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'
import { fetchFavorites, removeFavorite } from '@/api/favorites'
import { SUB_CATEGORY_LABELS, type FavoriteItem } from '@/types'
import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'
import { Heart, Download, Copy, Trash2, X, Eye, Clock } from 'lucide-vue-next'
import HistoryDetail from '@/components/history/HistoryDetail.vue'

const router = useRouter()
const workspace = useWorkspaceStore()

const loading = ref(false)
const error = ref<string | null>(null)
const actionError = ref<string | null>(null)
const currentPage = ref(1)
const pageSize = ref(20)
const totalPages = ref(0)

const favorites = ref<FavoriteItem[]>([])
const detailRecordId = ref<number | null>(null)

// 图片加载失败追踪
const imgErrors = reactive<Set<string>>(new Set())

function handleImgError(id: string) {
  imgErrors.add(id)
}

function handleDownload(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = 'ecomai-favorite.jpg'
  a.click()
}

async function handleUnfavorite(id: string) {
  try {
    await removeFavorite(id)
    favorites.value = favorites.value.filter((f) => f.id !== id)
  } catch (e: any) {
    actionError.value = getErrorMessage(e, '取消收藏失败，请稍后重试')
  }
}

function handleReGenerate(item: FavoriteItem) {
  if (!item.config) {
    actionError.value = '该记录无配置快照，无法再次生成'
    return
  }
  workspace.loadConfig(item.config)
  router.push('/workspace')
}

function handleViewDetail(historyRecordId: number) {
  detailRecordId.value = historyRecordId
}

async function loadFavorites() {
  loading.value = true
  error.value = null
  try {
    const res = await fetchFavorites({
      page: currentPage.value,
      pageSize: pageSize.value,
    })
    favorites.value = res.data
    totalPages.value = res.pagination.totalPages
  } catch (e: any) {
    error.value = getErrorMessage(e, ERROR_DEFAULTS.LOAD_FAILED)
    favorites.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadFavorites()
})
</script>

<template>
  <div class="p-6 max-w-6xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-semibold text-slate-900">
        <Heart class="w-5 h-5 inline mr-2 text-red-400 fill-current" />
        我的收藏
      </h2>
      <p class="text-sm text-slate-500">
        {{ totalPages > 0 ? `第 ${currentPage} / ${totalPages} 页` : '' }}
      </p>
    </div>

    <!-- 操作错误提示 -->
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

    <!-- Loading State -->
    <div v-if="loading" class="text-center py-20">
      <svg class="animate-spin w-8 h-8 mx-auto text-brand-purple" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25"/>
        <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" class="opacity-75"/>
      </svg>
      <p class="mt-3 text-sm text-slate-400">加载中...</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="text-center py-20">
      <p class="text-red-500 mb-3">{{ error }}</p>
      <button @click="loadFavorites" class="btn-secondary text-sm px-4 py-2">重试</button>
    </div>

    <div v-else-if="favorites.length === 0" class="text-center py-20 text-slate-400">
      <Heart class="w-10 h-10 mx-auto mb-3 opacity-50" />
      <p>暂无收藏</p>
      <p class="text-sm mt-1">在工作台生成图片或收藏历史记录后可在此查看</p>
    </div>

    <div
      v-else
      class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4"
    >
      <template v-for="item in favorites" :key="item.id">
        <!-- history 类型卡片 -->
        <div
          v-if="item.targetType === 'history'"
          class="glass-card overflow-hidden group animate-fade-in"
        >
          <div class="relative aspect-square canvas-checkerboard">
            <img
              v-if="item.thumbnailUrl && !imgErrors.has(item.id)"
              :src="item.thumbnailUrl"
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
            <div class="flex items-center gap-2 mt-1 flex-wrap">
              <span class="px-2 py-0.5 rounded-full text-xs bg-brand-purple/10 text-brand-purple">
                {{ item.subCategory ? (SUB_CATEGORY_LABELS[item.subCategory] || item.subCategory) : '历史记录' }}
              </span>
              <span
                v-if="item.sourceUserName && item.sourceUserId !== item.userId"
                class="text-xs text-slate-400 truncate"
              >
                来自：{{ item.sourceUserName }}
              </span>
            </div>
          </div>

          <div class="flex items-center justify-center gap-1 p-2 border-t border-slate-100">
            <button
              @click="item.historyRecordId != null && handleViewDetail(item.historyRecordId)"
              class="p-2 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
              title="查看详情"
            >
              <Eye class="w-4 h-4" />
            </button>
            <button
              @click="handleReGenerate(item)"
              :disabled="!item.config"
              :class="!item.config
                ? 'p-2 rounded-lg text-slate-300 cursor-not-allowed'
                : 'p-2 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors'"
              :title="!item.config ? '无配置快照，无法再次生成' : '再次生成'"
            >
              <Copy class="w-4 h-4" />
            </button>
            <button
              @click="handleUnfavorite(item.id)"
              class="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
              title="取消收藏"
            >
              <Trash2 class="w-4 h-4" />
            </button>
          </div>
        </div>

        <!-- image 类型卡片（保持原样） -->
        <div
          v-else
          class="glass-card overflow-hidden group animate-fade-in"
        >
          <div class="relative aspect-square canvas-checkerboard">
            <img
              v-if="item.imageUrl && !imgErrors.has(item.id)"
              :src="item.imageUrl"
              class="w-full h-full object-cover"
              loading="lazy"
              @error="handleImgError(item.id)"
            />
            <div v-else class="w-full h-full flex items-center justify-center bg-slate-100">
              <Heart class="w-8 h-8 text-slate-300" />
            </div>
            <div class="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
          </div>

          <div class="flex items-center justify-center gap-1 p-2 border-t border-slate-100">
            <button
              @click="handleDownload(item.imageUrl)"
              class="p-2 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
              title="下载"
            >
              <Download class="w-4 h-4" />
            </button>
            <button
              @click="handleReGenerate(item)"
              class="p-2 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
              title="再次生成"
            >
              <Copy class="w-4 h-4" />
            </button>
            <button
              @click="handleUnfavorite(item.id)"
              class="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
              title="取消收藏"
            >
              <Trash2 class="w-4 h-4" />
            </button>
          </div>
        </div>
      </template>
    </div>

    <div v-if="totalPages > 1" class="flex justify-center items-center gap-2 mt-6">
      <button
        :disabled="currentPage <= 1"
        @click="currentPage--; loadFavorites()"
        class="px-3 py-1.5 rounded-lg text-sm border border-slate-200 disabled:opacity-40"
      >上一页</button>
      <span class="text-sm text-slate-500">第 {{ currentPage }} / {{ totalPages }} 页</span>
      <button
        :disabled="currentPage >= totalPages"
        @click="currentPage++; loadFavorites()"
        class="px-3 py-1.5 rounded-lg text-sm border border-slate-200 disabled:opacity-40"
      >下一页</button>
    </div>

    <!-- 历史记录详情弹窗 -->
    <HistoryDetail
      v-if="detailRecordId !== null"
      :record-id="detailRecordId"
      @close="detailRecordId = null"
    />
  </div>
</template>

<style scoped>
.fade-enter-active { transition: opacity 0.3s ease; }
.fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
