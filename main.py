import asyncio
import sys
import uvicorn

from PyQt6.QtWidgets import QApplication
from fastapi import FastAPI
from qasync import QEventLoop

from pet.pet import NuanbaoPet
from api.chat import router as chat_router
from agent.llm_agent import LLMAgent
from core import event_bus, EventCategory
from core.fonts import get_default_font
from core.logger import setup_logger

logger = setup_logger()

# ── FastAPI ──
app = FastAPI()
app.include_router(chat_router)


async def main():
    loop = asyncio.get_running_loop()

    # 1. FastAPI 作为 asyncio task
    uvicorn_config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop=loop)
    uvicorn_server = uvicorn.Server(uvicorn_config)
    api_task = asyncio.create_task(uvicorn_server.serve())
    logger.info("[API] uvicorn → http://0.0.0.0:8000")

    # 2. 宠物 GUI
    event_bus.publish(EventCategory.SYSTEM, "app_started")
    pet = NuanbaoPet()
    pet.show()

    # 3. LLM Agent 订阅 EventBus (无 API key 时自动进入 mock 模式)
    LLMAgent()
    logger.info("[LLM] agent ready")

    # 4. 等待退出
    await asyncio.Event().wait()

    # 5. 清理
    uvicorn_server.should_exit = True
    await api_task


if __name__ == "__main__":
    qt_app = QApplication(sys.argv)
    qt_app.setFont(get_default_font(10))

    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    with loop:
        loop.run_until_complete(main())
    logger.info("[Main] shutdown complete")
