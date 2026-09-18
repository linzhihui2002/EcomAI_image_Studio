<script setup lang="ts">
/**
 * 编辑器画布：vue-konva Stage 渲染图层文档
 *
 * - 图层坐标按"预览尺寸"记录（见 store.computePreviewScale），Stage 缩放只影响视口
 * - 滚轮缩放（以鼠标点为中心）、按住空格拖拽平移、窗口 resize 自适应
 * - 选中/拖拽/缩放图层（Transformer），锁定图层不可拖拽
 * - crop 工具：叠加可拖拽/缩放裁剪矩形，应用时换算为原图像素坐标写入 toolParams
 * - 笔刷选区（mask 工具 / Agent 计划）：按住鼠标涂抹，红色 40% 半透明笔迹，
 *   Enter 确认 → emit('confirm-mask')；坐标经 Stage 逆变换换算为内容区预览坐标
 * - 对外暴露 exportScene()：以原图分辨率导出当前画布（临时 Stage 重绘，预览缩放不影响清晰度）
 */
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import Konva from 'konva'
import {
  Stage,
  Layer,
  Image as KonvaImage,
  Text as KonvaText,
  Rect as KonvaRect,
  Line as KonvaLine,
  Circle as KonvaCircle,
  Group as KonvaGroup,
  Transformer as KonvaTransformer,
} from 'vue-konva'
import { useEditorStore, type MaskStrokePoint } from '@/stores/editor'
import type { EditorLayer } from '@/api/editor'

const emit = defineEmits<{
  (e: 'confirm-mask'): void
  (e: 'upload-request'): void
}>()

const store = useEditorStore()

/** 笔刷模式是否激活：mask 工具激活 或 Agent 面板手动开启（供节点配置/事件/模板共用，需在使用前声明） */
const isMaskBrushMode = computed(() => store.isMaskBrushMode)

// vue-konva 4 在运行时通过 expose 提供 getNode()/getStage()，此处用宽松类型接收模板引用
const stageRef = ref<any>(null)
const sceneLayerRef = ref<any>(null)
const transformerRef = ref<any>(null)
const cropRectRef = ref<any>(null)
const cropTransformerRef = ref<any>(null)

// ===== 图片元素缓存（Konva Image 渲染需要 HTMLImageElement） =====
const imageEls = reactive<Record<string, HTMLImageElement | null>>({})

watch(
  () => store.sortedLayers,
  (layers) => {
    for (const layer of layers) {
      if (layer.type === 'image' && layer.url && imageEls[layer.url] === undefined) {
        imageEls[layer.url] = null
        store
          .loadImageEl(layer.url!)
          .then((el) => {
            // markRaw：避免 HTMLImageElement 被 Vue 代理，Konva drawImage 需要原始元素
            imageEls[layer.url!] = markRaw(el)
          })
          .catch(() => {
            console.error('[editor-canvas] 图层图片加载失败', layer.url)
          })
      }
    }
  },
  { immediate: true, deep: true },
)

// ===== 容器尺寸与自适应 =====
const containerEl = ref<HTMLDivElement | null>(null)
const containerSize = ref({ width: 0, height: 0 })
let resizeObserver: ResizeObserver | null = null
/** 每份新内容（新背景图）只做一次 fit-to-viewport */
let fittedForSource = false

onMounted(() => {
  if (containerEl.value) {
    resizeObserver = new ResizeObserver(() => {
      if (!containerEl.value) return
      containerSize.value = {
        width: containerEl.value.clientWidth,
        height: containerEl.value.clientHeight,
      }
    })
    resizeObserver.observe(containerEl.value)
    containerSize.value = {
      width: containerEl.value.clientWidth,
      height: containerEl.value.clientHeight,
    }
  }
})

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
  // 兜底：涂抹中鼠标在画布外释放时结束笔迹
  window.addEventListener('mouseup', handleBrushMouseUp)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('keyup', handleKeyUp)
  window.removeEventListener('mouseup', handleBrushMouseUp)
})

watch(
  () => store.sourceImage,
  () => {
    // 新内容进入：等待容器尺寸就绪后 fit 一次
    fittedForSource = false
    void nextTick(() => tryFit())
  },
)

watch(containerSize, () => tryFit())

function tryFit() {
  if (fittedForSource) return
  if (!store.sourceImage || containerSize.value.width <= 0) return
  store.fitToViewport(containerSize.value.width, containerSize.value.height)
  fittedForSource = true
}

// ===== 空格平移 =====
const isSpaceDown = ref(false)

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable
}

