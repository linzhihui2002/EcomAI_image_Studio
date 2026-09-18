<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Sparkles, Mail, Lock, ArrowLeft, Loader2, Check, ShieldCheck } from 'lucide-vue-next'
import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'

const router = useRouter()

// 阶段: email -> verify -> success
const step = ref<'email' | 'verify' | 'success'>('email')

// 表单字段
const email = ref('')
const code = ref('')
const password = ref('')
const confirmPassword = ref('')

// 状态
const sending = ref(false)
const countdown = ref(0)
const submitting = ref(false)
const errorMsg = ref('')
const showSuggestions = ref(false)

let countdownTimer: ReturnType<typeof setInterval> | null = null

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})

const API_BASE = '/api/v1'

// 邮箱域名补全
const emailDomains = ['@gmail.com', '@outlook.com', '@qq.com', '@163.com']
const filteredDomains = computed(() => {
  if (!email.value || email.value.includes('@')) return []
  return emailDomains
})

function fillDomain(domain: string) {
  const atIndex = email.value.indexOf('@')
  if (atIndex > 0) {
    email.value = email.value.substring(0, atIndex) + domain
  } else {
    email.value += domain
  }
  showSuggestions.value = false
}

// 发送验证码
async function sendCode() {
  if (countdown.value > 0 || !email.value) return
  if (!email.value.includes('@')) {
    errorMsg.value = '请输入正确的邮箱地址'
    return
  }
  errorMsg.value = ''
  sending.value = true

  try {
    const res = await fetch(`${API_BASE}/auth/send-code`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.value, purpose: 'reset_password' }),
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
      step.value = 'verify'
    } else {
      // 发送验证码场景：1001 可能表示邮箱不存在
      const sendCodeErrorMap: Record<number, string> = {
        1001: '该邮箱未注册，请检查后重试',
        1008: '账号不存在，请先注册',
        1006: '验证码发送过于频繁，请稍后再试',
        3002: '邮箱格式无效，请检查后重试',
      }
      const mappedMsg = sendCodeErrorMap[data.code]
      errorMsg.value = mappedMsg || getErrorMessage(
        { code: data.code, message: data.message },
        ERROR_DEFAULTS.SEND_CODE_FAILED,
      )
    }
  } catch {
    errorMsg.value = ERROR_DEFAULTS.NETWORK
    sending.value = false
  }
}

// 密码一致性检查
const passwordMatch = computed(() => {
  if (!confirmPassword.value) return true
  return password.value === confirmPassword.value
})

