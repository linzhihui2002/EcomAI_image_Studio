import { createRouter, createWebHistory } from 'vue-router'
import { watch } from 'vue'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { guest: true },
    },
    {
      path: '/forgot-password',
      name: 'forgot-password',
      component: () => import('@/views/ForgotPasswordView.vue'),
      meta: { guest: true },
    },
    {
      path: '/',
      component: () => import('@/components/layout/AppLayout.vue'),
      children: [
        {
          path: '',
          name: 'home',
          component: () => import('@/views/HomeView.vue'),
        },
        {
          path: 'workspace',
          name: 'workspace',
          component: () => import('@/views/WorkspaceView.vue'),
        },
        {
          path: 'history',
          name: 'history',
          component: () => import('@/views/HistoryView.vue'),
        },
        {
          path: 'favorites',
          name: 'favorites',
          component: () => import('@/views/FavoritesView.vue'),
        },
        {
          path: 'team',
          name: 'team',
          component: () => import('@/views/TeamView.vue'),
        },
        {
          path: 'purchase',
          name: 'purchase',
          component: () => import('@/views/PurchaseView.vue'),
        },
        {
          path: 'admin',
          name: 'admin',
          component: () => import('@/views/AdminView.vue'),
          meta: { admin: true },
        },
        {
          path: 'toolbox',
          redirect: '/toolbox/plan-analysis',
        },
        {
          path: 'toolbox/plan-analysis',
          name: 'toolbox-plan-analysis',
          component: () => import('@/views/toolbox/PlanAnalysisView.vue'),
        },
        {
          path: 'toolbox/image-merge',
          name: 'toolbox-image-merge',
          component: () => import('@/views/toolbox/ImageMergeView.vue'),
        },
        {
          path: 'toolbox/text-to-image',
          name: 'toolbox-text-to-image',
          component: () => import('@/views/toolbox/TextToImageView.vue'),
        },
        {
          path: 'toolbox/chat-gen',
          name: 'toolbox-chat-gen',
          component: () => import('@/views/toolbox/ChatGenView.vue'),
        },
        {
          path: 'toolbox/product-replace',
          name: 'toolbox-product-replace',
          component: () => import('@/views/toolbox/ProductReplaceView.vue'),
        },
        {
          path: 'toolbox/ai-model',
          name: 'toolbox-ai-model',
          component: () => import('@/views/toolbox/AiModelView.vue'),
        },
        {
          path: 'toolbox/model-product',
          name: 'toolbox-model-product',
          component: () => import('@/views/toolbox/ModelProductView.vue'),
        },
        {
          path: 'toolbox/prompt-reverse',
          name: 'toolbox-prompt-reverse',
          component: () => import('@/views/toolbox/PromptReverseView.vue'),
        },
        {
          path: 'editor',
          name: 'editor',
          component: () => import('@/views/editor/EditorView.vue'),
        },
        {
          path: 'profile',
          name: 'profile',
          component: () => import('@/views/ProfileView.vue'),
        },
        {
          path: 'orders',
          name: 'orders',
          component: () => import('@/views/MyOrdersView.vue'),
        },
        {
          path: 'help',
          name: 'help',
          component: () => import('@/views/HelpCenterView.vue'),
        },
      ],
    },
  ],
})

router.beforeEach(async (to, _from, next) => {
  const auth = useAuthStore()

  // 等待认证初始化完成
  if (auth.authLoading) {
    await new Promise<void>((resolve) => {
      const unwatch = watch(
        () => auth.authLoading,
        (val) => {
          if (!val) {
            unwatch()
            resolve()
          }
        },
      )
    })
  }

  const isLoggedIn = auth.isLoggedIn

  if (to.meta.guest && isLoggedIn) {
    next('/')
  } else if (!to.meta.guest && !isLoggedIn && to.name !== 'login') {
    next('/login')
  } else {
    next()
  }
})

export default router