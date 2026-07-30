"""聊天接口"""
from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/health")
async def health_check(request: Request):
    """健康检查接口"""
    return {"status": "healthy"}