function handleKeyDown(e: KeyboardEvent) {
  // 笔刷模式下 Enter 确认选区（蒙版生成由父组件处理）
  if (e.code === 'Enter' && isMaskBrushMode.value) {
    if (isTypingTarget(e.target)) return
    e.preventDefault()
    emit('confirm-mask')
    return
  }
  if (e.code !== 'Space' || isSpaceDown.value) return
  if (isTypingTarget(e.target)) return
  e.preventDefault()
  isSpaceDown.value = true
}

function handleKeyUp(e: KeyboardEvent) {
  if (e.code === 'Space') isSpaceDown.value = false
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
})

// ===== Stage 配置与视口交互 =====

const stageConfig = computed(() => ({
  width: containerSize.value.width,
  height: containerSize.value.height,
  x: store.viewport.x,
  y: store.viewport.y,
  scaleX: store.viewport.scale,
  scaleY: store.viewport.scale,
  draggable: isSpaceDown.value,
}))

/** 滚轮缩放：以鼠标指针为中心（空格未按下时同样生效） */
function handleWheel(e: Konva.KonvaEventObject<WheelEvent>) {
  e.evt.preventDefault()
  const stage = stageRef.value?.getStage?.() as Konva.Stage | undefined
  if (!stage) return
  const pointer = stage.getPointerPosition()
  if (!pointer) return
  const oldScale = store.viewport.scale
  const direction = e.evt.deltaY < 0 ? 1 : -1
  const factor = direction > 0 ? 1.1 : 1 / 1.1
  const newScale = Math.min(8, Math.max(0.05, oldScale * factor))
  // 保持指针下的内容位置不变
  const mousePointTo = {
    x: (pointer.x - store.viewport.x) / oldScale,
    y: (pointer.y - store.viewport.y) / oldScale,
  }
  store.viewport = {
    scale: newScale,
    x: pointer.x - mousePointTo.x * newScale,
    y: pointer.y - mousePointTo.y * newScale,
  }
}

/** 空格拖拽结束后把 Stage 位移同步回 store 视口 */
function handleStageDragEnd() {
  const stage = stageRef.value?.getStage?.() as Konva.Stage | undefined
  if (!stage) return
  store.viewport = {
    ...store.viewport,
    x: stage.x(),
    y: stage.y(),
  }
}

/** 点击空白处取消选中；笔刷模式下按住鼠标开始涂抹 */
function handleStageMouseDown(e: Konva.KonvaEventObject<MouseEvent>) {
  if (isMaskBrushMode.value) {
    handleBrushMouseDown()
    return
  }
  if (e.target === e.target.getStage()) {
    store.selectLayer(null)
  }
}

// ===== 图层节点配置 =====

const TEXT_FONT_SIZE = 32
const TEXT_FONT_FAMILY = 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif'

function baseNodeConfig(layer: EditorLayer) {
  return {
    id: layer.id,
    x: layer.x,
    y: layer.y,
    rotation: layer.rotation ?? 0,
    opacity: layer.opacity ?? 1,
    visible: layer.visible ?? true,
    // 笔刷模式下禁止拖拽图层，避免与涂抹手势冲突
    draggable: !(layer.locked ?? false) && !isSpaceDown.value && !isMaskBrushMode.value,
  }
}

function imageNodeConfig(layer: EditorLayer) {
  return {
    ...baseNodeConfig(layer),
    image: imageEls[layer.url ?? ''] ?? undefined,
    width: layer.width,
    height: layer.height,
  }
}

function textNodeConfig(layer: EditorLayer) {
  return {
    ...baseNodeConfig(layer),
    text: layer.text ?? '',
    width: layer.width,
    fontSize: TEXT_FONT_SIZE,
    fontFamily: TEXT_FONT_FAMILY,
    fill: '#1e293b',
    wrap: 'word' as const,
  }
}

// ===== 图层拖拽 / 变换 =====

function handleDragStart(layer: EditorLayer) {
  if (layer.locked) return
  store.pushSnapshot()
}

function handleDragEnd(layer: EditorLayer, e: Konva.KonvaEventObject<DragEvent>) {
  if (layer.locked) return
  const node = e.target
  store.updateLayer(layer.id, { x: Math.round(node.x()), y: Math.round(node.y()) })
}

function handleDragMove(layer: EditorLayer, e: Konva.KonvaEventObject<DragEvent>) {
  if (layer.locked) return
  const node = e.target
  store.updateLayer(layer.id, { x: Math.round(node.x()), y: Math.round(node.y()) }, { snapshot: false })
}

