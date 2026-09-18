<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import {
  Upload,
  Download,
  UserCircle,
  Loader2,
  RefreshCw,
  AlertCircle,
  ImageOff,
  Sparkles,
  ChevronDown,
  ArrowLeft,
} from 'lucide-vue-next'
import { generateAiModel } from '@/api/toolbox'
import { getErrorMessage } from '@/lib/error'
import ToolCostBadge from '@/components/common/ToolCostBadge.vue'
import WalletCostPanel from '@/components/common/WalletCostPanel.vue'
import { useAuthStore } from '@/stores/auth'

const FEATURE_KEY = 'toolbox.ai_model'
const auth = useAuthStore()
const walletCostRef = ref<InstanceType<typeof WalletCostPanel> | null>(null)
const insufficientBalance = ref(false)

// ===== 状态 =====
const personImage = ref<string>('')        // 可选人物图 base64 data URL
const personFileName = ref<string>('')
const country = ref<string>('')            // 必填国家
const prompt = ref<string>('')             // 必填提示词
const resultImage = ref<string>('')        // 结果图 base64 data URL
const isProcessing = ref(false)
const errorMsg = ref<string>('')
const isDragOver = ref(false)

const customCountry = ref('')
const countryOpen = ref(false)
const countryTrigger = ref<HTMLElement | null>(null)
const countryPos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })

const countries = [
  '美国', '英国', '德国', '法国', '日本',
  '韩国', '澳大利亚', '加拿大', '巴西', '墨西哥',
  '印度', '印尼', '泰国', '越南', '菲律宾',
  '马来西亚', '新加坡', '沙特阿拉伯', '阿联酋', '土耳其',
  '波兰', '西班牙', '意大利', '荷兰', '俄罗斯',
]

const race = ref<string>('')
const raceOpen = ref(false)
const raceTrigger = ref<HTMLElement | null>(null)
const racePos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })

const raceOptions = [
  '东亚人种', '东南亚人种', '南亚人种', '中东人种',
  '白人/高加索人种', '黑人/非洲人种', '拉丁裔', '北欧人种',
]

// ===== 计算属性 =====
const hasResult = computed(() => !!resultImage.value)

// ===== 工具函数 =====
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function isAcceptedImage(file: File): boolean {
  return ['image/jpeg', 'image/png', 'image/webp'].includes(file.type)
}

async function handleFile(file: File) {
  errorMsg.value = ''
  if (!isAcceptedImage(file)) {
    errorMsg.value = '图片格式不支持，请使用 JPG、PNG 或 WebP 格式'
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    errorMsg.value = '图片大小超出限制，请压缩后重试（最大 20MB）'
    return
  }
  try {
    const base64 = await fileToBase64(file)
    personImage.value = base64
    personFileName.value = file.name
    // 切换人物图后清空旧结果
    resultImage.value = ''
  } catch {
    errorMsg.value = '图片读取失败，请重试'
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    handleFile(input.files[0])
  }
  // 重置 input value 以便重复选择同一文件
  input.value = ''
}

function onDrop(event: DragEvent) {
  isDragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleFile(file)
}

function onDragOver() {
  isDragOver.value = true
}

function onDragLeave() {
  isDragOver.value = false
}

function resetAll() {
  personImage.value = ''
  personFileName.value = ''
  country.value = '美国'
  customCountry.value = ''
  countryOpen.value = false
  race.value = ''
  raceOpen.value = false
  prompt.value = ''
  resultImage.value = ''
  errorMsg.value = ''
}

function clearPersonImage() {
  personImage.value = ''
  personFileName.value = ''
  resultImage.value = ''
}

async function updateCountryPosition() {
  if (!countryTrigger.value) return
  await nextTick()
  const rect = countryTrigger.value.getBoundingClientRect()
  countryPos.value = {
    top: rect.bottom + 4,
    left: rect.left,
    width: rect.width,
  }
}

