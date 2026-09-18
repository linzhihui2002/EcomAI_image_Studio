<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getFeaturePricingByKey, getPerUseCost } from '@/api/featurePricing'
import { Wallet, Users, AlertCircle, Coins, Loader2 } from 'lucide-vue-next'

const props = defineProps<{
  featureKey: string
}>()

const auth = useAuthStore()

const cost = ref<number>(0)
const isLoading = ref(true)

onMounted(async () => {
  try {
    const pricing = await getFeaturePricingByKey(props.featureKey)
    cost.value = getPerUseCost(pricing)
  } catch {
    cost.value = 0
  } finally {
    isLoading.value = false
  }
})

const isPriced = computed(() => cost.value > 0)
const isTeamWallet = computed(() => auth.selectedWallet === 'team')
const showTeamButton = computed(
  () => !!auth.currentTeamId && auth.teamPoolBalance > 0,
)

const balanceInsufficient = computed(
  () => isPriced.value && auth.selectedWalletBalance < cost.value,
)

const walletName = computed(() =>
  isTeamWallet.value ? auth.currentTeam?.name || '团队' : '个人',
)

defineExpose({ cost })
</script>

<template>
  <div class="rounded-lg border overflow-hidden" :class="
    auth.selectedWallet === 'personal'
      ? 'border-green-200 bg-green-50/50'
      : 'border-brand-purple/20 bg-brand-gradient-subtle/30'
  ">
    <div class="px-3 py-2.5 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <component
          :is="auth.selectedWallet === 'personal' ? Wallet : Users"
          :class="['w-4 h-4', auth.selectedWallet === 'personal' ? 'text-green-600' : 'text-brand-purple']"
        />
        <span class="text-xs font-semibold" :class="auth.selectedWallet === 'personal' ? 'text-green-700' : 'text-brand-purple'">
          支付方式
        </span>
      </div>
      <div class="flex items-center gap-1.5">
        <button
          @click="auth.switchWallet('personal')"
          :class="[
            'px-2.5 py-1 rounded-md text-[11px] font-medium transition-all duration-200 cursor-pointer',
            auth.selectedWallet === 'personal'
              ? 'bg-green-600 text-white shadow-sm'
              : 'bg-green-100 text-green-600 hover:bg-green-200',
          ]"
        >
          个人 {{ auth.user?.personalPoints.toLocaleString() }}
        </button>
        <button
          v-if="showTeamButton"
          @click="auth.switchWallet('team')"
          :class="[
            'px-2.5 py-1 rounded-md text-[11px] font-medium transition-all duration-200 cursor-pointer',
            auth.selectedWallet === 'team'
              ? 'bg-brand-purple text-white shadow-sm'
              : 'bg-brand-gradient-subtle text-brand-purple hover:bg-brand-gradient-subtle/70',
          ]"
        >
          团队 {{ auth.teamPoolBalance.toLocaleString() }}
        </button>
      </div>
    </div>

    <!-- 团队钱包说明 -->
    <div v-if="isTeamWallet" class="px-3 pb-2.5 pt-0">
      <p class="text-[11px] leading-relaxed" :class="!isPriced || auth.teamPoolBalance >= cost ? 'text-blue-600' : 'text-amber-600'">
        <template v-if="!isPriced">
          将从「{{ auth.currentTeam?.name }}」团队钱包按实际消耗扣点
        </template>
        <template v-else-if="auth.teamPoolBalance >= cost">
          将从「{{ auth.currentTeam?.name }}」团队钱包扣除 {{ cost }} 灵感币
        </template>
        <template v-else>
          团队钱包余额不足！需要 {{ cost }}，仅剩 {{ auth.teamPoolBalance }}
        </template>
      </p>
    </div>

    <!-- 消耗展示 -->
    <div class="px-3 pb-2.5">
      <div v-if="isLoading" class="flex items-center gap-1.5 text-[11px] text-slate-400">
        <Loader2 class="w-3 h-3 animate-spin" />
        加载定价...
      </div>
      <div v-else class="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50/80 border border-amber-200/60">
        <Coins class="w-4 h-4 text-amber-500" />
        <span class="text-sm text-amber-700">
          <template v-if="isPriced">
            本次消耗 <strong class="text-amber-800">{{ cost }}</strong> 灵感币
          </template>
          <template v-else>
            暂未定价
          </template>
        </span>
        <span v-if="isPriced" class="text-xs text-amber-400 ml-auto">
          余额 {{ auth.selectedWalletBalance.toLocaleString() }}
        </span>
      </div>
    </div>

    <!-- 余额不足警告 -->
    <div v-if="balanceInsufficient" class="px-3 pb-2.5">
      <div class="flex items-start gap-2 p-2.5 rounded-lg bg-amber-50 border border-amber-200/60">
        <AlertCircle class="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
        <div class="flex-1 min-w-0">
          <p class="text-xs font-medium text-amber-700">
            {{ walletName }}钱包余额不足
          </p>
          <p class="text-[11px] text-amber-600 mt-0.5">
            当前余额 {{ auth.selectedWalletBalance }} 灵感币，本次需要 {{ cost }} 灵感币。
            <router-link
              v-if="!isTeamWallet"
              to="/purchase"
              class="font-medium underline hover:text-amber-800"
            >
              去充值 →
            </router-link>
            <router-link
              v-else-if="auth.currentTeamId"
              :to="{ path: '/team', query: { action: 'topup' } }"
              class="font-medium underline hover:text-amber-800"
            >
              充值团队钱包 →
            </router-link>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>