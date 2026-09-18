<script setup lang="ts">
/**
 * 前后对比覆盖层：原图（背景图）与当前画布导出图左右分割对比
 * - 底层为当前画布导出，上层为原图，通过 CSS clip-path inset 按分割百分比裁切
 * - 分割线可拖拽；两张图均为 object-contain，尺寸一致时分割位置对齐
 */
import { ref } from 'vue'
import { MoveHorizontal } from 'lucide-vue-next'

const props = defineProps<{
  originalUrl: string
  currentUrl: string
}>()

const positionPercent = ref(50)
const containerEl = ref<HTMLDivElement | null>(null)
const dragging = ref(false)

function updateFromPointer(clientX: number) {
  const el = containerEl.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (rect.width <= 0) return
  const percent = ((clientX - rect.left) / rect.width) * 100
  positionPercent.value = Math.min(100, Math.max(0, percent))
}

function handlePointerDown(e: PointerEvent) {
  dragging.value = true
  updateFromPointer(e.clientX)
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', handlePointerUp)
}

function handlePointerMove(e: PointerEvent) {
  if (!dragging.value) return
  updateFromPointer(e.clientX)
}

function handlePointerUp() {
  dragging.value = false
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', handlePointerUp)
}

/** clip-path：只显示分割线左侧的原图 */
function clipStyle(): string {
  return `inset(0 ${100 - positionPercent.value}% 0 0)`
}
</script>

<template>
  <div
    ref="containerEl"
    class="absolute inset-0 z-20 bg-white/90 backdrop-blur-sm select-none cursor-ew-resize"
    @pointerdown="handlePointerDown"
  >
    <!-- 底层：当前画布导出 -->
    <img
      :src="props.currentUrl"
      alt="当前效果"
      class="absolute inset-0 w-full h-full object-contain p-6"
      draggable="false"
    />
    <!-- 上层：原图（clip 裁切，与底层同样式保证分割对齐） -->
    <img
      :src="props.originalUrl"
      alt="原图"
      class="absolute inset-0 w-full h-full object-contain p-6"
      :style="{ clipPath: clipStyle() }"
      draggable="false"
    />

    <!-- 分割线与手柄 -->
    <div
      class="absolute top-6 bottom-6 w-0.5 bg-white shadow-glow pointer-events-none"
      :style="{ left: positionPercent + '%' }"
    >
      <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-7 h-7 rounded-full bg-white shadow-card flex items-center justify-center">
        <MoveHorizontal class="w-4 h-4 text-brand-purple" />
      </div>
    </div>

    <!-- 角标 -->
    <span class="absolute top-2 left-2 px-2 py-0.5 rounded-full bg-black/50 text-white text-[10px] pointer-events-none">原图</span>
    <span class="absolute top-2 right-2 px-2 py-0.5 rounded-full bg-black/50 text-white text-[10px] pointer-events-none">当前</span>
  </div>
</template>
