<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getPublicAnnouncements } from '@/api/admin'
import { getErrorMessage } from '@/lib/error'
import type { Announcement } from '@/types'
import { Megaphone, X, ChevronRight, AlertCircle, Info, CheckCircle2, AlertTriangle, List } from 'lucide-vue-next'

const announcements = ref<Announcement[]>([])
const loading = ref(false)
const currentIndex = ref(0)
const showDetail = ref(false)
const showAllAnnouncements = ref(false)

async function fetchAnnouncements() {
  loading.value = true
  try {
    announcements.value = await getPublicAnnouncements()
  } catch (err) {
    console.error('获取公告失败:', getErrorMessage(err))
    announcements.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchAnnouncements()
})

const activeAnnouncements = computed(() => {
  const now = new Date()
  return announcements.value
    .filter((a) => {
      if (!a.isActive) return false
      if (a.expiresAt && new Date(a.expiresAt) < now) return false
      return true
    })
    .sort((a, b) => {
      if (a.isPinned && !b.isPinned) return -1
      if (!a.isPinned && b.isPinned) return 1
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    })
})

const currentAnnouncement = computed(() => activeAnnouncements.value[currentIndex.value])

const typeConfig = {
  info: { icon: Info, color: 'text-blue-600', bg: 'bg-blue-50', border: 'border-blue-200' },
  warning: { icon: AlertTriangle, color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200' },
  success: { icon: CheckCircle2, color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-200' },
  important: { icon: AlertCircle, color: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200' },
}

function nextAnnouncement() {
  if (currentIndex.value < activeAnnouncements.value.length - 1) {
    currentIndex.value++
  } else {
    currentIndex.value = 0
  }
}

function prevAnnouncement() {
  if (currentIndex.value > 0) {
    currentIndex.value--
  } else {
    currentIndex.value = activeAnnouncements.value.length - 1
  }
}

function formatDate(isoStr: string): string {
  if (!isoStr) return '—'
  const date = new Date(isoStr)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 外部调用：打开全部公告弹窗 */
function openAllAnnouncements() {
  showAllAnnouncements.value = true
}

defineExpose({ openAllAnnouncements })
</script>

<template>
  <div v-if="activeAnnouncements.length > 0" class="announcement-bar-wrapper">
    <div :class="['announcement-bar', typeConfig[currentAnnouncement.type]?.bg]">
      <div class="flex items-center gap-3">
        <component
          :is="typeConfig[currentAnnouncement.type]?.icon || Megaphone"
          :class="['w-4 h-4 flex-shrink-0', typeConfig[currentAnnouncement.type]?.color]"
        />

        <div class="flex-1 min-w-0">
          <button
            @click="showDetail = true"
            class="text-left hover:opacity-80 transition-opacity w-full"
          >
            <p :class="['text-sm font-medium truncate', typeConfig[currentAnnouncement.type]?.color]">
              {{ currentAnnouncement.title }}
            </p>
          </button>
        </div>

        <div v-if="activeAnnouncements.length > 1" class="flex items-center gap-1 flex-shrink-0">
          <button
            @click="prevAnnouncement"
            class="p-1 rounded hover:bg-black/5 transition-colors"
            title="上一条"
          >
            <ChevronRight class="w-3.5 h-3.5 text-slate-400 rotate-180" />
          </button>
          <span class="text-xs text-slate-400 min-w-[28px] text-center">
            {{ currentIndex + 1 }} / {{ activeAnnouncements.length }}
          </span>
          <button
            @click="nextAnnouncement"
            class="p-1 rounded hover:bg-black/5 transition-colors"
            title="下一条"
          >
            <ChevronRight class="w-3.5 h-3.5 text-slate-400" />
          </button>
        </div>

        <button
          @click="showAllAnnouncements = true"
          class="p-1 rounded hover:bg-black/5 transition-colors flex-shrink-0"
          title="查看全部公告"
        >
          <List class="w-4 h-4 text-slate-400" />
        </button>

        <button
          @click="$emit('close')"
          class="p-1 rounded hover:bg-black/5 transition-colors flex-shrink-0"
          title="关闭"
        >
          <X class="w-4 h-4 text-slate-400" />
        </button>
      </div>
    </div>

    <!-- 公告详情弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showDetail"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showDetail = false"
        >
          <div class="bg-white rounded-2xl w-full max-w-lg mx-4 p-6 shadow-2xl animate-scale-in max-h-[80vh] overflow-y-auto">
            <div class="flex items-start justify-between mb-4">
              <div class="flex items-center gap-2">
                <component
                  :is="typeConfig[currentAnnouncement.type]?.icon || Megaphone"
                  :class="['w-5 h-5', typeConfig[currentAnnouncement.type]?.color]"
                />
                <h3 class="text-lg font-semibold text-slate-900">
                  {{ currentAnnouncement.title }}
                </h3>
              </div>
              <button
                @click="showDetail = false"
                class="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X class="w-5 h-5" />
              </button>
            </div>

            <div :class="['p-4 rounded-xl mb-4', typeConfig[currentAnnouncement.type]?.bg]">
              <p class="text-sm text-slate-700 leading-relaxed whitespace-pre-line">
                {{ currentAnnouncement.content }}
              </p>
            </div>

            <div class="flex items-center justify-between text-xs text-slate-400 pt-3 border-t border-slate-100">
              <span>发布时间：{{ formatDate(currentAnnouncement.createdAt) }}</span>
              <span v-if="currentAnnouncement.expiresAt" class="text-amber-500">
                有效期至：{{ formatDate(currentAnnouncement.expiresAt).split(' ')[0] }}
              </span>
            </div>

            <div v-if="activeAnnouncements.length > 1" class="mt-4 pt-4 border-t border-slate-100">
              <p class="text-xs font-medium text-slate-500 mb-3">其他公告</p>
              <div class="space-y-2 max-h-40 overflow-y-auto">
                <button
                  v-for="(ann, idx) in activeAnnouncements.filter((_, i) => i !== currentIndex)"
                  :key="ann.id"
                  @click="currentIndex = activeAnnouncements.indexOf(ann); showDetail = true"
                  class="w-full text-left p-2.5 rounded-lg hover:bg-slate-50 transition-colors group"
                >
                  <div class="flex items-center gap-2">
                    <component
                      :is="typeConfig[ann.type]?.icon || Megaphone"
                      :class="['w-3.5 h-3.5 flex-shrink-0', typeConfig[ann.type]?.color]"
                    />
                    <p class="text-sm text-slate-600 group-hover:text-slate-900 truncate flex-1">
                      {{ ann.title }}
                    </p>
                    <ChevronRight class="w-3.5 h-3.5 text-slate-300 group-hover:text-slate-500" />
                  </div>
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 全部公告记录弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showAllAnnouncements"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showAllAnnouncements = false"
        >
          <div class="bg-white rounded-2xl w-full max-w-2xl mx-4 p-6 shadow-2xl animate-scale-in max-h-[80vh] overflow-y-auto">
            <div class="flex items-center justify-between mb-5">
              <div class="flex items-center gap-2">
                <List class="w-5 h-5 text-brand-purple" />
                <h3 class="text-lg font-semibold text-slate-900">全部公告记录</h3>
              </div>
              <button
                @click="showAllAnnouncements = false"
                class="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X class="w-5 h-5" />
              </button>
            </div>

            <!-- 统计概览 -->
            <div class="grid grid-cols-4 gap-3 mb-5">
              <div class="p-3 rounded-xl bg-slate-50 text-center">
                <p class="text-lg font-bold text-slate-900">{{ announcements.length }}</p>
                <p class="text-xs text-slate-500">总公告数</p>
              </div>
              <div class="p-3 rounded-xl bg-green-50 text-center">
                <p class="text-lg font-bold text-green-600">{{ announcements.filter((a) => a.isActive).length }}</p>
                <p class="text-xs text-slate-500">已发布</p>
              </div>
              <div class="p-3 rounded-xl bg-amber-50 text-center">
                <p class="text-lg font-bold text-amber-600">{{ announcements.filter((a) => a.isPinned).length }}</p>
                <p class="text-xs text-slate-500">已置顶</p>
              </div>
              <div class="p-3 rounded-xl bg-slate-100 text-center">
                <p class="text-lg font-bold text-slate-400">{{ announcements.filter((a) => !a.isActive).length }}</p>
                <p class="text-xs text-slate-500">已停用</p>
              </div>
            </div>

            <!-- 公告列表 -->
            <div v-if="announcements.length === 0" class="text-center py-12 text-slate-400">
              <Megaphone class="w-10 h-10 mx-auto mb-2 opacity-50" />
              <p class="text-sm">暂无公告记录</p>
            </div>

            <div v-else class="space-y-3">
              <div
                v-for="ann in [...announcements].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())"
                :key="ann.id"
                @click="currentIndex = activeAnnouncements.findIndex((a) => a.id === ann.id) >= 0 ? activeAnnouncements.findIndex((a) => a.id === ann.id) : 0; showDetail = true; showAllAnnouncements = false"
                :class="[
                  'p-4 rounded-xl border cursor-pointer transition-all duration-200 hover:shadow-md group',
                  typeConfig[ann.type]?.border,
                  typeConfig[ann.type]?.bg,
                  !ann.isActive && 'opacity-55 grayscale',
                ]"
              >
                <div class="flex items-start gap-3">
                  <component
                    :is="typeConfig[ann.type]?.icon || Megaphone"
                    :class="['w-5 h-5 flex-shrink-0 mt-0.5', typeConfig[ann.type]?.color]"
                  />
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1 flex-wrap">
                      <h4 class="font-medium text-sm text-slate-900">{{ ann.title }}</h4>
                      <span
                        v-if="ann.isPinned"
                        class="px-1.5 py-0.5 rounded-full bg-amber-100 text-[10px] font-medium text-amber-700"
                      >
                        置顶
                      </span>
                      <span
                        v-if="!ann.isActive"
                        class="px-1.5 py-0.5 rounded-full bg-slate-200 text-[10px] font-medium text-slate-500"
                      >
                        已停用
                      </span>
                      <span
                        v-if="ann.expiresAt && new Date(ann.expiresAt) < new Date()"
                        class="px-1.5 py-0.5 rounded-full bg-red-50 text-[10px] font-medium text-red-500 border border-red-200"
                      >
                        已过期
                      </span>
                    </div>
                    <p class="text-xs text-slate-600 line-clamp-2 leading-relaxed">{{ ann.content }}</p>
                    <div class="flex items-center gap-3 mt-2 text-[11px] text-slate-400">
                      <span>{{ formatDate(ann.createdAt) }}</span>
                      <span v-if="ann.expiresAt" :class="[new Date(ann.expiresAt) < new Date() ? 'text-red-400' : 'text-amber-500']">
                        至 {{ formatDate(ann.expiresAt).split(' ')[0] }}
                      </span>
                    </div>
                  </div>
                  <ChevronRight class="w-4 h-4 text-slate-300 group-hover:text-brand-purple flex-shrink-0 mt-1 transition-colors" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.announcement-bar-wrapper {
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.05), rgba(6, 182, 212, 0.05));
  border-bottom: 1px solid rgba(139, 92, 246, 0.1);
}

.announcement-bar {
  padding: 0.75rem 1.5rem;
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
