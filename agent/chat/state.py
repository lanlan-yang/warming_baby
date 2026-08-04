"""
agent/chat/state.py - LangGraph State 定义

定义 Agent 的状态结构，用于在 LangGraph 节点之间传递数据。
"""
from typing import TypedDict, Annotated, Any
from operator import add


class AgentState(TypedDict):
    """
    Agent 状态 - LangGraph 节点间共享的数据结构

    Attributes:
        messages: 对话历史 (LangChain Message 对象列表)
        user_input: 用户当前输入
        response: LLM 返回的结构化响应 (ChatResponse)
        error: 错误信息 (如果有)
        location: 用户位置信息 (prompt 文本)
        need_memory: 是否需要查询记忆
        memory_context: 查询到的记忆文本
        new_memories: 需要保存的新记忆列表
        memory_save_result: 记忆保存结果

    Example:
        state: AgentState = {
            "messages": [HumanMessage("你好")],
            "user_input": "你好",
            "response": None,
            "error": None,
            "location": "用户位置：中国 四川 成都",
            "need_memory": False,
            "memory_context": "",
            "new_memories": [],
            "memory_save_result": None,
        }
    """
    messages: Annotated[list[Any], add]  # 累积消息 (add reducer 会自动合并列表)
    user_input: str
    response: dict | None  # ChatResponse.model_dump()
    error: str | None
    location: str  # 用户位置信息 (prompt 文本)
    need_memory: bool  # 是否需要查询记忆
    memory_context: str  # 查询到的记忆文本（空字符串表示无）
    new_memories: list  # 需要保存的新记忆列表
    memory_save_result: dict | None  # 记忆保存结果
