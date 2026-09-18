<script setup lang="ts">
/**
 * 右下属性面板（两段式）：
 * 1. 选中图层变换属性：x/y/宽高/旋转/不透明度，文本图层附文字内容编辑
 * 2. 激活工具参数：依据 params_schema 动态渲染
 *    number → 滑杆 + 数值输入；choices → 下拉；boolean → 开关；string → 文本输入
 *    mask_data_uri → 笔刷涂抹选区入口（EditorMaskBrushPanel，画布上涂抹生成蒙版）
 * 点"应用"向父组件抛出 apply 事件执行工具
 */
import { computed } from 'vue'
import { Loader2, Play } from 'lucide-vue-next'
import { useEditorStore } from '@/stores/editor'
import type { EditorParamRule } from '@/api/editor'
import EditorMaskBrushPanel from './EditorMaskBrushPanel.vue'

const props = defineProps<{
  toolRunning: boolean
}>()

const emit = defineEmits<{
  (e: 'apply'): void
}>()

const store = useEditorStore()

/** 参数字段中文映射兜底（后端 rule.label 优先） */
const FIELD_LABELS: Record<string, string> = {
  x: '起点 X',
  y: '起点 Y',
  width: '宽度',
  height: '高度',
  brightness: '亮度',
  contrast: '对比度',
  saturation: '饱和度',
  temperature: '色温',
  horizontal: '水平翻转',
  vertical: '垂直翻转',
  angle: '旋转角度',
}

function paramLabel(key: string, rule: EditorParamRule): string {
  return rule.label?.split('（')[0] ?? FIELD_LABELS[key] ?? key
}

interface ParamEntry {
  key: string
  rule: EditorParamRule
  label: string
}

const toolParamEntries = computed<ParamEntry[]>(() => {
  const schema = store.activeToolDef?.params_schema
  if (!schema) return []
  return Object.entries(schema).map(([key, rule]) => ({
    key,
    rule,
    label: paramLabel(key, rule),
  }))
})

// ===== 图层属性 =====

function pushSnapshotForEdit() {
  store.pushSnapshot()
}

function updateLayerField(field: 'x' | 'y' | 'width' | 'height' | 'rotation' | 'opacity', value: number) {
  const layer = store.selectedLayer
  if (!layer) return
  const patch: Record<string, number> = { [field]: value }
  store.updateLayer(layer.id, patch, { snapshot: false })
}

function updateLayerText(value: string) {
  const layer = store.selectedLayer
  if (!layer) return
  store.updateLayer(layer.id, { text: value }, { snapshot: false })
}

const selectedOpacityPercent = computed({
  get: () => Math.round((store.selectedLayer?.opacity ?? 1) * 100),
  set: (v: number) => updateLayerField('opacity', Math.min(1, Math.max(0, v / 100))),
})

// ===== 工具参数 =====

function numberValue(key: string): number {
  const v = store.toolParams[key]
  return typeof v === 'number' ? v : Number(v ?? 0) || 0
}

function stepOf(rule: EditorParamRule): number {
  return rule.integer ? 1 : 1
}

function updateNumberParam(key: string, value: number) {
  store.setToolParam(key, value)
}

function updateParam(key: string, value: number | string | boolean) {
  store.setToolParam(key, value)
}
</script>

