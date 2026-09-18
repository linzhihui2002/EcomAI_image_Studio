import { createApp, type Directive } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/lib/error'
import './style.css'

declare global {
  interface HTMLElement {
    _clickOutsideHandler?: (event: MouseEvent) => void
  }
}

const clickOutsideDirective: Directive = {
  mounted(el: HTMLElement, binding) {
    el._clickOutsideHandler = (event: MouseEvent) => {
      if (!(el === event.target || el.contains(event.target as Node))) {
        binding.value(event)
      }
    }
    document.addEventListener('click', el._clickOutsideHandler)
  },
  unmounted(el: HTMLElement) {
    document.removeEventListener('click', el._clickOutsideHandler!)
  },
}

const app = createApp(App)
app.directive('click-outside', clickOutsideDirective)

// 全局 Vue 错误处理器：捕获组件渲染、生命周期、watch 等未处理的异常
app.config.errorHandler = (err, instance, info) => {
  const msg = getErrorMessage(err)
  // 开发环境输出详细错误信息，生产环境仅提示用户友好消息
  console.error('[全局错误]', err, info)
  // 避免在认证错误时重复提示（由路由守卫处理）
  if (msg.includes('登录') || msg.includes('认证')) return
  // 非静默错误时通知用户
  if (instance?.$parent) {
    // 可扩展为调用 toast 组件统一展示
    console.warn('[用户提示]', msg)
  }
}

// 全局未处理的 Promise rejection 处理
window.addEventListener('unhandledrejection', (event) => {
  const msg = getErrorMessage(event.reason)
  console.error('[未处理的 Promise 错误]', event.reason)
  // 阻止默认的浏览器控制台错误输出（已由上面处理）
  // event.preventDefault() // 如需完全静默可取消注释
})

const pinia = createPinia()
app.use(pinia)
app.use(router)

// 初始化认证状态（恢复会话），完成后再挂载应用
const auth = useAuthStore()
auth.initAuth().finally(() => {
  app.mount('#app')
})