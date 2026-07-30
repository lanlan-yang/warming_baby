import threading
import signal
import sys
import uvicorn

from PyQt6.QtWidgets import QApplication
from fastapi import FastAPI

from pet.pet import run
from api.chat import router as chat_router


app = FastAPI()
app.include_router(chat_router)

server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000))


def start_api():
    print("[API] uvicorn started on http://0.0.0.0:8000")
    server.run()


if __name__ == '__main__':
    api_thread = threading.Thread(target=start_api, daemon=False)
    api_thread.start()

    # 确保退出时 uvicorn 也能关闭
    def cleanup():
        print("[API] shutting down...")
        server.should_exit = True
        api_thread.join(timeout=5)
    
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (cleanup(), sys.exit(0)))
    QApplication.instance().aboutToQuit.connect(cleanup)

    run()
