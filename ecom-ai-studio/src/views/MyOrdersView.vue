<script setup lang="ts">
import { ref } from 'vue'
import { Package, ShoppingBag } from 'lucide-vue-next'

const activeTab = ref<'all' | 'pending' | 'completed'>('all')
const tabs = [
  { key: 'all' as const, label: '全部' },
  { key: 'pending' as const, label: '待处理' },
  { key: 'completed' as const, label: '已完成' },
]

// TODO: 对接订单列表 API
const orders = ref<any[]>([])
const loading = ref(false)
</script>

<template>
  <div class="p-6 max-w-4xl mx-auto">
    <h2 class="text-xl font-semibold text-slate-900 mb-6">我的订单</h2>

    <!-- 选项卡 -->
    <div class="flex gap-2 mb-6">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="activeTab = tab.key"
        :class="[
          'px-4 py-2 rounded-xl text-sm font-medium transition-all',
          activeTab === tab.key
            ? 'bg-brand-gradient text-white shadow-sm'
            : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50',
        ]"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 订单列表 -->
    <div v-if="loading" class="text-center py-20">
      <svg class="animate-spin w-8 h-8 mx-auto text-brand-purple" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25" />
        <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" class="opacity-75" />
      </svg>
      <p class="mt-3 text-sm text-slate-400">加载中...</p>
    </div>

    <div v-else-if="orders.length === 0" class="glass-card p-12 rounded-2xl">
      <div class="text-center">
        <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
          <ShoppingBag class="w-8 h-8 text-slate-300" />
        </div>
        <p class="text-slate-500 font-medium">暂无订单</p>
        <p class="text-sm text-slate-400 mt-1">您还没有任何订单记录</p>
      </div>
    </div>

    <div v-else class="space-y-4">
      <!-- TODO: 渲染订单列表 -->
      <div
        v-for="order in orders"
        :key="order.id"
        class="glass-card p-5 rounded-2xl"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <Package class="w-5 h-5 text-brand-purple" />
            <span class="font-medium text-slate-900">订单 #{{ order.id }}</span>
          </div>
          <span class="text-sm text-slate-500">{{ order.status }}</span>
        </div>
      </div>
    </div>
  </div>
</template>