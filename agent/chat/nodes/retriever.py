"""
agent/chat/nodes/retriever.py - 记忆检索节点

职责：从向量库查询相关记忆。
"""
from agent.chat.state import AgentState
from core.logger import setup_logger

logger = setup_logger()


async def retriever_node(state: AgentState) -> dict:
    """
    记忆检索节点：如果需要，从向量库查询相关记忆

    Args:
        state: 当前状态

    Returns:
        {"memory_context": str}  空字符串表示无记忆或不需要查
    """
    if not state.get("need_memory"):
        return {"memory_context": ""}

    user_input = state["user_input"]

    try:
        from memory import get_memory_manager
        mem_mgr = get_memory_manager()

        if not mem_mgr.is_ready:
            logger.info("[RetrieverNode] 记忆系统未就绪，跳过")
            return {"memory_context": ""}

        memory_text = mem_mgr.get_relevant_memories(user_input, max_items=3)

        if memory_text:
            logger.info(f"[RetrieverNode] 查到记忆: {memory_text[:80]}")
        else:
            logger.info("[RetrieverNode] 无相关记忆")

        return {"memory_context": memory_text}

    except Exception as e:
        logger.warning(f"[RetrieverNode] 查询失败: {e}")
        return {"memory_context": ""}
