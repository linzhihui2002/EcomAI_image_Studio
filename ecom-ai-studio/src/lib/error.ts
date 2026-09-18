/**
 * 统一错误处理模块
 *
 * 职责：
 * 1. 将各类错误（API 错误、网络错误、系统错误）统一翻译为友好的中文提示
 * 2. 提供错误码 → 中文消息的映射表
 * 3. 供所有组件、Store、API 客户端统一调用，确保错误提示一致
 */

// ==================== 错误码 → 中文消息映射 ====================

/** API 业务错误码对应的中文提示 */
const API_ERROR_MESSAGES: Record<number, string> = {
  // 认证相关 (1001-1099)
  1001: '登录已过期，请重新登录',
  1002: '认证信息无效，请重新登录',
  1003: '您没有权限执行此操作',
  1004: '密码错误，请重新输入',
  1005: '验证码错误或已过期',
  1006: '验证码发送过于频繁，请稍后再试',
  1007: '该账号已注册，请直接登录',
  1008: '账号不存在，请先注册',

  // 请求参数相关 (2001-2099)
  2001: '请求参数有误，请检查输入内容',
  2002: '文件格式不支持，请上传正确格式的文件',
  2003: '文件大小超出限制，请压缩后重试',
  2004: '必填项不能为空，请完整填写',

  // 业务逻辑相关 (3001-3099)
  3001: '灵感币余额不足，请先充值',
  3003: '图片生成任务排队中，请耐心等待',
  3004: '图片生成失败，服务暂时繁忙，请稍后重试',
  3005: '参考图处理失败，请更换图片后重试',
  // 注: 3002/3008/3009 在后端有多个业务含义(校验/计费/团队/验证码),
  // 不设置默认映射,由 getErrorMessage 回退到后端返回的 message 字段

  // 兑换码/支付相关 (4001-4099)
  // 4001 在后端用作通用参数校验错误码(generation/toolbox/pro 等多模块 30+ 处使用),
  // 非兑换码专属,统一交由 message 兜底
  4002: '该兑换码已被使用，无法重复兑换',
  // 4003 在后端用于"对话历史超出长度限制"(generation.py),非兑换码专属,交由 message 兜底
  // 4004 在不同业务下语义不同(任务不存在/方案已锁定/文件不存在等),统一交由 message 兜底
  // 4005 仅专业模式使用,无业务冲突,直接映射
  4005: '存在未确认或失败的任务，无法生图，请先确认所有任务方案',
  4006: '兑换码已达到总使用次数上限，无法继续使用',
  4007: '该账号已达到此兑换码的使用次数限制',

  // 权限相关 (5001-5099)
  5001: '服务器内部错误，请稍后重试',

  // 团队相关 (3006-3010)
  3006: '团队名称已存在，请更换名称',
  3007: '邀请码无效或已过期',

  // 团队邀请码相关 (3010-3019)
  3010: '邀请码已达到最大使用次数',
  3011: '邀请码已被管理员失效',

  // 转账/解散相关 (3012-3019)
  3012: '个人余额不足，无法完成转账',
  3013: '仅团队创建者可解散团队',
  3014: '余额转移失败，团队解散已中止',
  3015: '转账金额必须大于 0',
  3016: '转账金额超过可用余额',
  3017: '转账失败，请稍后重试',
  3018: '仅团队创建者可向团队钱包转账',

  // 系统相关 (9001-9999)
  9001: '服务器内部错误，请稍后重试',
  9002: '服务暂时不可用，请稍后再试',
  9003: '数据库操作失败，请稍后重试',
}

// ==================== 网络错误类型判断与翻译 ====================