function toggleCountryDropdown() {
  if (countryOpen.value) {
    countryOpen.value = false
  } else {
    raceOpen.value = false
    updateCountryPosition()
    countryOpen.value = true
  }
}

function selectCountry(c: string) {
  if (c === '其他') {
    country.value = '其他'
    customCountry.value = ''
  } else {
    country.value = c
    customCountry.value = ''
  }
  countryOpen.value = false
}

function backToCountrySelect() {
  country.value = '美国'
  customCountry.value = ''
  countryOpen.value = false
}

async function updateRacePosition() {
  if (!raceTrigger.value) return
  await nextTick()
  const rect = raceTrigger.value.getBoundingClientRect()
  racePos.value = {
    top: rect.bottom + 4,
    left: rect.left,
    width: rect.width,
  }
}

function toggleRaceDropdown() {
  if (raceOpen.value) {
    raceOpen.value = false
  } else {
    countryOpen.value = false
    updateRacePosition()
    raceOpen.value = true
  }
}

function selectRace(r: string) {
  race.value = r
  raceOpen.value = false
}

function onCountryClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (countryTrigger.value && !countryTrigger.value.contains(target)) {
    const dropdown = document.querySelector('[data-country-dropdown]')
    if (dropdown && dropdown.contains(target)) return
    countryOpen.value = false
  }
  if (raceTrigger.value && !raceTrigger.value.contains(target)) {
    const raceDropdown = document.querySelector('[data-race-dropdown]')
    if (raceDropdown && raceDropdown.contains(target)) return
    raceOpen.value = false
  }
}

// 滚动时实时更新打开的下拉框位置，避免错位
function onScroll() {
  if (countryOpen.value) updateCountryPosition()
  if (raceOpen.value) updateRacePosition()
}

onMounted(() => {
  document.addEventListener('click', onCountryClickOutside)
  window.addEventListener('scroll', onScroll, true)  // capture phase 捕获所有滚动
})

onUnmounted(() => {
  document.removeEventListener('click', onCountryClickOutside)
  window.removeEventListener('scroll', onScroll, true)
})

// ===== 业务逻辑 =====
async function startGenerate() {
  if (isProcessing.value) return
  errorMsg.value = ''
  insufficientBalance.value = false
  if (!country.value || (country.value === '其他' && !customCountry.value.trim())) {
    errorMsg.value = '请选择国家'
    return
  }
  if (!race.value) {
    errorMsg.value = '请选择人种'
    return
  }
  if (!prompt.value.trim()) {
    errorMsg.value = '请输入提示词'
    return
  }

  // 余额校验
	const cost = walletCostRef.value?.cost ?? 0
	if (cost > 0 && auth.selectedWalletBalance < cost) {
    errorMsg.value = `灵感币余额不足，预计消耗 ${cost}，当前余额 ${auth.selectedWalletBalance}，请先充值`
    insufficientBalance.value = true
    return
  }

  isProcessing.value = true
  resultImage.value = ''
  try {
    const resolvedCountry = country.value === '其他' ? customCountry.value.trim() : country.value
    const res = await generateAiModel({
      person_image: personImage.value || undefined,
      country: resolvedCountry,
      race: race.value,
      prompt: prompt.value.trim(),
    })
    resultImage.value = res.image

    // 同步本地余额（后端已扣款；失败时忽略，后端为权威源）
    if (cost > 0) {
      try { auth.deductPoints(cost) } catch { /* ignore */ }
    }
  } catch (err) {
    errorMsg.value = getErrorMessage(err, '生成模特失败')
  } finally {
    isProcessing.value = false
  }
}

