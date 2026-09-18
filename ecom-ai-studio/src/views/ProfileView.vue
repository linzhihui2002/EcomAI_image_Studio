<script setup lang="ts">
import { ref, computed, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  User, Mail, Calendar, Shield, Award,
  Lock, ShieldCheck, ArrowLeft, Loader2, Check,
} from 'lucide-vue-next'
import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'
import AiProviderPanel from '@/components/profile/AiProviderPanel.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// ==================== 选项卡 ====================
const activeTab = ref<'profile' | 'security' | 'providers'>('profile')

// 支持以 /profile?tab=providers 直达指定页签（供头像下拉菜单的「模型服务商配置」入口使用）
const TAB_NAMES = ['profile', 'security', 'providers'] as const

function syncTabFromQuery(value: unknown) {
  if (typeof value === 'string' && (TAB_NAMES as readonly string[]).includes(value)) {
    activeTab.value = value as 'profile' | 'security' | 'providers'
  }
}

syncTabFromQuery(route.query.tab)
watch(() => route.query.tab, syncTabFromQuery)

function switchTab(tab: 'profile' | 'security' | 'providers') {
  activeTab.value = tab
  // 手动切换后清掉深链参数，避免刷新时又跳回进入时的页签
  if (route.query.tab) {
    router.replace({ path: '/profile' })
  }
  if (tab === 'security') {
    step.value = 'sendCode'
    code.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    errorMsg.value = ''
  }
}

// ==================== 个人中心 ====================
const roleLabel = computed(() => {
  if (!auth.user) return ''
  return auth.user.role === 'admin' ? '管理员' : '普通用户'
})

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

// ==================== 修改密码 ====================
const step = ref<'sendCode' | 'changePassword' | 'success'>('sendCode')

const code = ref('')
const newPassword = ref('')
const confirmPassword = ref('')

const sending = ref(false)
const countdown = ref(0)
const submitting = ref(false)
const errorMsg = ref('')

let countdownTimer: ReturnType<typeof setInterval> | null = null

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})

const passwordMatch = computed(() => {
  if (!confirmPassword.value) return true
  return newPassword.value === confirmPassword.value
})

async function sendCode() {
  if (countdown.value > 0) return

  errorMsg.value = ''
  sending.value = true

  try {
    const res = await fetch('/api/v1/auth/send-code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: auth.user?.email, purpose: 'reset_password' }),
    })
    const data = await res.json()
    if (data.code === 0) {
      countdown.value = 60
      countdownTimer = setInterval(() => {
        countdown.value--
        if (countdown.value <= 0) {
          clearInterval(countdownTimer!)
          countdownTimer = null
        }
      }, 1000)
      step.value = 'changePassword'
    } else {
      const sendCodeErrorMap: Record<number, string> = {
        1006: '验证码发送过于频繁，请稍后再试',
      }
      const mappedMsg = sendCodeErrorMap[data.code]
      errorMsg.value = mappedMsg || getErrorMessage(
        { code: data.code, message: data.message },
        ERROR_DEFAULTS.SEND_CODE_FAILED,
      )
    }
  } catch {
    errorMsg.value = ERROR_DEFAULTS.NETWORK
  } finally {
    sending.value = false
  }
}

async function handleChangePassword() {
  errorMsg.value = ''

  if (!code.value) {
    errorMsg.value = '请输入验证码'
    return
  }
  if (code.value.length !== 6) {
    errorMsg.value = '验证码为 6 位数字'
    return
  }
  if (!newPassword.value) {
    errorMsg.value = '请设置新密码'
    return
  }
  if (newPassword.value.length < 6) {
    errorMsg.value = '密码长度至少 6 位'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    errorMsg.value = '两次输入的密码不一致'
    return
  }

  submitting.value = true

  try {
    const res = await fetch('/api/v1/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: auth.user?.email,
        code: code.value,
        password: newPassword.value,
      }),
    })
    const data = await res.json()
    if (data.code === 0) {
      step.value = 'success'
    } else {
      const changePwErrorMap: Record<number, string> = {
        3009: '验证码错误或已过期',
      }
      const mappedMsg = changePwErrorMap[data.code]
      errorMsg.value = mappedMsg || getErrorMessage(
        { code: data.code, message: data.message },
        ERROR_DEFAULTS.CHANGE_PASSWORD_FAILED,
      )
    }
  } catch {
    errorMsg.value = ERROR_DEFAULTS.NETWORK
  } finally {
    submitting.value = false
  }
}