function translateNetworkError(err: unknown): string | null {
  if (!(err instanceof Error)) return null

  const msg = err.message.toLowerCase()

  // 网络连接类
  if (msg.includes('failed to fetch') || msg.includes('networkerror') || msg.includes('network request failed')) {
    return '无法连接到服务器，请确认后端服务已启动'
  }
  if (msg.includes('err_connection_refused') || msg.includes('connection refused')) {
    return '服务器未启动或端口不可达，请联系管理员'
  }
  if (msg.includes('err_connection_reset') || msg.includes('connection reset')) {
    return '服务器连接被重置，请稍后重试'
  }
  if (msg.includes('abort') || msg.includes('aborted')) {
    return '请求已取消'
  }

  // HTTP 状态类（fetch 不会抛出这些，但 axios/其他库可能）
  // 注意：使用更严格的匹配条件，避免误将包含状态码数字的一般性消息错误分类
  if (msg.includes('status 401') || msg.includes('unauthorized')) {
    return '登录状态已失效，请重新登录'
  }
  if (msg.includes('status 403') || msg.includes('forbidden')) {
    return '您没有权限执行此操作'
  }
  if (msg.includes('status 404') || msg.includes('not found')) {
    return '请求的资源不存在'
  }
  if (msg.includes('status 429') || msg.includes('too many requests')) {
    return '操作过于频繁，请稍后再试'
  }
  if (msg.includes('status 500') || msg.includes('internal server error')) {
    return '服务器内部错误，请稍后重试'
  }
  if (msg.includes('status 502') || msg.includes('status 503') || msg.includes('status 504')) {
    return '服务暂时不可用，请稍后再试'
  }
  if (msg.includes('timeout') || msg.includes('timed out')) {
    return '请求超时，请检查网络后重试'
  }

  // CORS 类
  if (msg.includes('cors') || msg.includes('cross-origin')) {
    return '跨域请求被拒绝，请联系技术支持'
  }

  return null
}

// ==================== 后端英文消息自动翻译 =================---

const BACKEND_MSG_TRANSLATIONS: Record<string, string> = {
  // Auth
  'Invalid credentials': '账号或密码错误，请重新输入',
  'User not found': '账号不存在，请先注册',
  'User already exists': '该邮箱已被注册，请直接登录',
  'Account disabled': '账号已被禁用，请联系管理员',
  'Token expired': '登录已过期，请重新登录',
  'Invalid token': '认证信息无效，请重新登录',
  'Code expired or invalid': '验证码错误或已过期',
  'Too many attempts': '操作过于频繁，请稍后再试',
  'Send code too frequently': '验证码发送过于频繁，请稍后再试',

  // Validation
  'Validation failed': '输入信息有误，请检查后提交',
  'Invalid email format': '邮箱格式不正确，请重新输入',
  'Password too short': '密码长度不足，请按要求设置',
  'Password too weak': '密码强度不够，请混合使用大小写字母、数字和特殊字符',
  'Required field missing': '必填项不能为空，请完整填写',
  'Invalid file type': '文件格式不支持，请上传正确格式的文件',
  'File too large': '文件大小超出限制，请压缩后重试',
  'Invalid image format': '图片格式不支持，请使用 JPG、PNG 或 WebP 格式',

  // Business
  'Insufficient balance': '灵感币余额不足，请先充值',
  'Quota exceeded': '今日使用次数已达上限，请明天再试',
  'Generation failed': '图片生成失败，请稍后重试',
  'Model busy': '模型当前繁忙，请稍后重试',
  'Reference image processing failed': '参考图处理失败，请更换图片后重试',
  'Queue full': '当前排队人数较多，请稍后重试',

  // Redemption
  'Redemption code not found': '兑换码不存在，请确认输入是否正确',
  'Redemption code already used': '该兑换码已被使用，无法重复兑换',
  'Redemption code expired': '兑换码已过期，请检查后重试',
  'Redemption code usage limit reached': '兑换码已达到总使用次数上限，无法继续使用',
  'Redemption code per-user limit reached': '该账号已达到此兑换码的使用次数限制',

  // Permission
  'Permission denied': '您没有权限执行此操作',
  'Admin only': '仅管理员可访问此功能',
  'Access denied': '访问被拒绝，请确认您有相应权限',

  // Team
  'Team name already exists': '团队名称已存在，请更换名称',
  'Invalid invite code': '邀请码无效或已过期',
  'Already a member': '您已经是该团队成员',
  'Team not found': '团队不存在或已解散',
  'Not team owner or admin': '仅团队管理员可执行此操作',

  // Transfer
  'Insufficient personal balance': '个人余额不足，无法完成转账',
  'Not team owner': '仅团队创建者可解散团队',
  'Only team owner can transfer': '仅团队创建者可向团队钱包转账',
  'Transfer amount must be positive': '转账金额必须大于 0',
  'Amount exceeds available balance': '转账金额超过可用余额',
  'Transfer failed': '转账失败，请稍后重试',
  'Current password is incorrect': '当前密码错误，请重新输入',
  'Team dissolution failed': '团队解散失败，请稍后重试',

  // System
  'Internal server error': '服务器内部错误，请稍后重试',
  'Service unavailable': '服务暂时不可用，请稍后再试',
  'Database error': '数据存储异常，请稍后重试',
  'Upstream service error': '上游服务异常，请稍后重试',
}

