import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'
import SmartMode from '@/components/workspace/SmartMode.vue'
import { getTemplateOptions } from '@/api/template'
import { getComplianceRules } from '@/api/compliance'
import { analyzeProduct } from '@/api/generation'

// Pinia auto-unwraps top-level refs, so we simulate with reactive that mimics unwrapped refs
const mockStore = reactive({
  productImages: [] as { id: string; url: string; name: string }[],
  mode: 'smart' as const,
  sceneStyle: null as any,
  proConfig: {} as any,
  estimatedCost: 0,
  isGenerating: false,
  canGenerate: false,
  referenceImage: null as any,
  smartEnPointsInvalid: false,
  complianceBlocks: [] as any[],
  addProductImages: vi.fn(),
  removeProductImage: vi.fn(),
  setSmartModeConfig: vi.fn(),
  setSceneStyle: vi.fn(),
  loadPricing: vi.fn(),
  setSmartEnPointsInvalid: vi.fn(),
})

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => mockStore,
}))

vi.mock('@/api/template', () => ({
  getTemplateOptions: vi.fn(),
  previewPrompt: vi.fn(),
}))

vi.mock('@/api/compliance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/compliance')>()),
  getComplianceRules: vi.fn(),
}))

vi.mock('@/api/generation', () => ({
  analyzeProduct: vi.fn(),
}))

function mountSmartMode() {
  return mount(SmartMode, {
    global: {
      // Teleport 打桩后下拉内容在组件内渲染，便于查找
      stubs: { teleport: true },
    },
  })
}

/** 打开站点下拉并选中指定站点 */
async function selectSite(wrapper: ReturnType<typeof mount>, siteName: string) {
  const trigger = wrapper.findAll('button').find((b) => b.text().includes('选择站点'))
  expect(trigger).toBeTruthy()
  await trigger!.trigger('click')
  await flushPromises()
  const option = wrapper.findAll('button').find((b) => b.text().includes(siteName))
  expect(option).toBeTruthy()
  await option!.trigger('mousedown')
  await flushPromises()
}

