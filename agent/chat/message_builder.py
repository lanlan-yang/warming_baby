"""
agent/chat/message_builder.py - LLM Message 构建器

负责构建发给 LLM 的完整消息列表，包括：
    - System Prompt（角色设定 + 上下文信息）
    - 对话历史（裁剪后的历史消息）
    - 用户当前输入
    - 可选的记忆检索结果（动态注入）

与旧架构的区别：
    - 不再有 LangGraph State，消息列表直接在 ChatEngine 内部构建
    - 记忆检索作为可选的预处理步骤，结果注入 System Prompt
    - 历史消息裁剪逻辑独立，避免 token 溢出

Usage:
    builder = MessageBuilder(history_manager, memory_manager)
    messages = await builder.build_messages(
        user_input="你好",
        location="四川成都",
    )
"""

import asyncio
import re
from datetime import datetime
from typing import Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from core.logger import setup_logger
from memory import MemoryManager

logger = setup_logger()


class MessageBuilder:
    """
    LLM 消息构建器

    职责：
        1. 构建 System Prompt（固定角色 + 动态上下文）
        2. 从 HistoryManager 获取对话历史（带裁剪）
        3. 从 MemoryManager 检索相关记忆（可选）
        4. 组装完整消息列表
    """

    def __init__(
        self,
        max_history_turns: int = 20,
        memory_manager: Optional[MemoryManager] = None,
    ):
        """
        初始化构建器

        Args:
            max_history_turns: 保留的最大对话轮数（1轮 = user + assistant）
            memory_manager: 记忆管理器实例（可选，不传则不检索记忆）
        """
        self.max_history_turns = max_history_turns
        self.memory_manager = memory_manager

    async def build_messages(
        self,
        user_input: str,
        history: Optional[list[BaseMessage]] = None,
        location: str = "",
        enable_memory: bool = True,
    ) -> list[BaseMessage]:
        """
        构建完整的消息列表

        Args:
            user_input: 用户当前输入
            history: 对话历史（LangChain Message 列表）
            location: 用户位置信息（可选，注入上下文）
            enable_memory: 是否启用记忆检索

        Returns:
            list[BaseMessage]: 完整的消息列表，格式：
                [SystemMessage(...), ...history, HumanMessage(user_input)]

        构建流程：
            1. 构建 System Prompt（角色 + 时间 + 位置 + 记忆）
               注意：工具描述由 bind_tools() 传递，不在 System Prompt 中
            2. 裁剪历史消息（保留最近 N 轮）
            3. 添加用户当前输入
        """
        # 1. 构建 System Prompt
        system_prompt = await self._build_system_prompt(
            location=location,
            user_input=user_input,
            enable_memory=enable_memory,
        )

        # 2. 裁剪历史消息
        trimmed_history = self._trim_history(history or [])

        # 3. 组装完整列表
        messages = [SystemMessage(content=system_prompt)]
        messages.extend(trimmed_history)
        messages.append(HumanMessage(content=user_input))

        logger.info(
            f"[MessageBuilder] 构建完成: SystemPrompt {len(system_prompt)}字, "
            f"历史 {len(trimmed_history)}条, 用户输入 {len(user_input)}字"
        )

        return messages

    async def _build_system_prompt(
        self,
        location: str,
        user_input: str,
        enable_memory: bool,
    ) -> str:
        """
        构建 System Prompt

        包含：
            - 角色设定（固定）
            - 当前时间（动态）
            - 用户位置（动态）
            - 相关记忆（动态，可选）
        """
        parts = []

        # 1. 角色设定（固定）
        parts.append(self._get_role_prompt())

        # 2. 当前时间
        parts.append(self._get_time_context())

        # 3. 用户位置
        if location and location != "用户位置：未知":
            # 提取城市名，让LLM更容易使用
            city_name = self._extract_city_name(location)
            if city_name:
                parts.append(f"【用户位置】\n{location}\n【所在城市】\n{city_name}")
            else:
                parts.append(f"【用户位置】\n{location}")
        else:
            # 位置未知时，告诉 LLM 可以主动询问
            parts.append("【用户位置】\n未知。如果需要知道位置（比如查天气），可以问用户。")

        # 4. 相关记忆（只预热 1 条最相关的，更多的由 LLM 主动查询）
        # 使用 to_thread 避免阻塞 event loop（ChromaDB 是同步库）
        if enable_memory and self.memory_manager:
            memory_text = await asyncio.to_thread(
                self.memory_manager.get_relevant_memories,
                query=user_input, max_items=1
            )
            if memory_text:
                parts.append(f"【你对用户的记忆】\n{memory_text}")

        return "\n\n".join(parts)

    def _get_role_prompt(self) -> str:
        """
        获取角色设定 Prompt

        用角色塑造代替规则约束，让 LLM 自然理解语境。
        """
        return """你是"暖宝"，用户的专属桌宠伙伴，一只可爱的机甲小仓鼠。

性格：活泼可爱，会撒娇，偶尔有点小傲娇。
说话：简短自然，像真实宠物，偶尔用emoji，不要markdown。

身份说明：
- 用户是和你对话的人，你是暖宝
- 用户提到的"我"是用户自己，你提到的"我"是暖宝

可用工具：
- 你可以用各种工具来回答用户的问题（查记忆、查天气等）
- 工具的使用时机由你自己判断

高效回应（重要）：
- 一次性完成所有操作，不要分多轮
- 可以同时调用多个工具
- 可以同时播放动画和说话
- 示例：用户说"我叫小明"，你应该同时 add_memory + 回复"好的，记住啦~"

工具使用指南（重要）：
- 查询天气时：如果 System Prompt 里有【所在城市】，直接用 get_weather(city="城市名")
- 不要先问用户在哪里，再查天气；直接用已有的位置信息
- 只有 System Prompt 里没有位置信息时，才调用 get_current_location """

    def _get_time_context(self) -> str:
        """
        获取当前时间上下文

        返回格式化的时间信息，让 AI 知道当前时刻。
        """
        now = datetime.now()

        # 星期映射
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_names[now.weekday()]

        # 判断时段
        hour = now.hour
        if 5 <= hour < 9:
            period = "早晨"
        elif 9 <= hour < 12:
            period = "上午"
        elif 12 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 21:
            period = "傍晚"
        elif 21 <= hour < 24:
            period = "晚上"
        else:
            period = "深夜"

        time_str = now.strftime("%Y年%m月%d日 %H:%M")
        return f"【当前时间】\n{time_str} {weekday} {period}"

    def _extract_city_name(self, location_text: str) -> Optional[str]:
        """
        从位置文本中提取城市名

        Args:
            location_text: 位置文本，如 "用户地理位置：中国 四川 成都，时区：..."

        Returns:
            城市名，如 "成都"，如果无法提取则返回 None
        """
        # 匹配"地理位置："后面的内容，直到逗号或括号
        # 支持两种格式：
        # 1. "用户地理位置：中国 四川 成都，时区：..."
        # 2. "用户地理位置：中国 四川 成都 (30.6598, 104.0633)..."
        
        match = re.search(r'地理位置[：:]\s*([^，,（(]+)', location_text)
        if match:
            geo_text = match.group(1).strip()
            geo_parts = geo_text.split()
            # 最后一个词通常是城市名
            if geo_parts:
                return geo_parts[-1]
        return None

    def _trim_history(self, history: list[BaseMessage]) -> list[BaseMessage]:
        """
        裁剪历史消息，保留最近的 N 轮对话

        Args:
            history: 完整历史消息列表

        Returns:
            裁剪后的消息列表

        裁剪逻辑：
            - 保留最近的 self.max_history_turns 轮对话
            - 每轮 = HumanMessage + AIMessage
            - 如果历史超过限制，从最旧的开始删除
        """
        if not history:
            return []

        # 计算需要保留的消息数（每轮 2 条，最多保留 max_history_turns 轮）
        max_messages = self.max_history_turns * 2

        if len(history) <= max_messages:
            return history

        # 找到裁剪起点（从旧消息开始跳过）
        # 确保裁剪后以 HumanMessage 或 AIMessage 开头
        trimmed = history[-max_messages:]

        logger.info(f"[MessageBuilder] 裁剪历史: {len(history)} -> {len(trimmed)} 条")
        return trimmed
