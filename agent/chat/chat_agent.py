"""
agent/chat/chat_agent.py - ChatAgent 核心类

OpenWorker 架构的 ChatAgent，使用 TurnEngine 实现 LLM 自主决策。

架构：
    TurnEngine.run() → LLM 自主决定是否调工具 → with_structured_output 返回 ChatResponse

组件协作：
    TurnEngine      - LLM + Tool 循环引擎（核心，返回 ChatResponse）
    MessageBuilder  - 构建 System Prompt + 历史 + 记忆
    LocationService - 获取位置（启动时一次，缓存）
    MemoryManager   - 记忆检索（消息构建时）和存储（对话后）

事件流程：
    EventBus.publish(USER_MESSAGE)
        ↓
    ChatAgent._on_user_message()
        ↓
    MessageBuilder.build_messages()  [构建消息 + 记忆检索]
        ↓
    TurnEngine.run()                  [LLM + 工具循环，返回 ChatResponse]
        ↓
    MemoryManager.add_memory()        [同步存储新记忆]
        ↓
    EventBus.publish(RESPONSE)        [通知 UI（含 emotion）]
"""

import asyncio
from typing import Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from core import event_bus, EventCategory, AgentEvent, SystemEvent
from core.logger import setup_logger
from providers import get_llm
from memory import MemoryManager, get_memory_manager
from tools.tool_base import ToolRegistry

from .chat_schema import ChatResponse, Emotion
from .engine import TurnEngine
from .message_builder import MessageBuilder
from tools.tool_location import LocationService

logger = setup_logger()


