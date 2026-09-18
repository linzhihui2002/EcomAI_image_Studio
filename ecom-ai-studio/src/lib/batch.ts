/**
 * 批量生成纯函数工具（无副作用，便于单测）
 */

/** TikTok 展示图组预设（选中后图型固定 main+scene+detail，尺寸提示 1:1/1:1/9:16） */
export const TIKTOK_SHOWCASE = 'tiktok_showcase'

/** 批量自定义图型选项（与后端 image_types 契约对齐） */
export const BATCH_IMAGE_TYPES: { code: string; name: string; ratio: string }[] = [
  { code: 'main', name: '主图', ratio: '1:1' },
  { code: 'scene', name: '场景图', ratio: '1:1' },
  { code: 'detail', name: '细节图', ratio: '9:16' },
]

/** 站点接口失败时的内置降级列表（与后端 /template/options 结构对齐） */
export const DEFAULT_BATCH_SITES: { code: string; name: string; language: string; isRtl: boolean }[] = [
  { code: 'us', name: '美国站 (US)', language: 'English', isRtl: false },
  { code: 'de', name: '德国站 (DE)', language: 'Deutsch', isRtl: false },
  { code: 'uk', name: '英国站 (UK)', language: 'English', isRtl: false },
  { code: 'jp', name: '日本站 (JP)', language: '日本語', isRtl: false },
]

/**
 * 站点编码 → 后端市场码（大写）
 * 'amazon_us' → 'US'；'us' → 'US'
 */
export function siteCodeToMarket(code: string): string {
  const tail = code.split('_').pop() || code
  return tail.toUpperCase()
}

/**
 * 文件名摘要（djb2 → base36 前 6 位），用于生成批量商品 product_id
 */
export function fileDigest(name: string): string {
  let hash = 5381
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) + hash + name.charCodeAt(i)) | 0
  }
  return (hash >>> 0).toString(36).slice(0, 6)
}

/**
 * 生成批量商品 product_id：序号（1 起）+ 文件名摘要
 */
export function makeBatchProductId(seq: number, fileName: string): string {
  return `p${seq}-${fileDigest(fileName)}`
}

/**
 * 批量预估总张数 = 商品数 × 站点数 × 图型数
 */
export function estimateBatchItems(productCount: number, siteCount: number, typeCount: number): number {
  return Math.max(0, productCount) * Math.max(0, siteCount) * Math.max(0, typeCount)
}

/** 审查风险等级 → 徽标样式（high 红 / medium 橙 / low 绿 / unknown 灰） */
export const REVIEW_RISK_STYLES: Record<string, { label: string; cls: string }> = {
  high: { label: '高风险', cls: 'bg-red-100 text-red-600 border-red-200' },
  medium: { label: '中风险', cls: 'bg-amber-100 text-amber-600 border-amber-200' },
  low: { label: '低风险', cls: 'bg-emerald-100 text-emerald-600 border-emerald-200' },
  unknown: { label: '未审', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
}

/** 明细状态 → 徽标样式 */
export const BATCH_ITEM_STATUS_STYLES: Record<string, { label: string; cls: string }> = {
  planned: { label: '排队中', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
  running: { label: '生成中', cls: 'bg-blue-100 text-blue-600 border-blue-200' },
  completed: { label: '已完成', cls: 'bg-emerald-100 text-emerald-600 border-emerald-200' },
  failed: { label: '失败', cls: 'bg-red-100 text-red-600 border-red-200' },
}
