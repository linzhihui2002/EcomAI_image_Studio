/**
 * AI 图片编辑器 Pinia Store
 *
 * 职责：
 * - 图层文档状态（有序数组，按 z 升序渲染）与选区
 * - 视口（缩放/平移）、激活工具与参数
 * - 撤销/重做（快照式，各上限 50）
 * - 自动保存（debounce 800ms；无 documentId 时先 POST 创建再 PUT）
 * - 坐标体系：图层坐标按"预览尺寸"记录；原图像素换算统一走本文件工具函数
 *   computePreviewScale()，导出/工具执行时用 exportScale 还原到原图分辨率
 * - 笔刷选区：mask 工具（inpaint_erase/inpaint_replace）或 Agent 面板激活笔刷模式，
 *   笔迹按预览坐标记录，确认后渲染为与目标图层图像同尺寸的白=选区 PNG 蒙版
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  EditorDocument,
  EditorLayer,
  EditorTool,
} from '@/api/editor'
import {
  createEditorDocument,
  updateEditorDocument,
} from '@/api/editor'

/** 预览最大边长：原图超过该值时按比例缩小预览（坐标体系随之按预览尺寸记录） */
export const MAX_PREVIEW_SIDE = 2048

/** 撤销/重做栈上限（步） */
const MAX_HISTORY = 50

/** 自动保存防抖间隔（毫秒） */
const AUTOSAVE_DELAY = 800

/** 保存状态 */
export type EditorSaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

/** 笔刷选区单笔笔迹（画布内容区预览坐标） */
export interface MaskStrokePoint {
  x: number
  y: number
}

/**
 * 计算预览缩放系数（坐标换算核心工具函数，唯一来源）
 * - 原图最长边 <= MAX_PREVIEW_SIDE 时为 1（坐标即原图像素）
 * - 超过时返回 <1 的等比缩小系数，图层坐标 = 原图像素 * previewScale
 */
export function computePreviewScale(naturalWidth: number, naturalHeight: number): number {
  const maxSide = Math.max(naturalWidth, naturalHeight)
  if (maxSide <= MAX_PREVIEW_SIDE || maxSide <= 0) return 1
  return MAX_PREVIEW_SIDE / maxSide
}

/** 生成图层 ID */
function genLayerId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 深拷贝图层快照（图层均为 JSON 安全结构） */
function cloneLayers(layers: EditorLayer[]): EditorLayer[] {
  return JSON.parse(JSON.stringify(layers)) as EditorLayer[]
}

