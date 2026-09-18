<script setup lang="ts">
/**
 * 左侧工具栏：按模块分组渲染编辑工具按钮（数据来自 GET /editor/tools）
 * 点击激活工具；再次点击取消激活
 */
import { computed } from 'vue'
import {
  Crop,
  FlipHorizontal,
  Palette,
  RotateCw,
  Wand2,
  type LucideIcon,
} from 'lucide-vue-next'
import { useEditorStore } from '@/stores/editor'
import type { EditorTool } from '@/api/editor'

const store = useEditorStore()

/** 模块中文名映射（未知模块回退为原名） */
const MODULE_LABELS: Record<string, string> = {
  basic: '基础调整',
  ai: 'AI 增强',
}

/** 工具图标映射（按工具名，未知工具用魔法棒） */
const TOOL_ICONS: Record<string, LucideIcon> = {
  color_adjust: Palette,
  crop: Crop,
  flip: FlipHorizontal,
  rotate: RotateCw,
}

interface ToolGroup {
  module: string
  label: string
  tools: EditorTool[]
}

const toolGroups = computed<ToolGroup[]>(() => {
  const groups = new Map<string, EditorTool[]>()
  for (const tool of store.tools) {
    const list = groups.get(tool.module) ?? []
    list.push(tool)
    groups.set(tool.module, list)
  }
  return Array.from(groups.entries()).map(([module, tools]) => ({
    module,
    label: MODULE_LABELS[module] ?? module,
    tools,
  }))
})

function toolIcon(name: string): LucideIcon {
  return TOOL_ICONS[name] ?? Wand2
}

function handleSelect(name: string) {
  store.setActiveTool(name)
}
</script>

<template>
  <aside class="w-52 shrink-0 h-full bg-white/80 backdrop-blur-xl border-r border-slate-200 flex flex-col">
    <div class="px-4 pt-4 pb-2">
      <h2 class="text-sm font-semibold text-slate-700">编辑工具</h2>
      <p class="text-xs text-slate-400 mt-0.5">点击工具后在右侧调整参数</p>
    </div>

    <div class="flex-1 overflow-y-auto px-3 pb-4 space-y-4">
      <div v-if="!store.toolsLoaded" class="space-y-2 pt-2">
        <div v-for="i in 3" :key="i" class="skeleton h-9 rounded-xl" />
      </div>

      <div v-for="group in toolGroups" :key="group.module">
        <p class="px-1 mb-1.5 text-xs font-medium text-slate-400">{{ group.label }}</p>
        <div class="space-y-1">
          <button
            v-for="tool in group.tools"
            :key="tool.name"
            type="button"
            :title="tool.description"
            class="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm transition-all duration-200 text-left"
            :class="store.activeTool === tool.name
              ? 'bg-brand-gradient text-white font-medium shadow-glow'
              : 'text-slate-600 hover:bg-brand-gradient-subtle hover:text-brand-purple'"
            @click="handleSelect(tool.name)"
          >
            <component :is="toolIcon(tool.name)" class="w-4 h-4 shrink-0" />
            <span class="truncate">{{ tool.label }}</span>
          </button>
        </div>
      </div>

      <div v-if="store.toolsLoaded && toolGroups.length === 0" class="px-1 py-6 text-center text-xs text-slate-400">
        暂无可用工具
      </div>
    </div>

    <!-- 操作提示 -->
    <div class="px-4 py-3 border-t border-slate-100 text-[11px] leading-5 text-slate-400">
      <p>滚轮缩放画布</p>
      <p>按住空格拖拽平移</p>
      <p>Ctrl+Z 撤销 / Ctrl+Y 重做</p>
    </div>
  </aside>
</template>