function handleTransformStart(layer: EditorLayer) {
  if (layer.locked) return
  store.pushSnapshot()
}

function handleImageTransformEnd(layer: EditorLayer, e: Konva.KonvaEventObject<Event>) {
  if (layer.locked) return
  const node = e.target
  const sx = node.scaleX()
  const sy = node.scaleY()
  node.scaleX(1)
  node.scaleY(1)
  store.updateLayer(layer.id, {
    x: Math.round(node.x()),
    y: Math.round(node.y()),
    width: Math.max(8, Math.round(layer.width * sx)),
    height: Math.max(8, Math.round(layer.height * sy)),
    rotation: Math.round(node.rotation() * 100) / 100,
  })
}

function handleTextTransformEnd(layer: EditorLayer, e: Konva.KonvaEventObject<Event>) {
  if (layer.locked) return
  const node = e.target
  const sx = node.scaleX()
  const sy = node.scaleY()
  node.scaleX(1)
  node.scaleY(1)
  store.updateLayer(layer.id, {
    x: Math.round(node.x()),
    y: Math.round(node.y()),
    width: Math.max(20, Math.round(layer.width * sx)),
    height: Math.max(20, Math.round(node.height() * sy)),
    rotation: Math.round(node.rotation() * 100) / 100,
  })
}

function handleNodeMouseDown(layer: EditorLayer) {
  // 笔刷模式下点击图层不改变选中（避免涂抹时切换选区目标）
  if (isMaskBrushMode.value) return
  store.selectLayer(layer.id)
}

// ===== 选中 Transformer =====

const selectionTransformerConfig = computed(() => {
  const selected = store.selectedLayer
  const isText = selected?.type === 'text'
  return {
    rotateEnabled: true,
    keepRatio: false,
    // 文本图层只允许左右拉伸（换行宽度），避免纵向形变
    enabledAnchors: isText ? ['middle-left', 'middle-right'] : undefined,
    anchorStroke: '#4F46E5',
    anchorFill: '#ffffff',
    anchorSize: 9 / store.viewport.scale,
    anchorCornerRadius: 2 / store.viewport.scale,
    borderStroke: '#4F46E5',
    borderStrokeWidth: 1 / store.viewport.scale,
    rotateAnchorOffset: 24 / store.viewport.scale,
  }
})

function updateTransformerAttachment() {
  const tr = transformerRef.value?.getNode?.() as Konva.Transformer | undefined
  const scene = sceneLayerRef.value?.getNode?.() as Konva.Layer | undefined
  if (!tr || !scene) return
  // 笔刷模式下不挂接 Transformer（避免涂抹时出现变换框）
  if (isMaskBrushMode.value) {
    tr.nodes([])
    tr.getLayer()?.batchDraw()
    return
  }
  const id = store.selectedLayerId
  const layer = id ? store.layers.find((l) => l.id === id) : null
  const node = id ? scene.findOne<Konva.Node>('#' + id) : undefined
  if (node && layer && !(layer.locked ?? false)) {
    tr.nodes([node])
  } else {
    tr.nodes([])
  }
  tr.getLayer()?.batchDraw()
}

watch(
  [() => store.selectedLayerId, () => store.sortedLayers, isSpaceDown, isMaskBrushMode],
  () => nextTick(updateTransformerAttachment),
  { deep: true },
)

onMounted(() => {
  void nextTick(updateTransformerAttachment)
})

// ===== 裁剪矩形（crop 工具） =====

const isCropActive = computed(() => store.activeTool === 'crop')
const cropRect = ref<{ x: number; y: number; width: number; height: number } | null>(null)
/** 裁剪框交互中：暂缓 params → rect 的回写，避免抖动 */
let cropInteracting = false

watch(isCropActive, (active) => {
  if (active) {
    const w = store.stageContentWidth
    const h = store.stageContentHeight
    cropRect.value = {
      x: Math.round(w * 0.1),
      y: Math.round(h * 0.1),
      width: Math.round(w * 0.8),
      height: Math.round(h * 0.8),
    }
    syncCropToParams()
  } else {
    cropRect.value = null
  }
})

