"""
agent/chat/engine.py - TurnEngine 核心引擎

Loop 风格的 LLM+Tool 循环引擎。
不再依赖 LangGraph，用简单的 while 循环实现 LLM 自主决策。

核心逻辑：
    1. LLM 收到消息和工具列表（tool_choice=auto）
    2. 如果 LLM 返回 tool_calls -> 执行工具 -> 结果塞回消息 -> 回到第 1 步
    3. 如果 LLM 没有返回 tool_calls -> 用 with_structured_output 输出结构化结果 -> 结束

优化：
    - 最后一轮直接返回 ChatResponse，省掉 ResponseExtractor 的额外调用
    - 同时解决了 play_animation 工具需要额外一次 LLM 调用的问题

Usage:
    from agent.chat.engine import TurnEngine

    engine = TurnEngine(llm=my_llm, tools=[weather_tool])
    messages = [SystemMessage("..."), HumanMessage("成都今天天气")]
    result = await engine.run(messages)  # 返回 ChatResponse
"""

import asyncio
from typing import Optional, Union

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    BaseMessage,
)
from langchain_core.language_models import BaseChatModel

from core.logger import setup_logger
from tools.tool_base import AgentTool
from .chat_schema import ChatResponse

logger = setup_logger()

class TurnEngine:
    """
    LLM+Tool 循环引擎

    每次 run() 调用是一轮完整的对话：
        - 前几轮：LLM 可以调用工具
        - 最后一轮：LLM 返回结构化的 ChatResponse（包含 text, emotion, new_memories）
        - 最多执行 max_turns 次工具调用后强制返回
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: Optional[list[AgentTool]] = None,
        max_turns: int = 5,
    ):
        """
        初始化引擎

        Args:
            llm: LangChain ChatModel 实例（如 ChatOpenAI / ChatDeepSeek）
            tools: 工具列表，不传则只能纯对话
            max_turns: 最大工具调用轮次，防止死循环
        """
        self.llm = llm
        self.tools = tools or []
        self.max_turns = max_turns

        # 构建工具查找表：name -> tool
        self._tool_map = {t.name: t for t in self.tools}

        # 如果有工具，提前绑定
        self._llm_with_tools = self.llm.bind_tools(self.tools) if self.tools else None

        # 预构建结构化输出（用于最后一轮）
        self._structured_llm = self.llm.with_structured_output(
            ChatResponse, method="function_calling"
        )

    async def run(
        self,
        messages: list[BaseMessage],
        tool_choice: str = "auto",
    ) -> ChatResponse:
        """
        执行一轮对话

        Args:
            messages: 消息列表（SystemMessage + HumanMessage + 历史）
            tool_choice: 工具选择策略
                - "auto": LLM 自主决定（推荐）
                - "none": 禁止工具调用
                - "required": 强制调工具

        Returns:
            ChatResponse: 结构化的聊天响应（包含 text, emotion, new_memories）

        执行流程：
            for turn in range(max_turns):
                1. LLM 生成回复
                2. 如果有 tool_calls -> 执行工具 -> 继续循环
                3. 如果没有 tool_calls -> 用结构化输出重生成 -> 返回 ChatResponse
            如果 max_turns 用完了 -> 强制返回结构化响应
        """
        logger.info(f"[TurnEngine] 开始执行对话，消息数: {len(messages)}, 工具数: {len(self.tools)}")

        # 决定用哪个 LLM（前几轮可以用工具，最后一轮用结构化）
        llm_for_tools = self._llm_with_tools if (self.tools and tool_choice != "none") else self.llm

        current_messages = list(messages)
        last_ai_message = None

        for turn in range(self.max_turns):
            # 1. 调用 LLM（可以用工具）
            logger.info(f"[TurnEngine] 第 {turn + 1} 次 LLM 调用")
            response = await llm_for_tools.ainvoke(current_messages)

            # 2. 如果有 tool_calls，执行工具，继续循环
            if response.tool_calls:
                logger.info(f"[TurnEngine] LLM 请求 {len(response.tool_calls)} 个工具调用")
                current_messages.append(response)

                tool_results = await self._execute_tool_calls(response.tool_calls)
                current_messages.extend(tool_results)
                continue  # 继续下一轮

            # 3. 没有 tool_calls，这是最后一轮，用结构化输出
            last_ai_message = response
            logger.info(f"[TurnEngine] LLM 准备生成最终响应")
            break

        # 如果用完了 max_turns，也用最后一次的结果
        if last_ai_message is None:
            logger.warning(f"[TurnEngine] 达到最大轮次 {self.max_turns}，强制返回")
            last_ai_message = response

        # 用结构化输出生成最终的 ChatResponse
        return await self._generate_structured_response(current_messages, last_ai_message)

    async def _generate_structured_response(
        self,
        messages: list[BaseMessage],
        last_ai_message: AIMessage,
    ) -> ChatResponse:
        """
        生成结构化响应

        用 with_structured_output 让 LLM 返回 ChatResponse 格式。
        这样可以同时获得 text, emotion, new_memories。

        Args:
            messages: 完整的消息历史
            last_ai_message: 最后一次 AI 回复（用于 fallback）

        Returns:
            ChatResponse: 结构化的聊天响应
        """
        try:
            logger.info("[TurnEngine] 生成结构化响应")
            
            # 添加一个额外的系统提示，告诉 LLM 现在需要输出最终结果
            final_instruction = SystemMessage(
                content="请根据之前的对话和工具调用结果，直接给出最终回复。"
                        "现在不能再调用任何工具了，你需要输出 ChatResponse 格式的结果，"
                        "包含 text（回复内容）、emotion（情绪）、new_memories（记忆）。"
            )
            
            structured_messages = messages + [final_instruction]
            result = await self._structured_llm.ainvoke(structured_messages)
            logger.info(
                f"[TurnEngine] 响应生成成功: emotion={result.emotion}, "
                f"memories={len(result.new_memories)}"
            )
            return result

        except Exception as e:
            logger.error(f"[TurnEngine] 结构化响应失败，使用 fallback: {e}")
            return self._fallback_response(last_ai_message)

    def _fallback_response(self, ai_message: AIMessage) -> ChatResponse:
        """
        Fallback 响应：当结构化生成失败时

        用关键词匹配判断 emotion，new_memories 返回空。
        """
        from .chat_schema import Emotion

        content = ai_message.content if ai_message.content else ""

        # 简单的关键词匹配
        emotion_keywords = {
            Emotion.HAPPY: ["哈哈", "开心", "😊", "😄"],
            Emotion.SAD: ["难过", "伤心", "😢"],
            Emotion.ANGRY: ["生气", "讨厌", "😠"],
            Emotion.SLEEP: ["困", "累", "😴"],
            Emotion.PLAY: ["玩", "🎉"],
        }

        emotion = Emotion.NEUTRAL
        for emo, keywords in emotion_keywords.items():
            if any(kw in content for kw in keywords):
                emotion = emo
                break

        return ChatResponse(
            text=content,
            emotion=emotion,
            new_memories=[],
        )

    async def _execute_tool_calls(
        self,
        tool_calls: list[dict],
    ) -> list[ToolMessage]:
        """
        并发执行多个工具调用

        Args:
            tool_calls: LangChain 格式的工具调用列表
                每个元素: {"name": "get_weather", "args": {"city": "成都"}, "id": "call_xxx"}

        Returns:
            list[ToolMessage]: 工具执行结果，按 tool_call_id 对应

        说明：
            - 并发执行，提高效率
            - 单个工具失败不影响其他工具（返回错误信息）
        """
        async def execute_single(call: dict) -> ToolMessage:
            tool_name = call["name"]
            tool_args = call.get("args", {})
            tool_call_id = call["id"]

            tool = self._tool_map.get(tool_name)
            if not tool:
                error_msg = f"工具 {tool_name} 不存在"
                logger.error(f"[TurnEngine] {error_msg}")
                return ToolMessage(error_msg, tool_call_id=tool_call_id)

            try:
                logger.info(f"[TurnEngine] 执行工具 {tool_name}: {tool_args}")
                result = await tool.ainvoke(tool_args)
                logger.info(f"[TurnEngine] 工具 {tool_name} 完成")
                return ToolMessage(str(result), tool_call_id=tool_call_id)
            except Exception as e:
                error_msg = f"工具 {tool_name} 执行失败: {str(e)}"
                logger.error(f"[TurnEngine] {error_msg}")
                return ToolMessage(error_msg, tool_call_id=tool_call_id)

        # 并发执行所有工具调用
        tasks = [execute_single(call) for call in tool_calls]
        results = await asyncio.gather(*tasks)

        return results

    def add_tool(self, tool: AgentTool) -> None:
        """动态添加工具（运行时可扩展）"""
        self.tools.append(tool)
        self._tool_map[tool.name] = tool
        self._llm_with_tools = self.llm.bind_tools(self.tools)
        logger.info(f"[TurnEngine] 动态添加工具: {tool.name}")

    def remove_tool(self, name: str) -> bool:
        """动态移除工具"""
        if name not in self._tool_map:
            return False
        self.tools = [t for t in self.tools if t.name != name]
        self._tool_map.pop(name)
        self._llm_with_tools = self.llm.bind_tools(self.tools) if self.tools else None
        logger.info(f"[TurnEngine] 动态移除工具: {name}")
        return True

    @property
    def tool_names(self) -> list[str]:
        """当前可用工具名称列表"""
        return list(self._tool_map.keys())