<template>
  <div class="flex-1 min-h-0 overflow-y-auto">
    <!-- 无选中且无工具 -->
    <div
      v-if="!store.selectedLayer && !store.activeTool"
      class="px-4 py-10 text-center text-xs text-slate-300"
    >
      选中图层或激活工具后，在此调整属性
    </div>

    <!-- 选中图层变换属性 -->
    <div v-if="store.selectedLayer" class="px-4 py-3 border-b border-slate-100">
      <h4 class="text-xs font-semibold text-slate-500 tracking-wide mb-2.5">图层属性</h4>

      <!-- 文本内容 -->
      <div v-if="store.selectedLayer.type === 'text'" class="mb-3">
        <label class="block text-[11px] text-slate-400 mb-1">文字内容</label>
        <textarea
          rows="2"
          class="w-full glass-input px-2.5 py-1.5 text-xs text-slate-700 resize-none"
          :value="store.selectedLayer.text ?? ''"
          @focus="pushSnapshotForEdit"
          @input="updateLayerText(($event.target as HTMLTextAreaElement).value)"
        />
      </div>

      <!-- 位置与尺寸 -->
      <div class="grid grid-cols-2 gap-2">
        <div>
          <label class="block text-[11px] text-slate-400 mb-1">X</label>
          <input
            type="number"
            class="w-full glass-input px-2 py-1 text-xs text-slate-700"
            :value="Math.round(store.selectedLayer.x)"
            @focus="pushSnapshotForEdit"
            @change="updateLayerField('x', Number(($event.target as HTMLInputElement).value) || 0)"
          />
        </div>
        <div>
          <label class="block text-[11px] text-slate-400 mb-1">Y</label>
          <input
            type="number"
            class="w-full glass-input px-2 py-1 text-xs text-slate-700"
            :value="Math.round(store.selectedLayer.y)"
            @focus="pushSnapshotForEdit"
            @change="updateLayerField('y', Number(($event.target as HTMLInputElement).value) || 0)"
          />
        </div>
        <div>
          <label class="block text-[11px] text-slate-400 mb-1">宽度</label>
          <input
            type="number"
            min="1"
            class="w-full glass-input px-2 py-1 text-xs text-slate-700"
            :value="Math.round(store.selectedLayer.width)"
            @focus="pushSnapshotForEdit"
            @change="updateLayerField('width', Math.max(1, Number(($event.target as HTMLInputElement).value) || 1))"
          />
        </div>
        <div>
          <label class="block text-[11px] text-slate-400 mb-1">高度</label>
          <input
            type="number"
            min="1"
            class="w-full glass-input px-2 py-1 text-xs text-slate-700"
            :value="Math.round(store.selectedLayer.height)"
            :disabled="store.selectedLayer.type === 'text'"
            :title="store.selectedLayer.type === 'text' ? '文本高度随内容自适应' : ''"
            @focus="pushSnapshotForEdit"
            @change="updateLayerField('height', Math.max(1, Number(($event.target as HTMLInputElement).value) || 1))"
          />
        </div>
        <div>
          <label class="block text-[11px] text-slate-400 mb-1">旋转（度）</label>
          <input
            type="number"
            class="w-full glass-input px-2 py-1 text-xs text-slate-700"
            :value="store.selectedLayer.rotation ?? 0"
            @focus="pushSnapshotForEdit"
            @change="updateLayerField('rotation', Number(($event.target as HTMLInputElement).value) || 0)"
          />
        </div>
        <div>
          <label class="block text-[11px] text-slate-400 mb-1">不透明度（%）</label>
          <input
            type="number"
            min="0"
            max="100"
            class="w-full glass-input px-2 py-1 text-xs text-slate-700"
            v-model.number="selectedOpacityPercent"
            @focus="pushSnapshotForEdit"
          />
        </div>
      </div>

      <!-- 不透明度滑杆 -->
      <input
        type="range"
        min="0"
        max="100"
        step="1"
        class="w-full mt-2 accent-brand-purple"
        v-model.number="selectedOpacityPercent"
      />
    </div>

    <!-- 激活工具参数 -->
    <div v-if="store.activeToolDef" class="px-4 py-3">
      <div class="mb-2.5">
        <h4 class="text-xs font-semibold text-slate-500 tracking-wide">
          工具参数：{{ store.activeToolDef.label }}
        </h4>
        <p class="text-[11px] text-slate-400 mt-0.5">{{ store.activeToolDef.description }}</p>
      </div>

      <div class="space-y-3">
        <div v-for="entry in toolParamEntries" :key="entry.key">
          <!-- 选区蒙版：笔刷涂抹交互入口（复用 EditorMaskBrushPanel） -->
          <template v-if="entry.key === 'mask_data_uri'">
            <EditorMaskBrushPanel />
          </template>

          <!-- number：滑杆 + 数值输入 -->
          <template v-else-if="entry.rule.type === 'number' && !entry.rule.choices">
            <div class="flex items-center justify-between mb-1">
              <label class="text-[11px] text-slate-400">{{ entry.label }}</label>
              <input
                type="number"
                class="w-20 glass-input px-1.5 py-0.5 text-xs text-slate-700 text-right"
                :min="entry.rule.min"
                :max="entry.rule.max"
                :step="stepOf(entry.rule)"
                :value="numberValue(entry.key)"
                @change="updateNumberParam(entry.key, Number(($event.target as HTMLInputElement).value) || 0)"
              />
            </div>
            <input
              type="range"
              class="w-full accent-brand-purple"
              :min="entry.rule.min ?? 0"
              :max="entry.rule.max ?? 100"
              :step="stepOf(entry.rule)"
              :value="numberValue(entry.key)"
              @input="updateNumberParam(entry.key, Number(($event.target as HTMLInputElement).value))"
            />
          </template>

          <!-- choices：下拉 -->
          <template v-else-if="entry.rule.choices">
            <label class="block text-[11px] text-slate-400 mb-1">{{ entry.label }}</label>
            <select
              class="w-full glass-input px-2 py-1.5 text-xs text-slate-700 bg-white"
              :value="String(store.toolParams[entry.key] ?? '')"
              @change="updateParam(entry.key, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="choice in entry.rule.choices" :key="String(choice)" :value="String(choice)">
                {{ choice }}
              </option>
            </select>
          </template>

          <!-- boolean：开关 -->
          <template v-else-if="entry.rule.type === 'boolean'">
            <div class="flex items-center justify-between">
              <label class="text-[11px] text-slate-400">{{ entry.label }}</label>
              <button
                type="button"
                role="switch"
                :aria-checked="store.toolParams[entry.key] === true"
                class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors"
                :class="store.toolParams[entry.key] === true ? 'bg-brand-purple' : 'bg-slate-200'"
                @click="updateParam(entry.key, !(store.toolParams[entry.key] === true))"
              >
                <span
                  class="inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform"
                  :class="store.toolParams[entry.key] === true ? 'translate-x-[18px]' : 'translate-x-0.5'"
                />
              </button>
            </div>
          </template>

          <!-- string：文本输入 -->
          <template v-else>
            <label class="block text-[11px] text-slate-400 mb-1">{{ entry.label }}</label>
            <input
              type="text"
              class="w-full glass-input px-2 py-1.5 text-xs text-slate-700"
              :value="String(store.toolParams[entry.key] ?? '')"
              @change="updateParam(entry.key, ($event.target as HTMLInputElement).value)"
            />
          </template>
        </div>
      </div>

      <!-- 应用按钮 -->
      <button
        type="button"
        class="btn-primary w-full mt-4 py-2 text-sm flex items-center justify-center gap-2"
        :disabled="props.toolRunning"
        @click="emit('apply')"
      >
        <Loader2 v-if="props.toolRunning" class="w-4 h-4 animate-spin" />
        <Play v-else class="w-4 h-4" />
        {{ props.toolRunning ? '处理中...' : '应用' }}
      </button>

      <p v-if="store.activeTool === 'crop'" class="mt-2 text-[11px] text-slate-400 leading-4">
        可直接拖拽画布上的裁剪框，坐标将自动换算为原图像素
      </p>
    </div>
  </div>
</template>
