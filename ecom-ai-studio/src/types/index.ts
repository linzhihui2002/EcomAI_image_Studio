// API Response Types
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface PaginatedResponse<T> extends ApiResponse<T> {
  pagination: {
    page: number
    pageSize: number
    total: number
    totalPages: number
  }
}

export type WalletType = 'personal' | 'team'

export interface User {
  id: string
  email: string
  avatar?: string
  personalPoints: number
  role: 'user' | 'admin'
  createdAt: string
  /** 用户参与的团队列表（profile 接口返回） */
  teams?: Team[]
}

export interface Team {
  id: string
  name: string
  category: string
  inviteCode: string
  ownerId: string
  memberCount: number
  poolBalance: number
}

export type TeamMemberRole = 'owner' | 'admin' | 'member'

export interface TeamMember {
  id: string
  email: string
  role: TeamMemberRole
  joinedAt: string
}

export type GenerationMode = 'smart' | 'pro'

export type SceneStyle =
  | 'nordic-minimal'
  | 'amazon-white'
  | 'natural-outdoor'
  | 'indoor-warm'
  | 'luxury-black-gold'
  | 'fresh-macaron'
  | 'tech-cool'
  | 'vintage-worn'
  | 'festive'

export type LightingStyle = 'natural' | 'studio-soft' | 'warm-dusk' | 'cool-tech'

export type CameraAngle = 'eye-level' | 'top-down' | 'low-45'

export type AspectRatio = '1:1' | '3:4' | '4:3' | '16:9' | 'custom'

export interface ProTaskCard {
  id: string
  name: string
  productImages: ProductImage[]
  referenceImage: ReferenceImage | null
  promptScheme: string
  polishedPrompt: string
  aspectRatio: AspectRatio
}

export interface ProConfig {
  rawPrompt: string
  polishedPrompt: string
  zhTags: string[]
  lighting: LightingStyle
  cameraAngle: CameraAngle
  aspectRatio: AspectRatio
  promptHistory: string[]
}

export interface ReferenceImage {
  url: string
  strength: number
}

export interface ProductImage {
  id: string
  url: string
  name: string
}

export interface GenerationConfig {
  mode: GenerationMode
  productImages: ProductImage[]
  referenceImage: ReferenceImage | null
  sceneStyle: SceneStyle | null
  proConfig: ProConfig
}

export interface GeneratedImage {
  id: string
  taskId: string
  batchId: string
  url: string
  prompt: string
  status: 'processing' | 'success' | 'failed'
  errorMsg?: string
  favorited: boolean
}

export interface FavoriteItem {
  id: string
  userId?: number
  targetType: 'image' | 'history'
  imageUrl: string
  batchId: string
  config: GenerationConfig
  createdAt: string
  // history 类型收藏的额外字段
  historyRecordId?: number
  title?: string
  thumbnailUrl?: string
  category?: HistoryCategory
  subCategory?: HistorySubCategory
  sourceUserId?: number
  sourceUserName?: string
}

export interface StyleCard {
  id: SceneStyle
  name: string
  icon: string
  description: string
  promptSuffix: string
  examples: string[]
}

export interface FeatureCard {
  id: string
  title: string
  description: string
  icon: string
  available: boolean
  badge?: string
  route?: string
}

export interface InspirationItem {
  id: string
  title: string
  imageUrl: string
  author: string
  tags: string[]
  configSnapshot: GenerationConfig
  pointsCost: number
}

export interface AdminStats {
  onlineUsers: number
  todayPoints: number
  qwenSuccessRate: number
  gptSuccessRate: number
  hourlyRequests: { hour: string; qwen: number; gpt: number }[]
  failureTrend: { hour: string; count: number }[]
  modelHealth: {
    qwen: { latency: number; status: 'green' | 'red'; lastCheck: string }
    gpt: { latency: number; status: 'green' | 'red'; lastCheck: string }
  }
}

export interface PointsRecord {
  id: string
  amount: number
  type: 'consume' | 'refund' | 'bonus' | 'topup'
  sourceWallet: WalletType
  teamId?: string
  description: string
  createdAt: string
}

export interface PricingPlan {
  id: number
  name: string
  price: number
  coins: number
  bonusCoins: number
  isActive: boolean
  sortOrder: number
  createdAt: string
}

export interface TeamConsumption {
  teamId: string
  teamName: string
  category: string
  memberCount: number
  totalCoinsConsumed: number
  todayCoinsConsumed: number
  weeklyCoinsConsumed: number
  monthlyCoinsConsumed: number
}

export interface RedemptionCode {
  id: string
  code: string
  coins: number
  expiresAt: string
  isUsed: boolean
  usedBy?: string
  usedAt?: string
  createdAt: string
  remark: string
  // 扩展：次数限制相关字段
  maxUses: number
  maxUsesPerUser: number
  useCount: number
  remainingUses?: number
}

export interface TeamInvitation {
  code: string
  expiresAt: string
  usageCount: number
  maxUsage: number
  createdAt: string
}

