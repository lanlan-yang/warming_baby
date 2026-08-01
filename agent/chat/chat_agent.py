"""
agent/chat/chat_agent.py - ChatAgent 组装

将 state、node、graph 组装成完整的 ChatAgent。
"""
import asyncio
import threading
from typing import TYPE_CHECKING

# 延迟导入 - 避免启动时加载 langchain
if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from core import event_bus, EventCategory, AgentEvent
from core.logger import setup_logger
from agent.chat.graph import build_graph
from agent.chat.state import AgentState
from agent.chat.node import chat_node
from agent.chat.chat_schema import ChatResponse

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
        self._llm_warmed = False
        self._main_loop = event_loop  # 保存事件循环引用

        event_bus.subscribe(
            EventCategory.AGENT,
            AgentEvent.USER_MESSAGE,
            self._on_user_message,
        )

        # 预热 LLM - 在后台线程中初始化，避免阻塞
        self._warmup_llm()

        logger.info("[ChatAgent] LangGraph initialized")

    def _warmup_llm(self):
        """
        预热 LLM - 在独立线程中初始化，避免阻塞 Qt 事件循环
        
        使用线程而不是 asyncio 任务，因为 init_chat_model 是同步的。
        """
        thread = threading.Thread(
            target=self._sync_warmup,
            daemon=True
        )
        thread.start()
        logger.info("[ChatAgent] LLM warmup thread started")

    def _sync_warmup(self):
        """同步预热 - 在独立线程中执行"""
        try:
            import time
            start = time.time()
            from providers import get_llm
            # 获取 LLM 实例（会触发初始化和缓存）
            llm = get_llm()
            self._llm_warmed = True
            logger.info(f"[ChatAgent] LLM warmed up in {time.time()-start:.2f}s")
        except Exception as e:
            logger.warning(f"[ChatAgent] LLM warmup failed: {e}")

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
            # 尝试获取当前运行的循环（推荐方式）
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 回退到 get_event_loop()
                loop = asyncio.get_event_loop()
                self._main_loop = loop  # 缓存起来

        # 在事件循环中创建任务
        loop.create_task(self.chat(message, kwargs.get("history")))

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

        state: AgentState = {
            "messages": messages,
            "user_input": message,
            "response": None,
            "error": None,
        }

        result = await self.graph.ainvoke(state)

        if "messages" in result:
            self._history = result["messages"][-10:]

        chat_response = ChatResponse.model_validate(result["response"])

        event_bus.publish(
            EventCategory.AGENT,
            AgentEvent.RESPONSE,
            result["response"],
        )

        return chat_response

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
        logger.info("[ChatAgent] Cleaned up")


# 导出供外部使用
__all__ = ["ChatAgent", "AgentState", "chat_node", "build_graph"]
