<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard,
  ImagePlus,
  Clock,
  Heart,
  Users,
  Shield,
  Coins,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Sparkles,
  Wrench,
  ClipboardList,
  Layers,
  Type,
  MessageSquare,
  Replace,
  UserCircle,
  ShoppingBag,
  ScanText,
  PenLine,
} from 'lucide-vue-next'
import { PopoverRoot, PopoverTrigger, PopoverPortal, PopoverContent } from 'radix-vue'
import type { Component } from 'vue'

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()
const auth = useAuthStore()

const sidebarWidth = computed(() =>
  appStore.sidebarCollapsed ? 'w-[80px]' : 'w-[240px]',
)

interface NavItem {
  label: string
  icon: Component
  route?: string
  adminOnly?: boolean
  children?: NavItem[]
}

const navItems: NavItem[] = [
  { label: '工作台', icon: LayoutDashboard, route: '/' },
  { label: 'AI商品图', icon: ImagePlus, route: '/workspace' },
  { label: 'AI图片编辑器', icon: PenLine, route: '/editor' },
  {
    label: 'AI工具箱',
    icon: Wrench,
    children: [
      { label: '生图计划分析', icon: ClipboardList, route: '/toolbox/plan-analysis' },
      { label: '图片合并', icon: Layers, route: '/toolbox/image-merge' },
      
      { label: '文生图', icon: Type, route: '/toolbox/text-to-image' },
      { label: '对话式生图', icon: MessageSquare, route: '/toolbox/chat-gen' },
      { label: '产品替换', icon: Replace, route: '/toolbox/product-replace' },
      { label: 'AI模特', icon: UserCircle, route: '/toolbox/ai-model' },
      { label: '模特商品图', icon: ShoppingBag, route: '/toolbox/model-product' },
      { label: '反推提示词', icon: ScanText, route: '/toolbox/prompt-reverse' },
    ],
  },
  { label: '历史记录', icon: Clock, route: '/history' },
  { label: '我的收藏', icon: Heart, route: '/favorites' },
  { label: '充值中心', icon: Coins, route: '/purchase' },
  { label: '团队管理', icon: Users, route: '/team' },
  { label: '管理后台', icon: Shield, route: '/admin', adminOnly: true },
]

const visibleItems = computed(() =>
  navItems.filter((item) => !item.adminOnly || auth.isAdmin),
)

// 已展开的父项 label 集合
const expandedMenus = ref<Set<string>>(new Set())

function isParent(item: NavItem): item is NavItem & { children: NavItem[] } {
  return Array.isArray(item.children) && item.children.length > 0
}

function isChildActive(childRoute: string): boolean {
  return route.path.startsWith(childRoute)
}

function isParentActive(item: NavItem): boolean {
  if (!isParent(item)) return false
  return item.children.some((child) => isChildActive(child.route!))
}

function isExpanded(item: NavItem): boolean {
  return expandedMenus.value.has(item.label)
}

function toggleExpand(item: NavItem) {
  if (!isParent(item)) return
  const next = new Set(expandedMenus.value)
  if (next.has(item.label)) {
    next.delete(item.label)
  } else {
    next.add(item.label)
  }
  expandedMenus.value = next
}

// 监听路由变化，命中子路由时自动展开父项
watch(
  () => route.path,
  () => {
    for (const item of visibleItems.value) {
      if (isParent(item) && isParentActive(item) && !expandedMenus.value.has(item.label)) {
        const next = new Set(expandedMenus.value)
        next.add(item.label)
        expandedMenus.value = next
      }
    }
  },
  { immediate: true },
)

function isActive(routePath: string) {
  if (routePath === '/') return route.path === '/'
  return route.path.startsWith(routePath)
}

function navigate(routePath: string) {
  router.push(routePath)
}

// 路由预加载：hover 侧边栏时提前加载目标页面 chunk
const prefetchedRoutes = new Set<string>()
function prefetchRoute(routePath: string) {
  if (prefetchedRoutes.has(routePath)) return
  prefetchedRoutes.add(routePath)

  const resolved = router.resolve(routePath)
  if (!resolved) return

  // 匹配到的路由记录中的组件是动态 import 函数
  const records = resolved.matched
  for (const record of records) {
    const comp = record.components?.default
    // Vite 动态 import 返回的函数，调用即可触发预加载
    if (typeof comp === 'function') {
      try {
        ;(comp as () => Promise<unknown>)()
      } catch {
        // 预加载失败静默忽略
      }
    }
  }
}
</script>

