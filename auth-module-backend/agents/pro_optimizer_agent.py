"""专业模式方案优化 Agent

负责：
1. 管理多轮对话上下文，维护优化记忆
2. 理解用户优化意图，渐进式改进提示词方案
3. 调用 LLM 生成优化后的方案并给出自然语言回复
"""
import json
from typing import Dict, Any, List, Optional
from services.generation_service import call_llm_chat, _extract_json_from_text


# 图片类型对应的角色描述
_IMAGE_TYPE_ROLE_DESC = {
    "main_image": "商品主图，决定点击率，需突出商品主体",
    "sub_image": "商品副图，补充展示商品多角度",
    "white_bg": "白底图，纯白背景商品展示",
    "scene": "场景图，生活化场景展示商品",
    "selling_point": "卖点图，突出商品核心卖点与文案",
    "checklist": "清单图，展示商品参数/清单信息",
    "material": "材质图，材质细节特写展示",
    "size_chart": "尺寸图，尺寸说明参考图",
    "other": "其他类型商品展示图",
}


class ProOptimizerAgent:
    """专业模式方案优化 Agent

    每个 batch+task 组合对应一个 Agent 实例，
    维护对话记忆，理解用户意图，渐进式优化方案。
    """

    def __init__(self, task_context: Dict[str, Any]):
        self.task_id = task_context.get("task_id", "")
        self.image_type = task_context.get("image_type", "other")
        self.image_type_label = task_context.get("image_type_label", "")
        self.platform = task_context.get("platform", "")
        self.region = task_context.get("region", "")
        self.target_language = task_context.get("target_language", "英语")
        self.product_info = task_context.get("product_info", {})
        # 记忆存储：记录关键优化决策
        self.memory: List[Dict[str, str]] = []

    def optimize(
        self,
        current_scheme: Dict[str, Any],
        user_input: str,
        dialog_history: Optional[List[Dict[str, str]]] = None,
        user_id: int = None,
    ) -> Dict[str, Any]:
        """执行一轮优化，返回优化后的方案 + AI 回复

        Args:
            current_scheme: 当前提示词方案 JSON
            user_input: 用户本轮输入的优化指令
            dialog_history: 对话历史 [{role, content}, ...]
            user_id: 用户 ID（BYOK：按用户自备通道号池依次尝试；None 时走平台通道）

        Returns:
            {"scheme": {...}, "reply": "AI 回复文本"}
        """
        # 1. 构建系统提示词
        system_prompt = self._build_system_prompt()

        # 2. 构建用户消息（含当前方案、记忆、历史、本轮指令）
        user_content = self._build_user_content(
            current_scheme, user_input, dialog_history
        )

        # 3. 调用 LLM
        raw_response = call_llm_chat(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.4,
            max_tokens=2000,
            user_id=user_id,
        )

        # 4. 解析响应（方案 + 回复文本）
        result = self._parse_response(raw_response, current_scheme)

        # 5. 更新记忆
        self._update_memory(user_input, result.get("reply", ""))

        return result

    def _build_system_prompt(self) -> str:
        role_desc = _IMAGE_TYPE_ROLE_DESC.get(self.image_type, "商品展示图")
        product_name = self.product_info.get("product_name", "商品")
        image_type_label = self.image_type_label or self.image_type
        target_lang = self.target_language
        return f"""你是一位专业的电商商品图提示词优化专家，正在帮助用户优化「{image_type_label}」（{role_desc}）的提示词方案。

当前商品：{product_name}
目标平台：{self.platform}
目标市场：{self.region}
图片文案语言：{target_lang}

你的任务：
1. 理解用户的优化指令（如"把背景改成浅灰色"、"添加促销角标"、"突出产品质感"等）
2. 基于当前方案，返回修改后的完整方案
3. 用自然语言简要回复用户，确认你做了什么修改

输出格式要求：
你必须返回一个 JSON 对象，包含两个字段：
{{
  "scheme": {{ ... 完整方案 JSON ... }},
  "reply": "你的自然语言回复，简要说明做了哪些修改"
}}

scheme 字段结构：
{{
  "image_name": "图片名称",
  "image_role": "图片定位/作用说明",
  "layout_prompt": {{
    "product_state": "商品呈现状态",
    "composition": "构图方式",
    "background": "背景描述",
    "corner_badge": "角标/装饰元素",
    "visual_focus": "视觉焦点"
  }},
  "copy": {{
    "main_title": "主标题",
    "sub_title": "副标题",
    "tags": ["标签1", "标签2"]
  }}
}}

规则：
- 文案字段（main_title, sub_title, tags）使用 {target_lang}
- layout_prompt 字段使用英文描述
- 仅修改用户指令涉及的字段，其他字段保持原样
- reply 不超过 150 字，用中文回复
- 输出 ONLY 一个合法 JSON 对象，不要 markdown 代码块包裹，不要额外解释"""

    def _build_user_content(
        self,
        current_scheme: Dict[str, Any],
        user_input: str,
        dialog_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        parts = []

        # 当前方案
        parts.append(
            f"当前提示词方案：\n{json.dumps(current_scheme, ensure_ascii=False, indent=2)}"
        )

        # 历史优化记忆（Agent 内部记忆，非完整对话历史）
        if self.memory:
            memory_text = "\n".join(
                f"- {m.get('summary', '')}" for m in self.memory[-5:]
            )
            parts.append(f"\n优化历史摘要：\n{memory_text}")

        # 对话历史（最近 10 轮）
        if dialog_history:
            history_text = "\n".join(
                f"{'用户' if m.get('role') == 'user' else '助手'}: {m.get('content', '')}"
                for m in dialog_history[-10:]
            )
            parts.append(f"\n对话历史：\n{history_text}")

        # 本轮指令
        parts.append(f"\n用户本轮指令：{user_input}")
        parts.append("\n请返回包含 scheme 和 reply 的 JSON 对象。")

        return "\n".join(parts)

    def _parse_response(
        self, raw_response: str, current_scheme: Dict[str, Any]
    ) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON，提取 scheme 和 reply"""
        try:
            parsed = _extract_json_from_text(raw_response)
        except Exception:
            # 解析失败，尝试只提取 scheme 部分
            parsed = _extract_json_from_text(raw_response)

        scheme = parsed.get("scheme", {})
        reply = parsed.get("reply", "已根据您的指令更新提示词方案")

        # 字段兜底：保留未修改字段的原始值
        scheme.setdefault("image_name", current_scheme.get("image_name", ""))
        scheme.setdefault("image_role", current_scheme.get("image_role", ""))
        scheme.setdefault("layout_prompt", {})
        scheme.setdefault("copy", {})

        lp = scheme["layout_prompt"]
        old_lp = current_scheme.get("layout_prompt", {})
        lp.setdefault("product_state", old_lp.get("product_state", ""))
        lp.setdefault("composition", old_lp.get("composition", ""))
        lp.setdefault("background", old_lp.get("background", ""))
        lp.setdefault("corner_badge", old_lp.get("corner_badge", "none"))
        lp.setdefault("visual_focus", old_lp.get("visual_focus", ""))

        cp = scheme["copy"]
        old_cp = current_scheme.get("copy", {})
        cp.setdefault("main_title", old_cp.get("main_title", ""))
        cp.setdefault("sub_title", old_cp.get("sub_title", ""))
        cp.setdefault("tags", old_cp.get("tags", []))

        return {"scheme": scheme, "reply": reply}

    def _update_memory(self, user_input: str, ai_reply: str) -> None:
        """更新 Agent 内部记忆，记录关键决策摘要"""
        summary = f"用户要求：{user_input[:80]}"
        self.memory.append({
            "user_input": user_input,
            "summary": summary,
            "reply_brief": ai_reply[:80],
        })
        # 保留最近 20 条记忆
        if len(self.memory) > 20:
            self.memory = self.memory[-20:]

    def summarize_memory(self) -> str:
        """将记忆压缩为摘要文本，供外部上下文使用"""
        if not self.memory:
            return "无历史优化记录"
        return "\n".join(
            f"{i+1}. {m.get('summary', '')}"
            for i, m in enumerate(self.memory)
        )