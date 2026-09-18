import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import ConfigPanel from '@/components/workspace/ConfigPanel.vue'

// Pinia auto-unwraps top-level refs, so we simulate with reactive that mimics unwrapped refs
const mockWs = reactive({
  mode: 'smart',
  generatedImages: [] as any[],
  canGenerate: true,
  estimatedCost: 0,
  proEstimatedCost: 0,
  singleImageCost: 0,
  proSingleImageCost: 0,
  productImages: [] as any[],
  proTaskCount: 0,
  smartEnPointsInvalid: false,
  complianceBlocks: [
    { rule: 'main_image.background', reason: '主图必须为纯白底' },
    { rule: 'global.forbidden', reason: '包含禁用词 FDA certified' },
  ] as { rule: string; reason: string }[],
  setMode: vi.fn(),
  loadPricing: vi.fn(),
  runGeneration: vi.fn(),
})

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => mockWs,
}))

const mockAuth = {
  selectedWallet: 'personal',
  selectedWalletBalance: 1000,
  currentTeam: null as { name: string } | null,
  deductPoints: vi.fn(() => true),
}

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => mockAuth,
}))

// 打桩重子组件，聚焦 ConfigPanel 自身逻辑
vi.mock('@/components/workspace/SmartMode.vue', () => ({
  default: { name: 'SmartMode', render: () => null },
}))
vi.mock('@/components/workspace/ProMode.vue', () => ({
  default: { name: 'ProMode', render: () => null },
}))
vi.mock('@/components/common/CostEstimator.vue', () => ({
  default: {
    name: 'CostEstimator',
    props: ['singleCost', 'totalCount', 'totalCost'],
    render: () => null,
  },
}))

describe('ConfigPanel 合规阻断与英文卖点校验拦截', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockWs.smartEnPointsInvalid = false
    mockWs.complianceBlocks = [
      { rule: 'main_image.background', reason: '主图必须为纯白底' },
      { rule: 'global.forbidden', reason: '包含禁用词 FDA certified' },
    ]
  })

  it('阻断错误展示：生图提交被合规阻断后，展示阻断原因列表', () => {
    const wrapper = mount(ConfigPanel)

    expect(wrapper.text()).toContain('内容未通过平台合规校验，请修正后重新生成')
    expect(wrapper.text()).toContain('main_image.background')
    expect(wrapper.text()).toContain('主图必须为纯白底')
    expect(wrapper.text()).toContain('global.forbidden')
    expect(wrapper.text()).toContain('包含禁用词 FDA certified')
  })

  it('无阻断信息时不展示合规阻断区域', () => {
    mockWs.complianceBlocks = []
    const wrapper = mount(ConfigPanel)

    expect(wrapper.text()).not.toContain('内容未通过平台合规校验')
  })

  it('英文卖点校验不通过 → 点击生成被拦截，不触发生成流程', async () => {
    mockWs.smartEnPointsInvalid = true
    const wrapper = mount(ConfigPanel)

    const btn = wrapper.findAll('button').find((b) => b.text().includes('一键智能批量生成'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')

    expect(mockWs.runGeneration).not.toHaveBeenCalled()
    expect(mockAuth.deductPoints).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('英文卖点视觉关键词包含中文或全角字符，请修正后再生成')

    mockWs.smartEnPointsInvalid = false
  })

  it('英文卖点校验通过 → 正常进入生成流程', async () => {
    mockWs.smartEnPointsInvalid = false
    const wrapper = mount(ConfigPanel)

    const btn = wrapper.findAll('button').find((b) => b.text().includes('一键智能批量生成'))
    await btn!.trigger('click')

    expect(mockWs.runGeneration).toHaveBeenCalledTimes(1)
  })
})
