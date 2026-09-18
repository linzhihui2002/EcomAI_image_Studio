<script setup lang="ts">
/**
 * 右上图层面板：图层列表（缩略/类型/名称）、选中高亮、显隐/锁定、上移下移、删除，
 * 以及新增图层（上传图片文件 → 本地 data URL 加为图层；新增文本图层）
 */
import { computed, ref } from 'vue'
import {
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  Image as ImageIcon,
  Lock,
  LockOpen,
  Plus,
  Trash2,
  Type,
} from 'lucide-vue-next'
import { useEditorStore } from '@/stores/editor'
import { getErrorMessage } from '@/lib/error'

const emit = defineEmits<{
  (e: 'error', message: string): void
}>()

const store = useEditorStore()

const fileInputRef = ref<HTMLInputElement | null>(null)

/** 面板展示：顶层图层在前（z 降序） */
const displayLayers = computed(() => [...store.sortedLayers].reverse())

function layerName(type: 'image' | 'text', url?: string, text?: string): string {
  if (type === 'text') return text?.trim() || '文本图层'
  if (!url) return '图片图层'
  if (url.startsWith('data:')) return '本地上传图片'
  const filename = url.split('/').pop() ?? url
  return decodeURIComponent(filename)
}

function isBackground(id: string): boolean {
  return store.backgroundLayerId === id
}

function handleUploadClick() {
  fileInputRef.value?.click()
}

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  // 上传成功后不在此处提示（由父组件统一提示），仅失败时向父组件上报错误
  try {
    await store.applyUploadedFile(file)
  } catch (err) {
    console.error('[editor-layer-panel] 图片上传失败', err)
    emit('error', getErrorMessage(err, '图片上传失败'))
  }
}

function handleDelete(id: string) {
  store.removeLayer(id)
}
</script>

<template>
  <div class="flex flex-col min-h-0 border-b border-slate-200">
    <!-- 标题与新增 -->
    <div class="flex items-center justify-between px-4 pt-3 pb-2">
      <h3 class="text-xs font-semibold text-slate-500 tracking-wide">
        图层
        <span class="text-slate-300 font-normal">（{{ store.layers.length }}）</span>
      </h3>
      <div class="flex items-center gap-1">
        <button
          type="button"
          class="p-1.5 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
          title="上传图片作为新图层"
          @click="handleUploadClick"
        >
          <ImageIcon class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="p-1.5 rounded-lg text-slate-400 hover:text-brand-purple hover:bg-brand-gradient-subtle transition-colors"
          title="新增文本图层"
          @click="store.addTextLayer()"
        >
          <Type class="w-4 h-4" />
        </button>
      </div>
      <input
        ref="fileInputRef"
        type="file"
        accept="image/*"
        class="hidden"
        @change="handleFileChange"
      />
    </div>

    <!-- 列表 -->
    <div class="flex-1 min-h-0 overflow-y-auto px-2 pb-2 space-y-0.5">
      <div
        v-if="store.layers.length === 0"
        class="py-8 text-center text-xs text-slate-300"
      >
        暂无图层
      </div>

      <div
        v-for="layer in displayLayers"
        :key="layer.id"
        class="group flex items-center gap-2 px-2 py-1.5 rounded-xl cursor-pointer transition-colors"
        :class="store.selectedLayerId === layer.id
          ? 'bg-brand-gradient-subtle ring-1 ring-brand-purple/30'
          : 'hover:bg-slate-100'"
        @click="store.selectLayer(layer.id)"
      >
        <!-- 缩略 / 类型图标 -->
        <div class="w-9 h-9 shrink-0 rounded-lg overflow-hidden bg-slate-100 flex items-center justify-center">
          <img
            v-if="layer.type === 'image' && layer.url"
            :src="layer.url"
            alt=""
            class="w-full h-full object-cover"
          />
          <Type v-else class="w-4 h-4 text-slate-400" />
        </div>

        <!-- 名称 -->
        <div class="flex-1 min-w-0">
          <p
            class="text-xs truncate"
            :class="(layer.visible ?? true) ? 'text-slate-700' : 'text-slate-300 line-through'"
            :title="layerName(layer.type, layer.url, layer.text)"
          >
            {{ layerName(layer.type, layer.url, layer.text) }}
          </p>
          <p v-if="isBackground(layer.id)" class="text-[10px] text-brand-purple">背景图层</p>
        </div>

        <!-- 操作按钮 -->
        <div class="flex items-center gap-0.5 shrink-0">
          <button
            type="button"
            class="p-1 rounded text-slate-300 hover:text-brand-purple transition-colors"
            :class="{ 'opacity-0 group-hover:opacity-100': store.selectedLayerId !== layer.id }"
            :title="layer.z === store.sortedLayers[0]?.z ? '已在最上层' : '上移一层'"
            @click.stop="store.reorderLayer(layer.id, 'up')"
          >
            <ChevronUp class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            class="p-1 rounded text-slate-300 hover:text-brand-purple transition-colors"
            :class="{ 'opacity-0 group-hover:opacity-100': store.selectedLayerId !== layer.id }"
            :title="layer.z === store.sortedLayers[store.sortedLayers.length - 1]?.z ? '已在最下层' : '下移一层'"
            @click.stop="store.reorderLayer(layer.id, 'down')"
          >
            <ChevronDown class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            class="p-1 rounded transition-colors"
            :class="(layer.visible ?? true) ? 'text-slate-400 hover:text-brand-purple' : 'text-slate-300'"
            :title="(layer.visible ?? true) ? '隐藏' : '显示'"
            @click.stop="store.toggleVisible(layer.id)"
          >
            <EyeOff v-if="layer.visible ?? true" class="w-3.5 h-3.5" />
            <Eye v-else class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            class="p-1 rounded transition-colors"
            :class="(layer.locked ?? false) ? 'text-amber-500' : 'text-slate-300 hover:text-brand-purple'"
            :title="(layer.locked ?? false) ? '解锁' : '锁定'"
            @click.stop="store.toggleLocked(layer.id)"
          >
            <Lock v-if="layer.locked ?? false" class="w-3.5 h-3.5" />
            <LockOpen v-else class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            class="p-1 rounded text-slate-300 hover:text-red-500 transition-colors disabled:cursor-not-allowed disabled:hover:text-slate-300"
            :title="(layer.locked ?? false) ? '锁定图层不可删除' : '删除图层'"
            :disabled="layer.locked ?? false"
            @click.stop="handleDelete(layer.id)"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>

    <!-- 底部新增提示 -->
    <div class="px-4 py-2 border-t border-slate-100">
      <button
        type="button"
        class="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs text-slate-500 hover:bg-slate-100 transition-colors"
        @click="handleUploadClick"
      >
        <Plus class="w-3.5 h-3.5" />
        上传图片添加图层
      </button>
    </div>
  </div>
</template>
