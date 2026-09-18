<script setup lang="ts">
import { ref, computed } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import ImageCard from '@/components/common/ImageCard.vue'
import { Maximize2 } from 'lucide-vue-next'

const workspace = useWorkspaceStore()
const previewImage = ref<string | null>(null)
const showPreview = ref(false)

function openPreview(url: string) {
  previewImage.value = url
  showPreview.value = true
}

function closePreview() {
  showPreview.value = false
  previewImage.value = null
}

function handleFavorite(id: string) {
  const img = workspace.generatedImages.find((g) => g.id === id)
  if (img) img.favorited = !img.favorited
}

function handleDownload(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = 'generated-image.jpg'
  a.click()
}

function handleRetry(id: string) {
  workspace.retryTask(id)
}

const successCount = computed(
  () => workspace.generatedImages.filter((g) => g.status === 'success').length,
)
</script>

<template>
  <div class="flex flex-col h-full bg-surface-light">
    <!-- 顶部工具栏 -->
    <div class="flex items-center justify-between px-4 py-2 border-b border-slate-200 bg-white/50">
      <div class="flex items-center gap-3">
        <span class="text-xs text-slate-500">
          <template v-if="workspace.isGenerating">
            生成中... {{ successCount }}/{{ workspace.generatedImages.length }}
          </template>
          <template v-else-if="workspace.generatedImages.length">
            共 {{ workspace.generatedImages.length }} 张结果
          </template>
          <template v-else>
            画布区域 — 上传商品图后开始生成
          </template>
        </span>
      </div>
      <div class="flex items-center gap-1">
        <button
          class="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          title="适应画布 (Shift+1)"
        >
          <Maximize2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- 画布内容区 -->
    <div class="flex-1 overflow-auto p-4">
      <!-- 空状态 -->
      <div
        v-if="workspace.generatedImages.length === 0"
        class="flex items-center justify-center h-full"
      >
        <div class="text-center">
          <div class="w-20 h-20 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
            <svg class="w-10 h-10 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
          </div>
          <p class="text-slate-400 text-sm">上传商品图后点击生成</p>
          <p class="text-slate-300 text-xs mt-1">生成的图片将在此处展示</p>
        </div>
      </div>

      <!-- 生成中 / 结果网格 -->
      <div
        v-else
        class="grid gap-4"
        :class="
          workspace.generatedImages.length <= 2
            ? 'grid-cols-2'
            : 'grid-cols-2'
        "
      >
        <ImageCard
          v-for="img in workspace.generatedImages"
          :key="img.id"
          :image="img"
          @favorite="handleFavorite"
          @download="handleDownload"
          @preview="openPreview"
          @retry="handleRetry"
        />
      </div>
    </div>

    <!-- 放大预览模态框 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showPreview"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-8"
          @click="closePreview"
        >
          <div
            class="relative max-w-4xl max-h-[80vh]"
            @click.stop
          >
            <img
              v-if="previewImage"
              :src="previewImage"
              class="max-w-full max-h-[80vh] object-contain rounded-xl shadow-2xl"
            />
            <button
              @click="closePreview"
              class="absolute top-4 right-4 w-10 h-10 rounded-full bg-white/20 backdrop-blur-sm text-white flex items-center justify-center hover:bg-white/30 transition-colors"
            >
              ✕
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: all 0.3s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from img,
.modal-leave-to img {
  transform: scale(0.9);
}
</style>