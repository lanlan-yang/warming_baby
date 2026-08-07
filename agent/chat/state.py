"""
agent/chat/state.py - LangGraph State 定义

所有数据流转都通过 State，节点只负责读写 State。

字段说明：
    - messages: 对话历史（reducer: add_messages）
    - iteration: 当前迭代次数（reducer: +1）
    - max_iterations: 最大迭代次数（不可变）
    - final_response: 最终的 ChatResponse（在 format 节点设置）
    - status: 当前状态（thinking, calling_tools, done）
"""

from typing import Annotated, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

from .chat_schema import ChatResponse


class ChatState(TypedDict, total=False):
    """
    Chat Graph 的完整状态

    total=False 表示所有字段可选（因为初始 state 可能只有 messages）

    所有流转数据都在这里：
        - 对话过程: messages
        - 循环控制: iteration, max_iterations
        - 最终结果: final_response
        - 调试信息: status
    """
    # ========== 对话历史 ==========
    messages: Annotated[list[BaseMessage], add_messages]

    # ========== 循环控制 ==========
    iteration: int
    max_iterations: int

    # ========== 最终结果 ==========
    final_response: Optional[ChatResponse]

    # ========== 调试信息 ==========
    status: str  # thinking, calling_tools, formatting, done
