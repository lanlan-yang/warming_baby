"""
agent/chat - 聊天模块

基于 LangGraph ReAct 架构的聊天实现。

文件说明：
    chat_agent.py    - ChatAgent 主类（入口）
    graph.py         - LangGraph 图组装 (ChatGraph)
    nodes.py         - 节点定义 (agent_node, tools_node, format_node)
    state.py         - 状态定义 (ChatState)
    chat_schema.py   - 数据模型 (ChatResponse, Emotion)
    auto_speak.py    - 自动说话功能

图结构：
    START → agent → [有工具调用?] → tools → agent (循环)
                   → [无工具调用?] → format → END

使用示例：
    from agent.chat import ChatAgent

    agent = ChatAgent()
    response = await agent.chat("你好")
"""

from .chat_agent import ChatAgent
from .graph import ChatGraph
from .chat_schema import ChatResponse, Emotion, MemoryExtract

__all__ = [
    "ChatAgent",
    "ChatGraph",
    "ChatResponse",
    "Emotion",
    "MemoryExtract",
]
