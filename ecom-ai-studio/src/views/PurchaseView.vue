<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { PricingPlan } from '@/types'
import { fetchPricingPlans, redeemCode } from '@/api/purchase'
import { fetchUserBalance } from '@/api/user'
import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'
import {
  Coins,
  Gift,
  Check,
  X,
  Wallet,
  Users,
  ArrowLeft,
  Ticket,
  ArrowRight,
  AlertCircle,
  ChevronDown,
  Plus,
} from 'lucide-vue-next'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const activePlans = ref<PricingPlan[]>([])
const redemptionCode = ref('')
const selectedPlanId = ref<number | null>(null)
const showRedemptionResult = ref(false)
const redemptionResultMessage = ref('')
const noticeMessage = ref<string | null>(null)

const topupTarget = ref<'personal' | 'team'>('personal')

const showTeamSelector = ref(false)
const teamSelectorRef = ref<HTMLElement | null>(null)
const actionError = ref<string | null>(null)

const hasTeams = computed(() => auth.teams.length > 0)

const activeTeamId = computed(() => {
  if (auth.teams.length === 1) return auth.teams[0].id
  return auth.currentTeamId
})

const activeTeam = computed(() =>
  auth.teams.find(t => t.id === activeTeamId.value) || null
)

const loading = ref(false)
const loadingPlans = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  await loadPlans()
  await loadBalance()
  if (route.query.action === 'topup') {
    // 兜底：如果尚未选择团队，自动选择第一个
    if (!auth.currentTeamId && auth.teams.length > 0) {
      auth.switchTeam(auth.teams[0].id)
    }
    if (auth.currentTeamId) {
      topupTarget.value = 'team'
    }
  }
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

function handleClickOutside(e: MouseEvent) {
  if (teamSelectorRef.value && !teamSelectorRef.value.contains(e.target as Node)) {
    showTeamSelector.value = false
  }
}

const selectedPlan = computed(() =>
  activePlans.value.find((p) => p.id === selectedPlanId.value),
)

function selectPlan(plan: PricingPlan) {
  selectedPlanId.value = plan.id
}

async function handleRedeem() {
  if (!redemptionCode.value.trim()) return
  
  loading.value = true
  try {
    const res = await redeemCode({
      code: redemptionCode.value.trim().toUpperCase(),
      walletType: topupTarget.value,
      teamId: activeTeamId.value || undefined,
    })
    
    // Update local balance
    if (topupTarget.value === 'personal' && auth.user) {
      auth.user.personalPoints = res.data.newBalance
    } else if (topupTarget.value === 'team' && activeTeamId.value) {
      const team = auth.teams.find(t => t.id === activeTeamId.value)
      if (team) team.poolBalance = res.data.newBalance
    }
    
    redemptionResultMessage.value = `兑换成功！已获得 ${res.data.coinsAdded} 灵感币`
  } catch (e: any) {
    const msg = getErrorMessage(e, ERROR_DEFAULTS.REDEEM_FAILED)
    // 保留已有的兑换码特定错误码处理
    if (e.code === 4001) redemptionResultMessage.value = '该兑换码不存在，请确认输入是否正确'
    else if (e.code === 4002) redemptionResultMessage.value = '该兑换码已被使用，无法重复兑换'
    else if (e.code === 4003) redemptionResultMessage.value = '该兑换码已过期，请检查后重试'
    else if (e.code === 4006) redemptionResultMessage.value = '该兑换码已达到总使用次数上限，无法继续使用'
    else if (e.code === 4007) redemptionResultMessage.value = '该账号已达到此兑换码的使用次数限制'
    else redemptionResultMessage.value = msg
  } finally {
    loading.value = false
    showRedemptionResult.value = true
    setTimeout(() => { showRedemptionResult.value = false }, 4000)
    redemptionCode.value = ''
  }
}

function handlePay() {
  // 支付功能暂未实现，使用 UI 内联提示替代 alert
  noticeMessage.value = '支付功能暂未开放，请使用兑换码充值'
  setTimeout(() => { noticeMessage.value = null }, 4000)
}

async function loadPlans() {
  loadingPlans.value = true
  try {
    const plans = await fetchPricingPlans(true)
    activePlans.value = plans.sort((a, b) => a.sortOrder - b.sortOrder)
  } catch (e: any) {
    error.value = getErrorMessage(e, '加载定价方案失败，请稍后重试')
  } finally {
    loadingPlans.value = false
  }
}

