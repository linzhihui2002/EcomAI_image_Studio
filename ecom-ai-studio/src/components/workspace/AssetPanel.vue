<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import SmartMode from './SmartMode.vue'
import ProMode from './ProMode.vue'
import CostEstimator from '../common/CostEstimator.vue'
import {
  Upload,
  ImagePlus,
  X,
  Sparkles,
  Wallet,
  Users,
  AlertCircle,
  ArrowRight,
  HelpCircle,
} from 'lucide-vue-next'

const workspace = useWorkspaceStore()
const auth = useAuthStore()

const fileInputRef = ref<HTMLInputElement | null>(null)
const refInputRef = ref<HTMLInputElement | null>(null)
const generateError = ref('')

const productFileInput = ref<HTMLInputElement | null>(null)
const referenceFileInput = ref<HTMLInputElement | null>(null)

const isDragOver = ref(false)
const isRefDragOver = ref(false)

// 参考方向选项（多选）
const refDirections = [
  { value: 'color', label: '色彩' },
  { value: 'composition', label: '构图' },
  { value: 'lighting', label: '光影' },
  { value: 'style', label: '整体风格' },
]
const selectedRefDirs = ref<string[]>(['style'])

function toggleRefDir(val: string) {
  const idx = selectedRefDirs.value.indexOf(val)
  if (idx >= 0) {
    selectedRefDirs.value.splice(idx, 1)
  } else {
    selectedRefDirs.value.push(val)
  }
}

// 用户自定义参考描述
const refDescription = ref('')

// 加载智能模式定价；专业模式定价由 ProMode 内部加载
onMounted(() => {
  workspace.loadPricing('ai_product_image.smart_mode')
})

// 估算展示：依据当前模式选用对应的定价字段
const displaySingleCost = computed(() =>
  workspace.mode === 'pro' ? workspace.proSingleImageCost : workspace.singleImageCost,
)
const displayTotalCount = computed(() =>
  workspace.mode === 'pro' ? workspace.proTaskCount : workspace.totalSmartSlots,
)
const displayTotalCost = computed(() =>
  workspace.mode === 'pro' ? workspace.proEstimatedCost : workspace.estimatedCost,
)

const canGenerate = computed(() => {
  // 定价未配置（estimatedCost === 0）时不阻塞生成，由后端最终判定扣点
  return workspace.productImages.length > 0 && !workspace.isGenerating
})

function triggerProductUpload() {
  productFileInput.value?.click()
}

function triggerReferenceUpload() {
  referenceFileInput.value?.click()
}

function handleProductFiles(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files) return

  const files = Array.from(input.files).slice(0, 10 - workspace.productImages.length)
  files.forEach((file) => {
    if (file.size <= 10 * 1024 * 1024) {
      const url = URL.createObjectURL(file)
      workspace.addProductImages([{ id: `img-${Date.now()}-${Math.random()}`, url, name: file.name }])
    }
  })
  input.value = ''
}

function handleReferenceFile(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  const file = input.files[0]
  if (file.size <= 10 * 1024 * 1024) {
    const url = URL.createObjectURL(file)
    workspace.setReferenceImage({ url, strength: 70 })
  }
  input.value = ''
}

function handleProductDragOver(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = true
}

function handleProductDragLeave() {
  isDragOver.value = false
}

function handleProductDrop(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = false
  if (!e.dataTransfer?.files) return

  const files = Array.from(e.dataTransfer.files).slice(0, 10 - workspace.productImages.length)
  files.forEach((file) => {
    if (file.type.startsWith('image/') && file.size <= 10 * 1024 * 1024) {
      const url = URL.createObjectURL(file)
      workspace.addProductImages([{ id: `img-${Date.now()}-${Math.random()}`, url, name: file.name }])
    }
  })
}

function handleRefDragOver(e: DragEvent) {
  e.preventDefault()
  isRefDragOver.value = true
}

function handleRefDragLeave() {
  isRefDragOver.value = false
}

function handleRefDrop(e: DragEvent) {
  e.preventDefault()
  isRefDragOver.value = false
  if (!e.dataTransfer?.files || e.dataTransfer.files.length === 0) return

  const file = e.dataTransfer.files[0]
  if (file.type.startsWith('image/') && file.size <= 10 * 1024 * 1024) {
    const url = URL.createObjectURL(file)
    workspace.setReferenceImage({ url, strength: 70 })
  }
}

function removeProductImage(id: string) {
  workspace.removeProductImage(id)
}

function clearReferenceImage() {
  workspace.setReferenceImage(null)
}

