<script setup lang="ts">
/**
 * 工具箱功能消耗徽章
 * 根据后端定价配置展示单次调用所需「灵感币」数量；
 * 未定价（cost === 0）时展示「免费」。
 */
import { ref, onMounted } from 'vue'
import { Coins, Loader2 } from 'lucide-vue-next'
import { getFeaturePricingByKey, getPerUseCost } from '@/api/featurePricing'

const props = defineProps<{
  featureKey: string
}>()

/** 当前单次消耗（0 表示免费 / 未定价 / 加载失败时降级为 0） */
const cost = ref<number>(0)
const isLoading = ref<boolean>(true)

onMounted(async () => {
  try {
    const pricing = await getFeaturePricingByKey(props.featureKey)
    cost.value = getPerUseCost(pricing)
  } catch {
    // 拉取定价失败时不阻塞用户操作，按 0 处理（后端会再做余额校验）
    cost.value = 0
  } finally {
    isLoading.value = false
  }
})

defineExpose({ cost })
</script>

<template>
  <span
    v-if="isLoading"
    class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-slate-50 border border-slate-200 text-[11px] font-medium text-slate-400"
  >
    <Loader2 class="w-3 h-3 animate-spin" />
    加载中...
  </span>
  <span
    v-else-if="cost === 0"
    class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-[11px] font-medium text-emerald-600"
  >
    <Coins class="w-3 h-3" />
    免费
  </span>
  <span
    v-else
    class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-amber-50/80 border border-amber-200/60 text-[11px] font-medium text-amber-700"
  >
    <Coins class="w-3 h-3 text-amber-500" />
    {{ cost }} 灵感币/次
  </span>
</template>
