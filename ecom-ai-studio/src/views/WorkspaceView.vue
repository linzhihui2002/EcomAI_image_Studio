<script setup lang="ts">
import { onMounted } from 'vue'
import AssetPanel from '@/components/workspace/AssetPanel.vue'
import CanvasArea from '@/components/workspace/CanvasArea.vue'
import BatchPanel from '@/components/workspace/BatchPanel.vue'
import { useWorkspaceStore } from '@/stores/workspace'

const workspace = useWorkspaceStore()

onMounted(() => {
  if (!workspace.productImages.length && !workspace.generatedImages.length) {
    workspace.reset()
  }
})
</script>

<template>
  <div class="h-full flex">
    <!-- 左侧配置面板（模式 → 上传 → 风格 → 生成） -->
    <div class="w-[340px] border-r border-slate-200 bg-white flex-shrink-0">
      <AssetPanel />
    </div>

    <!-- 右侧：画布区 + 批量生成面板（简单/专业模式通用底部面板，不改变左右分栏结构） -->
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="flex-1 min-h-0">
        <CanvasArea />
      </div>
      <BatchPanel />
    </div>
  </div>
</template>
