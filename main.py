"""
main.py - 应用入口

架构:
    main.py (入口) -> app.py (Application 类)
    Qt EventLoop + EventBus + LangGraph

流程:
    1. 创建 Qt 应用和事件循环
    2. 初始化 LLM 配置监听器
    3. 创建 Application 实例
    4. 运行完整生命周期
"""
import sys

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from core.logger import setup_logger, logger
from core.fonts import get_default_font
from settings import init_llm_config_listener
from app import Application

# 在入口文件初始化日志
setup_logger()

# 初始化 LLM 配置监听器 (避免循环导入)
init_llm_config_listener()


def run():
    """启动应用 (唯一入口)"""
    # 1. 创建 Qt 应用
    qt_app = QApplication(sys.argv)
    qt_app.setFont(get_default_font(10))
    
    # 2. 创建事件循环
    loop = QEventLoop(qt_app)
    
    # 3. 创建应用实例并运行
    app = Application(qt_app, loop)
    
    try:
        with loop:
            loop.run_until_complete(app.run())
    except RuntimeError as e:
        if "Event loop stopped" not in str(e):
            raise
    
    logger.info("[App] Exit")


if __name__ == "__main__":
    run()
