import threading
import signal
import sys
import threading
import signal
import sys
import uvicorn

from fastapi import FastAPI

from pet.pet import run
from api.chat import router as chat_router
from core.logger import setup_logger

logger = setup_logger()



app = FastAPI()
app.include_router(chat_router)

server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000))


def start_api():
    logger.info("[API] uvicorn started on http://0.0.0.0:8000")
    server.run()


def cleanup():
    logger.info("[API] shutting down...")
    server.should_exit = True
    api_thread.join(timeout=5)


if __name__ == '__main__':
    api_thread = threading.Thread(target=start_api, daemon=False)
    api_thread.start()

    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (cleanup(), sys.exit(0)))

    run(on_quit=cleanup)
