"""
agent/chat/state.py - LangGraph State 定义

定义 Agent 的状态结构，用于在 LangGraph 节点之间传递数据。
"""
from typing import TypedDict, Annotated
from operator import add

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    Agent 状态 - LangGraph 节点间共享的数据结构

    Attributes:
        messages: 对话历史 (LangChain Message 对象列表)
        user_input: 用户当前输入
        response: LLM 返回的结构化响应 (ChatResponse)
        error: 错误信息 (如果有)

    Example:
        state: AgentState = {
            "messages": [HumanMessage("你好")],
            "user_input": "你好",
            "response": None,
            "error": None,
        }
    """
    messages: Annotated[list[BaseMessage], add]  # 累积消息 (add reducer 会自动合并列表)
    user_input: str
    response: dict | None  # ChatResponse.model_dump()
    error: str | None