export const useEditorStore = defineStore('editor', () => {
  // ===== 文档状态 =====
  const documentId = ref<number | null>(null)
  const documentTitle = ref('')
  /** 来源图标识（source_image_id，通常为 /api/v1/images/ 下的文件名） */
  const sourceImageId = ref<string | null>(null)

  // ===== 图层状态（按 z 升序的有序数组） =====
  const layers = ref<EditorLayer[]>([])
  const selectedLayerId = ref<string | null>(null)
  /** 背景图层 ID（来自 loadFromImage 的首层，前后对比与导出基准） */
  const backgroundLayerId = ref<string | null>(null)

  // ===== 来源图信息（预览/原图尺寸） =====
  // previewScale 为本次会话固定值（loadFromImage 时确定）：
  // 工具结果替换背景图后仍沿用同一系数，保证整个会话坐标体系稳定
  const sourceImage = ref<{
    url: string
    naturalWidth: number
    naturalHeight: number
    previewWidth: number
    previewHeight: number
    previewScale: number
  } | null>(null)

  // ===== 视口（Stage 级缩放与平移，图层坐标不受影响） =====
  const viewport = ref<{ scale: number; x: number; y: number }>({ scale: 1, x: 0, y: 0 })

  // ===== 工具状态 =====
  const tools = ref<EditorTool[]>([])
  const toolsLoaded = ref(false)
  const activeTool = ref<string | null>(null)
  const toolParams = ref<Record<string, number | string | boolean>>({})

  // ===== 笔刷选区（mask 工具 / Agent 计划共用） =====
  /** 笔刷直径（内容区预览坐标像素） */
  const maskBrushSize = ref(32)
  /** 涂抹笔迹（预览坐标），空数组表示尚未涂抹 */
  const maskStrokes = ref<MaskStrokePoint[][]>([])
  /** 最近一次生成的蒙版 data URI（笔迹变化后自动失效置空） */
  const lastMaskDataUri = ref('')
  /** Agent 面板手动开启的笔刷模式（非工具栏激活） */
  const maskBrushManual = ref(false)

  // ===== 撤销/重做（快照式） =====
  const undoStack = ref<EditorLayer[][]>([])
  const redoStack = ref<EditorLayer[][]>([])
  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)

  // ===== 前后对比 =====
  const compareMode = ref(false)

  // ===== 保存状态 =====
  const saveState = ref<EditorSaveState>('idle')
  const saveError = ref('')

  // ===== 图片元素缓存（导出原图分辨率时复用，非响应式） =====
  const imageElCache = new Map<string, HTMLImageElement>()

  // ===== 计算属性 =====

  /** 按 z 升序的可见图层（渲染顺序即数组顺序） */
  const sortedLayers = computed(() =>
    [...layers.value].sort((a, b) => a.z - b.z),
  )

  const selectedLayer = computed(
    () => layers.value.find((l) => l.id === selectedLayerId.value) ?? null,
  )

  const backgroundLayer = computed(
    () => layers.value.find((l) => l.id === backgroundLayerId.value) ?? null,
  )

  const activeToolDef = computed(
    () => tools.value.find((t) => t.name === activeTool.value) ?? null,
  )

  /**
   * 预览坐标 → 原图像素 的换算系数（导出、工具执行用）
   * 以 loadFromImage 时确定的 previewScale 为准；无背景图时为 1
   */
  const exportScale = computed(() => sourceImage.value?.previewScale ?? 1)

  /** 笔刷模式是否激活：mask 工具激活 或 Agent 面板手动开启 */
  const isMaskBrushMode = computed(
    () => maskBrushManual.value || activeToolDef.value?.requires_mask === true,
  )

  /** 是否有涂抹笔迹 */
  const hasMaskStrokes = computed(() => maskStrokes.value.length > 0)

  /**
   * 画布是否已有图片内容（存在至少一个含 url 的图片图层）
   * 下载 / 前后对比 / 保存到历史 的前置条件判断统一走此属性
   */
  const hasImageContent = computed(
    () => layers.value.some((l) => l.type === 'image' && !!l.url),
  )

  /**
   * 笔刷选区的目标图层：选中的图片图层优先，否则背景图层
   * （与工具执行的目标图层规则一致）
   */
  const maskTargetLayer = computed<EditorLayer | null>(() => {
    const selected = selectedLayer.value
    if (selected && selected.type === 'image' && selected.url) return selected
    return backgroundLayer.value
  })

  /** 舞台内容尺寸（预览空间下背景图尺寸；无背景图时给画布默认尺寸） */
  const stageContentWidth = computed(() => sourceImage.value?.previewWidth ?? 1024)
  const stageContentHeight = computed(() => sourceImage.value?.previewHeight ?? 1024)

  // ===== 图片元素加载 =====

  /** 加载并缓存图片元素（导出/测量自然尺寸用） */
  function loadImageEl(url: string): Promise<HTMLImageElement> {
    const cached = imageElCache.get(url)
    if (cached && cached.complete && cached.naturalWidth > 0) {
      return Promise.resolve(cached)
    }
    return new Promise((resolve, reject) => {
      const el = new Image()
      el.crossOrigin = 'anonymous'
      el.onload = () => {
        imageElCache.set(url, el)
        resolve(el)
      }
      el.onerror = () => reject(new Error(`图片加载失败: ${url}`))
      el.src = url
    })
  }

  // ===== 快照 / 撤销 / 重做 =====

  /** 任何变更前压栈（快照式），并清空重做栈 */
  function pushSnapshot() {
    undoStack.value.push(cloneLayers(layers.value))
    if (undoStack.value.length > MAX_HISTORY) {
      undoStack.value.shift()
    }
    redoStack.value = []
  }

  function undo() {
    const prev = undoStack.value.pop()
    if (!prev) return
    redoStack.value.push(cloneLayers(layers.value))
    layers.value = prev
    // 撤销后选中层可能已不存在
    if (selectedLayerId.value && !layers.value.some((l) => l.id === selectedLayerId.value)) {
      selectedLayerId.value = null
    }
    markDirty()
  }

  function redo() {
    const next = redoStack.value.pop()
    if (!next) return
    undoStack.value.push(cloneLayers(layers.value))
    layers.value = next
    if (selectedLayerId.value && !layers.value.some((l) => l.id === selectedLayerId.value)) {
      selectedLayerId.value = null
    }
    markDirty()
  }

  // ===== 图层操作 =====

  /** 获取下一个可用 z 值（置顶） */
  function nextZ(): number {
    return layers.value.reduce((max, l) => Math.max(max, l.z), -1) + 1
  }

  /**
   * 更新图层属性。
   * @param opts.snapshot 连续交互（拖拽/滑杆）传 false，由调用方在交互开始时 pushSnapshot
   */
  function updateLayer(
    id: string,
    patch: Partial<EditorLayer>,
    opts: { snapshot?: boolean } = {},
  ) {
    if (opts.snapshot) pushSnapshot()
    const index = layers.value.findIndex((l) => l.id === id)
    if (index < 0) return
    layers.value[index] = { ...layers.value[index], ...patch }
    markDirty()
  }

  /**
   * 从图片 URL 创建背景图层（编辑器首次加载入口）
   * 坐标按预览尺寸记录；加载后由画布组件调用 fitToViewport()
   */
  async function loadFromImage(options: { url: string; imageId?: string }) {
    const el = await loadImageEl(options.url)
    const scale = computePreviewScale(el.naturalWidth, el.naturalHeight)
    sourceImage.value = {
      url: options.url,
      naturalWidth: el.naturalWidth,
      naturalHeight: el.naturalHeight,
      previewWidth: Math.round(el.naturalWidth * scale),
      previewHeight: Math.round(el.naturalHeight * scale),
      previewScale: scale,
    }
    sourceImageId.value = options.imageId ?? null
    documentId.value = null
    documentTitle.value = ''

    const bgId = genLayerId('layer')
    backgroundLayerId.value = bgId
    layers.value = [
      {
        id: bgId,
        type: 'image',
        url: options.url,
        x: 0,
        y: 0,
        width: sourceImage.value.previewWidth,
        height: sourceImage.value.previewHeight,
        rotation: 0,
        opacity: 1,
        visible: true,
        locked: false,
        z: 0,
      },
    ]
    selectedLayerId.value = bgId
    undoStack.value = []
    redoStack.value = []
    markDirty()
  }

  /**
   * 工具执行结果替换背景图层（crop 等会改变图片尺寸的工具）
   * 坐标体系沿用会话固定的 previewScale：新预览尺寸 = 新自然尺寸 * previewScale
   */
  async function replaceBackgroundImage(url: string, naturalWidth?: number, naturalHeight?: number) {
    const bgId = backgroundLayerId.value
    const layer = bgId === null ? null : layers.value.find((l) => l.id === bgId)
    const src = sourceImage.value
    if (!bgId || !layer || !src) return
    let naturalW = naturalWidth ?? 0
    let naturalH = naturalHeight ?? 0
    if (!naturalW || !naturalH) {
      const el = await loadImageEl(url)
      naturalW = el.naturalWidth
      naturalH = el.naturalHeight
    }
    sourceImage.value = {
      ...src,
      naturalWidth: naturalW,
      naturalHeight: naturalH,
      previewWidth: Math.round(naturalW * src.previewScale),
      previewHeight: Math.round(naturalH * src.previewScale),
    }
    updateLayer(bgId, {
      url,
      x: 0,
      y: 0,
      width: sourceImage.value.previewWidth,
      height: sourceImage.value.previewHeight,
    })
  }

  /** 新增图片图层（上传文件 → data URL / 对象 URL 均可） */
  async function addImageLayer(url: string) {
    const el = await loadImageEl(url)
    // 统一使用会话固定的 previewScale 换算，保证导出到原图分辨率时尺寸正确
    const scale = sourceImage.value?.previewScale ?? computePreviewScale(el.naturalWidth, el.naturalHeight)
    const width = Math.round(el.naturalWidth * scale)
    const height = Math.round(el.naturalHeight * scale)
    pushSnapshot()
    const id = genLayerId('layer')
    // 放到舞台内容区中心（以背景图预览尺寸为参照）
    const x = Math.round((stageContentWidth.value - width) / 2)
    const y = Math.round((stageContentHeight.value - height) / 2)
    const layer: EditorLayer = {
      id,
      type: 'image',
      url,
      x,
      y,
      width,
      height,
      rotation: 0,
      opacity: 1,
      visible: true,
      locked: false,
      z: nextZ(),
    }
    layers.value = [...layers.value, layer]
    selectedLayerId.value = id
    markDirty()
  }

  /**
   * 应用本地上传的图片（data URL）
   * - 画布尚无图片图层时：作为底图加载（建立坐标体系 + backgroundLayerId）
   * - 已有图片图层时：追加为普通图层（置顶居中，等价 addImageLayer）
   * @returns 'background' = 已作为底图；'layer' = 已作为新图层
   */
  async function applyUploadedImage(url: string): Promise<'background' | 'layer'> {
    if (layers.value.some((l) => l.type === 'image' && !!l.url)) {
      await addImageLayer(url)
      return 'layer'
    }
    // 画布完全为空：等价于首次进入编辑器的加载流程
    if (layers.value.length === 0) {
      await loadFromImage({ url })
      return 'background'
    }
    // 已有图层但都不是图片（如仅文本）：补一张底图，置于最底层（预览坐标 x/y = 0）
    const el = await loadImageEl(url)
    const scale = computePreviewScale(el.naturalWidth, el.naturalHeight)
    const previewWidth = Math.round(el.naturalWidth * scale)
    const previewHeight = Math.round(el.naturalHeight * scale)
    sourceImage.value = {
      url,
      naturalWidth: el.naturalWidth,
      naturalHeight: el.naturalHeight,
      previewWidth,
      previewHeight,
      previewScale: scale,
    }
    sourceImageId.value = null

    pushSnapshot()
    const id = genLayerId('layer')
    const minZ = layers.value.reduce((min, l) => Math.min(min, l.z), 0)
    const layer: EditorLayer = {
      id,
      type: 'image',
      url,
      x: 0,
      y: 0,
      width: previewWidth,
      height: previewHeight,
      rotation: 0,
      opacity: 1,
      visible: true,
      locked: false,
      z: minZ - 1,
    }
    layers.value = [...layers.value, layer]
    backgroundLayerId.value = id
    selectedLayerId.value = id
    markDirty()
    return 'background'
  }

  /**
   * 上传本地文件：类型校验 → 读取为 data URL → 走 applyUploadedImage 统一入口
   * 失败时抛出可直接展示的中文错误信息
   */
  async function applyUploadedFile(file: File): Promise<'background' | 'layer'> {
    if (!file.type.startsWith('image/')) {
      throw new Error('仅支持 JPG/PNG/WebP 等图片文件')
    }
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result as string)
      reader.onerror = () => reject(new Error('图片读取失败，请重试'))
      reader.readAsDataURL(file)
    })
    try {
      return await applyUploadedImage(dataUrl)
    } catch (err) {
      console.error('[editor] 上传图片解码失败', err)
      throw new Error('图片解码失败，请更换图片格式（如 JPG/PNG/WebP）')
    }
  }

  /** 新增文本图层（默认尺寸下选中，供属性面板编辑文字） */
  function addTextLayer(text = '双击编辑文字') {
    pushSnapshot()
    const id = genLayerId('layer')
    const layer: EditorLayer = {
      id,
      type: 'text',
      text,
      x: Math.round(stageContentWidth.value * 0.15),
      y: Math.round(stageContentHeight.value * 0.4),
      width: Math.round(stageContentWidth.value * 0.7),
      height: 64,
      rotation: 0,
      opacity: 1,
      visible: true,
      locked: false,
      z: nextZ(),
    }
    layers.value = [...layers.value, layer]
    selectedLayerId.value = id
    markDirty()
  }

  function selectLayer(id: string | null) {
    selectedLayerId.value = id
  }

  function removeLayer(id: string) {
    const layer = layers.value.find((l) => l.id === id)
    if (!layer || layer.locked) return
    pushSnapshot()
    layers.value = layers.value.filter((l) => l.id !== id)
    if (selectedLayerId.value === id) selectedLayerId.value = null
    if (backgroundLayerId.value === id) backgroundLayerId.value = null
    markDirty()
  }

  function toggleVisible(id: string) {
    const layer = layers.value.find((l) => l.id === id)
    if (!layer) return
    updateLayer(id, { visible: !(layer.visible ?? true) }, { snapshot: true })
  }

  function toggleLocked(id: string) {
    const layer = layers.value.find((l) => l.id === id)
    if (!layer) return
    updateLayer(id, { locked: !(layer.locked ?? false) }, { snapshot: true })
  }

  /**
   * 上移/下移一层：与相邻层交换 z 后按 z 重排（有序数组）
   */
  function reorderLayer(id: string, direction: 'up' | 'down') {
    const sorted = sortedLayers.value
    const index = sorted.findIndex((l) => l.id === id)
    if (index < 0) return
    const targetIndex = direction === 'up' ? index + 1 : index - 1
    if (targetIndex < 0 || targetIndex >= sorted.length) return
    const current = sorted[index]
    const target = sorted[targetIndex]
    pushSnapshot()
    updateLayer(current.id, { z: target.z })
    updateLayer(target.id, { z: current.z })
    // 交换后统一重排数组顺序，保持"数组顺序 = z 升序"
    layers.value = [...layers.value].sort((a, b) => a.z - b.z)
  }

  // ===== 工具 =====

  /** 工具是否需要选区蒙版（registry requires_mask） */
  function isMaskTool(name: string | null): boolean {
    if (!name) return false
    return tools.value.find((t) => t.name === name)?.requires_mask === true
  }

  /** 激活工具并按 params_schema 默认值初始化参数；再次点击取消激活 */
  function setActiveTool(name: string | null) {
    if (activeTool.value === name) {
      activeTool.value = null
      toolParams.value = {}
      // 取消激活时清理笔迹与手动笔刷模式
      clearMaskStrokes()
      maskBrushManual.value = false
      return
    }
    activeTool.value = name
    const def = tools.value.find((t) => t.name === name)
    const params: Record<string, number | string | boolean> = {}
    if (def) {
      for (const [key, rule] of Object.entries(def.params_schema)) {
        if (rule.default !== undefined) {
          params[key] = rule.default
        } else if (rule.required) {
          // 必填且无默认值的参数给安全的初始值（如 crop 的 x/y/width/height）
          if (rule.type === 'number') {
            params[key] = rule.min !== undefined ? rule.min : 0
          } else if (rule.type === 'boolean') {
            params[key] = false
          } else {
            params[key] = ''
          }
        }
      }
    }
    toolParams.value = params
    // 切到非蒙版工具时清理笔迹与手动笔刷模式（蒙版工具之间切换保留选区可复用）
    if (!isMaskTool(activeTool.value)) {
      clearMaskStrokes()
      maskBrushManual.value = false
    }
  }

  function setToolParam(key: string, value: number | string | boolean) {
    toolParams.value = { ...toolParams.value, [key]: value }
  }

  // ===== 笔刷选区（mask 工具 / Agent 计划共用） =====

  /** 开始一笔新笔迹（预览坐标） */
  function beginMaskStroke(point: MaskStrokePoint) {
    lastMaskDataUri.value = ''
    maskStrokes.value = [...maskStrokes.value, [point]]
  }

  /** 给最后一笔追加采样点（预览坐标） */
  function extendMaskStroke(point: MaskStrokePoint) {
    lastMaskDataUri.value = ''
    const strokes = maskStrokes.value
    if (strokes.length === 0) return
    const last = strokes[strokes.length - 1]
    strokes[strokes.length - 1] = [...last, point]
  }

  /** 结束当前笔迹（预留：当前无额外处理，保持接口对称） */
  function endMaskStroke() {
    // 采样点在 mousemove 中实时追加，此处无需处理
  }

  /** 清空重涂（同时使已生成蒙版失效） */
  function clearMaskStrokes() {
    if (maskStrokes.value.length === 0 && !lastMaskDataUri.value) return
    maskStrokes.value = []
    lastMaskDataUri.value = ''
  }

  /**
   * 把笔迹渲染为与目标图层图像同尺寸的选区蒙版（base64 PNG data URI）
   * - 白色笔刷 = 选区，透明底 = 非选区
   * - 预览坐标 → 原图像素换算：按图层矩形内相对位置映射（兼容图层拖拽/缩放/旋转），
   *   图层未变形时等价于直接乘 exportScale
   */
  async function buildMaskDataUri(target: EditorLayer): Promise<string | null> {
    if (!target.url || maskStrokes.value.length === 0) return null
    const el = await loadImageEl(target.url)
    const naturalW = el.naturalWidth
    const naturalH = el.naturalHeight
    if (!naturalW || !naturalH) return null
    if (target.width <= 0 || target.height <= 0) return null

    const canvas = document.createElement('canvas')
    canvas.width = naturalW
    canvas.height = naturalH
    const ctx = canvas.getContext('2d')
    if (!ctx) return null

    // 图层预览尺寸 → 图像像素 的映射系数（图层被自由缩放后 width/height 即预览下显示尺寸）
    const scaleX = naturalW / target.width
    const scaleY = naturalH / target.height
    // 旋转逆变换（Konva 旋转为顺时针角度，y 轴向下坐标系）
    const rad = ((target.rotation ?? 0) * Math.PI) / 180
    const cos = Math.cos(rad)
    const sin = Math.sin(rad)
    const cx = target.x + target.width / 2
    const cy = target.y + target.height / 2
    const toImagePoint = (p: MaskStrokePoint): { x: number; y: number } => {
      const dx = p.x - cx
      const dy = p.y - cy
      // 世界坐标 → 图层局部坐标（旋转逆变换）
      const localDx = dx * cos + dy * sin
      const localDy = -dx * sin + dy * cos
      const lx = localDx + target.width / 2
      const ly = localDy + target.height / 2
      return { x: lx * scaleX, y: ly * scaleY }
    }

    const lineW = Math.max(2, maskBrushSize.value * Math.sqrt(Math.abs(scaleX * scaleY)))
    ctx.lineWidth = lineW
    ctx.strokeStyle = '#ffffff'
    ctx.fillStyle = '#ffffff'
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    for (const stroke of maskStrokes.value) {
      if (stroke.length === 0) continue
      if (stroke.length === 1) {
        // 单点点击 → 圆点
        const p = toImagePoint(stroke[0])
        ctx.beginPath()
        ctx.arc(p.x, p.y, lineW / 2, 0, Math.PI * 2)
        ctx.fill()
        continue
      }
      ctx.beginPath()
      stroke.forEach((pt, i) => {
        const p = toImagePoint(pt)
        if (i === 0) ctx.moveTo(p.x, p.y)
        else ctx.lineTo(p.x, p.y)
      })
      ctx.stroke()
    }
    return canvas.toDataURL('image/png')
  }

  /**
   * 确认选区：生成蒙版并记录到 lastMaskDataUri；
   * 若当前激活工具需要蒙版，同时写入 toolParams.mask_data_uri
   * @returns 蒙版 data URI（未涂抹/无目标图层时返回 null）
   */
  async function confirmMaskSelection(): Promise<string | null> {
    const target = maskTargetLayer.value
    if (!target || !target.url || maskStrokes.value.length === 0) return null
    const uri = await buildMaskDataUri(target)
    if (!uri) return null
    lastMaskDataUri.value = uri
    if (isMaskTool(activeTool.value)) {
      setToolParam('mask_data_uri', uri)
    }
    return uri
  }

  // ===== 视口 =====

  /** fit-to-viewport：以画布容器尺寸缩放并居中背景图 */
  function fitToViewport(containerWidth: number, containerHeight: number) {
    const contentW = stageContentWidth.value
    const contentH = stageContentHeight.value
    if (containerWidth <= 0 || containerHeight <= 0 || contentW <= 0 || contentH <= 0) return
    const scale = Math.min(containerWidth / contentW, containerHeight / contentH) * 0.9
    viewport.value = {
      scale,
      x: (containerWidth - contentW * scale) / 2,
      y: (containerHeight - contentH * scale) / 2,
    }
  }

  // ===== 自动保存 =====

  let autosaveTimer: ReturnType<typeof setTimeout> | null = null
  let savingPromise: Promise<void> | null = null

  /** 标记脏并调度防抖自动保存 */
  function markDirty() {
    saveState.value = 'dirty'
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = setTimeout(() => {
      void runAutosave()
    }, AUTOSAVE_DELAY)
  }

  async function runAutosave() {
    if (savingPromise) {
      // 上一次保存未结束，等待其完成后再跑一轮，避免并发写穿
      await savingPromise.catch(() => undefined)
    }
    const payloadLayers = cloneLayers(layers.value)
    saveState.value = 'saving'
    savingPromise = (async () => {
      try {
        if (documentId.value === null) {
          const doc: EditorDocument = await createEditorDocument({
            source_image_id: sourceImageId.value ?? undefined,
            title: documentTitle.value,
            layers: payloadLayers,
          })
          documentId.value = doc.id
        } else {
          await updateEditorDocument(documentId.value, {
            title: documentTitle.value,
            layers: payloadLayers,
          })
        }
        saveState.value = 'saved'
        saveError.value = ''
      } catch (err) {
        saveState.value = 'error'
        saveError.value = err instanceof Error ? err.message : '自动保存失败'
        console.error('[editor] 自动保存失败', err)
      } finally {
        savingPromise = null
      }
    })()
    await savingPromise
  }

  /** 更新标题（触发自动保存） */
  function setTitle(title: string) {
    documentTitle.value = title
    markDirty()
  }

  /**
   * 立即执行一次保存（跳过防抖等待）。
   * 用于"保存到历史"等需要确保 documentId 已存在的场景。
   */
  async function flushAutosave() {
    if (autosaveTimer) {
      clearTimeout(autosaveTimer)
      autosaveTimer = null
    }
    await runAutosave()
  }

  // ===== 重置 =====

  function reset() {
    if (autosaveTimer) {
      clearTimeout(autosaveTimer)
      autosaveTimer = null
    }
    documentId.value = null
    documentTitle.value = ''
    sourceImageId.value = null
    sourceImage.value = null
    layers.value = []
    selectedLayerId.value = null
    backgroundLayerId.value = null
    viewport.value = { scale: 1, x: 0, y: 0 }
    activeTool.value = null
    toolParams.value = {}
    maskBrushSize.value = 32
    maskStrokes.value = []
    lastMaskDataUri.value = ''
    maskBrushManual.value = false
    undoStack.value = []
    redoStack.value = []
    compareMode.value = false
    saveState.value = 'idle'
    saveError.value = ''
    imageElCache.clear()
  }

  return {
    // state
    documentId,
    documentTitle,
    sourceImageId,
    layers,
    selectedLayerId,
    backgroundLayerId,
    sourceImage,
    viewport,
    tools,
    toolsLoaded,
    activeTool,
    toolParams,
    maskBrushSize,
    maskStrokes,
    lastMaskDataUri,
    maskBrushManual,
    undoStack,
    redoStack,
    canUndo,
    canRedo,
    compareMode,
    saveState,
    saveError,
    // computed
    sortedLayers,
    selectedLayer,
    backgroundLayer,
    activeToolDef,
    exportScale,
    isMaskBrushMode,
    hasMaskStrokes,
    hasImageContent,
    maskTargetLayer,
    stageContentWidth,
    stageContentHeight,
    // actions
    loadImageEl,
    pushSnapshot,
    undo,
    redo,
    updateLayer,
    loadFromImage,
    replaceBackgroundImage,
    addImageLayer,
    applyUploadedImage,
    applyUploadedFile,
    addTextLayer,
    selectLayer,
    removeLayer,
    toggleVisible,
    toggleLocked,
    reorderLayer,
    setActiveTool,
    setToolParam,
    beginMaskStroke,
    extendMaskStroke,
    endMaskStroke,
    clearMaskStrokes,
    buildMaskDataUri,
    confirmMaskSelection,
    fitToViewport,
    markDirty,
    setTitle,
    flushAutosave,
    reset,
  }
})
