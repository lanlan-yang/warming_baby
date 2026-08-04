"""
agent/chat/chat_agent.py - ChatAgent 组装

将 state、node、graph 组装成完整的 ChatAgent。
"""
import asyncio
from typing import TYPE_CHECKING

# 延迟导入 - 避免启动时加载 langchain
if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from core import event_bus, EventCategory, AgentEvent
from core.logger import setup_logger
from agent.chat.graph import build_graph
from agent.chat.state import AgentState
from agent.chat.nodes import chat_node
from agent.chat.chat_schema import ChatResponse
from tools.get_location import LocationService

logger = setup_logger()


def _get_langchain_messages():
    """延迟获取 langchain messages 类型"""
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
    return BaseMessage, HumanMessage, AIMessage



class ChatAgent:
    """
    LangGraph 实现的聊天 Agent

    使用方式:
        agent = ChatAgent()
        await agent.chat("你好")

    架构:
        EventBus.publish(USER_MESSAGE)
            ↓
        ChatAgent._on_user_message()
            ↓
        LangGraph.invoke(state)
            ↓
        chat_node → LLM.with_structured_output(ChatResponse)
            ↓
        ChatResponse 对象 (自动验证)
            ↓
        EventBus.publish(RESPONSE, response)
            ↓
        UI 更新
    """

    def __init__(self, event_loop=None):
        """
        初始化 ChatAgent
        
        Args:
            event_loop: 可选的事件循环引用，如果不提供则在需要时获取
        """
        self.graph = build_graph()
        self._history: list = []
        self._main_loop = event_loop
        
        # 位置服务 - 启动时获取一次，后续从缓存读取
        self._location_service = LocationService()
        self._location_text: str = "用户位置：未知"

        event_bus.subscribe(
            EventCategory.AGENT,
            AgentEvent.USER_MESSAGE,
            self._on_user_message,
        )
        
        # 监听自动说话事件
        event_bus.subscribe(
            EventCategory.AGENT,
            AgentEvent.AUTO_SPEAK,
            self._on_auto_speak,
        )

        # 后台异步获取位置 (不阻塞 init)
        if event_loop:
            event_loop.create_task(self._fetch_location())
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._fetch_location())
            except RuntimeError:
                pass  # 没有事件循环，延迟到首次 chat 时获取

        logger.info("[ChatAgent] LangGraph initialized")

    async def _fetch_location(self):
        """后台异步获取位置"""
        try:
            location = await self._location_service.get_current()
            if location:
                self._location_text = location.to_prompt_text()
                logger.info(f"[ChatAgent] 位置已获取: {self._location_text}")
            else:
                logger.warning("[ChatAgent] 位置获取失败")
        except Exception as e:
            logger.error(f"[ChatAgent] 位置获取异常: {e}")

    def _on_user_message(self, message: str, **kwargs):
        """
        处理 USER_MESSAGE 事件

        Args:
            message: 用户消息
            **kwargs: 额外参数
        """
        logger.info(f"[ChatAgent] Received USER_MESSAGE: '{message}'")

        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)

        # 获取事件循环 - 优先使用保存的引用
        loop = self._main_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
                self._main_loop = loop

        # 在事件循环中创建任务
        loop.create_task(self.chat(message, kwargs.get("history")))

    def _on_auto_speak(self, prompt: str, **kwargs):
        """
        处理 AUTO_SPEAK 事件

        与 USER_MESSAGE 不同：
        1. 不显示 thinking 状态（无感）
        2. 不加入对话历史

        Args:
            prompt: 给 LLM 的提示词
            **kwargs: 额外参数
        """
        logger.info(f"[ChatAgent] Received AUTO_SPEAK: '{prompt[:30]}...'")

        loop = self._main_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
                self._main_loop = loop

        # 后台执行，不阻塞
        loop.create_task(self.auto_speak(prompt))

    async def auto_speak(self, prompt: str) -> None:
        """
        执行自动说话（静默模式）

        Args:
            prompt: 给 LLM 的提示词
        """
        try:
            logger.info("[ChatAgent] Auto speak start...")
            
            # 延迟导入
            from langchain_core.messages import SystemMessage, HumanMessage
            
            from providers import get_llm
            from agent.chat.chat_schema import ChatResponse
            
            llm = get_llm()
            structured_llm = llm.with_structured_output(ChatResponse, method="function_calling")
            
            # 直接用 prompt，不加历史
            messages = [
                SystemMessage(content="你是一只会说话的小宠物，说话简短可爱，5-15字。"),
                HumanMessage(content=prompt),
            ]
            
            chat_response = await structured_llm.ainvoke(messages)
            
            logger.info(f"[ChatAgent] Auto speak done: '{chat_response.text}'")
            
            # 发布响应（与正常对话相同的事件）
            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.RESPONSE,
                chat_response.model_dump(),
            )

        except Exception as e:
            logger.error(f"[ChatAgent] Auto speak error: {e}")

    async def chat(
        self,
        message: str,
        history: list[dict] | None = None
    ) -> ChatResponse:
        """
        执行聊天

        Args:
            message: 用户消息
            history: 可选的历史消息

        Returns:
            ChatResponse: AI 响应

        Example:
            agent = ChatAgent()
            response = await agent.chat("你好")
            print(response.text, response.emotion)
        """
        try:
            # 延迟导入 langchain messages
            _, HumanMessage, AIMessage = _get_langchain_messages()
            
            messages = self._history.copy()

            if history:
                for msg in history:
                    role = msg.get("role", "user")
                    msg_content = msg.get("content", "")
                    if role == "user":
                        messages.append(HumanMessage(content=msg_content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=msg_content))

            # 懒加载位置（如果还没获取到）
            if self._location_text == "用户位置：未知":
                try:
                    location = await self._location_service.get_current()
                    if location:
                        self._location_text = location.to_prompt_text()
                except Exception:
                    pass

            state: AgentState = {
                "messages": messages,
                "user_input": message,
                "response": None,
                "error": None,
                "location": self._location_text,
            }

            result = await self.graph.ainvoke(state)

            if "messages" in result:
                self._history = result["messages"][-10:]

            # 检查是否有错误，有错误时不再发布 RESPONSE 事件
            # 因为 LLM_CONFIG_ERROR 事件已经在 node.py 中处理了
            if result.get("error"):
                logger.warning(f"[ChatAgent] Skipping RESPONSE event due to error: {result['error']}")
                # 返回错误响应但不触发 RESPONSE 事件
                return ChatResponse.model_validate(result["response"])

            chat_response = ChatResponse.model_validate(result["response"])

            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.RESPONSE,
                result["response"],
            )

            return chat_response
            
        except Exception as e:
            logger.error(f"[ChatAgent] Chat error: {e}")
            # 通知 UI LLM 配置错误
            from core import SystemEvent
            event_bus.publish(
                EventCategory.SYSTEM,
                SystemEvent.LLM_CONFIG_ERROR,
                {"error": str(e), "source": "chat"}
            )
            # 返回错误响应
            return ChatResponse(
                text="呜呜...我好像没电了，主人能检查一下我的配置吗？",
                emotion="confused",
                animation="idle"
            )

    def clear_history(self):
        """清空对话历史"""
        self._history = []
        logger.info("[ChatAgent] History cleared")

    def cleanup(self):
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
        logger.info("[ChatAgent] Cleaned up")


# 导出供外部使用
__all__ = ["ChatAgent", "AgentState", "chat_node", "build_graph"]
