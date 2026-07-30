import uvicorn

from fastapi import FastAPI
from api.chat import router as chat_router
from core.logger import setup_logger

logger = setup_logger()

app = FastAPI()
app.include_router(chat_router)

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8002)
    logger.info("[API] uvicorn started on http://0.0.0.0:8002")