/** 裁剪框（预览坐标）→ 原图像素坐标，写入 toolParams 供执行用 */
function syncCropToParams() {
  const rect = cropRect.value
  if (!rect) return
  const scale = store.exportScale
  const naturalW = store.sourceImage?.naturalWidth ?? Math.round(rect.width * scale)
  const naturalH = store.sourceImage?.naturalHeight ?? Math.round(rect.height * scale)
  let x = Math.round(rect.x * scale)
  let y = Math.round(rect.y * scale)
  let width = Math.round(rect.width * scale)
  let height = Math.round(rect.height * scale)
  // clamp 到原图边界（backend 也会校验，这里提前保证合法）
  x = Math.min(Math.max(0, x), Math.max(0, naturalW - 1))
  y = Math.min(Math.max(0, y), Math.max(0, naturalH - 1))
  width = Math.min(Math.max(1, width), naturalW - x)
  height = Math.min(Math.max(1, height), naturalH - y)
  store.setToolParam('x', x)
  store.setToolParam('y', y)
  store.setToolParam('width', width)
  store.setToolParam('height', height)
}

/** 属性面板手改参数 → 裁剪框回显（图像素 → 预览坐标） */
watch(
  () => ({ ...store.toolParams }),
  (params) => {
    if (!isCropActive.value || cropInteracting || !cropRect.value) return
    const scale = store.exportScale
    const x = Number(params.x)
    const y = Number(params.y)
    const width = Number(params.width)
    const height = Number(params.height)
    if ([x, y, width, height].every((v) => Number.isFinite(v) && v >= 0)) {
      cropRect.value = {
        x: x / scale,
        y: y / scale,
        width: Math.max(1, width) / scale,
        height: Math.max(1, height) / scale,
      }
    }
  },
)

const cropRectConfig = computed(() => {
  const rect = cropRect.value
  const scale = store.viewport.scale
  return {
    x: rect?.x ?? 0,
    y: rect?.y ?? 0,
    width: rect?.width ?? 0,
    height: rect?.height ?? 0,
    fill: 'rgba(79, 70, 229, 0.08)',
    stroke: '#4F46E5',
    strokeWidth: 2 / scale,
    dash: [6 / scale, 4 / scale],
    draggable: true,
  }
})

const cropTransformerConfig = computed(() => {
  const scale = store.viewport.scale
  return {
    rotateEnabled: false,
    keepRatio: false,
    enabledAnchors: [
      'top-left',
      'top-center',
      'top-right',
      'middle-left',
      'middle-right',
      'bottom-left',
      'bottom-center',
      'bottom-right',
    ],
    anchorStroke: '#4F46E5',
    anchorFill: '#ffffff',
    anchorSize: 8 / scale,
    anchorCornerRadius: 2 / scale,
    borderStroke: '#4F46E5',
    borderStrokeWidth: 1 / scale,
  }
})

function handleCropDragStart() {
  cropInteracting = true
}

function handleCropDragEnd(e: Konva.KonvaEventObject<DragEvent>) {
  const node = e.target
  cropRect.value = {
    ...(cropRect.value ?? { width: 0, height: 0 }),
    x: node.x(),
    y: node.y(),
  }
  cropInteracting = false
  syncCropToParams()
}

function handleCropTransformEnd(e: Konva.KonvaEventObject<Event>) {
  const node = e.target
  const sx = node.scaleX()
  const sy = node.scaleY()
  node.scaleX(1)
  node.scaleY(1)
  cropRect.value = {
    x: node.x(),
    y: node.y(),
    width: Math.max(1, (cropRect.value?.width ?? 0) * sx),
    height: Math.max(1, (cropRect.value?.height ?? 0) * sy),
  }
  cropInteracting = false
  syncCropToParams()
}

// crop 激活时把裁剪框挂到裁剪 Transformer
watch(
  [isCropActive, cropRect],
  () =>
    nextTick(() => {
      const tr = cropTransformerRef.value?.getNode?.() as Konva.Transformer | undefined
      const rectNode = cropRectRef.value?.getNode?.() as Konva.Rect | undefined
      if (!tr) return
      tr.nodes(isCropActive.value && rectNode ? [rectNode] : [])
      tr.getLayer()?.batchDraw()
    }),
  { deep: true },
)

// ===== 笔刷选区（mask 工具 / Agent 计划） =====

/** 当前是否正在涂抹（按住鼠标） */
const isPainting = ref(false)

/**
 * 鼠标位置 → Stage 内容区预览坐标（Stage 逆变换，含缩放与平移）
 */
function getContentPointer(): MaskStrokePoint | null {
  const stage = stageRef.value?.getStage?.() as Konva.Stage | undefined
  if (!stage) return null
  const pointer = stage.getPointerPosition()
  if (!pointer) return null
  const inverted = stage.getAbsoluteTransform().copy().invert()
  const pos = inverted.point(pointer)
  return { x: pos.x, y: pos.y }
}

