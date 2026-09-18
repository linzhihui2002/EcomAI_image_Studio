import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import SmartMode from '@/components/workspace/SmartMode.vue'

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
  getTemplateOptions: vi.fn().mockResolvedValue({ sites: [], scenes: [], imageTypes: [] }),
  previewPrompt: vi.fn(),
}))

vi.mock('@/api/compliance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/compliance')>()),
  getComplianceRules: vi.fn().mockResolvedValue({ platform: '', imageTypes: {}, globalForbidden: [] }),
}))

// Mock the API call
vi.mock('@/api/generation', () => ({
  analyzeProduct: vi.fn().mockResolvedValue({
    product_name: '测试产品',
    target_audience: '测试受众',
    selling_points: '测试卖点',
    usage_scenario: '测试场景',
    product_category: '测试类目',
  }),
}))

describe('SmartMode AI帮写按钮状态', () => {
  beforeEach(() => {
    mockStore.productImages = []
  })

  function mountSmartMode() {
    return mount(SmartMode, {
      global: {
        stubs: {
          Teleport: false,
        },
      },
    })
  }

  function findAiHelpButton(wrapper: ReturnType<typeof mount>) {
    const buttons = wrapper.findAll('button')
    for (let i = 0; i < buttons.length; i++) {
      if (buttons[i].text().includes('AI 帮写')) {
        return buttons[i]
      }
    }
    return null
  }

  it('初始状态：无图片、无文本 → 按钮禁用', () => {
    const wrapper = mountSmartMode()
    const btn = findAiHelpButton(wrapper)
    expect(btn).not.toBeNull()
    expect((btn!.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('有文本但无图片 → 按钮禁用，title 显示提示', async () => {
    const wrapper = mountSmartMode()
    const textarea = wrapper.find('textarea')
    await textarea.setValue('这是一段商品描述文本')

    const btn = findAiHelpButton(wrapper)
    expect(btn).not.toBeNull()
    expect((btn!.element as HTMLButtonElement).disabled).toBe(true)
    expect((btn!.element as HTMLButtonElement).title).toBe('上传至少一张商品图片后可使用 AI 帮写')
  })

  it('有一张图片 + 有文本 → 按钮启用', async () => {
    mockStore.productImages = [{ id: 'img-1', url: 'blob:test', name: 'test.png' }]
    const wrapper = mountSmartMode()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('商品描述')

    const btn = findAiHelpButton(wrapper)
    expect(btn).not.toBeNull()
    expect((btn!.element as HTMLButtonElement).disabled).toBe(false)
    expect((btn!.element as HTMLButtonElement).title).toBe('')
  })

  it('有多张图片 + 有文本 → 按钮启用', async () => {
    mockStore.productImages = [
      { id: 'img-1', url: 'blob:1', name: '1.png' },
      { id: 'img-2', url: 'blob:2', name: '2.png' },
      { id: 'img-3', url: 'blob:3', name: '3.png' },
    ]
    const wrapper = mountSmartMode()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('多张图片的商品描述')

    const btn = findAiHelpButton(wrapper)
    expect(btn).not.toBeNull()
    expect((btn!.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('删除所有图片后 → 按钮重新禁用，title 显示提示', async () => {
    // 先有图片
    mockStore.productImages = [{ id: 'img-1', url: 'blob:test', name: 'test.png' }]
    const wrapper = mountSmartMode()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('商品描述')

    // 确认有图片时启用
    let btn = findAiHelpButton(wrapper)
    expect((btn!.element as HTMLButtonElement).disabled).toBe(false)

    // 删除所有图片
    mockStore.productImages = []
    await wrapper.vm.$nextTick()

    btn = findAiHelpButton(wrapper)
    expect(btn).not.toBeNull()
    expect((btn!.element as HTMLButtonElement).disabled).toBe(true)
    expect((btn!.element as HTMLButtonElement).title).toBe('上传至少一张商品图片后可使用 AI 帮写')
  })

  it('有图片但无文本 → 按钮启用', async () => {
    mockStore.productImages = [{ id: 'img-1', url: 'blob:test', name: 'test.png' }]
    const wrapper = mountSmartMode()

    const btn = findAiHelpButton(wrapper)
    expect(btn).not.toBeNull()
    expect((btn!.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('空文本 → 有图片时按钮启用', async () => {
    mockStore.productImages = [{ id: 'img-1', url: 'blob:test', name: 'test.png' }]
    const wrapper = mountSmartMode()

    // 输入空格
    const textarea = wrapper.find('textarea')
    await textarea.setValue('   ')

    const btn = findAiHelpButton(wrapper)
    expect(btn).not.toBeNull()
    expect((btn!.element as HTMLButtonElement).disabled).toBe(false)
  })
})