describe('SmartMode 模板引擎 UI（站点选择器 / 合规摘要 / 英文卖点校验）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockStore.productImages = []
    mockStore.smartEnPointsInvalid = false

    vi.mocked(getTemplateOptions).mockResolvedValue({
      sites: [
        { code: 'amazon_us', name: 'Amazon 美国', language: 'English', isRtl: false },
        { code: 'amazon_ae', name: 'Amazon 阿联酋', language: 'العربية', isRtl: true },
      ],
      scenes: ['outdoor'],
      imageTypes: [{ code: 'main_image', name: '主图' }],
    })

    vi.mocked(getComplianceRules).mockResolvedValue({
      platform: 'amazon',
      imageTypes: {
        main_image: { background: '纯白底', maxTextLen: 0, productRatioMin: 0.85, forbidden: [] },
      },
      globalForbidden: [{ term: 'FDA certified', severity: 'high' }],
    })

    vi.mocked(analyzeProduct).mockResolvedValue({
      product_name: '测试产品',
      target_audience: '测试受众',
      selling_points: '测试卖点',
      usage_scenario: '测试场景',
      product_category: '测试类目',
      sellingPointsEn: [
        { titleEn: 'Long battery life', descEn: 'Up to 12 hours of playback', visualKeywords: ['battery icon'] },
      ],
    } as any)
  })

  it('站点选择器渲染与联动写回 store：选择站点后写入 smartModeConfig.site 并展示语言与 RTL 标记', async () => {
    const wrapper = mountSmartMode()
    await flushPromises()

    // 挂载时拉取模板选项
    expect(getTemplateOptions).toHaveBeenCalledTimes(1)

    await selectSite(wrapper, 'Amazon 阿联酋')

    // 写回 store
    expect(mockStore.setSmartModeConfig).toHaveBeenCalledWith(
      expect.objectContaining({ site: 'amazon_ae' }),
    )
    // 展示所选站点语言与 RTL 标记
    expect(wrapper.text()).toContain('Amazon 阿联酋')
    expect(wrapper.text()).toContain('العربية')
    expect(wrapper.text()).toContain('RTL')
  })

  it('模板选项加载失败时降级为内置默认站点列表，不阻塞页面', async () => {
    vi.mocked(getTemplateOptions).mockRejectedValue(new Error('network error'))
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const wrapper = mountSmartMode()
    await flushPromises()

    await selectSite(wrapper, '美国站 (US)')
    expect(mockStore.setSmartModeConfig).toHaveBeenCalledWith(
      expect.objectContaining({ site: 'us' }),
    )
    expect(warnSpy).toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('合规规则改绑平台选择器：挂载按默认平台拉取，切换平台换键，站点选择不触发查询', async () => {
    const wrapper = mountSmartMode()
    await flushPromises()

    // 挂载即按默认平台 Amazon（映射为规则键 amazon）拉取
    expect(getComplianceRules).toHaveBeenCalledTimes(1)
    expect(getComplianceRules).toHaveBeenCalledWith('amazon')

    // 切换平台 → TikTok Shop 映射为 tiktok_shop 重新拉取
    const platformTrigger = wrapper.findAll('button').find((b) => b.text().trim() === 'Amazon')
    expect(platformTrigger).toBeTruthy()
    await platformTrigger!.trigger('click')
    await flushPromises()
    const tiktokOption = wrapper.findAll('button').find((b) => b.text().includes('TikTok Shop'))
    expect(tiktokOption).toBeTruthy()
    await tiktokOption!.trigger('mousedown')
    await flushPromises()
    expect(getComplianceRules).toHaveBeenLastCalledWith('tiktok_shop')

    // 站点选择只承担语言/市场语义，不再触发合规规则查询
    const callsAfterPlatform = vi.mocked(getComplianceRules).mock.calls.length
    await selectSite(wrapper, 'Amazon 美国')
    expect(vi.mocked(getComplianceRules).mock.calls.length).toBe(callsAfterPlatform)

    // 摘要：平台名 + 主图规则 + 禁用词
    expect(wrapper.text()).toContain('主图：纯白底、产品占比≥85%、无文字')
    expect(wrapper.text()).toContain('禁用词：FDA certified')
  })

  it('英文卖点视觉关键词含中文 → 失焦红框提示，并置 store 校验状态为拦截', async () => {
    mockStore.productImages = [{ id: 'img-1', url: 'data:image/png;base64,iVBORw0KGgo=', name: 'test.png' }]
    const wrapper = mountSmartMode()
    await flushPromises()

    // 触发 AI 帮写 → 商品分析返回 sellingPointsEn 自动填充
    const textarea = wrapper.find('textarea')
    await textarea.setValue('商品描述')
    const aiBtn = wrapper.findAll('button').find((b) => b.text().includes('AI 帮写'))
    expect(aiBtn).toBeTruthy()
    await aiBtn!.trigger('click')
    await flushPromises()

    // 英文卖点编辑区出现并自动填充
    expect(wrapper.text()).toContain('英文卖点')
    const keywordInput = wrapper.find('input[placeholder*="视觉关键词"]')
    expect(keywordInput.exists()).toBe(true)
    expect((keywordInput.element as HTMLInputElement).value).toBe('battery icon')

    // 输入含中文的关键词后失焦 → 红框 + 提示
    await keywordInput.setValue('white background, 白色背景')
    await keywordInput.trigger('blur')
    await flushPromises()

    expect(keywordInput.classes()).toContain('border-red-400')
    expect(wrapper.text()).toContain('视觉关键词仅支持英文')
    // 校验状态写回 store（ConfigPanel 生图前据此拦截提交）
    expect(mockStore.setSmartEnPointsInvalid).toHaveBeenLastCalledWith(true)
    // 英文卖点写回 smartModeConfig.sellingPointsEn
    expect(mockStore.setSmartModeConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        sellingPointsEn: [
          expect.objectContaining({ titleEn: 'Long battery life', visualKeywords: ['battery icon'] }),
        ],
      }),
    )
  })

  it('无英文卖点时校验默认通过（允许跳过，向后兼容）', async () => {
    const wrapper = mountSmartMode()
    await flushPromises()

    expect(wrapper.text()).not.toContain('英文卖点')
    expect(mockStore.setSmartEnPointsInvalid).toHaveBeenCalledWith(false)
  })

  it('英文卖点视觉关键词全为英文 → 失焦校验通过，无红框', async () => {
    mockStore.productImages = [{ id: 'img-1', url: 'data:image/png;base64,iVBORw0KGgo=', name: 'test.png' }]
    const wrapper = mountSmartMode()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('商品描述')
    const aiBtn = wrapper.findAll('button').find((b) => b.text().includes('AI 帮写'))
    await aiBtn!.trigger('click')
    await flushPromises()

    const keywordInput = wrapper.find('input[placeholder*="视觉关键词"]')
    await keywordInput.setValue('white background, studio lighting')
    await keywordInput.trigger('blur')
    await flushPromises()

    expect(keywordInput.classes()).not.toContain('border-red-400')
    expect(wrapper.text()).not.toContain('请移除中文或全角字符')
    expect(mockStore.setSmartEnPointsInvalid).toHaveBeenLastCalledWith(false)
  })
})