/**
 * 尝试将后端返回的英文消息翻译为中文
 * 匹配策略：精确匹配 > 长模式模糊匹配 > 短模式模糊匹配
 */
export function translateBackendMessage(msg: string): string {
  if (!msg) return ''
  const trimmed = msg.trim()
  const lowerTrimmed = trimmed.toLowerCase()

  // 1. 精确匹配
  if (BACKEND_MSG_TRANSLATIONS[trimmed]) {
    return BACKEND_MSG_TRANSLATIONS[trimmed]
  }

  // 2. 模糊匹配（按模式长度降序排列，更长/更具体的模式优先匹配，避免短词误匹配）
  const sortedEntries = Object.entries(BACKEND_MSG_TRANSLATIONS).sort(
    (a, b) => b[0].length - a[0].length,
  )
  for (const [en, zh] of sortedEntries) {
    if (lowerTrimmed.includes(en.toLowerCase())) {
      return zh
    }
  }

  // 无法识别的英文消息：返回原消息（可能是中文）
  return trimmed
}

// ==================== 核心函数：获取友好的中文错误消息 ====================

/**
 * 从任意错误对象中提取并返回用户友好的中文错误消息
 *
 * 支持的错误类型：
 * - ApiError（含 code/message/details）
 * - 标准 Error
 * - 网络错误（TypeError 等）
 * - 未知类型
 *
 * @param err - 捕获到的错误对象
 * @param fallback - 当无法识别时的默认提示
 */
export function getErrorMessage(err: unknown, fallback = '操作失败，请稍后重试'): string {
  // 1. 空值处理
  if (!err) return fallback

  // 2. 字符串类型
  if (typeof err === 'string') {
    const translated = translateBackendMessage(err)
    return translated || fallback
  }

  // 3. ApiError 类型（含错误码）
  if (err && typeof err === 'object' && 'code' in err) {
    const apiErr = err as { code: number; message?: string; details?: unknown }
    // 优先使用错误码映射
    if (apiErr.code && API_ERROR_MESSAGES[apiErr.code]) {
      return API_ERROR_MESSAGES[apiErr.code]
    }
    // 其次尝试翻译 message
    if (apiErr.message) {
      return translateBackendMessage(apiErr.message)
    }
    return fallback
  }

  // 4. 标准 Error 类型
  if (err instanceof Error) {
    // 先尝试匹配网络错误模式
    const networkMsg = translateNetworkError(err)
    if (networkMsg) return networkMsg

    // 再尝试翻译 message 内容
    return translateBackendMessage(err.message) || fallback
  }

  // 5. 其他未知类型
  return fallback
}

/**
 * 上下文感知的错误消息获取函数
 *
 * 解决问题：同一错误码在不同业务场景下语义不同（如 1001 在登录时=凭证错误，在 API 调用时=token 过期）
 * 通过 context 参数指定当前场景，返回该场景下最准确的中文提示
 *
 * @param err - 捕获到的错误对象
 * @param fallback - 默认提示
 * @param context - 业务上下文：'login' | 'register' | 'api' | 'pro' | 'general'
 */