function handleBrushMouseDown() {
  if (!isMaskBrushMode.value || isSpaceDown.value) return
  const point = getContentPointer()
  if (!point) return
  isPainting.value = true
  store.beginMaskStroke(point)
}

function handleBrushMouseMove() {
  if (!isPainting.value || !isMaskBrushMode.value || isSpaceDown.value) return
  const point = getContentPointer()
  if (!point) return
  store.extendMaskStroke(point)
}

function handleBrushMouseUp() {
  if (!isPainting.value) return
  isPainting.value = false
  store.endMaskStroke()
}

/** 涂抹中鼠标移出画布 → 结束当前笔迹 */
function handleBrushMouseLeave() {
  if (!isPainting.value) return
  isPainting.value = false
  store.endMaskStroke()
}

/** 笔迹半透明高亮颜色（红色 40%） */
const MASK_STROKE_COLOR = 'rgba(239, 68, 68, 0.4)'

/** 笔迹渲染配置：多点 → 折线，单点 → 圆点 */
interface MaskStrokeRenderItem {
  kind: 'line' | 'dot'
  config: Record<string, unknown>
}

const maskStrokeRenderItems = computed<MaskStrokeRenderItem[]>(() => {
  const size = store.maskBrushSize
  return store.maskStrokes.map((stroke) => {
    if (stroke.length <= 1) {
      const p = stroke[0] ?? { x: -9999, y: -9999 }
      return {
        kind: 'dot' as const,
        config: {
          x: p.x,
          y: p.y,
          radius: size / 2,
          fill: MASK_STROKE_COLOR,
          listening: false,
        },
      }
    }
    return {
      kind: 'line' as const,
      config: {
        points: stroke.flatMap((p) => [p.x, p.y]),
        stroke: MASK_STROKE_COLOR,
        strokeWidth: size,
        lineCap: 'round' as const,
        lineJoin: 'round' as const,
        tension: 0,
        listening: false,
      },
    }
  })
})

/** 笔迹裁剪组：限制显示在目标图层矩形内（与蒙版生成范围一致） */
const maskClipGroupConfig = computed(() => {
  const target = store.maskTargetLayer
  if (!target) return null
  return {
    clipX: target.x,
    clipY: target.y,
    clipWidth: target.width,
    clipHeight: target.height,
  }
})

// ===== 对外暴露：原图分辨率导出 =====

/**
 * 以指定倍率导出场景图层（不含裁剪框/Transformer 等辅助元素）。
 * - 默认按原图分辨率导出：pixelRatio = 1 / store.exportScale（previewScale 即预览坐标 → 原图像素系数），
 *   Stage 的 x/y/scale 不参与离屏渲染，只有 toDataURL 的 pixelRatio 才能放大输出位图
 * - 传 1 得到预览分辨率导出（前后对比用，速度更快）
 */
async function exportScene(scaleMultiplier?: number): Promise<string | null> {
  const scene = sceneLayerRef.value?.getNode?.() as Konva.Layer | undefined
  // 只要存在带 url 的图片图层即可导出（不强制依赖背景图层）
  const hasImage = store.sortedLayers.some((l) => l.type === 'image' && !!l.url)
  if (!scene || !hasImage) return null
  const pixelRatio = scaleMultiplier ?? 1 / (store.exportScale || 1)
  // 确保所有图片元素已加载完成
  const imageLayers = store.sortedLayers.filter((l) => l.type === 'image' && l.url)
  await Promise.all(
    imageLayers.map((l) =>
      store.loadImageEl(l.url!).catch(() => null),
    ),
  )
  const tempStage = new Konva.Stage({
    // Konva Stage.toDataURL 要求挂载容器：挂临时离屏容器，导出后立即清理
    container: (() => {
      const el = document.createElement('div')
      el.style.position = 'fixed'
      el.style.left = '-99999px'
      el.style.top = '0'
      el.style.width = '0'
      el.style.height = '0'
      el.style.overflow = 'hidden'
      document.body.appendChild(el)
      return el
    })(),
    width: store.stageContentWidth,
    height: store.stageContentHeight,
  })
  // 场景层克隆直接挂到临时 Stage（Layer 只能作为 Stage 的子节点）
  tempStage.add(scene.clone())
  const dataUrl = tempStage.toDataURL({ pixelRatio })
  const containerEl = tempStage.container()
  tempStage.destroy()
  containerEl.remove()
  return dataUrl
}

