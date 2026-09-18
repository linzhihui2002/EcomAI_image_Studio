import { api } from './client'

// ===== 类型定义 =====

/** 站点选项（GET /template/options 返回） */
export interface TemplateSite {
  code: string        // 站点编码（如 "amazon_us"），用于 smartModeConfig.site 与合规规则查询
  name: string        // 展示名（如 "Amazon 美国"）
  language: string    // 该站点语言（如 "English"）
  isRtl: boolean      // 是否从右到左语言（如阿拉伯语）
}

/** 图片类型选项 */
export interface TemplateImageType {
  code: string
  name: string
}

/** GET /template/options 响应 data */
export interface TemplateOptions {
  sites: TemplateSite[]
  scenes: string[]
  imageTypes: TemplateImageType[]
}

/** 中文卖点 */
export interface TemplateSellingPoint {
  title: string
  desc: string
  visualKeywords?: string[]
}

/** 英文卖点（可编辑后随预览/生成提交） */
export interface TemplateSellingPointEn {
  titleEn: string
  descEn: string
  visualKeywords: string[]
}

/** 提示词预览入参（POST /template/preview） */
export interface PreviewPromptPayload {
  productInfo: {
    productName: string
    targetAudience: string
    usageScenario: string
    productCategory: string
    sellingPoints: TemplateSellingPoint[]
  }
  sellingPointsEn?: TemplateSellingPointEn[]
  scene: string
  site: string
  imageType: string
}

/** 提示词预览响应 data */
export interface PromptPreview {
  prompts: {
    main: string
    scene: string
    detail: string
  }
  warnings: string[]
}

// ===== API 函数 =====

/** 后端 /template/options 原始站点条目（兼容 code/site、isRtl/rtl 两种命名） */
interface RawTemplateSite {
  code?: string
  name?: string
  site?: string
  language?: string
  isRtl?: boolean
  rtl?: boolean
}

/** 站点条目归一：兼容后端字段命名/大小写差异；无可识别站点码时返回 null */
function normalizeSite(raw: RawTemplateSite): TemplateSite | null {
  const code = String(raw.code || raw.site || '').trim().toLowerCase()
  if (!code) return null
  return {
    code,
    name: String(raw.name || code.toUpperCase()),
    language: String(raw.language || ''),
    isRtl: Boolean(raw.isRtl ?? raw.rtl ?? false),
  }
}

/** 图型条目归一：兼容字符串（"main"）与对象（{code,name}）两种形状 */
function normalizeImageType(raw: unknown): TemplateImageType | null {
  if (typeof raw === 'string' && raw.trim()) {
    return { code: raw.trim(), name: raw.trim() }
  }
  if (raw && typeof raw === 'object') {
    const item = raw as { code?: string; name?: string }
    const code = String(item.code || '').trim()
    if (code) return { code, name: String(item.name || code) }
  }
  return null
}

/**
 * 获取模板引擎选项（站点/场景/图片类型）
 * 站点列表用于智能模式"站点/语言"选择器与批量任务站点选择；失败时由调用方降级为内置默认列表
 */
export async function getTemplateOptions(): Promise<TemplateOptions> {
  const response = await api.get<{
    code: number
    data: TemplateOptions
  }>('/template/options', undefined, 30000)
  const data = (response as any).data ?? {}
  return {
    sites: Array.isArray(data.sites)
      ? data.sites
          .map(normalizeSite)
          .filter((s: TemplateSite | null): s is TemplateSite => s !== null)
      : [],
    scenes: Array.isArray(data.scenes) ? data.scenes : [],
    imageTypes: Array.isArray(data.imageTypes ?? data.image_types)
      ? (data.imageTypes ?? data.image_types)
          .map(normalizeImageType)
          .filter((t: TemplateImageType | null): t is TemplateImageType => t !== null)
      : [],
  }
}

/**
 * 提示词预览 - 基于商品信息与站点生成三段英文提示词（主/场景/细节）
 * 用于专业模式方案确认前的提示词预览，30 秒超时
 */
export async function previewPrompt(
  payload: PreviewPromptPayload
): Promise<PromptPreview> {
  const response = await api.post<{
    code: number
    data: PromptPreview
  }>('/template/preview', payload, 30000)
  return (response as any).data
}