export interface InvitationVerification {
  valid: boolean
  teamName?: string
  teamId?: string
  remainingUses?: number
  expiresAt?: string
}

export interface Announcement {
  id: string
  title: string
  content: string
  type: 'info' | 'warning' | 'success' | 'important'
  isPinned: boolean
  isActive: boolean
  createdAt: string
  createdBy?: string
  expiresAt?: string
}

export interface TransferLog {
  id: string
  transferType: 'team_to_owner' | 'personal_to_team'
  fromUserId: string
  fromWallet: WalletType
  teamId: string
  toUserId?: string
  toWallet: WalletType
  amount: number
  status: 'success' | 'failed'
  errorMsg?: string
  createdAt: string
  fromUserEmail?: string
}

// ==================== 专业模式(Pro Mode)类型 ====================

/** 专业模式图片类型(9 类,与后端 ImageType 枚举对齐) */
export type ProImageType =
  | 'main_image' // 主图
  | 'sub_image' // 副图
  | 'white_bg' // 白底图
  | 'scene' // 场景图
  | 'selling_point' // 卖点图
  | 'checklist' // 清单图
  | 'material' // 材质图
  | 'size_chart' // 尺寸图
  | 'other' // 其他

/** 提示词方案状态(与后端 SchemeStatus 枚举对齐) */
export type SchemeStatus =
  | 'pending' // 待处理
  | 'analyzing' // AI 分析整合中
  | 'optimizing' // 对话优化中
  | 'confirmed' // 已确认,待生图
  | 'locked' // 已锁定,生图中
  | 'failed' // 失败

/** 排版提示词结构 */
export interface LayoutPrompt {
  /** 商品呈现状态,例如"正面平放、品牌 logo 朝上" */
  product_state: string
  /** 构图说明,例如"居中对称构图,商品占画面 85%" */
  composition: string
  /** 背景描述,例如"纯白背景 RGB 255,255,255" */
  background: string
  /** 角标/装饰元素,例如"右上角圆形促销徽章" */
  corner_badge: string
  /** 视觉焦点,例如"材质细节特写" */
  visual_focus: string
}

/** 文案内容结构 */
export interface CopyContent {
  /** 主标题文案 */
  main_title: string
  /** 副标题文案 */
  sub_title: string
  /** 标签数组,例如 ["新品","限时折扣"] */
  tags: string[]
}

/** 提示词方案(AI 分析整合/对话优化的输出) */
export interface PromptScheme {
  image_name: string
  image_role: string
  layout_prompt: LayoutPrompt
  copy: CopyContent
}

/** 对话消息(AI 对话优化的历史记录) */
export interface DialogMessage {
  /** 消息角色:user(用户) / assistant(AI) */
  role: 'user' | 'assistant'
  /** 消息文本内容 */
  content: string
  /** 时间戳 ISO8601 字符串 */
  timestamp: string
  /** 该轮对话生成的方案快照(仅 assistant 携带) */
  scheme_snapshot?: PromptScheme
}

/** 专业模式单个任务的状态 */
export interface ProTaskState {
  /** 任务 ID */
  task_id: string
  /** 图片类型 */
  image_type: ProImageType
  /** 任务名称(展示用) */
  task_name: string
  /** 方案状态 */
  status: SchemeStatus
  /** 当前提示词方案 */
  scheme?: PromptScheme
  /** 对话历史 */
  dialog_history: DialogMessage[]
  /** 版本快照列表,用于回滚 */
  version_snapshots: PromptScheme[]
  /** 生图任务 ID(确认后才有,用于轮询生图进度) */
  generation_task_id?: string
  /** 生图结果 URL */
  result_url?: string
  /** 后端已生成图片但 base64 数据已从轮询响应中剥离，需单独获取 */
  has_image?: boolean
  /** 错误消息(失败时填充) */
  error_message?: string
  /** 创建时间 */
  created_at: string
  /** 最后更新时间 */
  updated_at: string
}

/** 专业模式批次状态查询响应 */
export interface ProBatchStatusResponse {
  /** 批次 ID */
  batch_id: string
  /** 批次整体状态 */
  status: SchemeStatus
  /** 任务列表 */
  tasks: ProTaskState[]
  /** 创建时间 */
  created_at: string
  /** 最后更新时间 */
  updated_at: string
}

/** 单个图片任务配置(提交给 AI 分析整合接口) */
export interface ProImageTaskInput {
  /** 任务名称,例如"主图-正面" */
  task_name: string
  /** 图片类型 */
  image_type: ProImageType
  /** 该任务专属的需求描述(可选) */
  requirement?: string
  /** 宽高比 */
  aspect_ratio: AspectRatio
}