defineExpose({ exportScene })
</script>

<template>
  <div
    ref="containerEl"
    class="relative flex-1 min-w-0 h-full overflow-hidden canvas-checkerboard"
    :class="isSpaceDown
      ? 'cursor-grab active:cursor-grabbing'
      : isMaskBrushMode ? 'cursor-crosshair' : 'cursor-default'"
  >
    <Stage
      ref="stageRef"
      :config="stageConfig"
      @wheel="handleWheel"
      @mousedown="handleStageMouseDown"
      @mousemove="handleBrushMouseMove"
      @mouseup="handleBrushMouseUp"
      @mouseleave="handleBrushMouseLeave"
      @dragend="handleStageDragEnd"
    >
      <!-- 场景层：文档图层（渲染顺序 = z 升序） -->
      <Layer ref="sceneLayerRef">
        <template v-for="layer in store.sortedLayers" :key="layer.id">
          <KonvaImage
            v-if="layer.type === 'image' && imageEls[layer.url ?? '']"
            :config="imageNodeConfig(layer)"
            @mousedown="handleNodeMouseDown(layer)"
            @dragstart="handleDragStart(layer)"
            @dragmove="handleDragMove(layer, $event)"
            @dragend="handleDragEnd(layer, $event)"
            @transformstart="handleTransformStart(layer)"
            @transformend="handleImageTransformEnd(layer, $event)"
          />
          <KonvaText
            v-else-if="layer.type === 'text'"
            :config="textNodeConfig(layer)"
            @mousedown="handleNodeMouseDown(layer)"
            @dragstart="handleDragStart(layer)"
            @dragmove="handleDragMove(layer, $event)"
            @dragend="handleDragEnd(layer, $event)"
            @transformstart="handleTransformStart(layer)"
            @transformend="handleTextTransformEnd(layer, $event)"
          />
        </template>
      </Layer>

      <!-- 覆盖层：选中框 / 裁剪框 -->
      <Layer>
        <template v-if="isCropActive && cropRect">
          <KonvaRect
            ref="cropRectRef"
            :config="cropRectConfig"
            @dragstart="handleCropDragStart"
            @dragend="handleCropDragEnd"
            @transformstart="handleCropDragStart"
            @transformend="handleCropTransformEnd"
          />
          <KonvaTransformer ref="cropTransformerRef" :config="cropTransformerConfig" />
        </template>
        <KonvaTransformer v-else ref="transformerRef" :config="selectionTransformerConfig" />
      </Layer>

      <!-- 覆盖层：笔刷涂抹笔迹（裁剪到目标图层矩形） -->
      <Layer v-if="isMaskBrushMode && maskClipGroupConfig" :listening="false">
        <KonvaGroup :config="maskClipGroupConfig">
          <template v-for="(item, i) in maskStrokeRenderItems" :key="i">
            <KonvaLine v-if="item.kind === 'line'" :config="item.config" />
            <KonvaCircle v-else :config="item.config" />
          </template>
        </KonvaGroup>
      </Layer>
    </Stage>

    <!-- 笔刷模式提示 -->
    <div
      v-if="isMaskBrushMode"
      class="absolute top-4 left-1/2 -translate-x-1/2 z-20 px-3 py-1.5 rounded-full bg-white/95 backdrop-blur-xl shadow-card-hover border border-slate-100 text-xs text-slate-600 pointer-events-none"
    >
      笔刷选区：按住鼠标在目标图层上涂抹，Enter 确认生成蒙版
    </div>

    <!-- 空画布占位：可直接上传本地图片作为底图开始编辑 -->
    <div
      v-if="!store.sourceImage"
      class="absolute inset-0 flex items-center justify-center p-6"
    >
      <div
        class="flex flex-col items-center text-center px-8 py-7 rounded-2xl bg-white/90 backdrop-blur-xl border border-slate-200 shadow-card"
      >
        <p class="text-sm text-slate-600">尚未加载图片</p>
        <p class="text-xs mt-1 text-slate-400">通过 /editor?imageId=xxx 进入可加载历史图片</p>
        <p class="text-xs mt-1 text-slate-400">也可从历史记录 / 工作台结果带图进入，或直接上传本地图片</p>
        <button
          type="button"
          class="btn-primary px-4 py-2 text-sm mt-4"
          @click="emit('upload-request')"
        >
          上传图片开始编辑
        </button>
      </div>
    </div>
  </div>
</template>
