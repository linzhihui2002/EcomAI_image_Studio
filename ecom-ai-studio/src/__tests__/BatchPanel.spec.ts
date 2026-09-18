import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'
import BatchPanel from '@/components/workspace/BatchPanel.vue'
import { getTemplateOptions } from '@/api/template'
import { siteCodeToMarket, makeBatchProductId, estimateBatchItems } from '@/lib/batch'
import { imageUrlToBase64 } from '@/lib/utils'

// Pinia auto-unwraps top-level refs, so we simulate with reactive that mimics unwrapped refs
const mockStore = reactive({
  productImages: [] as { id: string; url: string; name: string }[],
  smartModeConfig: {
    platform: 'TikTok Shop',
    size: '1024x1024',
    productInfo: { selling_points: '防水防摔' } as any,
    sellingPointsEn: undefined as any,
  } as any,
  singleImageCost: 2,
  // 批量状态
  batchTaskId: null as string | null,
  batchStatus: 'idle',
  batchItems: [] as any[],
  batchCounts: {} as Record<string, number>,
  batchTotalItems: 0,
  batchCoinsLocked: 0,
  batchUnitCost: 0,
  batchWarnings: [] as string[],
  batchPct: 0,
  batchError: '',
  isBatchSubmitting: false,
  isBatchTracking: false,
  failedBatchItems: [] as any[],
  removeProductImage: vi.fn(),
  submitBatch: vi.fn(),
  retryBatchFailed: vi.fn(),
})

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => mockStore,
}))

vi.mock('@/api/template', () => ({
  getTemplateOptions: vi.fn(),
}))

// api/compliance 使用真实实现（toCompliancePlatform 为纯映射，验证展示名 → 规则键的联动）
vi.mock('@/lib/utils', () => ({
  imageUrlToBase64: vi.fn(),
}))

/** 展开面板 */
async function expand(wrapper: ReturnType<typeof mount>) {
  const bar = wrapper.findAll('button').find((b) => b.text().includes('批量生成'))
  expect(bar).toBeTruthy()
  await bar!.trigger('click')
  await flushPromises()
}

/** 挂载 BatchPanel（Teleport 打桩后确认弹层在组件内渲染，便于查找） */
function mountBatchPanel() {
  return mount(BatchPanel, {
    global: {
      stubs: { teleport: true },
    },
  })
}

/** 勾选指定站点 chip */
async function selectSites(wrapper: ReturnType<typeof mount>, names: string[]) {
  for (const name of names) {
    const btn = wrapper.findAll('button').find((b) => b.text().includes(name))
    expect(btn, `站点按钮 ${name} 应存在`).toBeTruthy()
    await btn!.trigger('click')
  }
  await flushPromises()
}

describe('lib/batch 纯函数', () => {
  it('siteCodeToMarket：模板站点码转后端市场码（大写尾段）', () => {
    expect(siteCodeToMarket('amazon_us')).toBe('US')
    expect(siteCodeToMarket('us')).toBe('US')
    expect(siteCodeToMarket('de')).toBe('DE')
  })

  it('makeBatchProductId：序号 + 文件名摘要，同文件同摘要', () => {
    const id1 = makeBatchProductId(1, 'shoe-red.png')
    expect(id1).toMatch(/^p1-[a-z0-9]+$/)
    expect(makeBatchProductId(2, 'shoe-red.png')).toBe('p2-' + id1.split('-')[1])
  })

  it('estimateBatchItems：商品 × 站点 × 图型', () => {
    expect(estimateBatchItems(2, 2, 3)).toBe(12)
    expect(estimateBatchItems(0, 2, 3)).toBe(0)
    expect(estimateBatchItems(3, -1, 2)).toBe(0)
  })
})