/** AI 分析整合请求体 */
export interface ProAnalyzeIntegrateRequest {
  /** 商品图 base64 列表(含 data: 前缀) */
  product_images: string[]
  /** 参考图 base64(可选) */
  reference_image?: string
  /** 参考图文字说明(可选) */
  reference_text?: string
  /** 目标平台,例如"amazon"/"taobao" */
  platform: string
  /** 目标市场,例如"us"/"cn" */
  region: string
  /** 目标语言,例如"en"/"zh" */
  target_language: string
  /** 输出尺寸,例如"1024x1024" */
  size: string
  /** 整体需求描述(可选) */
  requirement?: string
  /** 任务列表 */
  image_tasks: ProImageTaskInput[]
  /** 商品信息(可选,缺失时由后端调用多模态补全) */
  product_info?: {
    product_name?: string
    category?: string
    material?: string
    features?: string[]
    selling_points?: string[]
  }
  /** 提示词语言，"en" 或 "zh" */
  prompt_language?: string
}

/** AI 分析整合响应数据 */
export interface ProAnalyzeIntegrateResponseData {
  /** 批次 ID */
  batch_id: string
  /** 任务列表(含 AI 生成的方案) */
  tasks: ProTaskState[]
  /** 商品信息(后端补全后的) */
  product_info?: {
    product_name: string
    category: string
    material: string
    features: string[]
    selling_points: string[]
  }
}

/** 对话优化请求体 */
export interface ProDialogOptimizeRequest {
  /** 批次 ID */
  batch_id: string
  /** 任务 ID */
  task_id: string
  /** 用户输入的优化指令 */
  user_input: string
  /** 对话历史(前端发送当前历史,后端追加) */
  dialog_history: DialogMessage[]
}

/** 对话优化响应数据 */
export interface ProDialogOptimizeResponseData {
  /** 任务 ID */
  task_id: string
  /** 更新后的方案 */
  scheme: PromptScheme
  /** AI 回复内容 */
  reply: string
  /** 追加后的对话历史 */
  dialog_history: DialogMessage[]
  /** 新版本快照序号 */
  version: number
}

/** 确认方案并触发生图请求体 */
export interface ProConfirmRequest {
  /** 批次 ID */
  batch_id: string
}

/** 确认方案响应数据 */
export interface ProConfirmResponseData {
  /** 批次 ID */
  batch_id: string
  /** 生图任务 ID 列表(供前端轮询) */
  task_ids: string[]
  /** 提示信息 */
  message: string
}

// ==================== 历史记录(History)类型 ====================

/** 一级类目 */
export type HistoryCategory = 'ai_product_image' | 'ai_toolbox'

/** 二级类目标识符 */
export type HistorySubCategory =
  | 'smart_mode'
  | 'pro_mode'
  | 'plan_analysis'
  | 'image_merge'
  | 'text_to_image'
  | 'chat_gen'
  | 'product_replace'
  | 'ai_model'
  | 'model_product'
  | 'prompt_reverse'
  | 'editor'

/** 历史记录列表项（不含完整数据） */
export interface HistoryRecordItem {
  id: number
  user_id: number
  category: HistoryCategory
  sub_category: HistorySubCategory
  title: string
  thumbnail_url: string | null
  shared_to_team: boolean
  shared_team_id: number | string | null
  created_at: string
}

/** 历史记录详情（含完整数据） */
export interface HistoryRecordDetail extends HistoryRecordItem {
  input_data: Record<string, any>
  output_data: Record<string, any>
  config_snapshot: Record<string, any> | null
}

/** 类目中文映射 */
export const CATEGORY_LABELS: Record<HistoryCategory, string> = {
  ai_product_image: 'AI商品图',
  ai_toolbox: 'AI工具箱',
}

/** 二级类目中文映射 */
export const SUB_CATEGORY_LABELS: Record<HistorySubCategory, string> = {
  smart_mode: '简单模式',
  pro_mode: '专业模式',
  plan_analysis: '生图计划分析',
  image_merge: '图片合并',
  text_to_image: '文生图',
  chat_gen: '对话式生图',
  product_replace: '产品替换',
  ai_model: 'AI模特',
  model_product: '模特商品图',
  prompt_reverse: '反推提示词',
  editor: '图片编辑器',
}

// ==================== 功能定价(Feature Pricing)类型 ====================

export type PricingType = 'per_image_resolution' | 'per_use'

export interface ResolutionTier {
  tier: string
  max_dimension: number
  coins: number
}

/** 功能定价配置（与后端 config JSON 对齐） */
export interface FeaturePricingConfig {
  /** per_use 时的单次价格 */
  coins?: number
  /** per_image_resolution 时的分辨率档位列表 */
  tiers?: ResolutionTier[]
}

/** 功能定价（公开查询返回的精简结构） */
export interface FeaturePricing {
  featureKey: string
  displayName: string
  category: string
  pricingType: PricingType
  config: FeaturePricingConfig
  sortOrder: number
}

/** 功能定价（管理员完整结构） */
export interface FeaturePricingAdmin extends FeaturePricing {
  id: number
  description: string | null
  isActive: boolean
  createdAt: string
  updatedAt: string
}