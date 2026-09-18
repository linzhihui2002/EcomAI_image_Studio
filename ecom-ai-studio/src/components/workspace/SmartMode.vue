<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { ChevronDown, Sparkles, Plus, Minus, ArrowLeft, AlertCircle, Globe, ShieldCheck, Languages } from 'lucide-vue-next'
import { resolveSizeFromRatioAndResolution, parseCustomSize, type SizeResult } from '@/lib/utils'
import { getErrorMessage } from '@/lib/error'
import { analyzeProduct } from '@/api/generation'
import { getTemplateOptions, type TemplateSite } from '@/api/template'
import { getComplianceRules, toCompliancePlatform, type ComplianceRules } from '@/api/compliance'

const workspace = useWorkspaceStore()

// ===== 站点/语言选择器（模板引擎选项，挂载时拉取） =====

/** 接口失败时的内置降级站点列表（不阻塞页面） */
const DEFAULT_SITES: TemplateSite[] = [
  { code: 'us', name: '美国站 (US)', language: 'English', isRtl: false },
  { code: 'uk', name: '英国站 (UK)', language: 'English', isRtl: false },
  { code: 'de', name: '德国站 (DE)', language: 'Deutsch', isRtl: false },
  { code: 'fr', name: '法国站 (FR)', language: 'Français', isRtl: false },
  { code: 'jp', name: '日本站 (JP)', language: '日本語', isRtl: false },
  { code: 'ae', name: '中东站 (AE)', language: 'العربية', isRtl: true },
  { code: 'sa', name: '沙特站 (SA)', language: 'العربية', isRtl: true },
]

const siteOptions = ref<TemplateSite[]>(DEFAULT_SITES)
const selectedSiteCode = ref('')
const siteOpen = ref(false)
const siteTrigger = ref<HTMLElement | null>(null)
const sitePos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })

const selectedSite = computed(() =>
  siteOptions.value.find((s) => s.code === selectedSiteCode.value) || null,
)

// ===== 平台合规规则（改绑平台选择器，遗留修正） =====
// 后端 /compliance/rules 的 platform 是电商平台键（amazon/temu/shopee/tiktok_shop/aliexpress/ozon），
// 站点选择器（site 码，如 amazon_us）仅承担语言/市场语义，不再作为规则查询入参。
const complianceRules = ref<ComplianceRules | null>(null)
const complianceLoading = ref(false)

async function fetchComplianceRules(platform: string) {
  complianceLoading.value = true
  try {
    complianceRules.value = await getComplianceRules(platform)
  } catch (err) {
    console.warn('[SmartMode] 合规规则加载失败:', err)
    complianceRules.value = null
  } finally {
    complianceLoading.value = false
  }
}

/** 合规摘要提示（如 "Amazon 平台合规 · 主图：纯白底、产品占比≥85%、无文字；禁用词：..."） */
const complianceSummary = computed(() => {
  if (!complianceRules.value) return ''
  const rules = complianceRules.value
  const platformName = selectedPlatformDisplayName.value || rules.platform
  const parts: string[] = []
  const main = rules.imageTypes?.main_image
  if (main) {
    const bits: string[] = []
    if (main.background) bits.push(main.background)
    if (typeof main.productRatioMin === 'number' && main.productRatioMin > 0) {
      // 兼容 0-1 小数与百分数两种契约表示
      const ratio = main.productRatioMin <= 1 ? main.productRatioMin * 100 : main.productRatioMin
      bits.push(`产品占比≥${Math.round(ratio)}%`)
    }
    if (main.maxTextLen === 0) bits.push('无文字')
    else if (typeof main.maxTextLen === 'number' && main.maxTextLen > 0) bits.push(`文字≤${main.maxTextLen}字符`)
    if (bits.length) parts.push(`主图：${bits.join('、')}`)
  }
  if (rules.globalForbidden?.length) {
    const terms = rules.globalForbidden.slice(0, 3).map((f) => f.term).join('、')
    const suffix = rules.globalForbidden.length > 3 ? ` 等 ${rules.globalForbidden.length} 项` : ''
    parts.push(`禁用词：${terms}${suffix}`)
  }
  return parts.length ? `${platformName} 平台合规 · ${parts.join('；')}` : ''
})

// 挂载时加载智能模式定价与模板引擎选项；setSmartModeConfig 在尺寸变化时会触发 recomputeCost
onMounted(async () => {
  workspace.loadPricing('ai_product_image.smart_mode')
  try {
    const options = await getTemplateOptions()
    if (options?.sites?.length) {
      siteOptions.value = options.sites
      // 已选站点不在新列表中时回退为未选择
      if (selectedSiteCode.value && !options.sites.some((s) => s.code === selectedSiteCode.value)) {
        selectedSiteCode.value = ''
      }
    }
  } catch (err) {
    console.warn('[SmartMode] 模板选项加载失败，已降级为默认站点列表:', err)
  }
})

const platforms = [
  'Amazon', 'AliExpress', 'Shopee', 'Lazada', 'TikTok Shop',
  'Temu', 'Shein', 'Walmart', 'eBay', 'Etsy',
  'Rakuten', 'Mercado Libre', 'Jumia', 'Daraz', 'Ozon',
  '独立站',
]