// 提交重置密码
async function handleReset() {
  errorMsg.value = ''

  if (!code.value) {
    errorMsg.value = '请输入验证码'
    return
  }
  if (code.value.length !== 6) {
    errorMsg.value = '验证码为 6 位数字'
    return
  }
  if (!password.value) {
    errorMsg.value = '请设置新密码'
    return
  }
  if (password.value.length < 6) {
    errorMsg.value = '密码长度至少 6 位'
    return
  }
  if (password.value !== confirmPassword.value) {
    errorMsg.value = '两次输入的密码不一致'
    return
  }

  submitting.value = true

  try {
    const res = await fetch(`${API_BASE}/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value,
        code: code.value,
        password: password.value,
      }),
    })
    const data = await res.json()
    if (data.code === 0) {
      step.value = 'success'
    } else {
      // 重置密码场景：1001 在此表示"该邮箱未注册"而非"token 过期"
      const resetPwErrorMap: Record<number, string> = {
        1001: '该邮箱未注册，请检查后重试',
        1008: '账号不存在，请先注册',
        3002: '输入信息有误，请检查后提交',
        3009: '验证码无效或已过期，请重新获取',
      }
      const mappedMsg = resetPwErrorMap[data.code]
      errorMsg.value = mappedMsg || getErrorMessage(
        { code: data.code, message: data.message },
        ERROR_DEFAULTS.RESET_PASSWORD_FAILED,
      )
    }
  } catch {
    errorMsg.value = ERROR_DEFAULTS.NETWORK
  } finally {
    submitting.value = false
  }
}

function goBack() {
  if (step.value === 'verify') {
    step.value = 'email'
  } else {
    router.push('/login')
  }
}
</script>

<template>
  <div class="flex h-screen bg-white overflow-hidden">
    <!-- 左侧轮播区域 60% -->
    <div class="hidden lg:flex lg:w-[60%] relative bg-slate-900 overflow-hidden">
      <div class="absolute inset-0 bg-brand-gradient opacity-90" />
      <div class="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(255,255,255,0.15),transparent_50%)]" />

      <div class="absolute top-20 left-20 w-64 h-64 rounded-full bg-white/5 blur-3xl animate-float" />
      <div class="absolute bottom-20 right-20 w-96 h-96 rounded-full bg-brand-cyan/20 blur-3xl animate-float" style="animation-delay: 2s;" />

      <div class="relative flex flex-col justify-center items-center w-full px-16">
        <div class="mb-12 text-center">
          <div class="flex items-center justify-center gap-3 mb-4">
            <div class="w-12 h-12 rounded-2xl bg-white/20 backdrop-blur-sm flex items-center justify-center">
              <Sparkles class="w-7 h-7 text-white" />
            </div>
          </div>
          <h1 class="text-4xl font-display font-bold text-white mb-3">
            EcomAI Studio
          </h1>
          <p class="text-lg text-white/70 max-w-md">
            AI驱动的跨境电商视觉工作台<br />让每件商品都拥有专业级展示图
          </p>
        </div>

        <div class="relative w-full max-w-lg aspect-[4/5] rounded-2xl overflow-hidden shadow-2xl">
          <div class="relative w-full h-full">
            <div class="absolute inset-[15%] z-10 rounded-xl overflow-hidden shadow-lg">
              <img src="https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&h=700&fit=crop" class="w-full h-full object-cover" />
              <div class="absolute top-2 left-2 px-2 py-0.5 bg-brand-gradient rounded-md text-xs text-white font-medium">
                AI 生成
              </div>
            </div>
            <div class="absolute top-4 right-4 w-[45%] aspect-square rounded-xl overflow-hidden shadow-md opacity-60 rotate-6 z-0">
              <img src="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&h=700&fit=crop" class="w-full h-full object-cover" />
              <div class="absolute top-1 left-1 px-1.5 py-0.5 bg-slate-800/80 rounded text-[10px] text-white">
                原图
              </div>
            </div>
          </div>
        </div>

        <div class="flex gap-12 mt-10">
          <div class="text-center">
            <p class="text-2xl font-display font-bold text-white">840万+</p>
            <p class="text-sm text-white/60">电商卖家信赖</p>
          </div>
          <div class="text-center">
            <p class="text-2xl font-display font-bold text-white">99.7%</p>
            <p class="text-sm text-white/60">生成成功率</p>
          </div>
          <div class="text-center">
            <p class="text-2xl font-display font-bold text-white">3.2秒</p>
            <p class="text-sm text-white/60">平均出图时间</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧表单卡片 40% -->
    <div class="flex-1 flex items-center justify-center p-8 bg-surface-light">
      <div class="w-full max-w-[400px]">
        <!-- 移动端 Logo -->
        <div class="text-center mb-8 lg:hidden">
          <div class="flex items-center justify-center gap-2 mb-3">
            <div class="w-10 h-10 rounded-xl bg-brand-gradient flex items-center justify-center">
              <Sparkles class="w-5 h-5 text-white" />
            </div>
          </div>
          <h1 class="text-2xl font-display font-bold gradient-text">EcomAI Studio</h1>
        </div>

        <div class="glass-card p-8">
          <!-- ==================== 阶段 1：输入邮箱 ==================== -->
          <template v-if="step === 'email'">
            <h2 class="text-xl font-semibold text-slate-900 mb-1">忘记密码</h2>
            <p class="text-sm text-slate-500 mb-6">请输入您的注册邮箱，我们将发送验证码</p>

            <div class="relative mb-6">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                邮箱地址
              </label>
              <div class="relative">
                <Mail class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="email"
                  type="email"
                  placeholder="请输入注册邮箱"
                  class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                  @focus="showSuggestions = true"
                  @blur="showSuggestions = false"
                  @keyup.enter="sendCode"
                />
              </div>
              <div
                v-if="showSuggestions && filteredDomains.length && !email.includes('@')"
                class="absolute z-10 mt-1 w-full bg-white rounded-xl border border-slate-200 shadow-lg overflow-hidden"
              >
                <button
                  v-for="domain in filteredDomains"
                  :key="domain"
                  @mousedown.prevent="fillDomain(domain)"
                  class="w-full px-4 py-2 text-sm text-left text-slate-600 hover:bg-slate-50 transition-colors"
                >
                  {{ email }}{{ domain }}
                </button>
              </div>
            </div>

            <div
              v-if="errorMsg"
              class="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 animate-fade-in"
            >
              {{ errorMsg }}
            </div>

            <button
              @click="sendCode"
              :disabled="sending || !email"
              class="btn-primary w-full flex items-center justify-center gap-2"
            >
              <Loader2 v-if="sending" class="w-4 h-4 animate-spin" />
              <span>{{ sending ? '发送中...' : '发送验证码' }}</span>
            </button>

            <div class="mt-6 text-center">
              <button
                @click="router.push('/login')"
                class="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-brand-purple transition-colors"
              >
                <ArrowLeft class="w-4 h-4" />
                返回登录
              </button>
            </div>
          </template>

          <!-- ==================== 阶段 2：验证验证码 + 设置新密码 ==================== -->
          <template v-else-if="step === 'verify'">
            <div class="flex items-center gap-2 mb-4">
              <button
                @click="goBack"
                class="p-1.5 rounded-lg hover:bg-slate-100 transition-colors"
              >
                <ArrowLeft class="w-4 h-4 text-slate-500" />
              </button>
              <div>
                <h2 class="text-xl font-semibold text-slate-900">重置密码</h2>
                <p class="text-xs text-slate-400">验证码已发送至 {{ email }}</p>
              </div>
            </div>

            <!-- 验证码 -->
            <div class="mb-4">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                验证码
              </label>
              <div class="flex gap-3">
                <div class="relative flex-1">
                  <ShieldCheck class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    v-model="code"
                    type="text"
                    placeholder="请输入 6 位验证码"
                    maxlength="6"
                    class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                    @keyup.enter="handleReset"
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

            <!-- 新密码 -->
            <div class="mb-4">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                新密码
              </label>
              <div class="relative">
                <Lock class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="password"
                  type="password"
                  placeholder="至少 6 位字符"
                  class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                />
              </div>
            </div>

            <!-- 确认密码 -->
            <div class="mb-6">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                确认密码
              </label>
              <div class="relative">
                <Lock class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="confirmPassword"
                  type="password"
                  placeholder="再次输入新密码"
                  class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                  :class="confirmPassword && !passwordMatch ? 'border-red-300 focus:ring-red-200' : ''"
                  @keyup.enter="handleReset"
                />
              </div>
              <p v-if="confirmPassword && !passwordMatch" class="text-xs text-red-500 mt-1">
                两次输入的密码不一致
              </p>
            </div>

            <!-- 错误提示 -->
            <div
              v-if="errorMsg"
              class="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 animate-fade-in"
            >
              {{ errorMsg }}
            </div>

            <button
              @click="handleReset"
              :disabled="submitting"
              class="btn-primary w-full flex items-center justify-center gap-2"
            >
              <Loader2 v-if="submitting" class="w-4 h-4 animate-spin" />
              <span>{{ submitting ? '重置中...' : '重置密码' }}</span>
            </button>
          </template>

          <!-- ==================== 阶段 3：成功反馈 ==================== -->
          <template v-else>
            <div class="text-center py-6">
              <div class="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4">
                <Check class="w-8 h-8 text-green-500" />
              </div>
              <h2 class="text-xl font-semibold text-slate-900 mb-2">密码重置成功</h2>
              <p class="text-sm text-slate-500 mb-8">
                您的新密码已设置成功，请使用新密码登录
              </p>
              <button
                @click="router.push('/login')"
                class="btn-primary w-full flex items-center justify-center gap-2"
              >
                返回登录
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.carousel-enter-active,
.carousel-leave-active {
  transition: all 0.6s ease;
}
.carousel-enter-from {
  opacity: 0;
  transform: scale(1.05);
}
.carousel-leave-to {
  opacity: 0;
  transform: scale(0.95);
}
</style>