function goBack() {
  step.value = 'sendCode'
  errorMsg.value = ''
}
</script>

<template>
  <div class="p-6 max-w-4xl mx-auto">
    <h2 class="text-xl font-semibold text-slate-900 mb-6">个人中心</h2>

    <!-- 选项卡导航 -->
    <div class="flex gap-1 mb-6 p-1 bg-slate-100 rounded-xl w-fit">
      <button
        @click="switchTab('profile')"
        :class="activeTab === 'profile' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'"
        class="px-4 py-2 rounded-lg text-sm font-medium transition-all"
      >
        个人资料
      </button>
      <button
        @click="switchTab('security')"
        :class="activeTab === 'security' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'"
        class="px-4 py-2 rounded-lg text-sm font-medium transition-all"
      >
        账号安全
      </button>
      <button
        @click="switchTab('providers')"
        :class="activeTab === 'providers' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'"
        class="px-4 py-2 rounded-lg text-sm font-medium transition-all"
      >
        模型服务商配置
      </button>
    </div>

    <!-- ==================== 面板 A：个人中心 ==================== -->
    <div v-show="activeTab === 'profile'">
      <div class="glass-card p-6 rounded-2xl">
        <div class="flex items-center gap-5 mb-6">
          <div
            class="w-16 h-16 rounded-full bg-brand-gradient flex items-center justify-center text-white text-2xl font-bold flex-shrink-0"
          >
            {{ auth.user?.email?.charAt(0).toUpperCase() || 'U' }}
          </div>
          <div>
            <h3 class="text-lg font-semibold text-slate-900">
              {{ auth.user?.email || '未知用户' }}
            </h3>
            <div class="flex items-center gap-3 mt-1">
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-xs text-slate-500">
                <Shield class="w-3 h-3" />
                {{ roleLabel }}
              </span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-brand-gradient-subtle text-xs text-brand-purple">
                <Award class="w-3 h-3" />
                {{ auth.user?.personalPoints || 0 }} 灵感币
              </span>
            </div>
          </div>
        </div>

        <div class="space-y-4">
          <div class="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-50">
            <Mail class="w-5 h-5 text-slate-400 flex-shrink-0" />
            <div class="min-w-0">
              <p class="text-xs text-slate-400">邮箱</p>
              <p class="text-sm text-slate-700 truncate">{{ auth.user?.email || '-' }}</p>
            </div>
          </div>

          <div class="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-50">
            <User class="w-5 h-5 text-slate-400 flex-shrink-0" />
            <div class="min-w-0">
              <p class="text-xs text-slate-400">用户 ID</p>
              <p class="text-sm text-slate-700 font-mono truncate">{{ auth.user?.id || '-' }}</p>
            </div>
          </div>

          <div class="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-50">
            <Calendar class="w-5 h-5 text-slate-400 flex-shrink-0" />
            <div class="min-w-0">
              <p class="text-xs text-slate-400">注册时间</p>
              <p class="text-sm text-slate-700">
                {{ auth.user?.createdAt ? formatDate(auth.user.createdAt) : '-' }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 面板 B：账号安全（修改密码） ==================== -->
    <div v-show="activeTab === 'security'">
      <div class="glass-card p-6 rounded-2xl">
        <div class="flex items-center gap-3 mb-5">
          <div class="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center">
            <Lock class="w-5 h-5 text-slate-500" />
          </div>
          <h3 class="text-base font-semibold text-slate-900">修改密码</h3>
        </div>

        <div class="max-w-md">
          <!-- 阶段 1：发送验证码 -->
          <template v-if="step === 'sendCode'">
            <p class="text-sm text-slate-500 mb-5">验证码将发送至您的注册邮箱 {{ auth.user?.email }}</p>

            <div
              v-if="errorMsg"
              class="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 animate-fade-in"
            >
              {{ errorMsg }}
            </div>

            <button
              @click="sendCode"
              :disabled="sending"
              class="btn-primary inline-flex items-center gap-2 px-5 py-2.5 text-sm"
            >
              <Loader2 v-if="sending" class="w-4 h-4 animate-spin" />
              <span>{{ sending ? '发送中...' : '发送验证码' }}</span>
            </button>
          </template>

          <!-- 阶段 2：验证验证码 + 设置新密码 -->
          <template v-else-if="step === 'changePassword'">
            <div class="flex items-center gap-2 mb-5">
              <button
                @click="goBack"
                class="p-1.5 rounded-lg hover:bg-slate-100 transition-colors"
              >
                <ArrowLeft class="w-4 h-4 text-slate-500" />
              </button>
              <p class="text-sm text-slate-500">验证码已发送至 {{ auth.user?.email }}</p>
            </div>

            <div class="mb-4">
              <label class="block text-sm text-slate-600 mb-1.5">验证码</label>
              <div class="flex gap-3">
                <div class="relative flex-1">
                  <ShieldCheck class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    v-model="code"
                    type="text"
                    placeholder="请输入 6 位验证码"
                    maxlength="6"
                    class="w-full pl-10 pr-4 py-2.5 text-sm rounded-xl border border-slate-200 bg-white focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 transition-all outline-none"
                    @keyup.enter="handleChangePassword"
                  />
                </div>
                <button
                  @click="sendCode"
                  :disabled="countdown > 0 || sending"
                  class="px-4 py-2.5 rounded-xl text-sm font-medium whitespace-nowrap transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                  :class="
                    countdown > 0
                      ? 'bg-slate-100 text-slate-400'
                      : 'bg-brand-gradient-subtle text-brand-purple hover:shadow-glow'
                  "
                >
                  <span v-if="sending">
                    <Loader2 class="w-4 h-4 animate-spin inline" />
                  </span>
                  <span v-else-if="countdown > 0">{{ countdown }}s</span>
                  <span v-else>重新发送</span>
                </button>
              </div>
            </div>

            <div class="mb-4">
              <label class="block text-sm text-slate-600 mb-1.5">新密码</label>
              <div class="relative">
                <Lock class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="newPassword"
                  type="password"
                  placeholder="至少 6 位字符"
                  class="w-full pl-10 pr-4 py-2.5 text-sm rounded-xl border border-slate-200 bg-white focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 transition-all outline-none"
                />
              </div>
            </div>

            <div class="mb-5">
              <label class="block text-sm text-slate-600 mb-1.5">确认新密码</label>
              <div class="relative">
                <Lock class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="confirmPassword"
                  type="password"
                  placeholder="请再次输入新密码"
                  class="w-full pl-10 pr-4 py-2.5 text-sm rounded-xl border border-slate-200 bg-white focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 transition-all outline-none"
                  :class="confirmPassword && !passwordMatch ? 'border-red-300 focus:ring-red-200' : ''"
                  @keyup.enter="handleChangePassword"
                />
              </div>
              <p v-if="confirmPassword && !passwordMatch" class="text-xs text-red-500 mt-1">
                两次输入的密码不一致
              </p>
            </div>

            <div
              v-if="errorMsg"
              class="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 animate-fade-in"
            >
              {{ errorMsg }}
            </div>

            <button
              @click="handleChangePassword"
              :disabled="submitting"
              class="btn-primary inline-flex items-center gap-2 px-5 py-2.5 text-sm"
            >
              <Loader2 v-if="submitting" class="w-4 h-4 animate-spin" />
              <span>{{ submitting ? '修改中...' : '确认修改' }}</span>
            </button>
          </template>

          <!-- 阶段 3：成功反馈 -->
          <template v-else>
            <div class="text-center py-4">
              <div class="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4">
                <Check class="w-8 h-8 text-green-500" />
              </div>
              <h3 class="text-lg font-semibold text-slate-900 mb-2">密码修改成功</h3>
              <p class="text-sm text-slate-500 mb-6">您的密码已更新，下次登录请使用新密码</p>
              <button
                @click="step = 'sendCode'; newPassword = ''; confirmPassword = ''; code = ''; errorMsg = ''"
                class="btn-secondary inline-flex items-center gap-2 px-5 py-2.5 text-sm"
              >
                返回
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- ==================== 面板 C：模型服务商配置（BYOK） ==================== -->
    <div v-if="activeTab === 'providers'">
      <AiProviderPanel />
    </div>
  </div>
</template>