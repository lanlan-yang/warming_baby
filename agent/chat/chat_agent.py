"""
agent/chat/chat_agent.py - ChatAgent 核心类

使用 LangGraph ReAct 架构实现 LLM 自主决策。

架构：
    ChatGraph.run_chat() → LLM 自主决定是否调工具 → ChatResponse（由 format 节点生成）
    记忆存储由 memory_node 确定性节点处理，不依赖 LLM 决策

组件：
    ChatGraph       - LangGraph ReAct 图（核心，返回 ChatResponse）
    内联消息构建    - System Prompt + 历史 + 核心记忆缓存
    LocationService - 获取位置（启动时一次，缓存）
    MemoryManager   - 记忆检索（存储由 memory_node 处理）
    CoreMemoryCache - 核心记忆缓存（启动时加载，常驻内存）

事件流程：
    EventBus.publish(USER_MESSAGE)
        ↓
    ChatAgent._on_user_message()
        ↓
    _build_messages()              [构建消息 + 核心记忆注入]
        ↓
    ChatGraph.run_chat()           [LLM + 工具循环 + 记忆存储，返回 ChatResponse]
        ↓
    EventBus.publish(RESPONSE)     [通知 UI（含 emotion）]
"""

import asyncio
from typing import Callable, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from core import event_bus, EventCategory, AgentEvent, SystemEvent
from core.logger import setup_logger
from core.errors import AgentError, ErrorCode
from providers import get_llm
from memory import MemoryManager, get_memory_manager, get_core_cache
from tools.tool_base import ToolRegistry

from .chat_schema import ChatResponse, Emotion
from .graph import ChatGraph
from .prompts import build_system_prompt
from tools.tool_location import LocationService

logger = setup_logger()


