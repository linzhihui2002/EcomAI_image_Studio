import { api } from './client'

// ===== 类型定义 =====

/** 单个图片类型的合规规则（字段按后端契约可扩展） */
export interface ComplianceImageTypeRule {
  background?: string         // 如 "纯白底"
  maxTextLen?: number         // 允许的最大文字长度（0 表示无文字）
  productRatioMin?: number    // 产品最小占比（0-1 小数或百分数，展示层做兼容换算）
  forbidden?: string[]        // 该类型图片的禁用项
  severity?: string
  [key: string]: unknown
}

/** 全局禁用词 */
export interface ComplianceForbidden {
  term: string
  severity: string
}

/** GET /compliance/rules 响应 data */
export interface ComplianceRules {
  platform: string
  imageTypes: Record<string, ComplianceImageTypeRule>
  globalForbidden: ComplianceForbidden[]
}

/** 生图提交被合规阻断时（400），data 内的阻断项 */
export interface ComplianceBlock {
  rule: string
  reason: string
  [key: string]: unknown
}

// ===== 平台键映射 =====

/**
 * 平台展示名 → 后端合规规则平台键的映射。
 * 后端 /compliance/rules 的 platform 取值为电商平台键（amazon/temu/shopee/tiktok_shop/aliexpress/ozon），
 * 而 SmartMode 平台选择器保存的是展示名（如 "Amazon"、"TikTok Shop"），查询前需经此映射；
 * 不在映射内的平台（Lazada/自定义等）后端暂无规则，返回 null（不拉取规则）。
 */
export const PLATFORM_RULE_KEYS: Record<string, string> = {
  'Amazon': 'amazon',
  'AliExpress': 'aliexpress',
  'Shopee': 'shopee',
  'TikTok Shop': 'tiktok_shop',
  'Temu': 'temu',
  'Ozon': 'ozon',
}

/** 平台展示名 → 合规规则平台键（无对应规则时返回 null） */
export function toCompliancePlatform(displayName: string | null | undefined): string | null {
  if (!displayName) return null
  return PLATFORM_RULE_KEYS[displayName] ?? null
}

// ===== API 函数 =====

/** 背景描述（后端为英文规则原文）→ 中文展示文案；未收录的原文透传 */
const BACKGROUND_LABELS: Record<string, string> = {
  'pure white rgb(255,255,255)': '纯白底',
  'white or light solid background preferred': '白色或浅色纯色底',
  'white or light solid background': '白色或浅色纯色底',
  'lifestyle scene allowed': '允许生活场景',
  'short-video style scene, vertical 9:16 friendly': '短视频风格场景（适配 9:16 竖版）',
  'any clean background': '干净背景即可',
}

/** 文字策略（text_policy）→ 允许的最大文字长度：0 表示无文字；未约定则不展示 */
function maxTextLenFromPolicy(policy: unknown): number | undefined {
  const text = String(policy ?? '').trim().toLowerCase()
  if (!text) return undefined
  return text.startsWith('no_text') ? 0 : undefined
}

/** 图型规则归一：后端下划线字段 → 前端展示字段（保留原始字段，展示层不丢失信息） */
function normalizeImageTypeRule(raw: unknown): ComplianceImageTypeRule {
  const source = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const rule: ComplianceImageTypeRule = { ...source }
  if (rule.productRatioMin === undefined && typeof source.product_min_ratio === 'number') {
    rule.productRatioMin = source.product_min_ratio
  }
  if (rule.maxTextLen === undefined) {
    rule.maxTextLen = maxTextLenFromPolicy(source.text_policy)
  }
  if (typeof rule.background === 'string') {
    rule.background = BACKGROUND_LABELS[rule.background.trim().toLowerCase()] ?? rule.background
  }
  return rule
}

/** 禁元素归一：兼容后端 name 与前端 term 两种字段命名 */
function normalizeForbidden(raw: unknown): ComplianceForbidden | null {
  if (!raw || typeof raw !== 'object') return null
  const item = raw as { term?: string; name?: string; severity?: string }
  const term = String(item.term || item.name || '').trim()
  if (!term) return null
  return { term, severity: String(item.severity || '') }
}

/**
 * 获取平台合规规则（如 platform=amazon）
 * 智能模式选择平台后拉取，用于展示平台合规摘要；站点选择器仅承担语言/市场语义，不参与规则查询
 */
export async function getComplianceRules(platform: string): Promise<ComplianceRules> {
  const response = await api.get<{
    code: number
    data: ComplianceRules
  }>('/compliance/rules', { platform }, 30000)
  const data = (response as any).data ?? {}
  const rawTypes = (data.imageTypes ?? data.image_rules ?? {}) as Record<string, unknown>
  const imageTypes: Record<string, ComplianceImageTypeRule> = {}
  for (const [key, value] of Object.entries(rawTypes)) {
    imageTypes[key] = normalizeImageTypeRule(value)
  }
  return {
    platform: String(data.platform || ''),
    imageTypes,
    globalForbidden: Array.isArray(data.globalForbidden)
      ? data.globalForbidden
          .map(normalizeForbidden)
          .filter((f: ComplianceForbidden | null): f is ComplianceForbidden => f !== null)
      : [],
  }
}
