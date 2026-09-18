<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { Sparkles, Mail, Lock, ArrowRight, Loader2, UserPlus } from 'lucide-vue-next'
import { getErrorMessage, ERROR_DEFAULTS } from '@/lib/error'

const auth = useAuthStore()
const router = useRouter()

// 主 Tab：登录 / 注册
const activeTab = ref<'login' | 'register'>('login')
// 登录子模式：密码登录 / 验证码登录
const loginMode = ref<'password' | 'code'>('password')

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

// 轮播
const carouselImages = [
  {
    before: 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&h=700&fit=crop',
    after: 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&h=700&fit=crop',
  },
  {
    before: 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&h=700&fit=crop',
    after: 'https://images.unsplash.com/photo-1606107557195-0e29a4b5b4aa?w=600&h=700&fit=crop',
  },
]

const currentSlide = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
let countdownTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => {
    currentSlide.value = (currentSlide.value + 1) % carouselImages.length
  }, 4000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (countdownTimer) clearInterval(countdownTimer)
})

// 发送验证码（真实 API 调用）
async function sendCode() {
  if (countdown.value > 0 || !email.value) return
  if (!email.value.includes('@')) {
    errorMsg.value = '请输入正确的邮箱地址'
    return
  }
  errorMsg.value = ''
  sending.value = true

  try {
    const purpose = activeTab.value === 'register' ? 'register' : 'login'
    const res = await fetch('/api/v1/auth/send-code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.value, purpose }),
    })
    if (!res.headers.get('content-type')?.includes('application/json')) {
      throw new Error('验证码服务暂时不可用，请稍后重试')
    }
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
    } else {
      errorMsg.value = getErrorMessage(
        { code: data.code, message: data.message },
        ERROR_DEFAULTS.SEND_CODE_FAILED,
      )
    }
  } catch (err: any) {
    errorMsg.value = getErrorMessage(err, ERROR_DEFAULTS.SEND_CODE_FAILED)
  } finally {
    sending.value = false
  }
}

// 邮箱域名补全
const emailDomains = ['@gmail.com', '@outlook.com', '@qq.com', '@163.com']
const showSuggestions = ref(false)
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

// 切换主 Tab 时清空表单和错误
function switchTab(tab: 'login' | 'register') {
  activeTab.value = tab
  errorMsg.value = ''
  code.value = ''
  password.value = ''
  confirmPassword.value = ''
}

// 登录处理
async function handleLogin() {
  errorMsg.value = ''
  if (!email.value) {
    errorMsg.value = '请输入邮箱地址'
    return
  }
  if (!email.value.includes('@')) {
    errorMsg.value = '请输入正确的邮箱地址'
    return
  }
  if (loginMode.value === 'code' && !code.value) {
    errorMsg.value = '请输入验证码'
    return
  }
  if (loginMode.value === 'password' && !password.value) {
    errorMsg.value = '请输入密码'
    return
  }

  submitting.value = true

  try {
    await auth.login(
      email.value,
      loginMode.value === 'code' ? code.value : password.value,
      loginMode.value === 'code',
    )
    router.push('/')
  } catch (err: any) {
    errorMsg.value = getErrorMessage(err, ERROR_DEFAULTS.LOGIN_FAILED)
  } finally {
    submitting.value = false
  }
}

