"""
main.py - 应用入口

架构:
    main.py (入口) -> app.py (Application 类)
    Qt EventLoop + EventBus + LangGraph

流程:
    1. 单例检查 (文件锁, 不依赖 Qt)
    2. 创建 Qt 应用和事件循环
    3. 初始化 LLM 配置监听器
    4. 创建 Application 实例
    5. 运行完整生命周期
"""
import sys
import os
import fcntl
import multiprocessing

# 单例锁文件
LOCK_FILE = os.path.join(os.path.expanduser('~'), '.warmbaby.lock')

# 全局引用，防止被垃圾回收
_lock_file = None


def _check_single_instance() -> bool:
    """使用文件锁检查单例 (不依赖 Qt，最可靠)

    进程退出时锁自动释放，无需手动清理。
    """
    global _lock_file
    _lock_file = open(LOCK_FILE, 'w')
    try:
        # 非阻塞方式获取独占锁
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # 写入 PID 方便调试
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True
    except OSError:
        # 锁已被其他进程持有
        _lock_file.close()
        _lock_file = None
        sys.exit(0)


def run():
    """启动应用 (唯一入口)"""
    from PyQt6.QtWidgets import QApplication
    from qasync import QEventLoop

    from core.logger import setup_logger, logger
    from core.fonts import get_default_font
    from settings import init_llm_config_listener
    from app import Application

    # 初始化日志
    setup_logger()

    # 初始化 LLM 配置监听器
    init_llm_config_listener()

    # 1. 单例检查 (在任何 Qt 对象创建之前)
    if not _check_single_instance():
        sys.exit(0)

    logger.info("[App] Single instance check passed")

    # 2. 创建 Qt 应用
    qt_app = QApplication(sys.argv)
    qt_app.setFont(get_default_font(10))

    # 3. 创建事件循环
    loop = QEventLoop(qt_app)

    # 4. 创建应用实例并运行
    app = Application(qt_app, loop)

    try:
        with loop:
            loop.run_until_complete(app.run())
    except RuntimeError as e:
        if "Event loop stopped" not in str(e):
            raise

    logger.info("[App] Exit")


if __name__ == "__main__":
    # PyInstaller frozen 应用必须调用 freeze_support()
    # 否则 multiprocessing spawn 的子进程会重新执行整个 frozen 可执行文件，
    # 导致子进程再次初始化 chromadb/onnxruntime -> 又 spawn 子进程 -> 无限循环 (spawn 炸弹)
    multiprocessing.freeze_support()
    run()
