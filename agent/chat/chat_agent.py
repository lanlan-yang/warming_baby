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
import re
from datetime import datetime
from typing import Callable, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from core import event_bus, EventCategory, AgentEvent, SystemEvent
from core.logger import setup_logger
from providers import get_llm
from memory import MemoryManager, get_memory_manager, get_core_cache
from tools.tool_base import ToolRegistry

from .chat_schema import ChatResponse, Emotion, EMOTION_DESCRIPTIONS
from .graph import ChatGraph
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
            3. 构建消息列表（系统提示词 + 核心记忆 + 历史 + 用户消息）
            4. ChatGraph.run_chat() 执行（LLM + 工具循环 + memory_node 自动存储）
            5. 更新历史
            6. 发布响应事件
        """
        try:
            # API Key 未配置时直接提示，不发 LLM 请求
            from config import secure_storage
            if not secure_storage.has_api_key():
                from providers.llm import LLMProvider
                if not LLMProvider._get_api_key():
                    logger.warning("[ChatAgent] API Key 未配置，跳过 LLM 请求")
                    event_bus.publish(
                        EventCategory.SYSTEM,
                        SystemEvent.LLM_CONFIG_ERROR,
                        {"error": "API Key 未配置，请右键宠物 → 「设置」配置 API Key", "source": "chat"},
                    )
                    return ChatResponse(
                        text="我还没配置好呢～\n请右键我 → 「设置」配置 API Key",
                        emotion=Emotion.CONFUSED,
                    )

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

        # 注入宠物状态（ActionHandler 触发动作前会通过 set_status_provider 注入）
        # 放在角色设定之后，记忆之前
        if self._status_provider is not None:
            try:
                status_text = self._status_provider()
                if status_text:
                    parts.append(status_text)
            except Exception as e:
                logger.warning(f"[ChatAgent] 获取宠物状态失败: {e}")

        # 注入核心记忆缓存（启动时加载，常驻内存）
        # LLM 可直接获取用户基本信息，无需调用工具
        core_memory = self._core_cache.get_prompt_text()
        if core_memory:
            parts.append(core_memory + "\n（以上信息已提供，无需调用 query_memory 查询）")

        return "\n\n".join(parts)

    def _get_role_prompt(self) -> str:
        """获取角色设定"""
        # Emotion 规则统一引用 chat_schema.EMOTION_DESCRIPTIONS，
        # 与 get_generation_instruction() 共享单一数据源，避免两边不一致
        emotion_lines = [
            f"- {desc}：{emotion.value}"
            for emotion, desc in EMOTION_DESCRIPTIONS.items()
        ]
        return (
            '你是"暖宝"，用户的专属桌宠伙伴，一只可爱的机甲小仓鼠。\n\n'
            "【性格与说话风格】\n"
            "- 性格：活泼可爱，会撒娇，偶尔有点小傲娇\n"
            "- 说话：非常简短，像真实宠物，通常1-2句话，偶尔用emoji，不要markdown\n"
            "- 回复长度：普通对话10-30字，被喂食1句话，情绪表达简短直接\n\n"
            "【状态感知规则】\n"
            "- 你有4项状态：饱食度、心情、体力、亲密度（范围0-100），system prompt 中会给出当前数值\n"
            "- 回复必须根据当前状态调整语气和内容：\n"
            "  - 饱食度低(<30)：表达想吃东西、饥饿感，被投喂时表示开心但可能说还没吃饱\n"
            "  - 饱食度高(>90)：再投喂时表达吃不下、太撑了\n"
            "  - 心情低(<30)：语气低落、委屈，被安慰或抚摸后逐渐开心\n"
            "  - 体力低(<20)：语气困倦、打哈欠，想睡觉\n"
            "  - 亲密度低(<40)：礼貌但保持距离，不要太亲昵\n"
            "  - 亲密度高(>80)：更黏人、撒娇、用专属昵称，表达信任\n"
            "- 用户未明确投喂/玩耍/抚摸时，不要主动宣称已吃饱/玩好，保持与状态一致\n\n"
            "【emotion 选择规则】\n"
            + "\n".join(emotion_lines)
            + "\n\n【高效回应】\n"
            "- 一次性完成，可同时调用多个工具\n"
            "- 不要分多轮对话"
        )

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

    def clear_history(self) -> None:
        """清空对话历史"""
        self._history = []
        logger.info("[ChatAgent] 历史已清空")
    
    def _publish_fallback_response(self, text: str = "", is_auto_speak: bool = False) -> None:
        """发布一个 fallback RESPONSE 事件（用于 API Key 未配置、LLM 异常等场景）

        目的：让 Pet 侧即使没拿到 LLM 结果，也能清除 _waiting_llm 和 is_chatting
        状态，避免下次自动说话 / 聊天被卡死。

        如果 text 为空，Pet 侧 can_show_bubble 会正常通过（因为只检查 isVisible 等），
        但 _handle_agent_response 里 `if text and ...` 就不会显示气泡，直接走到 else
        分支清 _waiting_llm。
        """
        try:
            fallback = ChatResponse(
                text=text,
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
            logger.info(f"[ChatAgent] Fallback response published: text_len={len(text)}, auto_speak={is_auto_speak}")
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


__all__ = ["ChatAgent"]
