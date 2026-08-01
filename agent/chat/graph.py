"""
agent/chat/graph.py - LangGraph 编排

只负责图的构建，包含所有节点和边的定义。
通过 build_graph() 函数返回编译后的 LangGraph。
"""
def _get_langgraph():
    """延迟获取 langgraph"""
    from langgraph.graph import StateGraph, END
    return StateGraph, END

from core.logger import setup_logger
from agent.chat.state import AgentState
from agent.chat.node import chat_node

logger = setup_logger()


def build_graph():
    """
    构建并编译 LangGraph

    当前架构 (v0.2):
        [chat_node] → END

    可扩展架构 (v0.3+):
        [chat_node] → [tool_node] → [chat_node] → END

    Returns:
        CompiledStateGraph: 编译后的 LangGraph

    Example:
        compiled_graph = build_graph()
        result = await compiled_graph.ainvoke(initial_state)
    """
    StateGraph, END = _get_langgraph()
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("chat", chat_node)

    # 添加边
    workflow.set_entry_point("chat")
    workflow.add_edge("chat", END)

    logger.info("[Graph] LangGraph built: chat -> END")
    return workflow.compile()