class ChatAgent:
    """
    ChatAgent - 对话代理

    使用 LangGraph ReAct 架构，LLM 自主决定是否调用工具。
    记忆存储由 memory_node 确定性节点自动处理。

    使用方式:
        agent = ChatAgent(event_loop=asyncio.get_event_loop())
        await agent.chat("你好")

    核心组件:
        - ChatGraph: LangGraph ReAct 图（agent → tools → format → memory → END）
        - LocationService: 位置获取
        - CoreMemoryCache: 核心记忆缓存（启动时加载，注入系统提示词）
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

        # 宠物状态提供者（可选，外部通过 set_status_provider 注入）
        # 返回 PetStats.to_prompt() 风格的字符串，注入 system prompt
        self._status_provider: Optional[Callable[[], str]] = None

        try:
            self._memory_manager: Optional[MemoryManager] = get_memory_manager()
            # 加载核心记忆缓存
            self._core_cache = get_core_cache()
            if self._memory_manager and self._memory_manager.is_ready:
                self._core_cache.load(self._memory_manager)
        except Exception:
            logger.warning("[ChatAgent] MemoryManager 不可用，记忆功能已禁用")
            self._memory_manager = None
            self._core_cache = get_core_cache()

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

        # MCP Server 状态变化 → 工具集变化 → 丢弃 ChatGraph 缓存（下次对话时重建并重新 bind_tools）
        event_bus.subscribe(
            EventCategory.SYSTEM,
            SystemEvent.MCP_SERVER_STATE,
            self._on_mcp_state_changed,
        )

        # 🔴 修复第 1/2 层缓存：注册配置监听器，LLM 相关配置变了立刻 invalidate 自身缓存
        self._register_config_listener()

    # ========================================================================
    # 宠物状态注入
    # ========================================================================
    def set_status_provider(self, provider: Optional[Callable[[], str]]):
        """
        注入宠物状态提供者

        Args:
            provider: 无参可调用对象，返回 PetStats.to_prompt() 风格的字符串
                      为 None 时清除注入。
        Usage:
            agent.set_status_provider(lambda: stats.to_prompt())
        """
        self._status_provider = provider
        logger.info(
            f"[ChatAgent] 状态提供者已{'设置' if provider else '清除'}"
        )

    def _register_config_listener(self):
        """注册配置监听器（LLM 相关配置变更时，丢弃自身缓存的 llm/chat_graph）"""
        self._location_fetch_started = False

        try:
            from config import config_manager

            def _on_llm_config_changed(key, value):
                # LLM 模型/Provider/BaseURL/全局参数/API Key 变更
                if key == "*" or key.startswith("llm"):
                    logger.info(
                        f"[ChatAgent] 配置 {key} 变更，丢弃旧的 LLM/ChatGraph 缓存（下次调用时重建）"
                    )
                    self._invalidate_llm_cache()

            config_manager.add_listener(_on_llm_config_changed)
        except Exception as e:
            logger.warning(f"[ChatAgent] 注册配置监听器失败: {e}")

        logger.info("[ChatAgent] 初始化完成")

    def _invalidate_llm_cache(self):
        """丢弃 LLM 和 ChatGraph 缓存（下次调用 chat/auto_speak 时会重建新实例）"""
        if self._chat_graph is not None:
            logger.debug("[ChatAgent] ChatGraph 缓存已清除")
        if self._llm is not None:
            logger.debug("[ChatAgent] LLM 缓存已清除")
        self._llm = None
        self._chat_graph = None

    def _on_mcp_state_changed(self, data: dict):
        """
        MCP Server 状态变化回调: 工具集变了 → 只丢弃 ChatGraph 缓存

        进入/离开 RUNNING 都意味着 tool_registry 内容变化，
        下次对话时 _ensure_chat_graph 会重建并重新 bind_tools。
        LLM 实例本身不受影响，不丢弃。
        """
        state = data.get("state", "")
        if state in ("running", "idle", "failed", "disabled"):
            if self._chat_graph is not None:
                logger.info(
                    f"[ChatAgent] MCP server '{data.get('name')}' → {state}，"
                    "丢弃 ChatGraph 缓存（下次对话重建工具绑定）"
                )
                self._chat_graph = None

    def _ensure_llm(self):
        """确保 LLM 已初始化（每次都从 LLMProvider 拿：配置变了会自动用新缓存）"""
        # 注意：这里不直接 return self._llm，强制从 LLMProvider 取一次
        # 原因：LLMProvider.reset() 清了缓存后，下一次 get_llm() 就会建新实例（新 API Key / 新模型）
        llm = get_llm()
        if self._llm is not llm:
            if self._llm is None:
                logger.info("[ChatAgent] LLM 已初始化")
            else:
                logger.info("[ChatAgent] 检测到 LLM 缓存已重建，更新 self._llm")
            self._llm = llm
        return self._llm

    def _ensure_chat_graph(self):
        """确保 ChatGraph 已初始化（当底层 LLM 变了时重建）"""
        llm = self._ensure_llm()
        # 若 chat_graph 没初始化，或它内部的 llm 引用不等于当前最新 llm，就重建
        if self._chat_graph is None or self._chat_graph.llm is not llm:
            if self._chat_graph is not None:
                logger.info("[ChatAgent] 底层 LLM 已变更，重建 ChatGraph（含 bound_tools 和 format_llm）")
            self._chat_graph = ChatGraph(llm=llm)
            logger.info("[ChatAgent] ChatGraph 已初始化")
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
            
            location = await self._location_service.get_current()
            
            if location and location.city:
                self._location_text = location.to_prompt_text()
                logger.info(f"[ChatAgent] 位置已获取: {self._location_text}")
            else:
                logger.info("[ChatAgent] 位置获取返回空结果")
                
        except Exception as e:
            logger.error(f"[ChatAgent] 位置获取异常: {e}", exc_info=True)

    def _on_user_message(self, message: str, **kwargs) -> None:
        """处理 USER_MESSAGE 事件

        kwargs 可选:
            history: 对话历史
            pre_status: 操作前的宠物状态快照文本（ActionHandler 传入）
                        LLM 应根据操作前的状态回复，而非操作后的
        """
        logger.info(f"[ChatAgent] USER_MESSAGE: '{message}'")
        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)
        self._run_in_background(
            self.chat(
                message,
                history=kwargs.get("history"),
                pre_status=kwargs.get("pre_status"),
            )
        )

    def _on_auto_speak(self, prompt: str, **kwargs) -> None:
        """处理 AUTO_SPEAK 事件"""
        logger.info(f"[ChatAgent] AUTO_SPEAK: '{prompt[:30]}...'")
        self._run_in_background(self.auto_speak(prompt))

    async def chat(
        self,
        message: str,
        history: Optional[list] = None,
        pre_status: Optional[str] = None,
    ) -> ChatResponse:
        """
        执行聊天（核心方法）

        流程：
            1. 确保 LLM 和 ChatGraph 已初始化
            2. 确保位置获取已启动
            3. 构建消息列表（系统提示词 + 核心记忆 + 历史 + 用户消息）
            4. ChatGraph.run_chat() 执行（LLM + 工具循环 + memory_node 自动存储）
            5. 更新历史
            6. 发布响应事件
        """
        try:
            # ============ 前置 Key 检查：缺哪个就用对应模板精确提示 ============
            from config import secure_storage

            # 1) LLM API Key
            llm_key_ok = secure_storage.has_api_key()
            if not llm_key_ok:
                from providers.llm import LLMProvider
                llm_key_ok = bool(LLMProvider._get_api_key())

            if not llm_key_ok:
                logger.warning("[ChatAgent] LLM API Key 未配置")
                raise AgentError._build(ErrorCode.CONFIG_MISSING_LLM_KEY)

            # 2) Embedding API Key (记忆功能用)
            # 不阻断对话，但用户首次进入/明确没 Key 时，直接抛出 CONFIG_MISSING_EMBED_KEY
            # 让 except AgentError 给出"记忆模型的 API Key 还没填哦……"的精确提示，
            # 避免用户以为能记住偏好，实际都静默漏掉了
            if not secure_storage.has_embedding_api_key():
                # 检查是否已经发过缺 key 提示（避免每说一句话都提示一次）
                # 用一个简单的会话级标记
                if not getattr(self, "_embed_missing_notified", False):
                    self._embed_missing_notified = True
                    logger.warning("[ChatAgent] Embedding API Key 未配置，首次触发结构化提示")
                    raise AgentError._build(ErrorCode.CONFIG_MISSING_EMBED_KEY)

            # 局部引用持有图实例：即使 MCP 工具变化事件在后续 await 窗口中
            # 丢弃了 self._chat_graph 缓存，本次对话仍使用本快照完整跑完
            graph = self._ensure_chat_graph()
            self._ensure_location_fetch()

            llm_history = self._prepare_history(history)
            messages = await self._build_messages(
                user_input=message,
                history=llm_history,
                location=self._location_text,
                pre_status=pre_status,
            )

            # 获取宠物状态文本，传给 graph 供 format_node 推断 emotion
            # 优先使用操作前的状态快照（ActionHandler 传入），让 LLM 根据操作前的状态回复
            # 例如：satiety=80 时被喂食，LLM 应看到 80 而非操作后的 100
            pet_status = pre_status or ""
            if not pet_status and self._status_provider is not None:
                try:
                    pet_status = self._status_provider() or ""
                except Exception as e:
                    logger.warning(f"[ChatAgent] 获取宠物状态失败: {e}")

            chat_response = await graph.run_chat(messages, pet_status=pet_status)

            self._update_history(message, chat_response.text)

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

        except AgentError as ae:
            # 结构化错误：直接用模板里的 user_message + action_hint，配对应表情
            logger.error(
                f"[ChatAgent] Chat AgentError: code={ae.code.value}, "
                f"msg={ae.user_message}, original={ae.original[:200] if ae.original else ''}"
            )
            resp = ChatResponse(
                text=ae.full_text("\n"),
                emotion=_to_emotion_enum(ae.emotion),
            )
            # 错误响应通过 RESPONSE 事件显示精确文本气泡
            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.RESPONSE,
                resp.model_dump(),
            )
            # LLM_CONFIG_ERROR 仅用于日志记录和 warmup 阶段，chat 时不再发
            # （避免和 RESPONSE 重复弹气泡，互相覆盖）
            logger.info(f"[ChatAgent] Error response sent: {ae.code.value}")
            return resp

        except Exception as e:
            # 兜底：任何没被节点层分类的异常，走 classify 统一转成 AgentError 模板
            ae = AgentError.classify(e)
            logger.error(
                f"[ChatAgent] Chat fallback: code={ae.code.value}, "
                f"raw={type(e).__name__}: {str(e)[:200]}"
            )
            resp = ChatResponse(
                text=ae.full_text("\n"),
                emotion=_to_emotion_enum(ae.emotion),
            )
            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.RESPONSE,
                resp.model_dump(),
            )
            return resp

    async def auto_speak(self, prompt: str) -> None:
        """
        执行自动说话（静默模式）

        不使用 ChatGraph，直接单次 LLM 调用生成短句。
        禁用思考模式以快速响应。
        """
        try:
            # API Key 未配置时：发一个空的 RESPONSE（带 fallback 文本），
            # 这样 Pet 侧能清掉 _waiting_llm 和 is_chatting，避免状态卡死
            from config import secure_storage
            if not secure_storage.has_api_key():
                from providers.llm import LLMProvider
                if not LLMProvider._get_api_key():
                    logger.info("[ChatAgent] Auto speak skipped: API Key 未配置")
                    self._publish_fallback_response(
                        text="",
                        is_auto_speak=True,
                    )
                    return

            logger.info("[ChatAgent] Auto speak start...")
            # 禁用思考模式，快速生成短句
            llm = get_llm(thinking_enabled=False)

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
                llm = get_llm(thinking_enabled=False)
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
                # 最终兜底：发一个空 RESPONSE，让 Pet 侧清理状态
                self._publish_fallback_response(text="", is_auto_speak=True)

    async def _build_messages(
        self,
        user_input: str,
        history: Optional[list[BaseMessage]] = None,
        location: str = "",
        pre_status: Optional[str] = None,
    ) -> list[BaseMessage]:
        """
        内联的消息构建（简化版 MessageBuilder）

        Args:
            pre_status: 操作前的状态快照文本。有值时优先使用，覆盖 status_provider。
        """
        # 有 pre_status 时，用临时 provider 替换（返回固定快照）
        if pre_status:
            status_provider = lambda: pre_status
        else:
            status_provider = self._status_provider

        system_prompt = build_system_prompt(
            location=location,
            status_provider=status_provider,
            core_cache=self._core_cache,
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

    def clear_history(self) -> None:
        """清空对话历史"""
        self._history = []
        logger.info("[ChatAgent] 历史已清空")
    
    def _publish_fallback_response(self, text: str = " ", is_auto_speak: bool = False) -> None:
        """发布一个 fallback RESPONSE 事件（用于 API Key 未配置、LLM 异常等场景）

        目的：让 Pet 侧即使没拿到 LLM 结果，也能清除 _waiting_llm 和 is_chatting
        状态，避免下次自动说话 / 聊天被卡死。

        text 默认留一个空格而非空串，因为 ChatResponse.text 要求 min_length=1。
        Pet 侧 _handle_agent_response 使用 `if text.strip()` 判断，空白文本不出气泡，
        直接走清除等待状态的分支。

        Args:
            text: 占位文本，留空或传空白字符串时不出气泡
            is_auto_speak: 是否是自动说话的 fallback
        """
        # 保证至少有一个空格，避免触发 min_length=1 校验
        safe_text = text if text and len(text) >= 1 else " "
        try:
            fallback = ChatResponse(
                text=safe_text,
                emotion=Emotion.NEUTRAL,
            )
            response_data = fallback.model_dump()
            if is_auto_speak:
                response_data['is_auto_speak'] = True
            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.RESPONSE,
                response_data,
            )
            logger.info(f"[ChatAgent] Fallback response published: text_len={len(safe_text)}, auto_speak={is_auto_speak}")
        except Exception as e:
            logger.error(f"[ChatAgent] Publish fallback failed: {e}")
    
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


def _to_emotion_enum(value: str) -> Emotion:
    """
    将 errors.py 模板里的 emotion 字符串转为 Emotion 枚举。

    容错：如果 templates 里写了一个不在 Emotion 里的值（比如 sleepy），
    兜底返回 CONFUSED，避免 UI 层收到不合法的 emotion 值卡渲染。
    """
    try:
        return Emotion(value)
    except ValueError:
        valid = {e.value for e in Emotion}
        logger.warning(
            f"[ChatAgent] 非法 emotion='{value}'，不在 {valid}，兜底用 CONFUSED"
        )
        return Emotion.CONFUSED


__all__ = ["ChatAgent"]
