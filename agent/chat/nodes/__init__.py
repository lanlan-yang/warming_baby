"""
agent/chat/nodes - LangGraph 节点集合

所有节点函数的导出入口，方便统一导入。

节点命名约定：
  - retriever: 检索 (读)
  - store:     存储 (写)
  - chat:      对话 (推理)
  - intent:    判断 (路由)

Usage:
    from agent.chat.nodes import chat_node, retriever_node, store_node
"""

from agent.chat.nodes.chat import chat_node
from agent.chat.nodes.intent import intent_node
from agent.chat.nodes.retriever import retriever_node
from agent.chat.nodes.store import store_node

# 兼容旧名称 (Deprecated)
memory_node = retriever_node
memory_save_node = store_node

__all__ = [
    "chat_node",
    "intent_node",
    "retriever_node",
    "store_node",
    # 兼容旧名称
    "memory_node",
    "memory_save_node",
]
