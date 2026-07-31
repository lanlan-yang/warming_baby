"""
agent/chat/chat_agent.py - ChatAgent 组装

将 state、node、graph 组装成完整的 ChatAgent。
"""
import asyncio

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from core import event_bus, EventCategory, AgentEvent
from core.logger import setup_logger
from agent.chat.graph import build_graph
from agent.chat.state import AgentState
from agent.chat.node import chat_node
from agent.chat.chat_schema import ChatResponse

logger = setup_logger()


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

    def __init__(self):
        """初始化 ChatAgent"""
        self.graph = build_graph()
        self._history: list[BaseMessage] = []

        event_bus.subscribe(
            EventCategory.AGENT,
            AgentEvent.USER_MESSAGE,
            self._on_user_message,
        )

        logger.info("[ChatAgent] LangGraph initialized")

    def _on_user_message(self, message: str, **kwargs):
        """
        处理 USER_MESSAGE 事件

        Args:
            message: 用户消息
            **kwargs: 额外参数
        """
        logger.info(f"[ChatAgent] Received USER_MESSAGE: '{message}'")

        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)

        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self.chat(message, kwargs.get("history")))
        except RuntimeError:
            asyncio.run(self.chat(message, kwargs.get("history")))

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
        messages = self._history.copy()

        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))

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
