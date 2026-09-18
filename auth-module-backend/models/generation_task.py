"""生成任务数据模型"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class ImageType(str, Enum):
    """图片类型枚举（专业模式支持 9 类）"""
    MAIN_IMAGE = "main_image"             # 主图
    SUB_IMAGE = "sub_image"               # 副图
    WHITE_BG = "white_bg"                 # 白底图
    SCENE = "scene"                       # 场景图
    SELLING_POINT = "selling_point"       # 卖点图
    CHECKLIST = "checklist"               # 清单图
    MATERIAL = "material"                 # 材质图
    SIZE_CHART = "size_chart"             # 尺寸图
    OTHER = "other"                       # 其他


class SchemeStatus(str, Enum):
    """提示词方案状态机"""
    PENDING = "pending"           # 待处理
    ANALYZING = "analyzing"       # AI 分析整合中
    OPTIMIZING = "optimizing"     # 对话优化中
    CONFIRMED = "confirmed"       # 已确认
    LOCKED = "locked"             # 已锁定（触发生图）
    FAILED = "failed"             # 分析失败


# 图片类型中文映射
IMAGE_TYPE_LABEL_CN = {
    ImageType.MAIN_IMAGE: "主图",
    ImageType.SUB_IMAGE: "副图",
    ImageType.WHITE_BG: "白底图",
    ImageType.SCENE: "场景图",
    ImageType.SELLING_POINT: "卖点图",
    ImageType.CHECKLIST: "清单图",
    ImageType.MATERIAL: "材质图",
    ImageType.SIZE_CHART: "尺寸图",
    ImageType.OTHER: "其他",
}


# 文案需求标记：True=必须文案，False=无文案，None=可选
IMAGE_TYPE_COPY_REQUIRED = {
    ImageType.MAIN_IMAGE: False,
    ImageType.SUB_IMAGE: False,
    ImageType.WHITE_BG: False,
    ImageType.SCENE: False,
    ImageType.SELLING_POINT: True,
    ImageType.CHECKLIST: True,
    ImageType.MATERIAL: None,
    ImageType.SIZE_CHART: True,
    ImageType.OTHER: None,
}


@dataclass
class LayoutPrompt:
    """排版提示词（控制版式/构图/背景/角标等视觉结构）"""
    product_state: str = ""        # 商品状态/角度
    composition: str = ""          # 构图方式
    background: str = ""           # 背景描述
    corner_badge: str = ""        # 角标
    visual_focus: str = ""         # 视觉重心

    def to_dict(self) -> dict:
        return {
            "product_state": self.product_state,
            "composition": self.composition,
            "background": self.background,
            "corner_badge": self.corner_badge,
            "visual_focus": self.visual_focus,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LayoutPrompt":
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            product_state=data.get("product_state", ""),
            composition=data.get("composition", ""),
            background=data.get("background", ""),
            corner_badge=data.get("corner_badge", ""),
            visual_focus=data.get("visual_focus", ""),
        )


@dataclass
class CopyContent:
    """文案内容（主标题/副标题/标签）"""
    main_title: str = ""
    sub_title: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "main_title": self.main_title,
            "sub_title": self.sub_title,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CopyContent":
        if not data or not isinstance(data, dict):
            return cls()
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = [str(tags)] if tags else []
        return cls(
            main_title=data.get("main_title", ""),
            sub_title=data.get("sub_title", ""),
            tags=[str(t) for t in tags],
        )


@dataclass
class PromptScheme:
    """提示词方案：单张图片的完整结构化配置"""
    image_name: str = ""            # 图片名称
    image_role: str = ""            # 图片定位/作用说明
    layout_prompt: LayoutPrompt = field(default_factory=LayoutPrompt)
    copy: CopyContent = field(default_factory=CopyContent)

    def to_dict(self) -> dict:
        return {
            "image_name": self.image_name,
            "image_role": self.image_role,
            "layout_prompt": self.layout_prompt.to_dict(),
            "copy": self.copy.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PromptScheme":
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            image_name=data.get("image_name", ""),
            image_role=data.get("image_role", ""),
            layout_prompt=LayoutPrompt.from_dict(data.get("layout_prompt")),
            copy=CopyContent.from_dict(data.get("copy")),
        )

    def is_empty(self) -> bool:
        """判断方案是否为空（需 AI 补全）"""
        return not (self.image_name or self.image_role
                   or self.layout_prompt.product_state
                   or self.layout_prompt.composition
                   or self.layout_prompt.background)


@dataclass
class DialogMessage:
    """对话消息"""
    role: str = "user"              # user / assistant
    content: str = ""

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ProTaskState:
    """专业模式单任务状态（含方案/对话/版本）"""
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    image_type: ImageType = ImageType.OTHER
    image_type_label: str = ""              # 图片类型中文名
    aspect_ratio: str = "1:1"               # 比例
    prompt_scheme: PromptScheme = field(default_factory=PromptScheme)
    scheme_status: SchemeStatus = SchemeStatus.PENDING
    dialog_history: List[Dict[str, str]] = field(default_factory=list)
    scheme_versions: List[Dict[str, Any]] = field(default_factory=list)  # 版本快照
    prompt_used: str = ""                   # 最终构建的生图提示词
    image_url: Optional[str] = None
    error_msg: Optional[str] = None
    gen_status: TaskStatus = TaskStatus.PENDING  # 生图状态

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_name": self.prompt_scheme.image_name or "",
            "image_type": self.image_type.value,
            "image_type_label": self.image_type_label or IMAGE_TYPE_LABEL_CN.get(self.image_type, ""),
            "aspect_ratio": self.aspect_ratio,
            "scheme": self.prompt_scheme.to_dict(),
            "status": self.scheme_status.value,
            "dialog_history": self.dialog_history,
            "version_snapshots": self.scheme_versions,
            "generation_task_id": None,
            "prompt_used": self.prompt_used,
            "result_url": self.image_url,
            "error_message": self.error_msg,
            "gen_status": self.gen_status.value,
            "created_at": "",
            "updated_at": "",
        }


@dataclass
class GenerationTask:
    """单张图片生成任务（简单模式）"""
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    batch_id: str = ""
    image_type: ImageType = ImageType.WHITE_BG
    slot_index: int = 0          # 在该类型中的序号
    slot_name: str = ""          # 用户自定义名称（仅 other 类型使用）
    slot_desc: str = ""          # 用户自定义描述（仅 other 类型使用）
    status: TaskStatus = TaskStatus.PENDING
    prompt_used: str = ""        # 最终使用的生图 prompt
    image_url: Optional[str] = None
    error_msg: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "batch_id": self.batch_id,
            "image_type": self.image_type.value,
            "slot_index": self.slot_index,
            "slot_name": self.slot_name,
            "slot_desc": self.slot_desc,
            "status": self.status.value,
            "prompt_used": self.prompt_used,
            "image_url": self.image_url,
            "error_msg": self.error_msg,
        }


@dataclass
class ProductInfo:
    """商品信息（AI分析结果）"""
    product_name: str = ""
    target_audience: str = ""
    selling_points: str = ""
    usage_scenario: str = ""
    product_category: str = ""
    # P0-1 双语卖点（可选）：[{title_en, desc_en, visual_keywords}]，缺省 None 向后兼容
    selling_points_en: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> dict:
        return {
            "product_name": self.product_name,
            "target_audience": self.target_audience,
            "selling_points": self.selling_points,
            "usage_scenario": self.usage_scenario,
            "product_category": self.product_category,
            "selling_points_en": self.selling_points_en,
        }

    def is_complete(self) -> bool:
        """检查所有字段是否都非空"""
        return all([
            self.product_name,
            self.target_audience,
            self.selling_points,
            self.usage_scenario,
            self.product_category,
        ])
