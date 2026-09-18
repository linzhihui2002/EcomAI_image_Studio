<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  ChevronDown,
  LogOut,
  User,
  Users,
  Plus,
  LogIn,
  Coins,
  Zap,
  Wallet,
  ArrowRightLeft,
  Bell,
  Package,
  HelpCircle,
  KeyRound,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'open-announcements'): void
}>()

const auth = useAuthStore()
const router = useRouter()
const showUserMenu = ref(false)
const showWalletSwitcher = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)

function handleClickOutside(event: MouseEvent) {
  if (userMenuRef.value && !userMenuRef.value.contains(event.target as Node)) {
    showUserMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

const avatarLetter = computed(() =>
  auth.user?.email?.charAt(0).toUpperCase() || 'U',
)

function toggleUserMenu() {
  if (!auth.isLoggedIn) {
    router.push('/login')
    return
  }
  showUserMenu.value = !showUserMenu.value
}

function closeUserMenu() {
  showUserMenu.value = false
}

function toggleWalletSwitcher() {
  showWalletSwitcher.value = !showWalletSwitcher.value
}

function closeWalletSwitcher() {
  showWalletSwitcher.value = false
}

function selectWallet(wallet: 'personal' | 'team') {
  auth.switchWallet(wallet)
  closeWalletSwitcher()
}

function goToPurchase(target?: 'personal' | 'team') {
  closeUserMenu()
  if (target === 'team') {
    router.push({ path: '/team', query: { action: 'topup' } })
  } else {
    router.push('/purchase')
  }
}

function goToProfile() {
  closeUserMenu()
  router.push('/profile')
}

/** 直达个人中心的「模型服务商配置」页签 */
function goToAiProviders() {
  closeUserMenu()
  router.push({ path: '/profile', query: { tab: 'providers' } })
}

function goToAccount() {
  closeUserMenu()
  router.push('/profile')
}

function goToOrders() {
  closeUserMenu()
  router.push('/orders')
}

function goToHelp() {
  closeUserMenu()
  router.push('/help')
}

function goToTeam() {
  closeUserMenu()
  router.push('/team')
}

function handleLogout() {
  auth.logout()
  closeUserMenu()
  router.push('/login')
}
</script>

<template>
  <header
    class="h-16 flex items-center justify-between px-6 border-b border-slate-200 bg-white/80 backdrop-blur-xl flex-shrink-0 relative z-40"
  >
    <div class="flex items-center gap-3">
      <div class="relative">
        <button
          @click="toggleWalletSwitcher"
          class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-50 border border-amber-200 hover:bg-amber-100 transition-all cursor-pointer"
        >
          <Zap class="w-4 h-4 text-amber-500" />
          <span class="text-sm font-medium text-amber-700">
            {{ auth.selectedWalletBalance.toLocaleString() }} 灵感币
          </span>
          <span
            v-if="auth.selectedWallet === 'personal'"
            class="text-[10px] px-1.5 py-0.5 rounded-full bg-green-100 text-green-600 font-medium"
          >
            个人
          </span>
          <span
            v-else
            class="text-[10px] px-1.5 py-0.5 rounded-full bg-brand-gradient-subtle text-brand-purple font-medium"
          >
            团队
          </span>
          <ChevronDown
            :class="['w-3.5 h-3.5 text-amber-400 transition-transform duration-200', showWalletSwitcher && 'rotate-180']"
          />
        </button>

        <Transition name="menu">
          <div
            v-if="showWalletSwitcher"
            class="absolute left-0 top-full mt-2 w-72 bg-white rounded-xl border border-slate-200 shadow-lg overflow-hidden z-50"
          >
            <div class="p-3 border-b border-slate-100">
              <p class="text-xs font-semibold text-slate-700 mb-2">选择支付钱包</p>
              <button
                @click="selectWallet('personal')"
                :class="[
                  'w-full flex items-center justify-between p-3 rounded-lg text-sm transition-all duration-200 cursor-pointer',
                  auth.selectedWallet === 'personal'
                    ? 'bg-green-50 border-2 border-green-300'
                    : 'bg-slate-50 border-2 border-transparent hover:bg-green-50/50 hover:border-green-200',
                ]"
              >
                <div class="flex items-center gap-2.5">
                  <div class="w-8 h-8 rounded-lg bg-green-100 flex items-center justify-center">
                    <Wallet class="w-4 h-4 text-green-600" />
                  </div>
                  <div class="text-left">
                    <p class="font-medium" :class="auth.selectedWallet === 'personal' ? 'text-green-800' : 'text-slate-700'">个人钱包</p>
                    <p class="text-[11px]" :class="auth.selectedWallet === 'personal' ? 'text-green-600' : 'text-slate-400'">仅自己可用，随身携带</p>
                  </div>
                </div>
                <div class="text-right">
                  <p class="font-semibold" :class="auth.selectedWallet === 'personal' ? 'text-green-700' : 'text-slate-600'">{{ auth.user?.personalPoints.toLocaleString() }}</p>
                  <p class="text-[10px] text-slate-400">灵感币</p>
                </div>
              </button>

              <button
                @click="selectWallet('team')"
                :disabled="!auth.currentTeamId || auth.teamPoolBalance <= 0"
                :class="[
                  'w-full flex items-center justify-between p-3 rounded-lg text-sm transition-all duration-200 cursor-pointer mt-2',
                  auth.selectedWallet === 'team'
                    ? 'bg-brand-gradient-subtle border-2 border-brand-purple/40'
                    : !auth.currentTeamId || auth.teamPoolBalance <= 0
                      ? 'opacity-40 cursor-not-allowed bg-slate-50 border-2 border-transparent'
                      : 'bg-slate-50 border-2 border-transparent hover:bg-brand-gradient-subtle/50 hover:border-brand-purple/30',
                ]"
              >
                <div class="flex items-center gap-2.5">
                  <div class="w-8 h-8 rounded-lg flex items-center justify-center" :class="auth.selectedWallet === 'team' ? 'bg-brand-purple/10' : 'bg-slate-100'">
                    <Users class="w-4 h-4" :class="auth.selectedWallet === 'team' ? 'text-brand-purple' : 'text-slate-400'" />
                  </div>
                  <div class="text-left">
                    <p class="font-medium" :class="auth.selectedWallet === 'team' ? 'text-brand-purple' : 'text-slate-700'">
                      {{ auth.currentTeam?.name || '团队钱包' }}
                    </p>
                    <p class="text-[11px]" :class="auth.selectedWallet === 'team' ? 'text-brand-purple/70' : 'text-slate-400'">
                      <template v-if="auth.currentTeamId">团队成员共享</template>
                      <template v-else>请先加入或选择团队</template>
                    </p>
                  </div>
                </div>
                <div class="text-right">
                  <p class="font-semibold" :class="auth.selectedWallet === 'team' ? 'text-brand-purple' : 'text-slate-600'">{{ auth.teamPoolBalance.toLocaleString() }}</p>
                  <p class="text-[10px] text-slate-400">灵感币</p>
                </div>
              </button>

              <div v-if="auth.selectedWallet === 'team'" class="mt-2 p-2 rounded-lg bg-blue-50/80 border border-blue-200/60">
                <div class="flex items-start gap-1.5">
                  <ArrowRightLeft class="w-3.5 h-3.5 text-blue-500 mt-0.5 flex-shrink-0" />
                  <p class="text-[11px] text-blue-600 leading-relaxed">
                    当前使用 <strong>{{ auth.currentTeam?.name }}</strong> 的团队钱包支付，消耗将从团队余额中扣除。
                  </p>
                </div>
              </div>
            </div>

            <div class="p-2 border-t border-slate-100 flex gap-2">
              <button
                @click="goToPurchase('personal')"
                class="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-xs font-medium text-green-600 hover:bg-green-50 transition-colors"
              >
                <Coins class="w-3.5 h-3.5" />
                充值个人
              </button>
              <button
                @click="goToPurchase('team')"
                :disabled="!auth.currentTeamId"
                class="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-xs font-medium transition-colors"
                :class="auth.currentTeamId ? 'text-brand-purple hover:bg-brand-gradient-subtle' : 'text-slate-300 cursor-not-allowed'"
              >
                <Coins class="w-3.5 h-3.5" />
                充值团队
              </button>
            </div>
          </div>
        </Transition>
      </div>
    </div>

    <div class="flex items-center gap-1">
      <!-- 公告铃铛按钮 -->
      <button
        @click="emit('open-announcements')"
        class="relative p-2 rounded-xl hover:bg-slate-100 active:scale-95 transition-all duration-200 group"
        title="查看公告"
      >
        <Bell class="w-5 h-5 text-slate-500 group-hover:text-brand-purple transition-colors duration-200" />
        <span class="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full animate-pulse" />
      </button>

      <div class="relative">
      <button
        @click.stop="toggleUserMenu"
        class="flex items-center gap-2.5 px-3 py-2 rounded-xl hover:bg-slate-100 transition-colors"
      >
        <div
          class="w-8 h-8 rounded-full bg-brand-gradient flex items-center justify-center text-white text-sm font-semibold"
        >
          {{ avatarLetter }}
        </div>
        <span class="text-sm font-medium text-slate-700 max-w-[140px] truncate">
          {{ auth.user?.email }}
        </span>
        <ChevronDown
          :class="['w-4 h-4 text-slate-400 transition-transform duration-200', showUserMenu && 'rotate-180']"
        />
      </button>

      <Transition name="menu">
        <div
          v-if="showUserMenu"
          ref="userMenuRef"
          class="absolute right-0 top-full mt-2 w-64 bg-white rounded-xl border border-slate-200 shadow-lg overflow-hidden z-50"
        >
          <div class="p-4 border-b border-slate-100">
            <p class="text-sm font-medium text-slate-900 truncate">
              {{ auth.user?.email }}
            </p>
            <div class="flex items-center gap-4 mt-2">
              <div class="flex items-center gap-1.5">
                <Wallet class="w-3.5 h-3.5 text-green-500" />
                <span class="text-xs text-slate-500">个人 <strong class="text-green-600">{{ auth.user?.personalPoints?.toLocaleString() }}</strong></span>
              </div>
              <div v-if="auth.currentTeamId" class="flex items-center gap-1.5">
                <Users class="w-3.5 h-3.5 text-brand-purple" />
                <span class="text-xs text-slate-500"><strong class="text-brand-purple">{{ auth.teamPoolBalance.toLocaleString() }}</strong></span>
              </div>
            </div>
          </div>

          <!-- 账号管理 -->
          <div class="p-2">
            <button
              @click="goToPurchase()"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <Coins class="w-4 h-4" />
              充值灵感币
            </button>
            <button
              @click="goToProfile()"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <User class="w-4 h-4" />
              个人中心
            </button>
            <button
              @click="goToAiProviders()"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <KeyRound class="w-4 h-4" />
              模型服务商配置
            </button>
          </div>

          <!-- 团队管理 -->
          <div class="border-t border-slate-100 p-2">
            <button
              @click="goToTeam()"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <Users class="w-4 h-4" />
              团队管理
            </button>
            <button
              @click="goToTeam()"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <Plus class="w-4 h-4" />
              创建团队
            </button>
            <button
              @click="goToTeam()"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <LogIn class="w-4 h-4" />
              加入团队
            </button>
          </div>

          <!-- 订单帮助 -->
          <div class="border-t border-slate-100 p-2">
            <button
              @click="goToOrders()"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <Package class="w-4 h-4" />
              我的订单
            </button>
            <button
              @click="goToHelp()"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <HelpCircle class="w-4 h-4" />
              帮助中心
            </button>
          </div>

          <div class="border-t border-slate-100 p-2">
            <button
              @click="handleLogout"
              class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-red-500 hover:bg-red-50 transition-colors"
            >
              <LogOut class="w-4 h-4" />
              退出登录
            </button>
          </div>
        </div>
      </Transition>
    </div>
    </div>
  </header>
</template>

<style scoped>
.menu-enter-active {
  transition: all 0.2s ease-out;
}
.menu-leave-active {
  transition: all 0.15s ease-in;
}
.menu-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.96);
}
.menu-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.96);
}
</style>