function downloadResult() {
  if (!resultImage.value) return
  const a = document.createElement('a')
  a.href = resultImage.value
  const baseName = personFileName.value
    ? personFileName.value.replace(/\.[^.]+$/, '')
    : 'ai-model'
  a.download = `${baseName}-model-${Date.now()}.png`
  a.click()
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <!-- 页面标题 -->
    <div>
      <h1 class="text-2xl font-display font-bold text-slate-900 flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <UserCircle class="w-5 h-5 text-white" />
        </div>
        AI模特
        <ToolCostBadge :feature-key="FEATURE_KEY" />
      </h1>
      <p class="text-slate-500 mt-1 text-sm">选择国家、人种并输入提示词，AI 生成专业模特角色卡模板（多角度视图、发型展示、表情排列、服装配色）</p>
    </div>

    <!-- 主容器 -->
    <div class="glass-card p-6 space-y-5">
      <!-- 人物图上传区（选填） -->
      <div class="space-y-2">
        <label class="text-sm font-medium text-slate-700 flex items-center gap-1.5">
          <UserCircle class="w-4 h-4 text-emerald-500" />
          人物图
          <span class="text-[11px] text-slate-400 font-normal">（选填，仅作姿态/风格参考，人种以设置为准）</span>
        </label>

        <!-- 已上传人物图：显示缩略图预览，点击可重新上传 -->
        <div v-if="personImage" class="relative group">
          <label
            for="ai-model-upload"
            class="block cursor-pointer"
            @drop.prevent="onDrop"
            @dragover.prevent="onDragOver"
            @dragleave.prevent="onDragLeave"
          >
            <div
              class="rounded-xl overflow-hidden border border-slate-200 bg-slate-50 p-3 flex items-center justify-center min-h-[200px] transition-all"
              :class="{ 'border-emerald-500 bg-emerald-50': isDragOver }"
            >
              <img
                :src="personImage"
                alt="人物图"
                class="max-h-[220px] w-auto max-w-full object-contain rounded-lg"
              />
            </div>
            <div class="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-all rounded-xl flex items-center justify-center">
              <div class="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-2 text-white text-sm">
                <RefreshCw class="w-4 h-4" />
                点击或拖拽更换图片
              </div>
            </div>
          </label>
          <input
            id="ai-model-upload"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            class="hidden"
            @change="onFileChange"
          />
          <button
            type="button"
            @click="clearPersonImage"
            class="absolute top-2 right-2 w-7 h-7 rounded-full bg-white/90 hover:bg-white shadow-sm flex items-center justify-center text-slate-500 hover:text-red-500 transition-colors"
            title="移除人物图"
          >
            <AlertCircle class="w-4 h-4" />
          </button>
        </div>

        <!-- 空状态：上传区 -->
        <label
          v-else
          for="ai-model-upload"
          class="block cursor-pointer group"
          @drop.prevent="onDrop"
          @dragover.prevent="onDragOver"
          @dragleave.prevent="onDragLeave"
        >
          <div
            :class="[
              'flex flex-col items-center justify-center py-10 px-6 rounded-2xl border-2 border-dashed transition-all duration-200',
              isDragOver
                ? 'border-emerald-500 bg-emerald-50'
                : 'border-emerald-300 bg-gradient-to-br from-emerald-50/50 to-teal-50/50 group-hover:border-emerald-500 group-hover:bg-emerald-50',
            ]"
          >
            <div class="w-14 h-14 rounded-2xl bg-white shadow-sm flex items-center justify-center mb-3">
              <Upload class="w-6 h-6 text-emerald-500" />
            </div>
            <h3 class="text-sm font-semibold text-slate-700 mb-1">点击或拖拽上传人物图</h3>
            <p class="text-xs text-slate-400 text-center max-w-xs">支持 JPG、PNG、WebP 格式，单张最大 20MB</p>
          </div>
          <input
            id="ai-model-upload"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            class="hidden"
            @change="onFileChange"
          />
        </label>
      </div>

      <!-- 国家选择 -->
      <div class="space-y-2">
        <label class="text-sm font-medium text-slate-700 flex items-center gap-1.5">
          <Sparkles class="w-4 h-4 text-emerald-500" />
          国家
          <span class="text-red-500 text-xs">*</span>
        </label>
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            country === '其他'
              ? 'border-emerald-500 ring-2 ring-emerald-200 bg-white'
              : countryOpen ? 'border-emerald-500 ring-2 ring-emerald-200' : 'border-slate-200',
          ]"
        >
          <template v-if="country !== '其他'">
            <button
              ref="countryTrigger"
              @click="toggleCountryDropdown"
              type="button"
              class="w-full flex items-center justify-between px-4 py-2.5 text-sm text-slate-700 cursor-pointer focus:outline-none"
            >
              <span>{{ country }}</span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', countryOpen && 'rotate-180']" />
            </button>
          </template>
          <div v-else class="flex items-center gap-1 pr-1">
            <button
              @click="backToCountrySelect"
              type="button"
              class="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 transition-colors flex-shrink-0"
              title="返回选择"
            >
              <ArrowLeft class="w-3.5 h-3.5" />
            </button>
            <input
              v-model="customCountry"
              placeholder="输入国家名称..."
              class="flex-1 min-w-0 py-2.5 pl-1 pr-2 text-sm text-emerald-600 placeholder:text-slate-300 bg-transparent focus:outline-none"
            />
            <span class="text-[10px] font-medium text-emerald-500/60 flex-shrink-0 pr-2">自定义</span>
          </div>
        </div>
      </div>

      <!-- 人种选择 -->
      <div class="space-y-2">
        <label class="text-sm font-medium text-slate-700 flex items-center gap-1.5">
          <Sparkles class="w-4 h-4 text-emerald-500" />
          人种
          <span class="text-red-500 text-xs">*</span>
        </label>
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            raceOpen ? 'border-emerald-500 ring-2 ring-emerald-200' : 'border-slate-200',
          ]"
        >
          <button
            ref="raceTrigger"
            @click="toggleRaceDropdown"
            type="button"
            class="w-full flex items-center justify-between px-4 py-2.5 text-sm text-slate-700 cursor-pointer focus:outline-none"
          >
            <span :class="race ? 'text-slate-700' : 'text-slate-400'">{{ race || '请选择人种' }}</span>
            <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', raceOpen && 'rotate-180']" />
          </button>
        </div>
      </div>

      <!-- 提示词输入 -->
      <div class="space-y-2">
        <label for="ai-model-prompt" class="text-sm font-medium text-slate-700 flex items-center gap-1.5">
          <Sparkles class="w-4 h-4 text-emerald-500" />
          提示词
          <span class="text-red-500 text-xs">*</span>
        </label>
        <textarea
          id="ai-model-prompt"
          v-model="prompt"
          rows="5"
          placeholder="描述模特特征，如：年轻女性，长发，职业装，自然妆容"
          class="w-full px-4 py-3 text-sm rounded-xl border border-slate-200 bg-white text-slate-700 placeholder:text-slate-400 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-200 outline-none transition resize-y"
        />
        <p class="text-[11px] text-slate-400">详细描述模特的外貌、服饰、风格等特征，可获得更精准的结果</p>
      </div>

      <!-- 钱包选择与消耗展示 -->
      <WalletCostPanel
        ref="walletCostRef"
        :feature-key="FEATURE_KEY"
      />

      <!-- 操作按钮组 -->
      <div class="flex flex-wrap gap-3">
        <button
          @click="startGenerate"
          :disabled="isProcessing"
          class="btn-primary flex items-center justify-center gap-2"
        >
          <Loader2 v-if="isProcessing" class="w-4 h-4 animate-spin" />
          <Sparkles v-else class="w-4 h-4" />
          {{ isProcessing ? '生成中...' : (hasResult ? '重新生成' : '生成模特') }}
        </button>
        <button
          v-if="hasResult"
          @click="downloadResult"
          class="btn-secondary flex items-center gap-2"
        >
          <Download class="w-4 h-4" />
          下载结果
        </button>
        <button
          @click="resetAll"
          class="btn-secondary flex items-center gap-2"
        >
          <RefreshCw class="w-4 h-4" />
          重置
        </button>
      </div>

      <!-- 处理中状态 -->
      <div v-if="isProcessing" class="flex flex-col items-center justify-center py-12">
        <div class="relative w-24 h-24 mb-6">
          <svg class="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="42" fill="none" stroke="#E5E7EB" stroke-width="8" />
            <circle
              cx="50" cy="50" r="42" fill="none" stroke="url(#aiModelGradient)"
              stroke-width="8" stroke-linecap="round"
              stroke-dasharray="180 264"
              class="animate-spin"
              style="transform-origin: center; animation-duration: 1.5s;"
            />
            <defs>
              <linearGradient id="aiModelGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#10B981" />
                <stop offset="100%" stop-color="#06B6D4" />
              </linearGradient>
            </defs>
          </svg>
          <div class="absolute inset-0 flex items-center justify-center">
            <Loader2 class="w-8 h-8 text-emerald-500 animate-spin" />
          </div>
        </div>
        <h3 class="text-lg font-semibold text-slate-700 mb-2">正在生成模特...</h3>
        <p class="text-sm text-slate-400">AI 正在根据您的描述生成专业模特角色卡模板，请稍候</p>
      </div>

      <!-- 结果展示区 -->
      <div v-if="hasResult && !isProcessing" class="space-y-2">
        <div class="flex items-center gap-2 text-sm font-medium text-emerald-600">
          <ImageOff class="w-4 h-4" />
          生成结果
          <span class="text-[10px] text-emerald-500 bg-emerald-50 px-1.5 py-0.5 rounded">角色卡</span>
        </div>
        <div
          class="rounded-xl overflow-hidden bg-slate-50 border border-slate-200 min-h-[280px] flex items-center justify-center p-3"
        >
          <img
            :src="resultImage"
            alt="AI模特结果"
            class="max-h-[480px] w-auto max-w-full object-contain rounded-lg shadow-lg"
          />
        </div>
      </div>

      <!-- 错误提示（内联） -->
      <div
        v-if="errorMsg"
        class="flex items-start gap-2 p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm"
      >
        <AlertCircle class="w-4 h-4 flex-shrink-0 mt-0.5" />
        <div class="flex-1">
          <span>{{ errorMsg }}</span>
          <router-link
            v-if="insufficientBalance"
            to="/purchase"
            class="inline-flex items-center gap-1 ml-2 text-emerald-600 hover:text-emerald-700 font-medium underline"
          >
            去充值
          </router-link>
        </div>
      </div>
    </div>

    <!-- 国家下拉面板 -->
    <Teleport to="body">
      <Transition name="dropdown">
        <div
          v-if="countryOpen"
          data-country-dropdown
          :style="{ position: 'fixed', top: countryPos.top + 'px', left: countryPos.left + 'px', width: countryPos.width + 'px' }"
          class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]"
        >
          <div class="max-h-[10rem] overflow-y-auto">
            <button
              v-for="c in countries"
              :key="c"
              @click="selectCountry(c)"
              type="button"
              :class="['w-full text-left px-4 py-2 text-sm transition-colors hover:bg-slate-50', country === c && 'bg-emerald-50 text-emerald-600 font-medium']"
            >{{ c }}</button>
            <div class="border-t border-slate-100" />
            <button
              @click="selectCountry('其他')"
              type="button"
              class="w-full text-left px-4 py-2 text-sm text-emerald-600 hover:bg-emerald-50 transition-colors flex items-center gap-1.5"
            >✏️ 自定义...</button>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 人种下拉面板 -->
    <Teleport to="body">
      <Transition name="dropdown">
        <div
          v-if="raceOpen"
          data-race-dropdown
          :style="{ position: 'fixed', top: racePos.top + 'px', left: racePos.left + 'px', width: racePos.width + 'px' }"
          class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]"
        >
          <div class="max-h-[10rem] overflow-y-auto">
            <button
              v-for="r in raceOptions"
              :key="r"
              @click="selectRace(r)"
              type="button"
              :class="['w-full text-left px-4 py-2 text-sm transition-colors hover:bg-slate-50', race === r && 'bg-emerald-50 text-emerald-600 font-medium']"
            >{{ r }}</button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
</style>
