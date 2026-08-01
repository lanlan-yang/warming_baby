"""
main.py - 应用入口

架构:
    Qt EventLoop + EventBus + LangGraph

优化:
    1. UI 优先: Pet 立即显示，Agent 在后台加载
    2. 无阻塞: LLM 初始化在后台线程
    3. 可降级: Agent 初始化失败不影响 UI
"""
import sys
import asyncio
import threading

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from core.logger import setup_logger, logger
from core import event_bus, EventCategory, shutdown_event, reinit_shutdown_event
from core.fonts import get_default_font
from pet.pet import NuanbaoPet

# 在入口文件初始化日志
setup_logger()


async def main():
    """主函数"""
    # 1. 创建并显示宠物 (无阻塞)
    pet = NuanbaoPet()
    pet.show()
    
    # 让 Qt 立即处理 UI 事件，确保宠物先显示出来
    QApplication.processEvents()
    logger.info("[Main] Pet created and shown")

    # 2. 在后台线程初始化 Agent (不阻塞主事件循环)
    # 先获取主事件循环的引用，传给 ChatAgent
    main_loop = asyncio.get_running_loop()
    chat_agent = None
    
    def init_agent_in_background():
        """后台线程: 初始化 Agent"""
        nonlocal chat_agent
        try:
            from agent import ChatAgent
            chat_agent = ChatAgent(event_loop=main_loop)  # 传递主循环引用
            logger.info("[Main] ChatAgent ready (initialized in background)")
        except Exception as e:
            logger.error(f"[Main] ChatAgent init failed: {e}")
            chat_agent = None
    
    # 启动后台线程
    thread = threading.Thread(target=init_agent_in_background, daemon=True)
    thread.start()
    logger.info("[Main] Agent init thread started")

    # 3. 等待退出 (使用全局 shutdown_event)
    logger.info("[Main] Waiting for shutdown...")
    await shutdown_event.wait()
    logger.info("[Main] Shutdown event received")

    # 4. 清理资源
    logger.info("[Main] Shutting down...")
    if chat_agent:
        chat_agent.cleanup()
    logger.info("[Main] Cleanup complete")


def run():
    """启动应用 (唯一入口)"""
    # 1. 创建 Qt 应用
    qt_app = QApplication(sys.argv)
    qt_app.setFont(get_default_font(10))

    # 2. 使用 qasync 将 Qt EventLoop 和 asyncio 结合
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    # 3. 重新初始化 shutdown_event，确保绑定到正确的事件循环
    reinit_shutdown_event()

    # 4. 运行主函数
    try:
        with loop:
            loop.run_until_complete(main())
    except RuntimeError as e:
        if "Event loop stopped" in str(e):
            logger.warning("[Main] Event loop stopped (app is closing)")
        else:
            raise

    logger.info("[Main] Exit")


if __name__ == "__main__":
    run()
