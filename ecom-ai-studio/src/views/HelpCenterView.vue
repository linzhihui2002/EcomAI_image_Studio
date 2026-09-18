<script setup lang="ts">
import { ref } from 'vue'
import { HelpCircle, MessageCircle, ChevronDown, Mail, Phone } from 'lucide-vue-next'

const activeFaq = ref<number | null>(null)

const faqs = [
  {
    id: 1,
    question: '如何使用 AI 生成商品图片？',
    answer: '在工作台中选择「商品图」功能，上传您的商品照片，选择风格和场景后点击生成即可。',
  },
  {
    id: 2,
    question: '灵感币如何使用？',
    answer: '灵感币是平台的虚拟货币，每次生成图片或使用高级功能时会消耗对应的灵感币。您可以在钱包页面进行充值。',
  },
  {
    id: 3,
    question: '生成的图片可以商用吗？',
    answer: '是的，所有由本平台生成的图片版权归您所有，可以用于商业用途。',
  },
  {
    id: 4,
    question: '如何加入或创建团队？',
    answer: '在团队页面可以创建新团队或通过邀请码加入已有团队，团队可以共享灵感币额度。',
  },
  {
    id: 5,
    question: '忘记密码怎么办？',
    answer: '在登录页面点击「忘记密码」，通过邮箱验证后即可重置密码。',
  },
]

function toggleFaq(id: number) {
  activeFaq.value = activeFaq.value === id ? null : id
}
</script>

<template>
  <div class="p-6 max-w-4xl mx-auto">
    <h2 class="text-xl font-semibold text-slate-900 mb-6">帮助中心</h2>

    <!-- 常见问题 -->
    <div class="glass-card p-6 rounded-2xl mb-6">
      <div class="flex items-center gap-3 mb-5">
        <div class="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center">
          <HelpCircle class="w-5 h-5 text-slate-500" />
        </div>
        <h3 class="text-base font-semibold text-slate-900">常见问题</h3>
      </div>

      <div class="space-y-2">
        <div
          v-for="faq in faqs"
          :key="faq.id"
          class="rounded-xl border border-slate-100 overflow-hidden"
        >
          <button
            @click="toggleFaq(faq.id)"
            class="w-full flex items-center justify-between px-4 py-3.5 text-left hover:bg-slate-50 transition-colors"
          >
            <span class="text-sm font-medium text-slate-700">{{ faq.question }}</span>
            <ChevronDown
              :class="[
                'w-4 h-4 text-slate-400 transition-transform duration-200',
                activeFaq === faq.id && 'rotate-180',
              ]"
            />
          </button>
          <Transition name="faq-slide">
            <div
              v-if="activeFaq === faq.id"
              class="px-4 pb-4 text-sm text-slate-500 leading-relaxed"
            >
              {{ faq.answer }}
            </div>
          </Transition>
        </div>
      </div>
    </div>

    <!-- 联系客服 -->
    <div class="glass-card p-6 rounded-2xl">
      <div class="flex items-center gap-3 mb-5">
        <div class="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center">
          <MessageCircle class="w-5 h-5 text-slate-500" />
        </div>
        <h3 class="text-base font-semibold text-slate-900">联系客服</h3>
      </div>

      <p class="text-sm text-slate-500 mb-5">
        如果您的问题未在常见问题中得到解答，请通过以下方式联系我们：
      </p>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="flex items-center gap-3 px-4 py-4 rounded-xl bg-slate-50">
          <div class="w-10 h-10 rounded-lg bg-white flex items-center justify-center shadow-sm">
            <Mail class="w-5 h-5 text-brand-purple" />
          </div>
          <div>
            <p class="text-sm font-medium text-slate-700">邮件支持</p>
            <p class="text-xs text-slate-400">support@example.com</p>
          </div>
        </div>

        <div class="flex items-center gap-3 px-4 py-4 rounded-xl bg-slate-50">
          <div class="w-10 h-10 rounded-lg bg-white flex items-center justify-center shadow-sm">
            <MessageCircle class="w-5 h-5 text-brand-purple" />
          </div>
          <div>
            <p class="text-sm font-medium text-slate-700">在线客服</p>
            <p class="text-xs text-slate-400">工作日 9:00 - 18:00</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.faq-slide-enter-active,
.faq-slide-leave-active {
  transition: all 0.25s ease;
}
.faq-slide-enter-from,
.faq-slide-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.faq-slide-enter-to,
.faq-slide-leave-from {
  opacity: 1;
  max-height: 200px;
}
</style>