describe('BatchPanel 批量生成面板', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockStore.productImages = [
      { id: 'img-1', url: 'blob:1', name: 'shoe-red.png' },
      { id: 'img-2', url: 'blob:2', name: 'shoe-blue.png' },
    ]
    mockStore.singleImageCost = 2
    mockStore.batchTaskId = null
    mockStore.batchStatus = 'idle'
    mockStore.batchItems = []
    mockStore.batchCounts = {}
    mockStore.batchTotalItems = 0
    mockStore.batchCoinsLocked = 0
    mockStore.batchWarnings = []
    mockStore.batchPct = 0
    mockStore.batchError = ''
    mockStore.isBatchSubmitting = false
    mockStore.isBatchTracking = false
    mockStore.failedBatchItems = []
    mockStore.submitBatch.mockResolvedValue({ batch_task_id: 'bt-1', total_items: 12, coins_locked: 24, unit_cost: 2, feature_key: 'batch', warnings: [] })
    mockStore.retryBatchFailed.mockResolvedValue(true)

    vi.mocked(getTemplateOptions).mockResolvedValue({
      sites: [
        { code: 'amazon_us', name: 'Amazon 美国', language: 'English', isRtl: false },
        { code: 'amazon_de', name: 'Amazon 德国', language: 'Deutsch', isRtl: false },
        { code: 'tiktok_uk', name: 'TikTok 英国', language: 'English', isRtl: false },
      ],
      scenes: [],
      imageTypes: [],
    })
    vi.mocked(imageUrlToBase64).mockResolvedValue('data:image/png;base64,AAAA')
  })

  it('批量预估计算：张数 = 商品 × 站点 × 图型，灵感币 = 单价 × 张数', async () => {
    const wrapper = mountBatchPanel()
    await flushPromises()
    await expand(wrapper)
    await selectSites(wrapper, ['Amazon 美国', 'Amazon 德国'])

    // 2 商品 × 2 站点 × 3 图型 = 12 张；单价 2 → 24 灵感币
    expect(wrapper.text()).toContain('预估 12 张')
    expect(wrapper.text()).toContain('约 24 灵感币')
  })

  it('TikTok 图组预设：图型固定 main+scene+detail 并展示尺寸提示', async () => {
    const wrapper = mountBatchPanel()
    await flushPromises()
    await expand(wrapper)
    await selectSites(wrapper, ['Amazon 美国'])

    // 先取消一个图型 → 2×1×2 = 4 张
    const detailBtn = wrapper.findAll('button').find((b) => b.text().trim() === '细节图')
    await detailBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('预估 4 张')

    // 选中 TikTok 预设 → 图型固定 3 个（预估回到 6 张）且图型按钮禁用 + 尺寸提示
    const presetBtn = wrapper.findAll('button').find((b) => b.text().includes('TikTok 展示图组'))
    await presetBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('预估 6 张')
    expect(wrapper.text()).toContain('TikTok 图组固定生成 主图(1:1) + 场景图(1:1) + 细节图(9:16)')
    expect(detailBtn!.attributes('disabled')).toBeDefined()
  })

  it('审查徽标（Task 9.3）：riskLevel 颜色映射，点击展示 issues 与 fixSuggestions', async () => {
    mockStore.batchTaskId = 'bt-9'
    mockStore.batchStatus = 'completed'
    mockStore.batchTotalItems = 4
    mockStore.batchCounts = { completed: 3, failed: 1 }
    mockStore.batchItems = [
      { item_key: 'k1', product_id: 'p1-a', site: 'US', image_type: 'main', prompt: '', status: 'completed', error: null, result_url: '', coins: 2, review: { riskLevel: 'high', issues: [{ rule: 'main.background', detail: '主图非纯白底' }], fixSuggestions: ['重拍白底图'] } },
      { item_key: 'k2', product_id: 'p2-b', site: 'US', image_type: 'scene', prompt: '', status: 'completed', error: null, result_url: '', coins: 2, review: { riskLevel: 'medium', issues: [], fixSuggestions: [] } },
      { item_key: 'k3', product_id: 'p3-c', site: 'DE', image_type: 'detail', prompt: '', status: 'completed', error: null, result_url: '', coins: 2, review: { riskLevel: 'low', issues: [], fixSuggestions: [] } },
      { item_key: 'k4', product_id: 'p4-d', site: 'DE', image_type: 'main', prompt: '', status: 'failed', error: '生成超时', result_url: null, coins: 0, review: null },
    ]
    mockStore.failedBatchItems = [mockStore.batchItems[3]]

    const wrapper = mountBatchPanel()
    await flushPromises()
    await expand(wrapper)

    // 四级徽标渲染 + 颜色映射（high 红 / medium 橙 / low 绿 / unknown 灰）
    const html = wrapper.html()
    expect(html).toContain('高风险')
    expect(html).toContain('bg-red-100')
    expect(html).toContain('中风险')
    expect(html).toContain('bg-amber-100')
    expect(html).toContain('低风险')
    expect(html).toContain('bg-emerald-100')
    expect(html).toContain('未审')
    expect(html).toContain('bg-slate-100')

    // 悬浮详情元素存在（hidden + group-hover:block）
    const tooltip = wrapper.find('.group-hover\\:block')
    expect(tooltip.exists()).toBe(true)
    expect(tooltip.text()).toContain('main.background：主图非纯白底')
    expect(tooltip.text()).toContain('重拍白底图')

    // 点击徽标 → 可达的审查详情展开
    const highBadge = wrapper.findAll('button').find((b) => b.text().includes('高风险'))
    await highBadge!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('审查详情 · p1-a')
    expect(wrapper.text()).toContain('main.background：主图非纯白底')
    expect(wrapper.text()).toContain('建议：重拍白底图')
  })

  it('重试按钮：无失败项禁用，有失败项可点击并调用重试', async () => {
    mockStore.batchTaskId = 'bt-9'
    mockStore.batchStatus = 'completed'
    mockStore.batchTotalItems = 2
    mockStore.batchCounts = { completed: 2 }
    mockStore.batchItems = [
      { item_key: 'k1', product_id: 'p1-a', site: 'US', image_type: 'main', prompt: '', status: 'completed', error: null, result_url: '', coins: 2, review: null },
      { item_key: 'k2', product_id: 'p1-a', site: 'US', image_type: 'scene', prompt: '', status: 'completed', error: null, result_url: '', coins: 2, review: null },
    ]
    mockStore.failedBatchItems = []

    const wrapper = mountBatchPanel()
    await flushPromises()
    await expand(wrapper)

    const retryBtn = wrapper.findAll('button').find((b) => b.text().includes('重试失败项'))
    expect(retryBtn).toBeTruthy()
    expect((retryBtn!.element as HTMLButtonElement).disabled).toBe(true)

    // 出现失败项后启用（重新查找按钮，避免元素复用导致的陈旧引用）
    const failedItem = { item_key: 'k2', product_id: 'p1-a', site: 'US', image_type: 'scene', prompt: '', status: 'failed', error: '超时', result_url: null, coins: 0, review: null }
    mockStore.batchItems = [mockStore.batchItems[0], failedItem]
    mockStore.batchCounts = { completed: 1, failed: 1 }
    mockStore.failedBatchItems = [failedItem]
    await flushPromises()

    const retryBtn2 = wrapper.findAll('button').find((b) => b.text().includes('重试失败项'))
    expect(retryBtn2).toBeTruthy()
    expect((retryBtn2!.element as HTMLButtonElement).disabled).toBe(false)
    await retryBtn2!.trigger('click')
    await flushPromises()
    expect(mockStore.retryBatchFailed).toHaveBeenCalledTimes(1)
  })

  it('提交流程：确认弹层展示张数与预估，确认后按契约 payload 调用 submitBatch；预检 400 原因展示', async () => {
    const wrapper = mountBatchPanel()
    await flushPromises()
    await expand(wrapper)
    await selectSites(wrapper, ['Amazon 美国', 'TikTok 英国'])

    // 打开确认弹层（2 商品 × 2 站点 × 3 图型 = 12 张，单价 2 → 24）
    const submitBtn = wrapper.findAll('button').find((b) => b.text().includes('提交批量任务'))
    await submitBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('确认提交批量任务')
    expect(wrapper.text()).toContain('共生成 12 张图片')

    // 确认提交 → submitBatch 收到契约 payload
    const confirmBtn = wrapper.findAll('button').find((b) => b.text().includes('确认提交'))
    await confirmBtn!.trigger('click')
    await flushPromises()

    expect(mockStore.submitBatch).toHaveBeenCalledTimes(1)
    const payload = mockStore.submitBatch.mock.calls[0][0]
    expect(payload.sites).toEqual(['US', 'UK'])
    expect(payload.image_types).toEqual(['main', 'scene', 'detail'])
    // 展示名 TikTok Shop 经映射为后端规则键 tiktok_shop
    expect(payload.platform).toBe('tiktok_shop')
    expect(payload.size).toBe('1024x1024')
    expect(payload.image_group).toBeUndefined()
    expect(payload.products).toHaveLength(2)
    expect(payload.products[0].selling_points).toBe('防水防摔')
    expect(payload.products[0].product_id).toMatch(/^p1-[a-z0-9]+$/)

    // 预检 400：err.data 内含原因 → 面板展示
    mockStore.submitBatch.mockRejectedValue({ code: 400, message: '预检失败', data: [{ rule: 'balance', reason: '灵感币余额不足' }] })
    const submitBtn2 = wrapper.findAll('button').find((b) => b.text().includes('提交批量任务'))
    await submitBtn2!.trigger('click')
    const confirmBtn2 = wrapper.findAll('button').find((b) => b.text().includes('确认提交'))
    await confirmBtn2!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('预检未通过：灵感币余额不足')
  })
})
