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
import multiprocessing

# 平台全局常量（整个应用统一使用，避免到处写 sys.platform 判断）
# 这里不能从 core.platform import，因为在某些打包/调试场景下 core/ 可能还不在 sys.path
# 所以在 main.py 内先自己检测一份，并在 core/platform.py 同步一份
_IS_WINDOWS = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"

# 单例锁文件
LOCK_FILE = os.path.join(os.path.expanduser("~"), ".warmbaby.lock")

# 全局引用，防止被垃圾回收
_lock_file = None


def _check_single_instance() -> bool:
    """使用文件锁检查单例 (不依赖 Qt，最可靠)

    跨平台实现:
    - Windows: 使用 msvcrt.locking
    - macOS / Linux: 使用 fcntl.flock

    进程退出时锁自动释放，无需手动清理。

    测试模式: 设置环境变量 WARMING_BABY_SKIP_LOCK=1 可跳过单例检查
              (用于开发调试时绕过锁文件冲突)
    """
    # 环境变量开关：开发调试时可临时跳过单例检查
    if os.environ.get("WARMING_BABY_SKIP_LOCK") == "1":
        print("[DEBUG] WARMING_BABY_SKIP_LOCK=1, 已跳过单例检查")
        return True

    global _lock_file
    try:
        _lock_file = open(LOCK_FILE, "w")
    except PermissionError as e:
        # 锁文件被占用但没拿到句柄（可能上一次进程崩溃残留 + 系统没释放）
        print(f"[WARN] 无法打开锁文件 {LOCK_FILE}: {e}")
        print("[WARN] 忽略单例检查继续启动（可能会同时运行多个实例）")
        return True

    try:
        if _IS_WINDOWS:
            # Windows: msvcrt.locking 是 Windows Python 标准库
            import msvcrt

            # LK_NBLCK: 非阻塞独占锁, 锁 1 字节
            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            # macOS / Linux: fcntl 标准库
            import fcntl

            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # 写入 PID 方便调试
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True
    except (OSError, IOError):
        # 锁已被其他进程持有
        try:
            _lock_file.close()
        except Exception:
            pass
        _lock_file = None
        print("[WARN] 检测到其他暖宝实例正在运行，本次启动跳过单例检查（开发模式）")
        return True


def run():
    """启动应用 (唯一入口)"""
    # PyInstaller frozen 环境: 手动定位 PyQt6 的 Qt6/bin DLL 目录
    # PyQt6 6.11 的 find_qt() 在 frozen 环境下 __file__ 指向 <frozen PyQt6>,
    # 无法定位 Qt6/bin, 导致 QtWidgets 等 .pyd 加载 Qt6 DLL 时报
    # "DLL load failed: 找不到指定的程序"。这里提前 add_dll_directory 兜底。
    # 注意: PyInstaller 6.x onedir 新布局下 _MEIPASS 可能指向 exe 目录或
    # _internal 子目录, 需依次探测多个候选路径。
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        meipass = getattr(sys, "_MEIPASS", exe_dir)
        for qt_bin in (
            os.path.join(meipass, "PyQt6", "Qt6", "bin"),
            os.path.join(exe_dir, "_internal", "PyQt6", "Qt6", "bin"),
            os.path.join(exe_dir, "PyQt6", "Qt6", "bin"),
        ):
            if os.path.isdir(qt_bin):
                try:
                    os.add_dll_directory(qt_bin)
                except (OSError, AttributeError):
                    pass
                os.environ["PATH"] = qt_bin + os.pathsep + os.environ.get("PATH", "")
                break

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
    # 导致子进程再次初始化 chromadb -> 又 spawn 子进程 -> 无限循环 (spawn 炸弹)
    multiprocessing.freeze_support()
    run()
