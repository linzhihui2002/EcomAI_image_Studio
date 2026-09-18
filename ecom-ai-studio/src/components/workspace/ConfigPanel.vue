<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import SmartMode from './SmartMode.vue'
import ProMode from './ProMode.vue'
import CostEstimator from '@/components/common/CostEstimator.vue'
import { Sparkles, Wand2, Zap, AlertCircle, X } from 'lucide-vue-next'

const workspace = useWorkspaceStore()
const auth = useAuthStore()

const generateError = ref('')

// 加载智能模式定价，供 CostEstimator 与余额检查使用
// （ProMode 内部会单独加载专业模式定价）
onMounted(() => {
  workspace.loadPricing('ai_product_image.smart_mode')
})

// 估算展示：依据当前模式选用对应的定价字段
const displaySingleCost = computed(() =>
  workspace.mode === 'pro' ? workspace.proSingleImageCost : workspace.singleImageCost,
)
const displayTotalCount = computed(() =>
  workspace.mode === 'pro' ? workspace.proTaskCount : workspace.productImages.length,
)
const displayTotalCost = computed(() =>
  workspace.mode === 'pro' ? workspace.proEstimatedCost : workspace.estimatedCost,
)

function handleGenerate() {
  generateError.value = ''
  // 英文卖点视觉关键词校验不通过（含中文/全角字符）时禁止提交生图
  if (workspace.mode === 'smart' && workspace.smartEnPointsInvalid) {
    generateError.value = '英文卖点视觉关键词包含中文或全角字符，请修正后再生成'
    return
  }
  // 估算价 > 0 时才做余额校验；定价未配置（=0）时不阻塞生成
  if (displayTotalCost.value > 0 && auth.selectedWalletBalance < displayTotalCost.value) {
    const walletName = auth.selectedWallet === 'personal'
      ? '个人'
      : auth.currentTeam?.name || '团队'
    generateError.value = `${walletName}钱包余额不足，当前余额 ${auth.selectedWalletBalance}，本次需要 ${displayTotalCost.value} 灵感币，请充值后再试`
    return
  }
  const success = auth.deductPoints(displayTotalCost.value)
  if (success) {
    workspace.runGeneration()
  }
}
</script>

<template>
  <div class="flex flex-col h-full bg-white">
    <!-- 标题 -->
    <div class="p-4 border-b border-slate-200">
      <h3 class="text-sm font-semibold text-slate-900 flex items-center gap-2">
        <Wand2 class="w-4 h-4 text-brand-purple" />
        配置面板
      </h3>
    </div>

    <div class="flex-1 overflow-y-auto p-4 space-y-5">
      <!-- 模式切换 -->
      <div>
        <label class="text-xs font-medium text-slate-700 mb-2 block">生成模式</label>
        <div class="flex bg-slate-100 rounded-xl p-1">
          <button
            @click="workspace.setMode('smart')"
            :class="[
              'flex-1 py-2 rounded-lg text-xs font-medium transition-all duration-200',
              workspace.mode === 'smart'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700',
            ]"
          >
            <Zap class="w-3.5 h-3.5 inline mr-1" />
            智能铺货
          </button>
          <button
            @click="workspace.setMode('pro')"
            :class="[
              'flex-1 py-2 rounded-lg text-xs font-medium transition-all duration-200',
              workspace.mode === 'pro'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700',
            ]"
          >
            <Sparkles class="w-3.5 h-3.5 inline mr-1" />
            专业精品
          </button>
        </div>
      </div>

      <!-- 模式内容 -->
      <SmartMode v-if="workspace.mode === 'smart'" />
      <ProMode v-else />

      <!-- 算力估算 -->
      <CostEstimator
        :single-cost="displaySingleCost"
        :total-count="displayTotalCount"
        :total-cost="displayTotalCost"
      />

      <!-- 生成操作错误提示 -->
      <Transition name="fade">
        <div v-if="generateError" class="flex items-center gap-2 p-2.5 rounded-lg bg-red-50 border border-red-200 text-sm text-red-600">
          <AlertCircle class="w-4 h-4 flex-shrink-0" />
          <span>{{ generateError }}</span>
          <button @click="generateError = ''" class="ml-auto"><X class="w-3.5 h-3.5" /></button>
        </div>
      </Transition>

      <!-- 平台合规阻断提示（生图提交被 400 拒绝且返回 blocks 时展示） -->
      <Transition name="fade">
        <div v-if="workspace.complianceBlocks.length > 0" class="p-2.5 rounded-lg bg-red-50 border border-red-200 space-y-1.5">
          <div class="flex items-center gap-2 text-sm text-red-600 font-medium">
            <AlertCircle class="w-4 h-4 flex-shrink-0" />
            <span>内容未通过平台合规校验，请修正后重新生成</span>
            <button @click="workspace.complianceBlocks = []" class="ml-auto"><X class="w-3.5 h-3.5" /></button>
          </div>
          <ul class="space-y-1 pl-6 list-disc">
            <li v-for="(block, idx) in workspace.complianceBlocks" :key="idx" class="text-xs text-red-600 leading-relaxed">
              <span class="font-medium">{{ block.rule }}</span>
              <span v-if="block.reason">：{{ block.reason }}</span>
            </li>
          </ul>
        </div>
      </Transition>

      <!-- 生成按钮 -->
      <button
        @click="handleGenerate"
        :disabled="!workspace.canGenerate"
        class="btn-primary w-full flex items-center justify-center gap-2 py-3"
      >
        <Sparkles class="w-4 h-4" />
        {{ workspace.mode === 'smart' ? '一键智能批量生成' : '开始生成' }}
      </button>

      <p class="text-[10px] text-slate-400 text-center">
        生成后将消耗对应灵感币，实际扣点以生成结果为准
      </p>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active { transition: opacity 0.3s ease; }
.fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>