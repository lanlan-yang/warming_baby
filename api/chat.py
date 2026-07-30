"""聊天接口"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from core import event_bus, EventCategory, AgentEvent

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy"}


@router.post("/chat")
async def chat(req: ChatRequest):
    """接收消息 → 发布到 EventBus → LLMAgent 处理 → 驱动宠物"""
    event_bus.publish(EventCategory.AGENT, AgentEvent.USER_MESSAGE, message=req.message)
    return {"status": "received", "message": req.message}

