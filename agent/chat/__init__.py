"""
agent/chat - 聊天模块

OpenWorker 架构下的聊天实现，不再依赖 LangGraph。

核心组件:
    ChatAgent       - 聊天代理主类
    TurnEngine      - LLM + Tool 循环引擎
    MessageBuilder  - 消息构建器
    ChatSchema      - 数据模型 (ChatResponse, Emotion, MemoryExtract)

使用示例:
    from agent.chat import ChatAgent

    agent = ChatAgent(event_loop=loop)
    response = await agent.chat("你好")
    print(response.text, response.emotion)
"""

from .chat_agent import ChatAgent
from .engine import TurnEngine
from .message_builder import MessageBuilder
from .chat_schema import ChatResponse, Emotion, MemoryExtract

__all__ = [
    "ChatAgent",
    "TurnEngine",
    "MessageBuilder",
    "ChatResponse",
    "Emotion",
    "MemoryExtract",
]
