from core.schemas import BaseSchema, ChatRole
from typing import Any
from datetime import datetime
from pydantic import Field

# 兼容 Python 3.10+ 的 Self 类型导入
try:
    from typing import Self
except ImportError:
    from typing_extensions import Self  # type: ignore


# ---------------- 聊天消息（完整消息） ----------------
class ChatMessage(BaseSchema):
    """一条完整的聊天消息，UI显示、历史存储、事件传输、接口传参全用这个"""
    role: str = Field(description=f"消息角色: {ChatRole.USER}, {ChatRole.ASSISTANT}, {ChatRole.SYSTEM}, {ChatRole.TOOL}")
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # 方便方法：直接转成LangChain的消息对象，给LLM用
    def to_lc_message(self):
        """转成LangChain的HumanMessage/AIMessage/SystemMessage"""
        from langchain_core.messages import (
            HumanMessage, AIMessage, SystemMessage, ToolMessage
        )
        msg_map = {
            ChatRole.USER: HumanMessage,
            ChatRole.ASSISTANT: AIMessage,
            ChatRole.SYSTEM: SystemMessage,
            ChatRole.TOOL: ToolMessage,
        }
        msg_class = msg_map[self.role]
        if self.role == ChatRole.TOOL:
            # ToolMessage需要tool_call_id，从metadata里取
            return msg_class(
                content=self.content,
                tool_call_id=self.metadata.get("tool_call_id", "")
            )
        return msg_class(content=self.content)

    @classmethod
    def from_lc_message(cls, lc_msg) -> Self:
        """从LangChain的消息对象转成我们的ChatMessage"""
        from langchain_core.messages import (
            HumanMessage, AIMessage, SystemMessage, ToolMessage
        )
        role_map = {
            HumanMessage: ChatRole.USER,
            AIMessage: ChatRole.ASSISTANT,
            SystemMessage: ChatRole.SYSTEM,
            ToolMessage: ChatRole.TOOL,
        }
        role = role_map.get(type(lc_msg), ChatRole.SYSTEM)
        content = lc_msg.content if isinstance(lc_msg.content, str) else ""
        return cls(role=role, content=content)

# ---------------- 流式输出块 ----------------
class ChatChunk(BaseSchema):
    """流式输出增量块，逐字显示用"""
    content_delta: str
    is_end: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseSchema):
    """聊天请求"""
    message: str


class ChatResponse(BaseSchema):
    """聊天响应"""
    status: str
    message: str
    reply: str | None = None  # AI 回复内容
    metadata: dict[str, Any] = Field(default_factory=dict)
