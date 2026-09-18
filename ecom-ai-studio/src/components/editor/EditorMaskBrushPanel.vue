<script setup lang="ts">
/**
 * 笔刷选区面板（mask 工具属性面板与 Agent 计划卡片复用）
 *
 * - 笔刷直径滑杆（画布内容区预览坐标像素）
 * - 清空重涂 / 生成蒙版按钮：生成蒙版调用 store.confirmMaskSelection()，
 *   把涂抹笔迹渲染为与目标图层图像同尺寸的白=选区 PNG data URI
 *   （工具栏流程自动写入 toolParams.mask_data_uri，Agent 流程存入 lastMaskDataUri）
 * - 笔迹绘制交互在 EditorCanvas（按住鼠标涂抹，红色 40% 半透明高亮，Enter 确认）
 */
import { computed, ref } from 'vue'
import { Brush, Loader2, Trash2 } from 'lucide-vue-next'
import { useEditorStore } from '@/stores/editor'

const store = useEditorStore()

const generating = ref(false)
const generateError = ref('')

const hasStrokes = computed(() => store.hasMaskStrokes)
const hasMask = computed(() => !!store.lastMaskDataUri)
const targetLayerName = computed(() => {
  const target = store.maskTargetLayer
  if (!target) return ''
  if (store.backgroundLayerId === target.id) return '背景图层'
  const filename = target.url?.split('/').pop() ?? ''
  return target.type === 'text' ? '文本图层' : decodeURIComponent(filename) || '图片图层'
})

async function handleGenerate() {
  if (generating.value) return
  generating.value = true
  generateError.value = ''
  try {
    const uri = await store.confirmMaskSelection()
    if (!uri) {
      generateError.value = '请先在画布上涂抹选区'
    }
  } catch (err) {
    console.error('[editor-mask-brush] 蒙版生成失败', err)
    generateError.value = err instanceof Error ? err.message : '蒙版生成失败'
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div class="rounded-xl border border-slate-200 bg-slate-50/60 p-2.5">
    <!-- 目标图层与蒙版状态 -->
    <div class="flex items-center justify-between mb-2">
      <span class="inline-flex items-center gap-1 text-[11px] text-slate-500 min-w-0">
        <Brush class="w-3.5 h-3.5 text-brand-purple shrink-0" />
        <span class="truncate">涂抹目标：{{ targetLayerName || '无图片图层' }}</span>
      </span>
      <span
        class="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium"
        :class="hasMask ? 'bg-emerald-100 text-emerald-600' : 'bg-slate-200 text-slate-500'"
      >
        {{ hasMask ? '蒙版已生成' : '未生成蒙版' }}
      </span>
    </div>

    <!-- 笔刷大小 -->
    <div class="flex items-center justify-between mb-1">
      <label class="text-[11px] text-slate-400">笔刷大小</label>
      <span class="text-[11px] font-medium text-slate-600 tabular-nums">{{ store.maskBrushSize }} px</span>
    </div>
    <input
      v-model.number="store.maskBrushSize"
      type="range"
      min="4"
      max="200"
      step="2"
      class="w-full accent-brand-purple"
    />

    <!-- 操作按钮 -->
    <div class="flex items-center gap-2 mt-2">
      <button
        type="button"
        class="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-[11px] font-medium text-slate-500 bg-white border border-slate-200 hover:border-slate-300 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        :disabled="!hasStrokes"
        title="清空画布上的涂抹笔迹，重新涂抹"
        @click="store.clearMaskStrokes()"
      >
        <Trash2 class="w-3.5 h-3.5" />
        清空重涂
      </button>
      <button
        type="button"
        class="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-[11px] font-medium text-white bg-brand-gradient hover:shadow-glow transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        :disabled="!hasStrokes || generating"
        title="把涂抹笔迹生成选区蒙版"
        @click="handleGenerate"
      >
        <Loader2 v-if="generating" class="w-3.5 h-3.5 animate-spin" />
        {{ generating ? '生成中...' : '生成蒙版' }}
      </button>
    </div>

    <p v-if="generateError" class="mt-1.5 text-[11px] text-red-500">{{ generateError }}</p>
    <p class="mt-1.5 text-[10px] text-slate-400 leading-4">
      在画布上按住鼠标涂抹选区（红色半透明高亮），按 Enter 或点击"生成蒙版"确认
    </p>
  </div>
</template>
