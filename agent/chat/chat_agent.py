"""
agent/chat/chat_agent.py - ChatAgent 核心类

使用 LangGraph ReAct 架构实现 LLM 自主决策。

架构：
    ChatGraph.run_chat() → LLM 自主决定是否调工具 → ChatResponse（由 format 节点生成）

组件：
    ChatGraph       - LangGraph ReAct 图（核心，返回 ChatResponse）
    内联消息构建    - System Prompt + 历史 + 记忆（简化版 MessageBuilder）
    LocationService - 获取位置（启动时一次，缓存）
    MemoryManager   - 记忆检索和存储

事件流程：
    EventBus.publish(USER_MESSAGE)
        ↓
    ChatAgent._on_user_message()
        ↓
    _build_messages()              [构建消息 + 记忆检索]
        ↓
    ChatGraph.run_chat()           [LLM + 工具循环，返回 ChatResponse]
        ↓
    MemoryManager.add_memory()     [同步存储新记忆]
        ↓
    EventBus.publish(RESPONSE)     [通知 UI（含 emotion）]
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

from core import event_bus, EventCategory, AgentEvent, SystemEvent
from core.logger import setup_logger
from providers import get_llm
from memory import MemoryManager, get_memory_manager
from tools.tool_base import ToolRegistry

from .chat_schema import ChatResponse, Emotion
from .graph import ChatGraph
from tools.tool_location import LocationService

logger = setup_logger()


class ChatAgent:
    """
    ChatAgent - 对话代理

    使用 LangGraph ReAct 架构，LLM 自主决定是否调用工具。

    使用方式:
        agent = ChatAgent(event_loop=asyncio.get_event_loop())
        await agent.chat("你好")

    核心组件:
        - ChatGraph: LangGraph ReAct 图，返回 ChatResponse
        - LocationService: 位置获取
        - MemoryManager: 记忆管理
    """

    def __init__(self, event_loop: Optional[asyncio.AbstractEventLoop] = None):
        """
        初始化 ChatAgent

        Args:
            event_loop: 可选的事件循环引用（用于创建后台任务）
        """
        self._main_loop = event_loop
        self._llm = None
        self._chat_graph = None

        self._history: list[BaseMessage] = []
        self._location_service = LocationService()
        self._location_text: str = ""

        try:
            self._memory_manager: Optional[MemoryManager] = get_memory_manager()
        except Exception:
            logger.warning("[ChatAgent] MemoryManager 不可用，记忆功能已禁用")
            self._memory_manager = None

        event_bus.subscribe(
            EventCategory.AGENT,
            AgentEvent.USER_MESSAGE,
            self._on_user_message,
        )
        event_bus.subscribe(
            EventCategory.AGENT,
            AgentEvent.AUTO_SPEAK,
            self._on_auto_speak,
        )

        self._location_fetch_started = False

        logger.info("[ChatAgent] 初始化完成")

    def _ensure_llm(self):
        """确保 LLM 已初始化"""
        if self._llm is None:
            self._llm = get_llm()
            logger.info("[ChatAgent] LLM 已初始化")
        return self._llm

    def _ensure_chat_graph(self):
        """确保 ChatGraph 已初始化"""
        if self._chat_graph is None:
            llm = self._ensure_llm()
            tools = ToolRegistry.get_tools()
            self._chat_graph = ChatGraph(llm=llm, tools=tools)
            logger.info(f"[ChatAgent] ChatGraph 已初始化，工具数: {len(tools)}")
        return self._chat_graph

    def _run_in_background(self, coro) -> None:
        """在后台运行协程"""
        try:
            if self._main_loop is None:
                try:
                    self._main_loop = asyncio.get_running_loop()
                except RuntimeError:
                    logger.warning("[ChatAgent] 无运行中的事件循环")
                    return
            
            task = self._main_loop.create_task(coro)
            task.add_done_callback(self._handle_task_result)

        except Exception as e:
            logger.error(f"[ChatAgent] Failed to run in background: {e}")

    def _handle_task_result(self, task: asyncio.Task) -> None:
        """处理任务完成后的异常"""
        if task.exception():
            logger.error(
                f"[ChatAgent] Background task error: {task.exception()}",
                exc_info=True
            )

    def start_location_fetch(self) -> None:
        """启动位置获取"""
        if not self._location_fetch_started:
            self._location_fetch_started = True
            self._run_in_background(self._fetch_location())
            logger.info("[ChatAgent] Location fetch started")

    def _ensure_location_fetch(self) -> None:
        """确保位置获取已启动"""
        self.start_location_fetch()

    async def _fetch_location(self) -> None:
        """后台异步获取位置"""
        try:
            logger.info("[ChatAgent] 开始获取位置...")
            
            if not self._location_service._uapi_key:
                logger.warning("[ChatAgent] 无 UAPI Key，跳过位置获取")
                return
            
            location = await self._location_service.get_current()
            
            if location and location.city:
                self._location_text = location.to_prompt_text()
                logger.info(f"[ChatAgent] 位置已获取: {self._location_text}")
            else:
                logger.warning("[ChatAgent] 位置获取返回空结果")
                
        except Exception as e:
            logger.error(f"[ChatAgent] 位置获取异常: {e}", exc_info=True)

    def _on_user_message(self, message: str, **kwargs) -> None:
        """处理 USER_MESSAGE 事件"""
        logger.info(f"[ChatAgent] USER_MESSAGE: '{message}'")
        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)
        self._run_in_background(self.chat(message, kwargs.get("history")))

    def _on_auto_speak(self, prompt: str, **kwargs) -> None:
        """处理 AUTO_SPEAK 事件"""
        logger.info(f"[ChatAgent] AUTO_SPEAK: '{prompt[:30]}...'")
        self._run_in_background(self.auto_speak(prompt))

    async def chat(
        self,
        message: str,
        history: Optional[list] = None,
    ) -> ChatResponse:
        """
        执行聊天（核心方法）

        流程：
            1. 确保 LLM 和 ChatGraph 已初始化
            2. 确保位置获取已启动
            3. 构建消息列表（内联的消息构建）
            4. ChatGraph.run_chat() 执行（LLM + 工具循环）
            5. 更新历史 + 存储记忆
            6. 发布响应事件
        """
        try:
            self._ensure_chat_graph()
            self._ensure_location_fetch()

            llm_history = self._prepare_history(history)
            messages = await self._build_messages(
                user_input=message,
                history=llm_history,
                location=self._location_text,
            )

            chat_response = await self._chat_graph.run_chat(messages)

            self._update_history(message, chat_response.text)

            if chat_response.new_memories and self._memory_manager:
                await self._save_memories(chat_response.new_memories)

            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.RESPONSE,
                chat_response.model_dump(),
            )

            logger.info(
                f"[ChatAgent] 响应完成: '{chat_response.text[:30]}...' "
                f"(emotion={chat_response.emotion})"
            )
            return chat_response

        except Exception as e:
            logger.error(f"[ChatAgent] Chat error: {e}")
            event_bus.publish(
                EventCategory.SYSTEM,
                SystemEvent.LLM_CONFIG_ERROR,
                {"error": str(e), "source": "chat"},
            )
            return ChatResponse(
                text="呜呜...我好像没电了，主人能检查一下我的配置吗？",
                emotion=Emotion.CONFUSED,
            )

    async def auto_speak(self, prompt: str) -> None:
        """
        执行自动说话（静默模式）

        不使用 ChatGraph，直接单次 LLM 调用生成短句。
        """
        try:
            logger.info("[ChatAgent] Auto speak start...")
            llm = self._ensure_llm()

            structured_llm = llm.with_structured_output(ChatResponse, method="function_calling")
            messages = [HumanMessage(content=prompt)]
            chat_response = await structured_llm.ainvoke(messages)

            response_data = chat_response.model_dump()
            response_data['is_auto_speak'] = True

            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.RESPONSE,
                response_data,
            )

            logger.info(f"[ChatAgent] Auto speak done: '{chat_response.text}'")

        except Exception as e:
            logger.error(f"[ChatAgent] Auto speak error: {e}")
            try:
                llm = self._ensure_llm()
                messages = [HumanMessage(content=prompt)]
                llm_response = await llm.ainvoke(messages)
                chat_response = ChatResponse(
                    text=str(llm_response.content),
                    emotion=Emotion.NEUTRAL,
                )
                response_data = chat_response.model_dump()
                response_data['is_auto_speak'] = True
                event_bus.publish(
                    EventCategory.AGENT,
                    AgentEvent.RESPONSE,
                    response_data,
                )
            except Exception as e2:
                logger.error(f"[ChatAgent] Auto speak fallback also failed: {e2}")

    async def _build_messages(
        self,
        user_input: str,
        history: Optional[list[BaseMessage]] = None,
        location: str = "",
    ) -> list[BaseMessage]:
        """
        内联的消息构建（简化版 MessageBuilder）
        """
        system_prompt = await self._build_system_prompt(
            location=location,
            user_input=user_input,
        )

        trimmed_history = self._trim_history(history or [])

        messages = [SystemMessage(content=system_prompt)]
        messages.extend(trimmed_history)
        messages.append(HumanMessage(content=user_input))

        logger.info(
            f"[ChatAgent] 构建消息: SystemPrompt {len(system_prompt)}字, "
            f"历史 {len(trimmed_history)}条"
        )

        return messages

    async def _build_system_prompt(
        self,
        location: str,
        user_input: str,
    ) -> str:
        """构建 System Prompt"""
        parts = []

        parts.append(self._get_role_prompt())
        parts.append(self._get_time_context())

        if location and location != "用户位置：未知":
            city_name = self._extract_city_name(location)
            if city_name:
                parts.append(f"【用户位置】\n{location}\n【所在城市】\n{city_name}")
            else:
                parts.append(f"【用户位置】\n{location}")
        else:
            parts.append("【用户位置】\n未知。如果需要知道位置（比如查天气），可以问用户。")

        if self._memory_manager:
            memory_text = await asyncio.to_thread(
                self._memory_manager.get_relevant_memories,
                query=user_input, max_items=1
            )
            if memory_text:
                parts.append(f"【你对用户的记忆】\n{memory_text}")

        return "\n\n".join(parts)

    def _get_role_prompt(self) -> str:
        """获取角色设定"""
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
- 只有 System Prompt 里没有位置信息时，才调用 get_current_location"""

    def _get_time_context(self) -> str:
        """获取时间上下文"""
        now = datetime.now()
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_names[now.weekday()]

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
        """从位置文本中提取城市名"""
        match = re.search(r'地理位置[：:]\s*([^，,（(]+)', location_text)
        if match:
            geo_text = match.group(1).strip()
            geo_parts = geo_text.split()
            if geo_parts:
                return geo_parts[-1]
        return None

    def _trim_history(self, history: list[BaseMessage]) -> list[BaseMessage]:
        """裁剪历史消息"""
        max_messages = 40
        if len(history) <= max_messages:
            return history
        
        trimmed = history[-max_messages:]
        logger.info(f"[ChatAgent] 裁剪历史: {len(history)} -> {len(trimmed)} 条")
        return trimmed

    def _prepare_history(
        self,
        external_history: Optional[list],
    ) -> list[BaseMessage]:
        """准备历史消息"""
        result = list(self._history)

        if external_history:
            for msg in external_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    result.append(HumanMessage(content=content))
                elif role == "assistant":
                    result.append(AIMessage(content=content))

        return result

    def _update_history(self, user_input: str, assistant_output: str) -> None:
        """更新对话历史"""
        self._history.append(HumanMessage(content=user_input))
        self._history.append(AIMessage(content=assistant_output))

        max_messages = 40
        if len(self._history) > max_messages:
            self._history = self._history[-max_messages:]

    async def _save_memories(self, new_memories: list) -> None:
        """异步存储新记忆"""
        if not self._memory_manager:
            return

        try:
            from memory.types import MemoryType

            type_map = {
                "fact": MemoryType.FACT,
                "preference": MemoryType.PREFERENCE,
                "event": MemoryType.EVENT,
                "context": MemoryType.CONTEXT,
                "skill": MemoryType.SKILL,
            }

            for mem in new_memories:
                mem_type = type_map.get(mem.memory_type, MemoryType.FACT)
                await asyncio.to_thread(
                    self._memory_manager.smart_add_memory, mem.content, mem_type
                )
                logger.info(f"[ChatAgent] 存储记忆: [{mem.memory_type}] {mem.content}")

        except Exception as e:
            logger.error(f"[ChatAgent] 存储记忆失败: {e}")

    def clear_history(self) -> None:
        """清空对话历史"""
        self._history = []
        logger.info("[ChatAgent] 历史已清空")

    def cleanup(self) -> None:
        """清理资源"""
        event_bus.unsubscribe(
            EventCategory.AGENT,
            AgentEvent.USER_MESSAGE,
            self._on_user_message,
        )
        event_bus.unsubscribe(
            EventCategory.AGENT,
            AgentEvent.AUTO_SPEAK,
            self._on_auto_speak,
        )
        logger.info("[ChatAgent] 已清理")


__all__ = ["ChatAgent"]