const regions = [
  '美国', '英国', '德国', '法国', '日本',
  '韩国', '澳大利亚', '加拿大', '巴西', '墨西哥',
  '印度', '印尼', '泰国', '越南', '菲律宾',
  '马来西亚', '新加坡', '沙特阿拉伯', '阿联酋', '土耳其',
  '波兰', '西班牙', '意大利', '荷兰', '俄罗斯',
]

const languages = [
  '英语', '中文', '日语', '韩语',
  '德语', '法语', '西班牙语', '意大利语',
  '葡萄牙语', '荷兰语', '波兰语', '俄语',
  '泰语', '越南语', '印尼语',
  '阿拉伯语', '土耳其语', '印地语', '马来语', '日语(简)',
]

const ratios = ['1:1', '3:4', '4:3', '16:9']

const selectedPlatform = ref('Amazon')
const selectedRegion = ref('美国')
const selectedLanguage = ref('英语')
const selectedRatio = ref('1:1')

const customPlatform = ref('')
const customRegion = ref('')
const customLanguage = ref('')
const customRatio = ref('')

// ===== 合规规则绑定平台（遗留修正） =====
/** 平台展示名（含自定义输入），合规规则与批量任务提交均以此为映射源 */
const selectedPlatformDisplayName = computed(() =>
  selectedPlatform.value === '其他' ? customPlatform.value.trim() : selectedPlatform.value,
)

/** 平台展示名 → 后端合规规则键（amazon/temu/...），映射外的平台无规则可查 */
const compliancePlatformKey = computed(() => toCompliancePlatform(selectedPlatformDisplayName.value))

// 平台变化即拉取对应平台合规规则（immediate：默认 Amazon 挂载即加载）
watch(compliancePlatformKey, (key) => {
  complianceRules.value = null
  if (!key) return
  fetchComplianceRules(key)
}, { immediate: true })

const platformOpen = ref(false)
const regionOpen = ref(false)
const languageOpen = ref(false)
const ratioOpen = ref('')

const platformTrigger = ref<HTMLElement | null>(null)
const regionTrigger = ref<HTMLElement | null>(null)
const languageTrigger = ref<HTMLElement | null>(null)
const ratioTrigger = ref<HTMLElement | null>(null)

const platformPos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })
const regionPos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })
const languagePos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })
const ratioPos = ref<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })

async function updatePosition(trigger: HTMLElement | null, pos: typeof platformPos) {
  if (!trigger) return
  await nextTick()
  const rect = trigger.getBoundingClientRect()
  pos.value = {
    top: rect.bottom + window.scrollY + 4,
    left: rect.left + window.scrollX,
    width: rect.width,
  }
}

async function openDropdown(which: string) {
  platformOpen.value = false
  regionOpen.value = false
  languageOpen.value = false
  ratioOpen.value = ''
  siteOpen.value = false
  if (which === 'site') {
    siteOpen.value = true
    await updatePosition(siteTrigger.value, sitePos)
  }
  if (which === 'platform') {
    platformOpen.value = true
    await updatePosition(platformTrigger.value, platformPos)
  }
  if (which === 'region') {
    regionOpen.value = true
    await updatePosition(regionTrigger.value, regionPos)
  }
  if (which === 'language') {
    languageOpen.value = true
    await updatePosition(languageTrigger.value, languagePos)
  }
  if (which === 'ratio') {
    ratioOpen.value = 'r'
    await updatePosition(ratioTrigger.value, ratioPos)
  }
}
const selectedResolution = ref('1024x1024')
const customResolution = ref('')
const customWidth = ref('')
const customHeight = ref('')

const resolutions = [
  { value: '1024x1024', label: '1K' },
  { value: '2048x2048', label: '2K' },
  { value: '3840x2160', label: '4K' },
  { value: 'custom', label: '自定义' },
]

const productDesc = ref('')
const referenceText = ref('')
const isAiWriting = ref(false)
const aiHelpError = ref('')

// ===== 英文卖点编辑区（AI 商品分析返回 sellingPointsEn 后自动填充） =====

interface EnSellingPointItem {
  titleEn: string
  descEn: string
  /** 视觉关键词输入原文（逗号分隔） */
  keywordsText: string
  /** 失焦校验：是否含中文/全角字符 */
  keywordInvalid: boolean
}

const enSellingPoints = ref<EnSellingPointItem[]>([])

/** 中文汉字 / 中文标点 / 全角字符（含全角字母数字与全角空格） */
const CJK_OR_FULLWIDTH_RE = /[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]/

/** 失焦校验：视觉关键词仅支持英文 */
function validateEnKeywords(item: EnSellingPointItem) {
  item.keywordInvalid = CJK_OR_FULLWIDTH_RE.test(item.keywordsText)
}

/** 逗号（半角/全角）分隔解析视觉关键词 */
function parseEnKeywords(text: string): string[] {
  return text.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
}

function hasEnPointContent(item: EnSellingPointItem): boolean {
  return !!(item.titleEn.trim() || item.descEn.trim() || item.keywordsText.trim())
}

