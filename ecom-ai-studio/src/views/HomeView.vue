<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import type { FeatureCard, InspirationItem, SceneStyle } from '@/types'
import { mockFeatureCards, mockInspirations, hotTags } from '@/mock/data'
import { Sparkles, Search, ArrowRight, Clock, Zap, TrendingUp, Lock, ChevronRight, Wrench, PenLine, AlertCircle, X } from 'lucide-vue-next'

const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()

const searchQuery = ref('')
const activeTags = ref<string[]>([])
const actionError = ref('')

const filteredInspirations = computed(() => {
  let items = mockInspirations
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    items = items.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        item.tags.some((t) => t.toLowerCase().includes(q)),
    )
  }
  if (activeTags.value.length) {
    items = items.filter((item) =>
      activeTags.value.some((t) =>
        item.tags.some((tag) => tag.includes(t)),
      ),
    )
  }
  return items
})

function toggleTag(tag: string) {
  const idx = activeTags.value.indexOf(tag)
  if (idx >= 0) {
    activeTags.value.splice(idx, 1)
  } else {
    activeTags.value.push(tag)
  }
}

function handleFeature(feature: FeatureCard) {
  if (feature.available && feature.route) {
    router.push(feature.route)
  }
}

function copyWorkflow(item: InspirationItem) {
  actionError.value = ''
  if (auth.selectedWalletBalance < item.pointsCost) {
    actionError.value = `${auth.selectedWallet === 'personal' ? '个人' : auth.currentTeam?.name || '团队'}钱包余额不足，无法复制工作流`
    return
  }
  if (confirm(`复制该工作流将消耗 ${item.pointsCost} 灵感币（${auth.selectedWallet === 'personal' ? '个人钱包' : '团队钱包·' + auth.currentTeam?.name}），是否继续？`)) {
    const success = auth.deductPoints(item.pointsCost)
    if (success) {
      workspace.loadConfig(item.configSnapshot)
      router.push('/workspace')
    }
  }
}

function goToWorkspace() {
  router.push('/workspace')
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <!-- 操作错误提示 -->
    <Transition name="fade">
      <div v-if="actionError" class="mb-4 px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 flex items-center justify-between">
        <span class="flex items-center gap-2">
          <AlertCircle class="w-4 h-4 flex-shrink-0" />
          {{ actionError }}
        </span>
        <button @click="actionError = ''"><X class="w-4 h-4" /></button>
      </div>
    </Transition>

    <!-- 全局搜索区 -->
    <div class="max-w-2xl mx-auto mb-10 pt-4">
      <div class="text-center mb-6">
        <h2 class="text-2xl font-display font-bold text-slate-900 mb-2">
          探索 AI 创作灵感
        </h2>
        <p class="text-slate-500">
          用 AI 为你的商品生成专业级展示图
        </p>
      </div>
      <div class="relative">
        <Search class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索风格、场景... 例如「北欧极简白底图」"
          class="w-full pl-12 pr-4 py-3.5 text-sm rounded-2xl border border-slate-200/80 bg-white/90 backdrop-blur-xl shadow-sm focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 transition-all duration-200"
        />
      </div>

      <!-- 热门标签 -->
      <div class="flex flex-wrap justify-center gap-2 mt-4">
        <button
          v-for="tag in hotTags"
          :key="tag"
          @click="toggleTag(tag)"
          :class="[
            'chip',
            activeTags.includes(tag) && 'chip-active',
          ]"
        >
          {{ tag }}
        </button>
      </div>
    </div>

    <!-- 核心功能矩阵 -->
    <section class="mb-12">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-slate-900 flex items-center gap-2">
          <Zap class="w-5 h-5 text-amber-500" />
          核心功能
        </h3>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <button
          v-for="feature in mockFeatureCards"
          :key="feature.id"
          @click="handleFeature(feature)"
          :disabled="!feature.available"
          :class="[
            'relative glass-card p-5 text-left transition-all duration-300 group',
            feature.available
              ? 'cursor-pointer hover:shadow-glow'
              : 'opacity-60 cursor-not-allowed',
          ]"
        >
          <div
            v-if="feature.badge"
            class="absolute top-3 right-3 px-2 py-0.5 rounded-full bg-slate-200 text-[10px] font-medium text-slate-500"
          >
            {{ feature.badge }}
          </div>
          <div
            :class="[
              'w-10 h-10 rounded-xl flex items-center justify-center mb-3 transition-transform duration-200 group-hover:scale-110',
              feature.available
                ? 'bg-brand-gradient text-white'
                : 'bg-slate-100 text-slate-400',
            ]"
          >
            <Sparkles v-if="feature.id === 'product-image'" class="w-5 h-5" />
            <PenLine v-else-if="feature.id === 'editor'" class="w-5 h-5" />
            <Wrench v-else class="w-5 h-5" />
          </div>
          <h4 class="font-semibold text-slate-900 mb-1">{{ feature.title }}</h4>
          <p class="text-sm text-slate-500">{{ feature.description }}</p>
        </button>
      </div>
    </section>

    <!-- 动态灵感信息流 -->
    <section>
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-slate-900 flex items-center gap-2">
          <TrendingUp class="w-5 h-5 text-brand-purple" />
          灵感案例
        </h3>
        <button
          @click="goToWorkspace"
          class="flex items-center gap-1 text-sm text-brand-purple hover:text-brand-cyan transition-colors"
        >
          查看更多
          <ChevronRight class="w-4 h-4" />
        </button>
      </div>

      <div
        v-if="filteredInspirations.length === 0"
        class="text-center py-16 text-slate-400"
      >
        <Search class="w-10 h-10 mx-auto mb-3 opacity-50" />
        <p>没有找到匹配的灵感案例</p>
        <p class="text-sm mt-1">试试其他关键词</p>
      </div>

      <div
        v-else
        class="columns-1 sm:columns-2 lg:columns-3 gap-4 space-y-4"
      >
        <div
          v-for="item in filteredInspirations"
          :key="item.id"
          class="break-inside-avoid glass-card overflow-hidden group cursor-pointer animate-fade-in"
        >
          <div class="relative aspect-[4/5] overflow-hidden">
            <img
              :src="item.imageUrl"
              :alt="item.title"
              class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
              loading="lazy"
            />
            <div
              class="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300"
            />
            <button
              @click="copyWorkflow(item)"
              class="absolute bottom-3 left-1/2 -translate-x-1/2 px-4 py-2 rounded-xl bg-white/90 backdrop-blur-sm text-sm font-medium text-slate-800 shadow-lg opacity-0 group-hover:opacity-100 transition-all duration-300 hover:bg-white flex items-center gap-1.5 whitespace-nowrap"
            >
              <Sparkles class="w-3.5 h-3.5 text-brand-purple" />
              复制同款工作流
            </button>
          </div>
          <div class="p-4">
            <h4 class="font-medium text-slate-900 mb-2">{{ item.title }}</h4>
            <div class="flex items-center justify-between">
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="tag in item.tags.slice(0, 3)"
                  :key="tag"
                  class="px-2 py-0.5 rounded-md bg-slate-100 text-[10px] font-medium text-slate-500"
                >
                  {{ tag }}
                </span>
              </div>
              <span class="text-xs text-slate-400 flex items-center gap-1">
                <Zap class="w-3 h-3" />
                {{ item.pointsCost }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.fade-enter-active { transition: opacity 0.3s ease; }
.fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>