// 注册处理
async function handleRegister() {
  errorMsg.value = ''

  if (!email.value) {
    errorMsg.value = '请输入邮箱地址'
    return
  }
  if (!email.value.includes('@')) {
    errorMsg.value = '请输入正确的邮箱地址'
    return
  }
  if (!code.value) {
    errorMsg.value = '请输入验证码'
    return
  }
  if (code.value.length !== 6) {
    errorMsg.value = '验证码为 6 位数字'
    return
  }
  if (!password.value) {
    errorMsg.value = '请设置密码'
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
    await auth.register(email.value, password.value, code.value)
    router.push('/')
  } catch (err: any) {
    errorMsg.value = getErrorMessage(err, ERROR_DEFAULTS.REGISTER_FAILED)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="flex h-screen bg-white overflow-hidden">
    <!-- 左侧轮播区域 60% -->
    <div class="hidden lg:flex lg:w-[60%] relative bg-slate-900 overflow-hidden">
      <!-- 渐变背景 -->
      <div class="absolute inset-0 bg-brand-gradient opacity-90" />
      <div class="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(255,255,255,0.15),transparent_50%)]" />

      <!-- 装饰元素 -->
      <div class="absolute top-20 left-20 w-64 h-64 rounded-full bg-white/5 blur-3xl animate-float" />
      <div class="absolute bottom-20 right-20 w-96 h-96 rounded-full bg-brand-cyan/20 blur-3xl animate-float" style="animation-delay: 2s;" />

      <!-- 内容 -->
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

        <!-- 轮播 -->
        <div class="relative w-full max-w-lg aspect-[4/5] rounded-2xl overflow-hidden shadow-2xl">
          <transition-group name="carousel">
            <div
              v-for="(img, idx) in carouselImages"
              :key="idx"
              v-show="currentSlide === idx"
              class="absolute inset-0"
            >
              <div class="relative w-full h-full">
                <div class="absolute inset-[15%] z-10 rounded-xl overflow-hidden shadow-lg">
                  <img :src="img.after" class="w-full h-full object-cover" />
                  <div class="absolute top-2 left-2 px-2 py-0.5 bg-brand-gradient rounded-md text-xs text-white font-medium">
                    AI 生成
                  </div>
                </div>
                <div class="absolute top-4 right-4 w-[45%] aspect-square rounded-xl overflow-hidden shadow-md opacity-60 rotate-6 z-0">
                  <img :src="img.before" class="w-full h-full object-cover" />
                  <div class="absolute top-1 left-1 px-1.5 py-0.5 bg-slate-800/80 rounded text-[10px] text-white">
                    原图
                  </div>
                </div>
              </div>
            </div>
          </transition-group>

          <!-- 轮播指示器 -->
          <div class="absolute bottom-6 left-1/2 -translate-x-1/2 flex gap-2 z-20">
            <button
              v-for="(_, idx) in carouselImages"
              :key="idx"
              @click="currentSlide = idx"
              :class="[
                'w-2 h-2 rounded-full transition-all duration-300',
                currentSlide === idx ? 'bg-white w-6' : 'bg-white/40',
              ]"
            />
          </div>
        </div>

        <!-- 底部数据 -->
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
          <!-- ========== 主 Tab 切换：登录 / 注册 ========== -->
          <div class="flex bg-slate-100 rounded-xl p-1 mb-6">
            <button
              @click="switchTab('login')"
              :class="[
                'flex-1 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 flex items-center justify-center gap-1.5',
                activeTab === 'login'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700',
              ]"
            >
              登录
            </button>
            <button
              @click="switchTab('register')"
              :class="[
                'flex-1 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 flex items-center justify-center gap-1.5',
                activeTab === 'register'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700',
              ]"
            >
              <UserPlus class="w-4 h-4" />
              注册
            </button>
          </div>

          <!-- ==================== 登录 Tab ==================== -->
          <template v-if="activeTab === 'login'">
            <h2 class="text-xl font-semibold text-slate-900 mb-1">欢迎回来</h2>
            <p class="text-sm text-slate-500 mb-6">登录您的 EcomAI 账户</p>

            <!-- 登录方式子切换：密码 / 验证码 -->
            <div class="flex bg-slate-50 rounded-lg p-0.5 mb-5">
              <button
                @click="loginMode = 'password'"
                :class="[
                  'flex-1 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
                  loginMode === 'password'
                    ? 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-400 hover:text-slate-600',
                ]"
              >
                密码登录
              </button>
              <button
                @click="loginMode = 'code'"
                :class="[
                  'flex-1 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
                  loginMode === 'code'
                    ? 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-400 hover:text-slate-600',
                ]"
              >
                验证码登录
              </button>
            </div>

            <!-- 邮箱输入 -->
            <div class="relative mb-4">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                邮箱地址
              </label>
              <div class="relative">
                <Mail class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="email"
                  type="email"
                  placeholder="请输入邮箱地址"
                  class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                  @focus="showSuggestions = true"
                  @blur="showSuggestions = false"
                  @keyup.enter="handleLogin"
                />
              </div>
              <!-- 邮箱域名补全 -->
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

            <!-- 密码登录 → 密码输入 -->
            <div v-if="loginMode === 'password'" class="mb-1">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                密码
              </label>
              <div class="relative">
                <Lock class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="password"
                  type="password"
                  placeholder="请输入密码"
                  class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                  @keyup.enter="handleLogin"
                />
              </div>
            </div>

            <!-- 忘记密码 -->
            <div v-if="loginMode === 'password'" class="flex justify-end mb-4">
              <router-link to="/forgot-password" class="text-xs text-brand-purple hover:underline">
                忘记密码？
              </router-link>
            </div>

            <!-- 验证码登录 → 验证码输入 -->
            <div v-else class="mb-6">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                验证码
              </label>
              <div class="flex gap-3">
                <div class="relative flex-1">
                  <Lock class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    v-model="code"
                    type="text"
                    placeholder="请输入验证码"
                    maxlength="6"
                    class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                    @keyup.enter="handleLogin"
                  />
                </div>
                <button
                  @click="sendCode"
                  :disabled="countdown > 0 || sending || !email"
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
                  <span v-else>发送验证码</span>
                </button>
              </div>
            </div>

            <!-- 错误提示 -->
            <div
              v-if="errorMsg"
              class="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 animate-fade-in"
            >
              {{ errorMsg }}
            </div>

            <!-- 登录按钮 -->
            <button
              @click="handleLogin"
              :disabled="submitting"
              class="btn-primary w-full flex items-center justify-center gap-2"
            >
              <Loader2 v-if="submitting" class="w-4 h-4 animate-spin" />
              <span>{{ submitting ? '登录中...' : '登 录' }}</span>
              <ArrowRight v-if="!submitting" class="w-4 h-4" />
            </button>
          </template>

          <!-- ==================== 注册 Tab ==================== -->
          <template v-else>
            <h2 class="text-xl font-semibold text-slate-900 mb-1">创建新账户</h2>
            <p class="text-sm text-slate-500 mb-6">注册即送 100 灵感币，开启 AI 生图之旅</p>

            <!-- 邮箱输入 -->
            <div class="relative mb-4">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                邮箱地址 <span class="text-red-400">*</span>
              </label>
              <div class="relative">
                <Mail class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="email"
                  type="email"
                  placeholder="请输入邮箱地址"
                  class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                  @focus="showSuggestions = true"
                  @blur="showSuggestions = false"
                />
              </div>
              <!-- 邮箱域名补全 -->
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

            <!-- 验证码（注册必填） -->
            <div class="mb-4">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                邮箱验证码 <span class="text-red-400">*</span>
              </label>
              <div class="flex gap-3">
                <div class="relative flex-1">
                  <Lock class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    v-model="code"
                    type="text"
                    placeholder="请输入 6 位验证码"
                    maxlength="6"
                    class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                  />
                </div>
                <button
                  @click="sendCode"
                  :disabled="countdown > 0 || sending || !email"
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
                  <span v-else-if="countdown > 0">{{ countdown }}s 后重发</span>
                  <span v-else>发送验证码</span>
                </button>
              </div>
            </div>

            <!-- 设置密码 -->
            <div class="mb-4">
              <label class="block text-sm font-medium text-slate-700 mb-1.5">
                设置密码 <span class="text-red-400">*</span>
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
                确认密码 <span class="text-red-400">*</span>
              </label>
              <div class="relative">
                <Lock class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  v-model="confirmPassword"
                  type="password"
                  placeholder="再次输入密码"
                  class="glass-input w-full pl-10 pr-4 py-2.5 text-sm"
                  @keyup.enter="handleRegister"
                />
              </div>
            </div>

            <!-- 错误提示 -->
            <div
              v-if="errorMsg"
              class="mb-4 p-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-600 animate-fade-in"
            >
              {{ errorMsg }}
            </div>

            <!-- 注册按钮 -->
            <button
              @click="handleRegister"
              :disabled="submitting"
              class="btn-primary w-full flex items-center justify-center gap-2"
            >
              <Loader2 v-if="submitting" class="w-4 h-4 animate-spin" />
              <UserPlus v-if="!submitting" class="w-4 h-4" />
              <span>{{ submitting ? '注册中...' : '注 册' }}</span>
            </button>
          </template>

          <!-- 底部协议提示 -->
          <p class="text-xs text-slate-400 text-center mt-6">
            {{ activeTab === 'login' ? '登录' : '注册' }}即表示同意
            <a href="#" class="text-brand-purple hover:underline">服务条款</a>
            和
            <a href="#" class="text-brand-purple hover:underline">隐私政策</a>
          </p>
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