/** 英文卖点是否全部通过校验（无英文卖点视为通过，向后兼容允许跳过） */
const enSellingPointsValid = computed(() =>
  enSellingPoints.value.every((p) => !p.keywordInvalid),
)

interface ImageSlot {
  id: string
  name: string
  desc: string
}

interface ImageGroup {
  key: string
  label: string
  hint: string
  min: number
  needName: boolean
  needDesc: boolean
  slots: ImageSlot[]
}

function makeId() {
  return `slot-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

const imageGroups = ref<ImageGroup[]>([
  {
    key: 'white',
    label: '白底图',
    hint: '白底主图，多角度呈现商品细节',
    min: 0,
    needName: false,
    needDesc: false,
    slots: [],
  },
  {
    key: 'scene',
    label: '场景图',
    hint: '展示商品的生活使用场景和人物搭配',
    min: 0,
    needName: false,
    needDesc: false,
    slots: [],
  },
  {
    key: 'selling',
    label: '卖点图',
    hint: '展示商品的核心卖点及细节特写',
    min: 0,
    needName: false,
    needDesc: false,
    slots: [],
  },
  {
    key: 'other',
    label: '其他',
    hint: '对比图、尺寸图等，根据商品智能匹配',
    min: 0,
    needName: true,
    needDesc: true,
    slots: [
      { id: makeId(), name: '对比图', desc: '与竞品对比展示优势' },
      { id: makeId(), name: '尺寸图', desc: '标注产品尺寸信息' },
    ],
  },
])

function addSlot(groupKey: string) {
  const group = imageGroups.value.find((g) => g.key === groupKey)
  if (!group) return
  group.slots.push({ id: makeId(), name: '', desc: '' })
}

function removeSlot(groupKey: string, slotId: string) {
  const group = imageGroups.value.find((g) => g.key === groupKey)
  if (!group) return
  group.slots = group.slots.filter((s) => s.id !== slotId)
}

async function aiHelp() {
  if (workspace.productImages.length === 0) {
    console.warn('[AI帮写] 无商品图片，操作取消')
    return
  }
  isAiWriting.value = true
  console.log('[AI帮写] 开始分析，图片数量:', workspace.productImages.length)
  try {
    const productImages = workspace.productImages
    const imageUrl = productImages[0].url
    let imageBase64 = imageUrl
    if (!imageUrl.startsWith('data:')) {
      try {
        const response = await fetch(imageUrl)
        const blob = await response.blob()
        imageBase64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onloadend = () => resolve(reader.result as string)
          reader.onerror = reject
          reader.readAsDataURL(blob)
        })
      } catch {
        // fallback
      }
    }

    const result = await analyzeProduct(imageBase64, productDesc.value)

    productDesc.value = [
      `[产品名称] ${result.product_name}`,
      `[目标受众] ${result.target_audience}`,
      `[卖点描述] ${result.selling_points}`,
      `[使用方式] ${result.usage_scenario}`,
      `[产品类目] ${result.product_category}`,
    ].join('\n')
    console.log('[AI帮写] 分析完成')
    aiHelpError.value = ''

    // 分析结果带英文卖点时自动填充英文卖点编辑区
    const enPoints = (result as any)?.sellingPointsEn
    if (Array.isArray(enPoints) && enPoints.length > 0) {
      enSellingPoints.value = enPoints.map((p: any) => ({
        titleEn: p?.titleEn || '',
        descEn: p?.descEn || '',
        keywordsText: Array.isArray(p?.visualKeywords) ? p.visualKeywords.join(', ') : '',
        keywordInvalid: false,
      }))
    }

  } catch (err: any) {
    console.error('[AI帮写] 分析失败:', err)
    aiHelpError.value = getErrorMessage(err) || 'AI帮写分析失败，请稍后重试'
  } finally {
    isAiWriting.value = false
    console.log('[AI帮写] 状态重置')
  }
}

// ===== 尺寸约束：分辨率 + 比例联动计算 =====
const sizeWarning = ref('')

/** 根据当前比例和分辨率计算最终有效尺寸 */
const resolvedSize = computed<SizeResult>(() => {
  const resInput = selectedResolution.value === 'custom'
    ? (customWidth.value && customHeight.value ? `${customWidth.value}x${customHeight.value}` : '')
    : selectedResolution.value
  return resolveSizeFromRatioAndResolution(selectedRatio.value, resInput)
})

/** 自定义输入校验（纯数值校验，不联动比例，异常时标橙） */
watch([customWidth, customHeight], ([w, h]) => {
  if (selectedResolution.value !== 'custom') return
  if (!w || !h) {
    sizeWarning.value = ''
    return
  }
  const wNum = parseInt(w, 10)
  const hNum = parseInt(h, 10)
  if (!wNum || !hNum || wNum <= 0 || hNum <= 0) {
    sizeWarning.value = ''
    return
  }
  // 用 parseCustomSize 做纯约束校验（会标记 corrected）
  const result = parseCustomSize(`${wNum}x${hNum}`)
  if (result?.corrected) {
    sizeWarning.value = result.reason || '输入值已自动调整以符合规则'
  } else {
    sizeWarning.value = ''
  }
})

/** 比例或预设分辨率切换时，清空警告 */
watch([selectedRatio, selectedResolution], () => {
  if (selectedResolution.value !== 'custom') {
    sizeWarning.value = ''
  }
})

// Sync smart mode config to workspace store for generation
function parseProductDesc(text: string): Record<string, string> | null {
  if (!text || !text.trim()) return null
  const result: Record<string, string> = {}
  const lines = text.split('\n')
  for (const line of lines) {
    const match = line.match(/\[(.+?)\]\s*(.+)/)
    if (match) {
      const keyMap: Record<string, string> = {
        '产品名称': 'product_name',
        '目标受众': 'target_audience',
        '卖点描述': 'selling_points',
        '使用方式': 'usage_scenario',
        '产品类目': 'product_category',
      }
      const enKey = keyMap[match[1]]
      if (enKey) {
        result[enKey] = match[2].trim()
      }
    }
  }
  return Object.keys(result).length > 0 ? result : null
}

watch(
  [selectedPlatform, selectedRegion, selectedLanguage, resolvedSize, productDesc, referenceText, imageGroups, selectedSiteCode, enSellingPoints],
  () => {
    const parsedProductInfo = parseProductDesc(productDesc.value)
    // 英文卖点：仅提交有内容的条目；校验不通过时由 ConfigPanel 阻止提交生图
    const sellingPointsEn = enSellingPoints.value
      .filter(hasEnPointContent)
      .map((p) => ({
        titleEn: p.titleEn.trim(),
        descEn: p.descEn.trim(),
        visualKeywords: parseEnKeywords(p.keywordsText),
      }))
    workspace.setSmartEnPointsInvalid(!enSellingPointsValid.value)
    workspace.setSmartModeConfig({
      platform: selectedPlatform.value === '其他' ? customPlatform.value : selectedPlatform.value,
      region: selectedRegion.value === '其他' ? customRegion.value : selectedRegion.value,
      targetLanguage: selectedLanguage.value === '其他' ? customLanguage.value : selectedLanguage.value,
      size: `${resolvedSize.value.width}x${resolvedSize.value.height}`,
      productInfo: parsedProductInfo,
      imageGroups: JSON.parse(JSON.stringify(imageGroups.value)),
      referenceText: referenceText.value || undefined,
      site: selectedSiteCode.value || undefined,
      sellingPointsEn: sellingPointsEn.length > 0 ? sellingPointsEn : undefined,
    })
  },
  { deep: true, immediate: true }
)
</script>

<template>
  <div class="space-y-5">
    <!-- 图一：生成设置 -->
    <div>
      <h4 class="text-xs font-semibold text-slate-800 mb-3">生成设置</h4>

      <div class="grid grid-cols-2 gap-2 mb-2">
        <!-- 平台 -->
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            selectedPlatform === '其他'
              ? 'border-brand-purple ring-2 ring-brand-purple/20 bg-white'
              : platformOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <template v-if="selectedPlatform !== '其他'">
            <button ref="platformTrigger" @click="openDropdown('platform')"
              class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
              <span>{{ selectedPlatform }}</span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', platformOpen && 'rotate-180']" />
            </button>
          </template>
          <div v-else class="flex items-center gap-1 pr-1">
            <button @click="selectedPlatform = 'Amazon'; customPlatform = ''; platformOpen = false"
              class="p-1 rounded-md hover:bg-slate-100 text-slate-400 transition-colors flex-shrink-0" title="返回选择">
              <ArrowLeft class="w-3.5 h-3.5" />
            </button>
            <input v-model="customPlatform" placeholder="输入平台名称..."
              class="flex-1 min-w-0 py-2 pl-1 pr-2 text-sm text-brand-purple placeholder:text-slate-300 bg-transparent focus:outline-none" />
            <span class="text-[10px] font-medium text-brand-purple/60 flex-shrink-0">自定义</span>
          </div>
        </div>

        <!-- 地区 -->
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            selectedRegion === '其他'
              ? 'border-brand-purple ring-2 ring-brand-purple/20 bg-white'
              : regionOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <template v-if="selectedRegion !== '其他'">
            <button ref="regionTrigger" @click="openDropdown('region')"
              class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
              <span>{{ selectedRegion }}</span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', regionOpen && 'rotate-180']" />
            </button>
          </template>
          <div v-else class="flex items-center gap-1 pr-1">
            <button @click="selectedRegion = '美国'; customRegion = ''; regionOpen = false"
              class="p-1 rounded-md hover:bg-slate-100 text-slate-400 transition-colors flex-shrink-0" title="返回选择">
              <ArrowLeft class="w-3.5 h-3.5" />
            </button>
            <input v-model="customRegion" placeholder="输入目标地区..."
              class="flex-1 min-w-0 py-2 pl-1 pr-2 text-sm text-brand-purple placeholder:text-slate-300 bg-transparent focus:outline-none" />
            <span class="text-[10px] font-medium text-brand-purple/60 flex-shrink-0">自定义</span>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-2 mb-3">
        <!-- 语言 -->
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            selectedLanguage === '其他'
              ? 'border-brand-purple ring-2 ring-brand-purple/20 bg-white'
              : languageOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <template v-if="selectedLanguage !== '其他'">
            <button ref="languageTrigger" @click="openDropdown('language')"
              class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
              <span>{{ selectedLanguage }}</span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', languageOpen && 'rotate-180']" />
            </button>
          </template>
          <div v-else class="flex items-center gap-1 pr-1">
            <button @click="selectedLanguage = '英语'; customLanguage = ''; languageOpen = false"
              class="p-1 rounded-md hover:bg-slate-100 text-slate-400 transition-colors flex-shrink-0" title="返回选择">
              <ArrowLeft class="w-3.5 h-3.5" />
            </button>
            <input v-model="customLanguage" placeholder="输入语言..."
              class="flex-1 min-w-0 py-2 pl-1 pr-2 text-sm text-brand-purple placeholder:text-slate-300 bg-transparent focus:outline-none" />
            <span class="text-[10px] font-medium text-brand-purple/60 flex-shrink-0">自定义</span>
          </div>
        </div>

        <!-- 比例 -->
        <div
          :class="[
            'relative rounded-xl border transition-all duration-200',
            selectedRatio === '其他'
              ? 'border-brand-purple ring-2 ring-brand-purple/20 bg-white'
              : ratioOpen === 'r' ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
          ]"
        >
          <template v-if="selectedRatio !== '其他'">
            <button ref="ratioTrigger" @click="openDropdown('ratio')"
              class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
              <span>{{ selectedRatio }}</span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200', ratioOpen === 'r' && 'rotate-180']" />
            </button>
          </template>
          <div v-else class="flex items-center gap-1 pr-1">
            <button @click="selectedRatio = '1:1'; customRatio = ''"
              class="p-1 rounded-md hover:bg-slate-100 text-slate-400 transition-colors flex-shrink-0" title="返回选择">
              <ArrowLeft class="w-3.5 h-3.5" />
            </button>
            <input v-model="customRatio" placeholder="例如 3:4 ..."
              class="flex-1 min-w-0 py-2 pl-1 pr-2 text-sm text-brand-purple placeholder:text-slate-300 bg-transparent focus:outline-none" />
            <span class="text-[10px] font-medium text-brand-purple/60 flex-shrink-0">自定义</span>
          </div>
        </div>
      </div>

      <!-- 站点/语言（模板引擎选项）：仅承担语言/市场语义，平台合规跟随上方平台选择 -->
      <div class="mb-5">
        <label class="text-xs font-medium text-slate-700 mb-1.5 block">
          站点 / 语言
          <span class="text-slate-400 font-normal">（市场语义）</span>
          <span class="inline-flex w-3.5 h-3.5 rounded-full border border-slate-300 text-[9px] leading-[14px] text-slate-400 justify-center cursor-help" title="选择目标站点，用于确定生成文案的语言与市场；平台合规规则跟随上方「平台」选择">?</span>
        </label>
        <div class="grid grid-cols-2 gap-2">
          <!-- 站点下拉 -->
          <div
            :class="[
              'relative rounded-xl border transition-all duration-200',
              siteOpen ? 'border-brand-purple ring-2 ring-brand-purple/20' : 'border-slate-200',
            ]"
          >
            <button ref="siteTrigger" @click="openDropdown('site')"
              class="w-full flex items-center justify-between px-3 py-2 text-sm text-slate-700 cursor-pointer focus:outline-none">
              <span class="flex items-center gap-1.5 truncate">
                <Globe class="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                <span class="truncate">{{ selectedSite ? selectedSite.name : '选择站点...' }}</span>
              </span>
              <ChevronDown :class="['w-3.5 h-3.5 text-slate-400 transition-transform duration-200 flex-shrink-0', siteOpen && 'rotate-180']" />
            </button>
          </div>

          <!-- 所选站点语言与 RTL 标记 -->
          <div class="rounded-xl border border-slate-200 bg-white px-3 py-2 flex items-center gap-1.5 overflow-hidden">
            <template v-if="selectedSite">
              <Languages class="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
              <span class="text-sm text-slate-700 truncate" :title="selectedSite.language">{{ selectedSite.language }}</span>
              <span v-if="selectedSite.isRtl"
                class="ml-auto flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-600 border border-amber-200">RTL</span>
            </template>
            <span v-else class="text-sm text-slate-300">站点语言</span>
          </div>
        </div>

        <!-- 平台合规摘要提示（跟随平台选择拉取，与站点/语言选择解耦） -->
        <div v-if="complianceSummary" class="mt-2 rounded-lg p-2.5 bg-slate-50 border border-slate-100 flex items-start gap-2">
          <ShieldCheck class="w-3.5 h-3.5 text-emerald-500 flex-shrink-0 mt-0.5" />
          <span class="text-[10px] text-slate-500 leading-relaxed">{{ complianceSummary }}</span>
        </div>
        <p v-else-if="complianceLoading" class="mt-2 text-[10px] text-slate-400">正在加载平台合规规则...</p>
        <p v-else-if="!compliancePlatformKey" class="mt-2 text-[10px] text-slate-400">当前平台暂无内置合规规则</p>
      </div>

      <!-- Teleported dropdowns (body level,不受父容器 overflow 裁剪) -->
      <Teleport to="body">
        <!-- 站点下拉 -->
        <Transition name="dropdown">
          <div v-if="siteOpen"
            :style="{ position: 'fixed', top: sitePos.top + 'px', left: sitePos.left + 'px', width: sitePos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]"
            @click.stop
          >
            <div class="max-h-[12rem] overflow-y-auto">
              <button v-for="s in siteOptions" :key="s.code" @mousedown="selectedSiteCode = s.code; siteOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedSiteCode === s.code && 'bg-brand-gradient-subtle text-brand-purple font-medium']"
              >
                <span>{{ s.name }}</span>
                <span class="ml-1.5 text-[10px] text-slate-400">{{ s.language }}<template v-if="s.isRtl"> · RTL</template></span>
              </button>
            </div>
          </div>
        </Transition>

        <!-- 平台下拉 -->
        <Transition name="dropdown">
          <div v-if="platformOpen"
            :style="{ position: 'fixed', top: platformPos.top + 'px', left: platformPos.left + 'px', width: platformPos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]"
            @click.stop
          >
            <div class="max-h-[10rem] overflow-y-auto">
              <button v-for="p in platforms" :key="p" @mousedown="selectedPlatform = p; platformOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedPlatform === p && 'bg-brand-gradient-subtle text-brand-purple font-medium']"
              >{{ p }}</button>
              <div class="border-t border-slate-100" />
              <button @mousedown="selectedPlatform = '其他'; platformOpen = false"
                class="w-full text-left px-3 py-1.5 text-sm text-brand-purple hover:bg-brand-gradient-subtle transition-colors flex items-center gap-1.5">✏️ 自定义...</button>
            </div>
          </div>
        </Transition>

        <!-- 地区下拉 -->
        <Transition name="dropdown">
          <div v-if="regionOpen"
            :style="{ position: 'fixed', top: regionPos.top + 'px', left: regionPos.left + 'px', width: regionPos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]"
            @click.stop
          >
            <div class="max-h-[10rem] overflow-y-auto">
              <button v-for="r in regions" :key="r" @mousedown="selectedRegion = r; regionOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedRegion === r && 'bg-brand-gradient-subtle text-brand-purple font-medium']"
              >{{ r }}</button>
              <div class="border-t border-slate-100" />
              <button @mousedown="selectedRegion = '其他'; regionOpen = false"
                class="w-full text-left px-3 py-1.5 text-sm text-brand-purple hover:bg-brand-gradient-subtle transition-colors flex items-center gap-1.5">✏️ 自定义...</button>
            </div>
          </div>
        </Transition>

        <!-- 语言下拉 -->
        <Transition name="dropdown">
          <div v-if="languageOpen"
            :style="{ position: 'fixed', top: languagePos.top + 'px', left: languagePos.left + 'px', width: languagePos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]"
            @click.stop
          >
            <div class="max-h-[10rem] overflow-y-auto">
              <button v-for="l in languages" :key="l" @mousedown="selectedLanguage = l; languageOpen = false"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedLanguage === l && 'bg-brand-gradient-subtle text-brand-purple font-medium']"
              >{{ l }}</button>
              <div class="border-t border-slate-100" />
              <button @mousedown="selectedLanguage = '其他'; languageOpen = false"
                class="w-full text-left px-3 py-1.5 text-sm text-brand-purple hover:bg-brand-gradient-subtle transition-colors flex items-center gap-1.5">✏️ 自定义...</button>
            </div>
          </div>
        </Transition>

        <!-- 比例下拉 -->
        <Transition name="dropdown">
          <div v-if="ratioOpen === 'r'"
            :style="{ position: 'fixed', top: ratioPos.top + 'px', left: ratioPos.left + 'px', width: ratioPos.width + 'px' }"
            class="bg-white rounded-xl border border-slate-200 shadow-xl overflow-hidden z-[9999]"
            @click.stop
          >
            <div class="max-h-[10rem] overflow-y-auto">
              <button v-for="r in ratios" :key="r" @mousedown="selectedRatio = r; ratioOpen = ''"
                :class="['w-full text-left px-3 py-1.5 text-sm transition-colors hover:bg-slate-50', selectedRatio === r && 'bg-brand-gradient-subtle text-brand-purple font-medium']"
              >{{ r }}</button>
              <div class="border-t border-slate-100" />
              <button @mousedown="selectedRatio = '其他'; ratioOpen = ''"
                class="w-full text-left px-3 py-1.5 text-sm text-brand-purple hover:bg-brand-gradient-subtle transition-colors flex items-center gap-1.5">✏️ 自定义...</button>
            </div>
          </div>
        </Transition>
      </Teleport>

      <!-- 点击空白处关闭所有下拉 -->
      <div v-if="platformOpen || regionOpen || languageOpen || ratioOpen || siteOpen"
        class="fixed inset-0 z-[9998]" @click="platformOpen = false; regionOpen = false; languageOpen = false; ratioOpen = ''; siteOpen = false"
      />

      <!-- 分辨率 -->
      <div class="mb-5">
        <label class="text-xs font-medium text-slate-700 mb-1.5 block">分辨率</label>
        <div class="grid grid-cols-4 gap-2">
          <button
            v-for="res in resolutions"
            :key="res.value"
            @click="selectedResolution = res.value"
            :class="[
              'py-2 rounded-xl text-xs font-medium transition-all duration-200 border',
              selectedResolution === res.value
                ? 'border-brand-purple bg-brand-gradient-subtle text-brand-purple shadow-glow'
                : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50',
            ]"
          >
            {{ res.label }}
          </button>
        </div>

        <!-- 自定义输入：双数字输入框 -->
        <Transition name="fade">
          <div v-if="selectedResolution === 'custom'" class="mt-2 animate-fade-in">
            <div class="flex items-center gap-1.5">
              <input
                v-model.number="customWidth"
                type="number"
                min="16"
                max="3840"
                step="16"
                placeholder="宽"
                class="glass-input flex-1 px-3 py-2.5 text-sm text-center [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              />
              <span class="text-slate-400 font-medium text-sm select-none">×</span>
              <input
                v-model.number="customHeight"
                type="number"
                min="16"
                max="3840"
                step="16"
                placeholder="高"
                class="glass-input flex-1 px-3 py-2.5 text-sm text-center [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              />
            </div>
            <p class="text-[10px] text-slate-400 mt-1">宽 × 高，需为 16 的倍数，最大不超过 3840</p>
          </div>
        </Transition>

        <!-- 有效尺寸提示 & 校验警告 -->
        <div class="mt-2 rounded-lg p-2.5 space-y-1.5" :class="sizeWarning ? 'bg-amber-50 border border-amber-200' : 'bg-slate-50 border border-slate-100'">
          <div class="flex items-center justify-between">
            <span class="text-[10px] text-slate-500">有效输出尺寸</span>
            <span class="text-xs font-semibold tabular-nums" :class="resolvedSize.corrected ? 'text-amber-600' : 'text-slate-800'">
              {{ resolvedSize.width }} × {{ resolvedSize.height }}
            </span>
          </div>
          <div class="flex items-center gap-2 text-[10px]" :class="sizeWarning ? 'text-amber-600' : 'text-slate-400'">
            <AlertCircle v-if="sizeWarning" class="w-3 h-3 flex-shrink-0" />
            <span>{{ sizeWarning || `${(Number(resolvedSize.width) * Number(resolvedSize.height) / 10000).toFixed(1)} 万像素 · 比例约束已应用` }}</span>
          </div>
        </div>
      </div>

      <!-- 商品信息 -->
      <div>
        <div class="flex items-center justify-between mb-1.5">
          <label class="text-xs font-medium text-slate-700 flex items-center gap-1">
            商品信息
            <span class="inline-flex w-3.5 h-3.5 rounded-full border border-slate-300 text-[9px] leading-[14px] text-slate-400 justify-center cursor-help" title="请输入包含以下信息生图效果会更好">?</span>
          </label>
          <button @click="aiHelp"
            :disabled="isAiWriting || workspace.productImages.length === 0"
            :title="workspace.productImages.length === 0 ? '上传至少一张商品图片后可使用 AI 帮写' : ''"
            class="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-medium transition-all duration-200 disabled:opacity-40"
            :class="
              isAiWriting
                ? 'bg-brand-gradient-subtle text-brand-purple'
                : 'bg-blue-50 text-blue-500 hover:bg-blue-100'
            ">
            <Sparkles :class="['w-3 h-3', isAiWriting && 'animate-spin']" />
            AI 帮写
          </button>
        </div>
        <div v-if="aiHelpError" class="flex items-center gap-1.5 mb-1.5 text-[11px] text-red-500">
          <AlertCircle class="w-3 h-3 flex-shrink-0" />
          <span>{{ aiHelpError }}</span>
        </div>
        <textarea
          v-model="productDesc"
          rows="4"
          placeholder="请输入包含以下信息生图效果会更好：&#10;[产品名称]&#10;[目标受众]&#10;[卖点描述]&#10;[使用方式]&#10;[产品类目]"
          class="glass-input w-full px-3 py-2.5 text-sm resize-none leading-relaxed"
        />

        <!-- 参考图描述 -->
        <div v-if="workspace.referenceImage" class="mt-3">
          <label class="text-xs font-medium text-slate-700 mb-1.5 block">
            参考维度
            <span class="text-slate-400 font-normal">（可选）</span>
          </label>
          <textarea
            v-model="referenceText"
            rows="2"
            placeholder="描述需要参考的维度，例如：参考这张图的构图和色调（留空则默认参考整体风格）"
            class="glass-input w-full px-3 py-2.5 text-sm resize-none leading-relaxed"
          />
        </div>
      </div>
    </div>

    <!-- 英文卖点编辑区（AI 商品分析返回英文卖点后展示） -->
    <div v-if="enSellingPoints.length > 0">
      <div class="flex items-center justify-between mb-3">
        <h4 class="text-xs font-semibold text-slate-800">英文卖点</h4>
        <span class="text-[10px] text-slate-400">视觉关键词仅支持英文（逗号分隔）</span>
      </div>

      <div class="space-y-2.5">
        <div
          v-for="(point, idx) in enSellingPoints"
          :key="idx"
          class="rounded-xl border border-slate-200 p-2.5 space-y-2"
        >
          <div class="flex items-center gap-2">
            <span class="w-5 h-5 flex-shrink-0 rounded-md bg-slate-100 text-[10px] font-semibold text-slate-500 flex items-center justify-center">
              {{ idx + 1 }}
            </span>
            <input
              v-model="point.titleEn"
              placeholder="英文卖点标题 (Title)"
              class="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg border border-slate-200 text-xs text-slate-700 placeholder:text-slate-300 focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 outline-none transition-all"
            />
          </div>
          <input
            v-model="point.descEn"
            placeholder="英文卖点描述 (Description)"
            class="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 text-xs text-slate-600 placeholder:text-slate-300 focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 outline-none transition-all"
          />
          <div>
            <input
              v-model="point.keywordsText"
              @blur="validateEnKeywords(point)"
              placeholder="视觉关键词，逗号分隔，如: white background, studio lighting"
              :class="[
                'w-full px-2.5 py-1.5 rounded-lg text-xs outline-none transition-all focus:ring-2',
                point.keywordInvalid
                  ? 'border-red-400 ring-2 ring-red-100 text-red-600 focus:ring-red-100 focus:border-red-400'
                  : 'border-slate-200 text-slate-600 placeholder:text-slate-300 focus:ring-brand-purple/20 focus:border-brand-purple/50',
              ]"
            />
            <p v-if="point.keywordInvalid" class="mt-1 flex items-center gap-1 text-[10px] text-red-500">
              <AlertCircle class="w-3 h-3 flex-shrink-0" />
              <span>视觉关键词仅支持英文，请移除中文或全角字符后重试</span>
            </p>
          </div>
        </div>
      </div>
      <p class="text-[10px] text-slate-400 pl-1 mt-1.5">
        英文卖点将用于目标站点的提示词生成，可不填写
      </p>
    </div>

    <!-- 套图结构配置 -->
    <div>
      <h4 class="text-xs font-semibold text-slate-800 mb-3">套图结构配置</h4>

      <!-- 自定义套图列表 -->
      <div class="space-y-4 animate-fade-in">
        <div
          v-for="group in imageGroups"
          :key="group.key"
          class="rounded-xl overflow-hidden"
        >
          <div class="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-slate-100">
            <div>
              <p class="text-xs font-semibold text-slate-800">{{ group.label }}</p>
              <p class="text-[10px] text-slate-400 mt-0.5">{{ group.hint }}</p>
            </div>
            <div class="flex items-center gap-1.5">
              <button
                @click="group.slots.length > 0 && removeSlot(group.key, group.slots[group.slots.length - 1].id)"
                :disabled="group.slots.length === 0"
                class="flex items-center justify-center w-6 h-6 rounded-md text-[11px] font-medium border transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
                :class="
                  group.slots.length > 0
                    ? 'text-red-500 border-red-200 hover:bg-red-50'
                    : 'text-slate-300 border-slate-200'
                "
              >
                <Minus class="w-3 h-3" />
              </button>
              <span class="text-xs font-semibold text-slate-600 min-w-[1.25rem] text-center">
                {{ group.slots.length }}
              </span>
              <button
                @click="addSlot(group.key)"
                class="flex items-center justify-center w-6 h-6 rounded-md text-[11px] font-medium text-brand-purple bg-white border border-slate-200 hover:bg-brand-gradient-subtle hover:border-transparent transition-all duration-200"
              >
                <Plus class="w-3 h-3" />
              </button>
            </div>
          </div>

          <!-- 仅"其他"组展开 slot 行；前三种只靠 header 的 +/- 按钮控制数量 -->
          <div v-if="group.needDesc" class="divide-y divide-slate-100">
            <div v-if="group.slots.length === 0" class="px-3 py-4 text-center text-[11px] text-slate-400">
              暂无配置，点击右上角 + 添加
            </div>
            <div
              v-for="(slot, idx) in group.slots"
              :key="slot.id"
              class="flex items-center gap-2 px-3 py-2.5"
            >
              <span class="w-5 h-5 flex-shrink-0 rounded-md bg-slate-100 text-[10px] font-semibold text-slate-500 flex items-center justify-center">
                {{ idx + 1 }}
              </span>

              <input
                v-model="slot.name"
                :placeholder="`${group.label}名称`"
                class="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg border border-slate-200 text-xs text-slate-700 placeholder:text-slate-300 focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 outline-none transition-all"
              />

              <input
                v-model="slot.desc"
                placeholder="描述生成要求..."
                class="flex-[2] min-w-0 px-2.5 py-1.5 rounded-lg border border-slate-200 text-xs text-slate-600 placeholder:text-slate-300 focus:ring-2 focus:ring-brand-purple/20 focus:border-brand-purple/50 outline-none transition-all"
              />

              <button
                @click="removeSlot(group.key, slot.id)"
                class="w-6 h-6 flex-shrink-0 rounded-md flex items-center justify-center text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                title="移除"
              >
                <Minus class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>

        <p class="text-[10px] text-slate-400 pl-1">
          共计 {{ imageGroups.reduce((sum, g) => sum + g.slots.length, 0) }} 张图片将被生成
        </p>
      </div>
    </div>
  </div>
</template>