export function getContextualErrorMessage(
  err: unknown,
  fallback = '操作失败，请稍后重试',
  context: 'login' | 'register' | 'api' | 'pro' | 'general' = 'general',
): string {
  // 如果是含错误码的对象，先检查是否有上下文覆盖映射
  if (err && typeof err === 'object' && 'code' in err) {
    const apiErr = err as { code: number; message?: string }

    // 登录场景：认证类错误码全部指向"凭证问题"而非"过期"
    if (context === 'login') {
      const loginOverride: Record<number, string> = {
        1001: '账号或密码错误，请重新输入',
        1002: '账号或密码错误，请重新输入',
        1004: '密码错误，请重新输入',
        1008: '账号不存在，请先注册',
      }
      if (apiErr.code && loginOverride[apiErr.code]) {
        return loginOverride[apiErr.code]
      }
    }

    // 注册场景
    if (context === 'register') {
      const registerOverride: Record<number, string> = {
        1007: '该邮箱已被注册，请直接登录',
        2006: '该邮箱已被注册，请直接登录',
        3002: '输入信息有误，请检查后提交',
        3009: '验证码无效或已过期，请重新获取',
      }
      if (apiErr.code && registerOverride[apiErr.code]) {
        return registerOverride[apiErr.code]
      }
    }

    // 专业模式场景：错误码 4003/4004/5003 在兑换码/工具箱等业务下语义不同，
    // 此处仅在专业模式上下文中覆盖为专业模式的中文提示
    if (context === 'pro') {
      const proOverride: Record<number, string> = {
        4002: '提示词方案格式不正确，请重新提交分析',
        4003: '对话历史超出长度限制，请清理历史后重试',
        4004: '方案已锁定或任务不存在，无法修改',
        4005: '存在未确认或失败的任务，无法生图，请先确认所有任务方案',
        5003: 'AI 对话服务暂时不可用，请稍后重试',
      }
      if (apiErr.code && proOverride[apiErr.code]) {
        return proOverride[apiErr.code]
      }
      // 超时类错误（code=-1 来自前端 AbortController 超时）给出更准确的提示
      if (apiErr.code === -1 && apiErr.message?.includes('超时')) {
        return 'AI 分析耗时较长，请稍后重试。若多次超时，建议减少同时分析的任务数量'
      }
    }
  }

  // 无上下文覆盖时走默认逻辑
  return getErrorMessage(err, fallback)
}

// ==================== 常用默认提示文案 ====================

export const ERROR_DEFAULTS = {
  NETWORK: '网络连接失败，请检查您的网络设置',
  TIMEOUT: '请求超时，请检查网络后重试',
  SERVER: '服务器暂时繁忙，请稍后重试',
  AUTH_EXPIRED: '登录已过期，请重新登录',
  AUTH_INVALID: '认证信息无效，请重新登录',
  PERMISSION_DENIED: '您没有权限执行此操作',
  UNKNOWN: '发生了未知错误，请稍后重试',
  LOAD_FAILED: '数据加载失败，请点击重试',
  SAVE_FAILED: '保存失败，请稍后重试',
  DELETE_FAILED: '删除失败，请稍后重试',
  UPLOAD_FAILED: '上传失败，请检查文件后重试',
  GENERATION_FAILED: '图片生成失败，请稍后重试',
  LOGIN_FAILED: '登录失败，请稍后重试',
  REGISTER_FAILED: '注册失败，请稍后重试',
  SEND_CODE_FAILED: '验证码发送失败，请稍后重试',
  RESET_PASSWORD_FAILED: '密码重置失败，请稍后重试',
  CHANGE_PASSWORD_FAILED: '密码修改失败，请稍后重试',
  REDEEM_FAILED: '兑换失败，请检查兑换码是否正确',
} as const
