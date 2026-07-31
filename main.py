"""
main.py - 应用入口

架构:
    Qt EventLoop + EventBus + LangGraph

流程:
    1. 初始化日志 (setup_logger)
    2. 启动 PyQt6 应用
    3. 初始化宠物 UI
    4. 初始化 LangGraph Agent
    5. 主循环等待退出
"""
import sys
import asyncio

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from core.logger import setup_logger, logger

# 在入口文件初始化日志
setup_logger()

from pet.pet import NuanbaoPet
from agent import ChatAgent
from core import event_bus, EventCategory, shutdown_event, reinit_shutdown_event
from core.fonts import get_default_font


async def main():
    """主函数"""
    # 1. 发布应用启动事件
    event_bus.publish(EventCategory.SYSTEM, "app_started")
    logger.info("[Main] App started")

    # 2. 创建并显示宠物
    pet = NuanbaoPet()
    pet.show()
    logger.info("[Main] Pet created")

    # 3. 创建 LangGraph ChatAgent
    chat_agent = ChatAgent()
    logger.info("[Main] ChatAgent (LangGraph) ready - 可以开始对话了")

    # 4. 等待退出（使用全局 shutdown_event）
    logger.info("[Main] Waiting for shutdown...")
    await shutdown_event.wait()
    logger.info("[Main] Shutdown event received")

    # 5. 清理资源
    logger.info("[Main] Shutting down...")
    chat_agent.cleanup()
    logger.info("[Main] Cleanup complete")


if __name__ == "__main__":
    # 1. 创建 Qt 应用
    qt_app = QApplication(sys.argv)
    qt_app.setFont(get_default_font(10))
    

    # 2. 使用 qasync 将 Qt EventLoop 和 asyncio 结合
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    # 2.5 重新初始化 shutdown_event，确保绑定到正确的事件循环
    reinit_shutdown_event()

    # 3. 运行主函数（处理可能的异常）
    try:
        with loop:
            loop.run_until_complete(main())
    except RuntimeError as e:
        # 如果 Qt 事件循环先停止（比如用户关闭窗口），捕获异常
        if "Event loop stopped" in str(e):
            logger.warning("[Main] Event loop stopped before main() completed (app is closing)")
        else:
            raise

    logger.info("[Main] Exit")
