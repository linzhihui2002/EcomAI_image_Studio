import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const h = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day} ${h}:${min}`
}

export function calculateCost(
  productCount: number,
  hasReference: boolean,
): number {
  const base = 5
  const refCost = hasReference ? 2 : 0
  return (base + refCost) * productCount
}

export function estimateTime(productCount: number): string {
  const perImage = 8
  const totalSeconds = productCount * perImage
  if (totalSeconds < 60) return `${totalSeconds}秒`
  const minutes = Math.ceil(totalSeconds / 60)
  return `约${minutes}分钟`
}

/** 尺寸约束规则 */
export const SIZE_LIMITS = {
  MAX_SIDE: 3840,          // 最大边长
  MULTIPLE_OF: 16,         // 宽高必须是该值的倍数
  MAX_RATIO: 3,            // 长边/短边 最大比例
  MIN_PIXELS: 655_360,     // 最小总像素数 (≈ 808x810)
  MAX_PIXELS: 8_294_400,   // 最大总像素数 (≈ 2880x2880)
} as const

export interface SizeResult {
  width: number
  height: number
  corrected: boolean       // 是否经过了自动修正
  reason?: string          // 修正原因说明
}

/**
 * 校验并自动修正图片尺寸
 * 规则：
 * 1. 最大边长 ≤ 3840
 * 2. 宽高都必须是 16 的倍数
 * 3. 长边与短边的比例不超过 3:1
 * 4. 总像素数：655,360 ~ 8,294,400
 */
export function validateAndCorrectSize(inputWidth: number, inputHeight: number): SizeResult {
  let w = Math.round(inputWidth)
  let h = Math.round(inputHeight)
  const reasons: string[] = []

  if (w <= 0 || h <= 0) {
    return { width: 1024, height: 1024, corrected: true, reason: '尺寸无效，已重置为默认值 1024×1024' }
  }

  // 规则2：宽高取整到16的倍数（就近取整）
  const origW = w
  const origH = h
  w = Math.round(w / 16) * 16
  h = Math.round(h / 16) * 16
  if (w !== origW || h !== origH) {
    reasons.push(`宽高已调整为16的倍数`)
  }

  // 规则1：最大边长不超过3840
  const maxSide = Math.max(w, h)
  if (maxSide > SIZE_LIMITS.MAX_SIDE) {
    const scale = SIZE_LIMITS.MAX_SIDE / maxSide
    w = Math.round(w * scale / 16) * 16
    h = Math.round(h * scale / 16) * 16
    reasons.push(`最大边长超过${SIZE_LIMITS.MAX_SIDE}，已等比缩放`)
  }

  // 规则3：比例不超过3:1
  const longSide = Math.max(w, h)
  const shortSide = Math.min(w, h)
  if (shortSide > 0 && longSide / shortSide > SIZE_LIMITS.MAX_RATIO) {
    if (w >= h) {
      w = h * SIZE_LIMITS.MAX_RATIO
    } else {
      h = w * SIZE_LIMITS.MAX_RATIO
    }
    w = Math.round(w / 16) * 16
    h = Math.round(h / 16) * 16
    reasons.push(`比例超过${SIZE_LIMITS.MAX_RATIO}:1，已调整`)
  }

  // 规则4：总像素数范围约束
  const totalPixels = w * h
  if (totalPixels < SIZE_LIMITS.MIN_PIXELS) {
    // 放大：按比例增加，保持宽高比
    const scale = Math.sqrt(SIZE_LIMITS.MIN_PIXELS / totalPixels)
    w = Math.round(w * scale / 16) * 16
    h = Math.round(h * scale / 16) * 16
    reasons.push(`总像素不足最低要求，已放大`)
  } else if (totalPixels > SIZE_LIMITS.MAX_PIXELS) {
    // 缩小：按比例缩小，保持宽高比
    const scale = Math.sqrt(SIZE_LIMITS.MAX_PIXELS / totalPixels)
    w = Math.round(w * scale / 16) * 16
    h = Math.round(h * scale / 16) * 16
    reasons.push(`总像素超出上限，已缩小`)
  }

  // 最终确保不低于最小值
  w = Math.max(16, w)
  h = Math.max(16, h)

  const corrected = reasons.length > 0
  return {
    width: w,
    height: h,
    corrected,
    reason: corrected ? reasons.join('；') : undefined,
  }
}

/**
 * 根据比例和分辨率（作为总像素预算）计算最终尺寸
 *
 * 核心逻辑：
 *   1. 比例为主 → 决定宽高比（如 16:9）
 *   2. 分辨率为总像素 → 提供像素预算（如 1K≈100万、2K≈400万）
 *   3. 按比例换算 → 总像素 ÷ 比例 → 分配出 width × height
 *   4. 约束修正 → 最终结果保证 ≤ MAX_PIXELS 且满足所有规则
 *
 * 注意：此函数返回的 corrected 永远为 false，
 * 因为这是系统按规则算出的最优解，不是用户的"错误输入"。
 * 只有 parseCustomSize()（纯手动输入校验）才会标记 corrected。
 *
 * @param ratioStr     比例如 "1:1", "3:4", "4:3", "16:9"
 * @param resolution   预设值("1024x1024"/"2048x2048"/"3840x2160") 或自定义输入("3000x2000")
 */
export function resolveSizeFromRatioAndResolution(
  ratioStr: string,
  resolution: string,
): SizeResult {
  // ── 第一步：从分辨率解析总像素预算（上限不超过 MAX_PIXELS）──
  const rawBudget = resolveTotalPixelBudget(resolution)
  const budget = Math.min(rawBudget, SIZE_LIMITS.MAX_PIXELS)

  // ── 第二步：解析比例，得到宽高比数值 ──
  const ratioMatch = ratioStr.match(/^(\d+):(\d+)$/)
  if (!ratioMatch) {
    // 无法识别的比例，默认 1:1
    const side = Math.floor(Math.sqrt(budget) / 16) * 16
    return { width: Math.max(16, side), height: Math.max(16, side), corrected: false }
  }

  const rw = parseInt(ratioMatch[1], 10)
  const rh = parseInt(ratioMatch[2], 10)
  const ratioValue = rw / rh // >1 表示横向，<1 表示竖向

  // ── 第三步：按比例分配总像素到宽和高（用 floor 取整确保不超预算）──
  // 设 w/h = ratioValue, w * h ≤ budget
  // => h = sqrt(budget / ratioValue), w = h * ratioValue
  let h = Math.floor(Math.sqrt(budget / ratioValue) / 16) * 16
  let w = Math.floor(h * ratioValue / 16) * 16

  // ── 第四步：兜底约束 ──
  // 确保 16 倍数、不低于最小边长、不超过最大边长、比例不超 3:1
  w = Math.max(16, w)
  h = Math.max(16, h)

  // 最大边长约束
  if (w > SIZE_LIMITS.MAX_SIDE) {
    w = Math.floor(SIZE_LIMITS.MAX_SIDE / 16) * 16
  }
  if (h > SIZE_LIMITS.MAX_SIDE) {
    h = Math.floor(SIZE_LIMITS.MAX_SIDE / 16) * 16
  }

  // 比例约束 3:1
  const longSide = Math.max(w, h)
  const shortSide = Math.min(w, h)
  if (shortSide > 0 && longSide / shortSide > SIZE_LIMITS.MAX_RATIO) {
    if (w >= h) {
      w = Math.floor(h * SIZE_LIMITS.MAX_RATIO / 16) * 16
    } else {
      h = Math.floor(w * SIZE_LIMITS.MAX_RATIO / 16) * 16
    }
  }

  // 最小总像素约束（如果太小则放大）
  if (w * h < SIZE_LIMITS.MIN_PIXELS) {
    const scale = Math.sqrt(SIZE_LIMITS.MIN_PIXELS / (w * h))
    w = Math.round(w * scale / 16) * 16
    h = Math.round(h * scale / 16) * 16
  }

  return { width: Math.max(16, w), height: Math.max(16, h), corrected: false }
}

/**
 * 从分辨率字符串中解析目标总像素数（像素预算）
 * - 预设值直接映射：1K→~100万，2K→~400万，3K→~829万
 * - 自定义输入(如"3000x2000")→取其乘积作为预算
 */
function resolveTotalPixelBudget(resolution: string): number {
  // 预设分辨率 → 总像素映射表
  const presetBudgetMap: Record<string, number> = {
    '1024x1024': 1024 * 1024,    // 1K
    '2048x2048': 2048 * 2048,    // 2K
    '3840x2160': 3840 * 2160,    // 4K
  }

  // 先查预设
  if (presetBudgetMap[resolution] !== undefined) {
    return presetBudgetMap[resolution]
  }

  // 自定义输入：解析 W×H，用其乘积作为总像素预算
  const customMatch = resolution.match(/^(\d+)\s*[xX×]\s*(\d+)$/)
  if (customMatch) {
    const cw = parseInt(customMatch[1], 10)
    const ch = parseInt(customMatch[2], 10)
    return cw * ch
  }

  // 兜底默认
  return 1024 * 1024
}

/**
 * 解析自定义尺寸输入字符串（仅做格式校验+约束修正，不含比例分配）
 * 注意：最终给模型时应使用 resolveSizeFromRatioAndResolution 来联动比例
 *
 * 输入格式: "3000x2000" 或 "2560×1440"
 */
export function parseCustomSize(input: string): SizeResult | null {
  const trimmed = input.trim()
  const match = trimmed.match(/^(\d+)\s*[xX×]\s*(\d+)$/)
  if (!match) return null
  const w = parseInt(match[1], 10)
  const h = parseInt(match[2], 10)
  return validateAndCorrectSize(w, h)
}

/**
 * 将图片 URL（Blob URL / HTTP URL）转换为 Base64 编码字符串
 * 如果已经是 data: 开头则直接返回
 */
export async function imageUrlToBase64(url: string): Promise<string> {
  if (url.startsWith('data:')) return url
  try {
    const response = await fetch(url)
    const blob = await response.blob()
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(reader.result as string)
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
  } catch {
    return url
  }
}