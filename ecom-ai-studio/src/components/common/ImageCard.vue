<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { GeneratedImage } from '@/types'
import { cn } from '@/lib/utils'
import {
  Heart,
  Download,
  Maximize2,
  RotateCcw,
  Loader2,
  ChevronDown,
  PenLine,
} from 'lucide-vue-next'

const router = useRouter()

// 跳转到编辑器，携带当前图片 URL 作为 imageId
function handleEdit(url: string) {
  router.push({ path: '/editor', query: { imageId: url } })
}

const props = defineProps<{
  image: GeneratedImage
}>()

const emit = defineEmits<{
  favorite: [id: string]
  download: [url: string]
  preview: [url: string]
  retry: [id: string]
}>()

const promptExpanded = ref(false)
// 图片加载状态（渐进式加载）
const imgLoaded = ref(false)
const imgError = ref(false)

function onImgLoad() {
  imgLoaded.value = true
  imgError.value = false
}

function onImgError() {
  imgError.value = true
}

function togglePrompt() {
  promptExpanded.value = !promptExpanded.value
}
</script>

<template>
  <div
    class="glass-card overflow-hidden group animate-fade-in"
  >
    <div class="relative aspect-square canvas-checkerboard">
      <template v-if="image.status === 'processing'">
        <div class="absolute inset-0 flex items-center justify-center bg-white/50">
          <Loader2 class="w-8 h-8 text-brand-purple animate-spin" />
        </div>
      </template>

      <template v-else-if="image.status === 'success'">
        <!-- url 为空时显示加载状态，避免渲染 <img src=""> 导致浏览器请求当前页面 -->
        <template v-if="!image.url">
          <div class="absolute inset-0 flex items-center justify-center bg-slate-50">
            <Loader2 class="w-8 h-8 text-brand-purple animate-spin" />
          </div>
        </template>
        <template v-else>
          <!-- 骨架占位：图片加载完成前显示 -->
          <div
            v-if="!imgLoaded && !imgError"
            class="absolute inset-0 bg-slate-100 animate-pulse"
          />
          <img
            :src="image.url"
            alt="Generated"
            class="w-full h-full object-cover transition-opacity duration-300"
            :class="imgLoaded ? 'opacity-100' : 'opacity-0'"
            loading="lazy"
            decoding="async"
            @load="onImgLoad"
            @error="onImgError"
          />
          <div
            class="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors duration-200"
          />
          <!-- 图片加载失败回退 -->
          <div
            v-if="imgError"
            class="absolute inset-0 flex flex-col items-center justify-center bg-slate-50 gap-2"
          >
            <span class="text-slate-300 text-2xl">🖼</span>
            <p class="text-xs text-slate-400">图片加载失败</p>
          </div>
        </template>
      </template>

      <template v-else>
        <div class="absolute inset-0 flex flex-col items-center justify-center bg-red-50 gap-2">
          <div class="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
            <span class="text-red-400 text-xl">!</span>
          </div>
          <p class="text-xs text-red-500">生成失败</p>
          <p v-if="image.errorMsg" class="text-[10px] text-red-400">
            {{ image.errorMsg }}
          </p>
        </div>
      </template>
    </div>

    <div
      v-if="image.status !== 'processing'"
      class="flex items-center justify-center gap-1 p-2 border-t border-slate-100 bg-white/50"
    >
      <button
        v-if="image.status === 'success'"
        @click="emit('favorite', image.id)"
        :class="cn(
          'p-2 rounded-lg text-slate-400 hover:text-amber-500 hover:bg-amber-50 transition-colors',
          image.favorited && 'text-amber-500',
        )"
        title="收藏"
      >
        <Heart
          :class="['w-4 h-4', image.favorited && 'fill-current']"
        />
      </button>
      <button
        v-if="image.status === 'success'"
        @click="handleEdit(image.url)"
        class="p-2 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
        title="编辑"
      >
        <PenLine class="w-4 h-4" />
      </button>
      <button
        v-if="image.status === 'success'"
        @click="emit('download', image.url)"
        class="p-2 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
        title="下载"
      >
        <Download class="w-4 h-4" />
      </button>
      <button
        v-if="image.status === 'success'"
        @click="emit('preview', image.url)"
        class="p-2 rounded-lg text-slate-400 hover:text-brand-cyan hover:bg-brand-gradient-subtle transition-colors"
        title="放大预览"
      >
        <Maximize2 class="w-4 h-4" />
      </button>
      <button
        v-if="image.status === 'failed'"
        @click="emit('retry', image.id)"
        class="p-2 rounded-lg text-red-400 hover:text-red-500 hover:bg-red-50 transition-colors"
        title="重试"
      >
        <RotateCcw class="w-4 h-4" />
      </button>
    </div>

    <!-- 提示词展示 -->
    <div
      v-if="image.status === 'success' && image.prompt"
      class="border-t border-slate-100"
    >
      <button
        @click="togglePrompt"
        class="w-full flex items-center gap-1 px-2 py-1.5 text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors"
      >
        <ChevronDown
          :class="[
            'w-3 h-3 transition-transform duration-200',
            promptExpanded && 'rotate-180',
          ]"
        />
        <span>提示词</span>
      </button>
      <div
        v-if="promptExpanded"
        class="px-2 pb-2"
      >
        <p class="text-xs text-slate-500 leading-relaxed break-words bg-slate-50 rounded p-2">
          {{ image.prompt }}
        </p>
      </div>
    </div>
  </div>
</template>