<script setup lang="ts">
import { computed } from 'vue'
import { Coins } from 'lucide-vue-next'

/**
 * 成本估算组件
 *
 * 新版 API（推荐）：
 *   - singleCost: 单张图片灵感币消耗
 *   - totalCount: 本次生成张数
 *   - totalCost:  本次总消耗
 *
 * 旧版 API（向后兼容，AssetPanel 等历史调用方仍可使用）：
 *   - cost          → 等价于 totalCost
 *   - productCount  → 等价于 totalCount
 *   - hasReference  → 已废弃，不再影响展示
 *
 * 当 singleCost === 0（定价未配置或未加载）时，展示「暂未定价」，
 * 不阻塞生成（由后端最终判定扣点）。
 */
const props = defineProps<{
  // 新 API（推荐）
  singleCost?: number
  totalCount?: number
  totalCost?: number
  // 旧 API（向后兼容）
  cost?: number
  productCount?: number
  hasReference?: boolean
}>()

const resolvedSingleCost = computed(() => props.singleCost ?? 0)
const resolvedTotalCount = computed(
  () => props.totalCount ?? props.productCount ?? 0,
)
const resolvedTotalCost = computed(() => props.totalCost ?? props.cost ?? 0)
const isPriced = computed(() => resolvedSingleCost.value > 0)
</script>

<template>
  <div class="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50/80 border border-amber-200/60">
    <Coins class="w-4 h-4 text-amber-500" />
    <span class="text-sm text-amber-700">
      <template v-if="isPriced">
        单张 <strong class="text-amber-800">{{ resolvedSingleCost }}</strong> 灵感币 · 本次 {{ resolvedTotalCount }} 张 · 共 <strong class="text-amber-800">{{ resolvedTotalCost }}</strong> 灵感币
      </template>
      <template v-else>
        暂未定价 · 本次 {{ resolvedTotalCount }} 张
      </template>
    </span>
    <span v-if="isPriced" class="text-xs text-amber-400 ml-auto">
      {{ resolvedTotalCount }}张 × {{ resolvedSingleCost }}
    </span>
  </div>
</template>
