"""
agent/chat/graph.py - LangGraph 编排

v0.4 架构（推荐）:
    [intent] → 条件路由 → [retriever] 或 [chat] → [store] → END

v0.3 架构:
    [intent] → 条件路由 → [retriever] 或 [chat] → END

v0.2 架构（已废弃）:
    [chat] → END
"""
def _get_langgraph():
    """延迟获取 langgraph"""
    from langgraph.graph import StateGraph, END
    return StateGraph, END

from core.logger import setup_logger
from agent.chat.state import AgentState
from agent.chat.nodes import chat_node, intent_node, retriever_node, store_node

logger = setup_logger()


def _route_by_intent(state: AgentState) -> str:
    """
    条件路由：根据意图决定走哪条路

    - need_memory=True: 先查记忆 → 再聊天
    - need_memory=False: 直接聊天
    """
    if state.get("need_memory"):
        return "retriever"
    return "chat"


def build_graph():
    """
    构建并编译 LangGraph

    当前架构 (v0.4):
        [intent] → 条件判断
            ├─ need_memory=true  → [retriever] → [chat] → [store] → END
            └─ need_memory=false → [chat] → [store] → END

    节点职责:
        intent:    判断是否需要查询记忆
        retriever: 从向量库检索相关记忆
        chat:      LLM 生成回复，同时提取新记忆
        store:     智能存储新记忆（关键词 + 可选 LLM 兜底）

    Returns:
        CompiledStateGraph: 编译后的 LangGraph

    Example:
        compiled_graph = build_graph()
        result = await compiled_graph.ainvoke(initial_state)
    """
    StateGraph, END = _get_langgraph()
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("intent", intent_node)
    workflow.add_node("retriever", retriever_node)
    workflow.add_node("chat", chat_node)
    workflow.add_node("store", store_node)

    # 设置入口
    workflow.set_entry_point("intent")

    # 条件路由：intent → retriever 或 chat
    workflow.add_conditional_edges("intent", _route_by_intent)

    # retriever → chat（检索完记忆去聊天）
    workflow.add_edge("retriever", "chat")

    # chat → store（聊完存储新记忆）
    workflow.add_edge("chat", "store")

    # store → END（存储完结束）
    workflow.add_edge("store", END)

    logger.info("[Graph] LangGraph v0.4 built: intent → (retriever →) chat → store → END")
    return workflow.compile()