class ChatAgent:
    """
    OpenWorker 架构的聊天 Agent

    使用方式:
        agent = ChatAgent(event_loop=asyncio.get_event_loop())
        await agent.chat("你好")

    核心组件:
        - TurnEngine: LLM + Tool 循环，返回 ChatResponse（含 emotion）
        - MessageBuilder: 消息构建
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

        # LLM 实例（延迟获取，避免启动时网络请求）
        self._llm = None

        # 历史消息（LangChain 格式）
        self._history: list[BaseMessage] = []

        # 位置服务 - 启动时异步获取一次
        self._location_service = LocationService()
        self._location_text: str = ""  # 空字符串表示未知

        # 记忆管理器（可选）
        try:
            self._memory_manager: Optional[MemoryManager] = get_memory_manager()
        except Exception:
            logger.warning("[ChatAgent] MemoryManager 不可用，记忆功能已禁用")
            self._memory_manager = None

        # 事件订阅
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

        # 延迟启动位置获取（等待真正有事件循环时再执行）
        self._location_fetch_started = False

        logger.info("[ChatAgent] OpenWorker 架构初始化完成")

    def _ensure_llm(self):
        """
        确保 LLM 已初始化

        延迟获取 LLM，避免启动时网络问题。
        第一次调用 chat 时才真正创建 LLM 实例。
        """
        if self._llm is None:
            self._llm = get_llm()
            logger.info("[ChatAgent] LLM 已初始化")
        return self._llm

    def _run_in_background(self, coro) -> None:
        """
        在后台运行协程（不阻塞当前调用）
        """
        try:
            if self._main_loop is None:
                try:
                    self._main_loop = asyncio.get_running_loop()
                    logger.debug("[ChatAgent] 获取到运行中的事件循环")
                except RuntimeError:
                    logger.warning("[ChatAgent] 无运行中的事件循环，任务无法启动")
                    return
            
            task = self._main_loop.create_task(coro)
            logger.debug(f"[ChatAgent] 创建后台任务: {coro.__class__.__name__}")
            
            # 用 add_done_callback 处理异常
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
        """
        启动位置获取（公开方法，供预热流程调用）

        在预热时调用，确保第一次聊天时已有位置信息。
        只执行一次。
        """
        if not self._location_fetch_started:
            self._location_fetch_started = True
            self._run_in_background(self._fetch_location())
            logger.info("[ChatAgent] Location fetch started")

    def _ensure_location_fetch(self) -> None:
        """
        确保位置获取任务已启动（兜底方法）

        如果预热时没有调用 start_location_fetch，
        在第一次聊天时会调用此方法。
        """
        self.start_location_fetch()

    async def _fetch_location(self) -> None:
        """后台异步获取位置"""
        try:
            logger.info("[ChatAgent] 开始获取位置...")
            
            if not self._location_service._uapi_key:
                logger.warning("[ChatAgent] 无 UAPI Key，跳过位置获取")
                return
            
            logger.info("[ChatAgent] 正在请求位置服务...")
            location = await self._location_service.get_current()
            
            if location and location.city:
                self._location_text = location.to_prompt_text()
                logger.info(f"[ChatAgent] 位置已获取: {self._location_text}")
            else:
                logger.warning("[ChatAgent] 位置获取返回空结果")
                
        except Exception as e:
            logger.error(f"[ChatAgent] 位置获取异常: {e}", exc_info=True)
            # 即使异常也不设置默认值，让 LLM 知道位置未知

    def _on_user_message(self, message: str, **kwargs) -> None:
        """
        处理 USER_MESSAGE 事件

        Args:
            message: 用户消息
            **kwargs: 可选参数（如历史消息）
        """
        logger.info(f"[ChatAgent] USER_MESSAGE: '{message}'")

        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)

        self._run_in_background(self.chat(message, kwargs.get("history")))

    def _on_auto_speak(self, prompt: str, **kwargs) -> None:
        """
        处理 AUTO_SPEAK 事件

        与 USER_MESSAGE 的区别：
            - 不显示 thinking 状态（无感）
            - 不加入对话历史

        Args:
            prompt: 给 LLM 的提示词
        """
        logger.info(f"[ChatAgent] AUTO_SPEAK: '{prompt[:30]}...'")

        self._run_in_background(self.auto_speak(prompt))

    async def chat(
        self,
        message: str,
        history: Optional[list] = None,
    ) -> ChatResponse:
        """
        执行聊天（核心方法）

        Args:
            message: 用户当前输入
            history: 可选的历史消息列表 [{role: "user"/"assistant", content: "..."}]

        Returns:
            ChatResponse: AI 的结构化响应

        执行流程：
            1. 确保 LLM 已初始化
            2. 确保位置获取已启动（延迟）
            3. 构建消息列表（System Prompt + 历史 + 用户输入 + 记忆）
            4. TurnEngine 执行（LLM 自主决定是否调工具，直接返回 ChatResponse）
            5. 更新历史 + 异步存储记忆
            6. 发布响应事件
        """
        try:
            # 1. 确保 LLM 已初始化
            llm = self._ensure_llm()

            # 2. 确保位置获取已启动（延迟到首次聊天）
            self._ensure_location_fetch()

            # 3. 构建消息列表
            message_builder = MessageBuilder(
                max_history_turns=20,
                memory_manager=self._memory_manager,
            )

            # 准备历史消息
            llm_history = self._prepare_history(history)

            # 获取工具 (用于 bind_tools)
            tools = ToolRegistry.get_tools()

            # 构建完整消息
            messages = await message_builder.build_messages(
                user_input=message,
                history=llm_history,
                location=self._location_text,
                enable_memory=True,
            )

            # 4. TurnEngine 执行（直接返回 ChatResponse）
            # 注意：工具信息通过 bind_tools() 传递给 LLM，不在 System Prompt 中
            engine = TurnEngine(llm=llm, tools=tools)
            chat_response = await engine.run(messages)

            # 5. 更新历史
            self._update_history(message, chat_response.text)

            # 同步存储新记忆（避免并发问题）
            if chat_response.new_memories and self._memory_manager:
                await self._save_memories(chat_response.new_memories)

            # 6. 发布响应事件
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

        不走 TurnEngine、记忆系统和工具，直接单次 LLM 调用生成短句。
        使用 with_structured_output 直接获取 ChatResponse（含 emotion）。
        用于定时问候、情绪表达等场景。

        Args:
            prompt: 给 LLM 的提示词
        """
        try:
            logger.info("[ChatAgent] Auto speak start...")

            llm = self._ensure_llm()

            # 直接用 with_structured_output 获取 ChatResponse
            structured_llm = llm.with_structured_output(ChatResponse, method="function_calling")
            messages = [HumanMessage(content=prompt)]
            chat_response = await structured_llm.ainvoke(messages)

            # 添加自动说话标识
            response_data = chat_response.model_dump()
            response_data['is_auto_speak'] = True

            # 发布响应事件
            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.RESPONSE,
                response_data,
            )

            logger.info(f"[ChatAgent] Auto speak done: '{chat_response.text}'")

        except Exception as e:
            logger.error(f"[ChatAgent] Auto speak error: {e}")
            # Fallback: 用原始 LLM 调用获取文本
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

    def _prepare_history(
        self,
        external_history: Optional[list],
    ) -> list[BaseMessage]:
        """
        准备历史消息（合并内部历史和外部历史）

        Args:
            external_history: 外部传入的历史列表

        Returns:
            LangChain 格式的消息列表
        """
        # 先复制内部历史
        result = list(self._history)

        # 再添加外部历史
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
        """
        更新对话历史

        Args:
            user_input: 用户输入
            assistant_output: AI 输出
        """
        self._history.append(HumanMessage(content=user_input))
        self._history.append(AIMessage(content=assistant_output))

        # 保留最近 20 轮
        max_messages = 40
        if len(self._history) > max_messages:
            self._history = self._history[-max_messages:]

    async def _save_memories(self, new_memories: list) -> None:
        """
        异步存储新记忆

        Args:
            new_memories: MemoryExtract 列表
        """
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
                # 使用 to_thread 避免阻塞 event loop
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
        """清理资源（取消事件订阅）"""
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