<template>
  <aside
    :class="cn(
      'flex flex-col border-r border-slate-200 bg-white transition-all duration-300 ease-in-out relative z-10',
      sidebarWidth,
    )"
  >
    <div class="flex items-center h-16 px-4 border-b border-slate-100 gap-3">
      <div
        class="w-9 h-9 rounded-xl bg-brand-gradient flex items-center justify-center flex-shrink-0"
      >
        <Sparkles class="w-5 h-5 text-white" />
      </div>
      <transition name="fade">
        <span
          v-if="!appStore.sidebarCollapsed"
          class="font-display font-bold text-lg gradient-text whitespace-nowrap"
        >
          EcomAI
        </span>
      </transition>
    </div>

    <nav class="flex-1 p-3 space-y-1 overflow-y-auto">
      <template v-for="item in visibleItems" :key="item.label">
        <!-- 父项：含 children 的导航项 -->
        <template v-if="isParent(item)">
          <!-- 折叠态：使用 Popover 浮层显示子菜单 -->
          <PopoverRoot v-if="appStore.sidebarCollapsed">
            <PopoverTrigger as-child>
              <button
                :class="cn(
                  'nav-item w-full justify-center px-2',
                  isParentActive(item) && 'nav-item-active',
                )"
                :title="item.label"
              >
                <component :is="item.icon" class="w-5 h-5 flex-shrink-0" />
              </button>
            </PopoverTrigger>
            <PopoverPortal>
              <PopoverContent
                side="right"
                align="start"
                :side-offset="8"
                class="z-50 ml-2 min-w-[180px] rounded-xl border border-slate-200 bg-white p-2 shadow-lg glass-card"
              >
                <div class="px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                  {{ item.label }}
                </div>
                <button
                  v-for="child in item.children"
                  :key="child.route"
                  @click="navigate(child.route!)"
                  @mouseenter="prefetchRoute(child.route!)"
                  :class="cn(
                    'nav-item w-full',
                    isChildActive(child.route!) && 'nav-item-active',
                  )"
                >
                  <component :is="child.icon" class="w-4 h-4 flex-shrink-0" />
                  <span class="whitespace-nowrap text-sm">{{ child.label }}</span>
                </button>
              </PopoverContent>
            </PopoverPortal>
          </PopoverRoot>

          <!-- 展开态：内联下拉菜单 -->
          <div v-else>
            <button
              @click="toggleExpand(item)"
              :class="cn(
                'nav-item w-full',
                isParentActive(item) && 'nav-item-active',
              )"
            >
              <component :is="item.icon" class="w-5 h-5 flex-shrink-0" />
              <span class="whitespace-nowrap flex-1 text-left">{{ item.label }}</span>
              <ChevronDown
                class="w-4 h-4 flex-shrink-0 text-slate-400 transition-transform duration-300"
                :class="isExpanded(item) ? 'rotate-180' : 'rotate-0'"
              />
            </button>
            <Transition name="dropdown">
              <div v-if="isExpanded(item)" class="mt-1 ml-3 space-y-1 border-l border-slate-200 pl-3">
                <button
                  v-for="child in item.children"
                  :key="child.route"
                  @click="navigate(child.route!)"
                  @mouseenter="prefetchRoute(child.route!)"
                  :class="cn(
                    'nav-item w-full',
                    isChildActive(child.route!) && 'nav-item-active',
                  )"
                >
                  <component :is="child.icon" class="w-4 h-4 flex-shrink-0" />
                  <span class="whitespace-nowrap text-sm">{{ child.label }}</span>
                </button>
              </div>
            </Transition>
          </div>
        </template>

        <!-- 普通叶子项 -->
        <button
          v-else
          @click="navigate(item.route!)"
          @mouseenter="prefetchRoute(item.route!)"
          :class="cn(
            'nav-item w-full',
            isActive(item.route!) && 'nav-item-active',
            appStore.sidebarCollapsed && 'justify-center px-2',
          )"
          :title="appStore.sidebarCollapsed ? item.label : undefined"
        >
          <component :is="item.icon" class="w-5 h-5 flex-shrink-0" />
          <span v-if="!appStore.sidebarCollapsed" class="whitespace-nowrap">
            {{ item.label }}
          </span>
        </button>
      </template>
    </nav>

    <div class="p-3 border-t border-slate-100">
      <button
        @click="appStore.toggleSidebar()"
        class="nav-item w-full justify-center"
        :title="appStore.sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
      >
        <ChevronLeft
          v-if="!appStore.sidebarCollapsed"
          class="w-5 h-5 flex-shrink-0"
        />
        <ChevronRight v-else class="w-5 h-5 flex-shrink-0" />
      </button>
    </div>
  </aside>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 下拉菜单展开/收起动画，时长 ≤ 300ms */
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  max-height: 0;
  transform: translateY(-4px);
}
.dropdown-enter-to,
.dropdown-leave-from {
  opacity: 1;
  max-height: 540px;
}
</style>