async function handleGenerate() {
  if (!canGenerate.value) return

  const cost = displayTotalCost.value
  // 估算价 > 0 时才做余额校验；定价未配置（=0）时不阻塞生成
  if (cost > 0 && auth.selectedWalletBalance < cost) {
    const walletName = auth.selectedWallet === 'personal'
      ? '个人'
      : auth.currentTeam?.name || '团队'
    generateError.value = `${walletName}钱包余额不足！当前余额 ${auth.selectedWalletBalance}，需要 ${cost}`
    return
  }

  const success = auth.deductPoints(cost)

  if (!success) {
    const walletName = auth.selectedWallet === 'personal'
      ? '个人'
      : auth.currentTeam?.name || '团队'
    generateError.value = `${walletName}钱包余额不足！当前余额 ${auth.selectedWalletBalance}，需要 ${cost}`
    return
  }

  generateError.value = ''

  await workspace.runGeneration()
}
</script>

<template>
  <div class="w-[340px] flex-shrink-0 bg-white border-r border-slate-200 overflow-y-auto flex flex-col">
    <div class="p-5 space-y-5 flex-1">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-1.5">
          <h2 class="text-base font-semibold text-slate-900">生成配置</h2>
          <div class="group relative">
            <HelpCircle class="w-4 h-4 text-slate-400 cursor-help" />
            <div class="absolute left-0 top-full mt-2 w-[232px] opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-[999]">
              <div class="bg-slate-800 text-white text-[11px] rounded-lg px-3 py-2.5 shadow-xl space-y-2">
                <p class="font-semibold text-white/90 border-b border-white/10 pb-1.5">模式说明</p>
                <div>
                  <p class="font-medium text-brand-purple-300 mb-0.5">简单模式</p>
                  <p class="text-white/70 leading-relaxed">操作极简，无需复杂设置。适合需求尚不明确的场景，AI 一键智能生成高质量商品图。</p>
                </div>
                <div>
                  <p class="font-medium text-cyan-300 mb-0.5">专业模式</p>
                  <p class="text-white/70 leading-relaxed">提供精细化参数调控，支持自定义提示词、光影、构图等。适合已有明确方案或对出图品质有更高要求的进阶用户。</p>
                </div>
              </div>
              <div class="absolute left-2.5 -top-full w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-b-[6px] border-b-slate-800"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="flex rounded-lg p-1 bg-slate-100 border border-slate-200/80">
        <button
          @click="workspace.setMode('smart')"
          :class="[
            'flex-1 py-1.5 px-3 text-xs font-medium rounded-md transition-all duration-200 cursor-pointer',
            workspace.mode === 'smart'
              ? 'bg-white text-brand-purple shadow-sm border border-slate-200/60'
              : 'text-slate-500 hover:text-slate-700',
          ]"
        >
          简单模式
        </button>
        <button
          @click="workspace.setMode('pro')"
          :class="[
            'flex-1 py-1.5 px-3 text-xs font-medium rounded-md transition-all duration-200 cursor-pointer',
            workspace.mode === 'pro'
              ? 'bg-white text-brand-purple shadow-sm border border-slate-200/60'
              : 'text-slate-500 hover:text-slate-700',
          ]"
        >
          专业模式
        </button>
      </div>

      <div v-if="workspace.mode === 'smart'" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-2">
            上传商品图
            <span class="text-xs text-slate-400 ml-1">(最多 10 张)</span>
          </label>
          <div
            @dragover="handleProductDragOver"
            @dragleave="handleProductDragLeave"
            @drop="handleProductDrop"
            :class="[
              'border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-all duration-200',
              isDragOver
                ? 'border-brand-purple bg-brand-gradient-subtle'
                : workspace.productImages.length >= 10
                  ? 'border-slate-200 bg-slate-50 cursor-not-allowed'
                  : 'border-slate-300 hover:border-brand-purple/40 hover:bg-slate-50',
            ]"
            @click="workspace.productImages.length < 10 && triggerProductUpload()"
          >
            <input
              ref="productFileInput"
              type="file"
              accept="image/*"
              multiple
              class="hidden"
              @change="handleProductFiles"
            />
            <Upload class="w-8 h-8 mx-auto mb-2" :class="isDragOver ? 'text-brand-purple' : 'text-slate-300'" />
            <p class="text-sm text-slate-500">
              {{ isDragOver ? '松开以上传' : '点击或拖拽上传商品图' }}
            </p>
            <p class="text-xs text-slate-400 mt-1">支持 JPG / PNG / WebP，单张 ≤10MB</p>
          </div>

          <div v-if="workspace.productImages.length > 0" class="grid grid-cols-3 gap-2 mt-3">
            <div
              v-for="(img, index) in workspace.productImages"
              :key="img.id"
              class="relative group aspect-square rounded-lg overflow-hidden border border-slate-200 bg-slate-100"
            >
              <img :src="img.url" :alt="img.name" class="w-full h-full object-cover" loading="lazy" />
              <div class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100">
                <button
                  @click.stop="removeProductImage(img.id)"
                  class="w-7 h-7 rounded-full bg-red-500 text-white flex items-center justify-center hover:bg-red-600 transition-colors"
                >
                  <X class="w-3.5 h-3.5" />
                </button>
              </div>
              <div class="absolute top-1 left-1 w-5 h-5 rounded-full bg-black/60 text-white text-[10px] font-bold flex items-center justify-center">
                {{ index + 1 }}
              </div>
            </div>
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-slate-700 mb-2">
            参考图（可选）
          </label>
          <div
            v-if="!workspace.referenceImage"
            @dragover="handleRefDragOver"
            @dragleave="handleRefDragLeave"
            @drop="handleRefDrop"
            :class="[
              'border-2 border-dashed rounded-xl p-3 text-center cursor-pointer transition-all duration-200',
              isRefDragOver
                ? 'border-cyan-500 bg-cyan-50'
                : 'border-slate-200 hover:border-cyan-300 hover:bg-slate-50/50',
            ]"
            @click="triggerReferenceUpload()"
          >
            <input
              ref="referenceFileInput"
              type="file"
              accept="image/*"
              class="hidden"
              @change="handleReferenceFile"
            />
            <ImagePlus class="w-6 h-6 mx-auto mb-1 text-slate-300" />
            <p class="text-xs text-slate-500">点击或拖拽上传参考图</p>
          </div>

          <div v-else class="space-y-2">
            <div class="relative rounded-lg overflow-hidden border border-slate-200 bg-slate-100">
              <img :src="workspace.referenceImage.url" alt="参考图" class="w-full max-h-32 object-contain" />
              <button
                @click="clearReferenceImage"
                class="absolute top-1 right-1 w-6 h-6 rounded-full bg-red-500/90 text-white flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity"
              >
                <X class="w-3.5 h-3.5" />
              </button>
            </div>
            <!-- 参考方向（多选） -->
            <div>
              <label class="flex items-center justify-between text-xs text-slate-600 mb-1.5">
                <span>参考方向</span>
                <span class="text-[10px] text-slate-400">可多选</span>
              </label>
              <div class="grid grid-cols-2 gap-1.5">
                <button
                  v-for="dir in refDirections"
                  :key="dir.value"
                  @click="toggleRefDir(dir.value)"
                  :class="[
                    'px-2 py-1.5 rounded-lg text-[11px] font-medium transition-all duration-200 border',
                    selectedRefDirs.includes(dir.value)
                      ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-sm'
                      : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50',
                  ]"
                >
                  {{ dir.label }}
                </button>
              </div>
            </div>
            <!-- 参考描述 -->
            <div>
              <label class="text-xs text-slate-600 mb-1.5 block">参考描述</label>
              <textarea
                v-model="refDescription"
                rows="2"
                placeholder="请描述希望参考的方向，如：保持参考图的配色与光影风格..."
                class="w-full px-2.5 py-2 rounded-lg border border-slate-200 bg-white text-[11px] text-slate-700 leading-relaxed resize-none focus:outline-none focus:ring-1 focus:ring-brand-purple/20 focus:border-brand-purple/50 placeholder:text-slate-300"
              />
            </div>
          </div>
        </div>
      </div>

      <component :is="workspace.mode === 'smart' ? SmartMode : ProMode" />

      <div class="pt-4 border-t border-slate-200 space-y-3">
        <CostEstimator
          :single-cost="displaySingleCost"
          :total-count="displayTotalCount"
          :total-cost="displayTotalCost"
        />

        <div class="rounded-lg border overflow-hidden" :class="
          auth.selectedWallet === 'personal'
            ? 'border-green-200 bg-green-50/50'
            : 'border-brand-purple/20 bg-brand-gradient-subtle/30'
        ">
          <div class="px-3 py-2.5 flex items-center justify-between">
            <div class="flex items-center gap-2">
              <component
                :is="auth.selectedWallet === 'personal' ? Wallet : Users"
                :class="['w-4 h-4', auth.selectedWallet === 'personal' ? 'text-green-600' : 'text-brand-purple']"
              />
              <span class="text-xs font-semibold" :class="auth.selectedWallet === 'personal' ? 'text-green-700' : 'text-brand-purple'">
                支付方式
              </span>
            </div>
            <div class="flex items-center gap-1.5">
              <button
                @click="auth.switchWallet('personal')"
                :class="[
                  'px-2.5 py-1 rounded-md text-[11px] font-medium transition-all duration-200 cursor-pointer',
                  auth.selectedWallet === 'personal'
                    ? 'bg-green-600 text-white shadow-sm'
                    : 'bg-green-100 text-green-600 hover:bg-green-200',
                ]"
              >
                个人 {{ auth.user?.personalPoints.toLocaleString() }}
              </button>
              <button
                v-if="auth.currentTeamId && auth.teamPoolBalance > 0"
                @click="auth.switchWallet('team')"
                :class="[
                  'px-2.5 py-1 rounded-md text-[11px] font-medium transition-all duration-200 cursor-pointer',
                  auth.selectedWallet === 'team'
                    ? 'bg-brand-purple text-white shadow-sm'
                    : 'bg-brand-gradient-subtle text-brand-purple hover:bg-brand-gradient-subtle/70',
                ]"
              >
                团队 {{ auth.teamPoolBalance.toLocaleString() }}
              </button>
            </div>
          </div>
          <div v-if="auth.selectedWallet === 'team'" class="px-3 pb-2.5 pt-0">
            <p class="text-[11px] leading-relaxed" :class="displayTotalCost === 0 || auth.teamPoolBalance >= displayTotalCost ? 'text-blue-600' : 'text-amber-600'">
              <template v-if="displayTotalCost === 0">
                将从「{{ auth.currentTeam?.name }}」团队钱包按实际生成结果扣点
              </template>
              <template v-else-if="auth.teamPoolBalance >= displayTotalCost">
                将从「{{ auth.currentTeam?.name }}」团队钱包扣除 {{ displayTotalCost }} 灵感币
              </template>
              <template v-else>
                ⚠️ 团队钱包余额不足！需要 {{ displayTotalCost }}，仅剩 {{ auth.teamPoolBalance }}
              </template>
            </p>
          </div>
        </div>

        <!-- 生成操作错误提示 -->
        <Transition name="fade">
          <div v-if="generateError" class="flex items-center gap-2 p-2.5 rounded-lg bg-red-50 border border-red-200 text-sm text-red-600">
            <AlertCircle class="w-4 h-4 flex-shrink-0" />
            <span>{{ generateError }}</span>
            <button @click="generateError = ''" class="ml-auto"><X class="w-3.5 h-3.5" /></button>
          </div>
        </Transition>

        <button
          @click="handleGenerate"
          :disabled="!canGenerate || (displayTotalCost > 0 && auth.selectedWalletBalance < displayTotalCost)"
          :class="[
            'w-full py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-200',
            canGenerate && (displayTotalCost === 0 || auth.selectedWalletBalance >= displayTotalCost)
              ? 'btn-primary text-white hover:shadow-glow hover:-translate-y-0.5'
              : 'bg-slate-100 text-slate-400 cursor-not-allowed',
          ]"
        >
          <Sparkles class="w-4 h-4" />
          {{ workspace.isGenerating ? '生成中...' : '开始生成' }}
        </button>

        <div v-if="displayTotalCost > 0 && auth.selectedWalletBalance < displayTotalCost" class="flex items-start gap-2 p-2.5 rounded-lg bg-amber-50 border border-amber-200/60">
          <AlertCircle class="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
          <div class="flex-1 min-w-0">
            <p class="text-xs font-medium text-amber-700">
              {{ auth.selectedWallet === 'personal' ? '个人钱包' : `${auth.currentTeam?.name || '团队'}钱包` }}余额不足
            </p>
            <p class="text-[11px] text-amber-600 mt-0.5">
              当前余额 {{ auth.selectedWalletBalance }} 灵感币，本次需要 {{ displayTotalCost }} 灵感币。
              <router-link
                v-if="auth.selectedWallet === 'personal'"
                to="/purchase"
                class="font-medium underline hover:text-amber-800"
              >
                去充值 →
              </router-link>
              <router-link
                v-else-if="auth.currentTeamId"
                :to="{ path: '/team', query: { action: 'topup' } }"
                class="font-medium underline hover:text-amber-800"
              >
                充值团队钱包 →
              </router-link>
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active { transition: opacity 0.3s ease; }
.fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