async function loadBalance() {
  try {
    const res = await fetchUserBalance(
      topupTarget.value,
      topupTarget.value === 'team' ? (activeTeamId.value ?? undefined) : undefined
    )
    if (res.data) {
      if (res.data.walletType === 'personal' && auth.user) {
        auth.user.personalPoints = res.data.balance
      } else if (res.data.walletType === 'team' && activeTeamId.value) {
        const team = auth.teams.find(t => t.id === activeTeamId.value)
        if (team) team.poolBalance = res.data.balance
      }
    }
  } catch {
    // Balance load failure is non-critical
  }
}

function goToCreateTeam() {
  actionError.value = null
  router.push('/team')
}

function setPersonalTarget() {
  topupTarget.value = 'personal'
  selectedPlanId.value = null
}

function setTeamTarget() {
  if (!hasTeams.value) return
  topupTarget.value = 'team'
  selectedPlanId.value = null
}

function selectTeam(teamId: string) {
  auth.switchTeam(teamId)
  topupTarget.value = 'team'
  selectedPlanId.value = null
  showTeamSelector.value = false
  loadBalance()
}

function toggleTeamSelector() {
  showTeamSelector.value = !showTeamSelector.value
}
</script>

<template>
  <div class="p-8 max-w-6xl mx-auto space-y-8">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-900">充值中心</h1>
        <p class="text-sm text-slate-500 mt-1">为您的账户充值灵感币，解锁更多 AI 生图能力</p>
      </div>
    </div>

    <!-- 并列双卡片：个人钱包 + 团队钱包 -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <!-- 个人钱包卡片 -->
      <div
        @click="setPersonalTarget"
        class="rounded-2xl p-6 bg-gradient-to-br from-green-50 to-emerald-50 border-2 transition-all duration-200 cursor-pointer"
        :class="topupTarget === 'personal' ? 'border-green-400 shadow-md' : 'border-green-200/60 hover:border-green-300'"
      >
        <div class="flex items-center justify-between mb-1">
          <span class="text-sm font-medium text-slate-600">个人钱包余额</span>
          <span v-if="topupTarget === 'personal'" class="text-[10px] font-medium px-2 py-0.5 rounded-full bg-green-200/60 text-green-700">当前充值目标</span>
        </div>
        <div class="flex items-baseline gap-2 mt-2">
          <Wallet class="w-7 h-7 text-green-500" />
          <span class="text-4xl font-bold text-green-700">
            {{ (auth.user?.personalPoints ?? 0).toLocaleString() }}
          </span>
          <span class="text-lg text-slate-500">灵感币</span>
        </div>
      </div>

      <!-- 团队钱包卡片 -->
      <div
        @click="setTeamTarget"
        class="rounded-2xl p-6 bg-gradient-to-br from-brand-gradient-subtle/40 to-purple-50/30 border-2 transition-all duration-200"
        :class="hasTeams
          ? (topupTarget === 'team' ? 'border-brand-purple shadow-md' : 'border-brand-purple/20 hover:border-brand-purple/40 cursor-pointer')
          : 'border-slate-200 opacity-70'"
      >
        <div class="flex items-center justify-between mb-1">
          <span class="text-sm font-medium text-slate-600">团队钱包余额</span>
          <span v-if="topupTarget === 'team' && hasTeams" class="text-[10px] font-medium px-2 py-0.5 rounded-full bg-brand-purple/15 text-brand-purple">当前充值目标</span>
        </div>

        <!-- 状态 A：有团队 -->
        <template v-if="hasTeams">
          <!-- 团队选择下拉（仅 2+ 团队时显示） -->
          <div
            v-if="auth.teams.length >= 2"
            ref="teamSelectorRef"
            class="relative mt-2 mb-2"
          >
            <button
              @click.stop="toggleTeamSelector"
              class="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-lg bg-white/70 border border-slate-200 hover:border-brand-purple/40 hover:bg-brand-gradient-subtle/30 transition-all cursor-pointer"
            >
              <Users class="w-3.5 h-3.5 text-brand-purple" />
              <span class="text-slate-600">{{ activeTeam?.name || '选择团队' }}</span>
              <ChevronDown
                :class="['w-3 h-3 text-slate-400 transition-transform duration-200', showTeamSelector && 'rotate-180']"
              />
            </button>

            <Transition name="menu">
              <div
                v-if="showTeamSelector"
                class="absolute left-0 top-full mt-1 w-64 bg-white rounded-xl border border-slate-200 shadow-lg overflow-hidden z-50"
              >
                <div class="p-1.5">
                  <button
                    v-for="team in auth.teams"
                    :key="team.id"
                    @click.stop="selectTeam(team.id)"
                    :class="[
                      'w-full flex items-center justify-between p-2.5 rounded-lg text-sm transition-all duration-200 cursor-pointer',
                      activeTeamId === team.id
                        ? 'bg-brand-gradient-subtle border border-brand-purple/20'
                        : 'hover:bg-slate-50 border border-transparent',
                    ]"
                  >
                    <div class="flex items-center gap-2.5">
                      <div
                        :class="[
                          'w-8 h-8 rounded-lg flex items-center justify-center',
                          activeTeamId === team.id ? 'bg-brand-purple/15' : 'bg-slate-100',
                        ]"
                      >
                        <Users
                          :class="['w-4 h-4', activeTeamId === team.id ? 'text-brand-purple' : 'text-slate-400']"
                        />
                      </div>
                      <div class="text-left">
                        <p
                          :class="['font-medium text-sm', activeTeamId === team.id ? 'text-brand-purple' : 'text-slate-700']"
                        >
                          {{ team.name }}
                        </p>
                        <p class="text-[11px] text-slate-400">{{ team.memberCount }} 名成员</p>
                      </div>
                    </div>
                    <div class="text-right">
                      <p
                        :class="['font-semibold text-sm', activeTeamId === team.id ? 'text-brand-purple' : 'text-slate-600']"
                      >
                        {{ team.poolBalance.toLocaleString() }}
                      </p>
                      <p class="text-[10px] text-slate-400">灵感币</p>
                    </div>
                  </button>
                </div>
              </div>
            </Transition>
          </div>

          <div class="flex items-baseline gap-2" :class="auth.teams.length >= 2 ? 'mt-1' : 'mt-2'">
            <Users class="w-7 h-7 text-brand-purple" />
            <span class="text-4xl font-bold text-brand-purple">
              {{ (activeTeam?.poolBalance ?? 0).toLocaleString() }}
            </span>
            <span class="text-lg text-slate-500">灵感币</span>
          </div>

          <div v-if="activeTeam" class="mt-3 flex items-start gap-2 p-2.5 rounded-lg bg-blue-50/80 border border-blue-200/60">
            <AlertCircle class="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
            <p class="text-[11px] text-blue-600 leading-relaxed">
              当前充值目标为 <strong>{{ activeTeam.name }}</strong> 团队钱包，充值后的灵感币将进入团队共享池，所有团队成员均可使用。
            </p>
          </div>
        </template>

        <!-- 状态 B：无团队（引导创建） -->
        <template v-else>
          <div class="flex items-baseline gap-2 mt-2">
            <Users class="w-7 h-7 text-slate-400" />
            <span class="text-4xl font-bold text-slate-400">--</span>
            <span class="text-lg text-slate-500">灵感币</span>
          </div>

          <div class="mt-3 flex items-start gap-2 p-2.5 rounded-lg bg-slate-100 border border-slate-200">
            <AlertCircle class="w-4 h-4 text-slate-400 mt-0.5 flex-shrink-0" />
            <p class="text-[11px] text-slate-500 leading-relaxed">
              你还没有团队，创建或加入团队后可充值团队共享钱包，与成员共享灵感币。
            </p>
          </div>

          <button
            @click="goToCreateTeam"
            class="mt-3 w-full py-2.5 rounded-xl text-sm font-semibold bg-brand-purple text-white hover:bg-brand-purple/90 transition-colors flex items-center justify-center gap-2 cursor-pointer"
          >
            <Plus class="w-4 h-4" />
            去创建团队
          </button>
        </template>
      </div>
    </div>

    <div>
      <h2 class="text-lg font-semibold text-slate-900 mb-1">使用兑换码</h2>
      <p class="text-sm text-slate-500 mb-4">如果您有兑换码，可在此处输入以获取灵感币</p>

      <div class="flex gap-3 max-w-md">
        <div class="relative flex-1">
          <Ticket class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            v-model="redemptionCode"
            type="text"
            placeholder="输入兑换码"
            maxlength="20"
            class="glass-input w-full pl-10 pr-4 py-2.5 rounded-xl text-sm focus:ring-2 focus:ring-brand-purple/30"
            @keyup.enter="handleRedeem"
          />
        </div>
        <button
          @click="handleRedeem"
          class="btn-secondary px-5 py-2.5 rounded-xl text-sm font-medium flex items-center gap-2"
        >
          <Gift class="w-4 h-4" />
          兑换
        </button>
      </div>

      <Transition name="fade">
        <div
          v-if="showRedemptionResult"
          :class="[
            'mt-3 px-4 py-2.5 rounded-lg text-sm font-medium inline-flex items-center gap-2',
            redemptionResultMessage.includes('成功')
              ? 'bg-green-50 text-green-700 border border-green-200'
              : 'bg-red-50 text-red-600 border border-red-200',
          ]"
        >
          <component :is="redemptionResultMessage.includes('成功') ? Check : X" class="w-4 h-4 flex-shrink-0" />
          {{ redemptionResultMessage }}
        </div>
      </Transition>

      <!-- 通知提示（替代 alert） -->
      <Transition name="fade">
        <div
          v-if="noticeMessage"
          class="mt-3 px-4 py-2.5 rounded-lg text-sm font-medium inline-flex items-center gap-2 bg-amber-50 text-amber-700 border border-amber-200"
        >
          <AlertCircle class="w-4 h-4 flex-shrink-0" />
          {{ noticeMessage }}
        </div>
      </Transition>
    </div>

    <div>
      <h2 class="text-lg font-semibold text-slate-900 mb-1">选择充值方案</h2>
      <p class="text-sm text-slate-500 mb-4">
        充值到{{ topupTarget === 'personal' ? '个人钱包' : `${activeTeam?.name || '团队'}钱包` }}，选择最适合您的方案
      </p>

      <div v-if="loadingPlans" class="text-center py-10">
        <svg class="animate-spin w-6 h-6 mx-auto text-brand-purple" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25"/>
          <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" class="opacity-75"/>
        </svg>
        <p class="mt-2 text-sm text-slate-400">加载定价方案...</p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        <div
          v-for="plan in activePlans"
          :key="plan.id"
          @click="selectPlan(plan)"
          :class="[
            'relative rounded-2xl border-2 p-6 cursor-pointer transition-all duration-300',
            selectedPlanId === plan.id
              ? 'border-brand-purple bg-white shadow-glow scale-[1.02]'
              : plan.sortOrder === 2
                ? 'border-amber-300 bg-white shadow-md hover:shadow-lg hover:-translate-y-1'
                : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-md',
          ]"
        >
          <div v-if="plan.sortOrder === 2" class="absolute -top-3 left-1/2 -translate-x-1/2">
            <span class="px-4 py-1 rounded-full text-xs font-semibold bg-gradient-to-r from-amber-400 to-orange-400 text-white shadow-sm">
              最受欢迎
            </span>
          </div>

          <div class="text-center mb-4">
            <h3 class="text-lg font-bold text-slate-900">{{ plan.name }}</h3>
            <div class="mt-3 flex items-baseline justify-center gap-1">
              <span class="text-3xl font-extrabold text-slate-900">¥{{ plan.price }}</span>
            </div>
          </div>

          <div class="space-y-2.5 mb-5">
            <div class="flex items-center justify-between py-2 border-b border-slate-100">
              <span class="text-sm text-slate-600">基础灵感币</span>
              <span class="font-semibold text-slate-900">{{ plan.coins.toLocaleString() }}</span>
            </div>
            <div v-if="plan.bonusCoins > 0" class="flex items-center justify-between py-2 border-b border-slate-100">
              <span class="text-sm text-slate-600 flex items-center gap-1">
                赠送灵感币
                <Gift class="w-3.5 h-3.5 text-pink-400" />
              </span>
              <span class="font-semibold text-pink-500">+{{ plan.bonusCoins.toLocaleString() }}</span>
            </div>
            <div class="flex items-center justify-between py-2">
              <span class="text-sm text-slate-600">单价</span>
              <span class="text-sm font-medium text-slate-500">
                ¥{{ (Number(plan.price) / (Number(plan.coins) + Number(plan.bonusCoins))).toFixed(3) }}/币
              </span>
            </div>
          </div>

          <button
            :class="[
              'w-full py-2.5 rounded-xl text-sm font-semibold transition-all duration-200',
              selectedPlanId === plan.id
                ? 'btn-primary text-white shadow-glow'
                : 'bg-slate-100 text-slate-700 hover:bg-slate-200',
            ]"
          >
            {{ selectedPlanId === plan.id ? '已选择' : '选择此方案' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active { transition: opacity 0.3s ease; }
.fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.modal-enter-active { transition: all 0.25s ease-out; }
.modal-leave-active { transition: all 0.2s ease-in; }
.modal-enter-from, .modal-leave-to { opacity: 0; transform: scale(0.95); }
.menu-enter-active { transition: all 0.2s ease-out; }
.menu-leave-active { transition: all 0.15s ease-in; }
.menu-enter-from { opacity: 0; transform: translateY(-4px); }
.menu-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
