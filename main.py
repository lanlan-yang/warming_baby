"""
main.py - 应用入口

架构:
    Qt EventLoop + EventBus + LangGraph

流程:
    1. 创建宠物（不显示）
    2. 后台预热（LLM + 记忆系统）
    3. 预热完成后显示宠物
    4. 等待退出并清理

特性:
    - 带超时：10秒内完成预热
    - 可降级：预热失败也显示宠物
    - 用户体验：看到宠物时已就绪
"""
import sys
import asyncio
import threading

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from core.logger import setup_logger, logger
from core import event_bus, EventCategory, SystemEvent, shutdown_event, reinit_shutdown_event
from core.fonts import get_default_font
from pet.pet import NuanbaoPet

# 在入口文件初始化日志
setup_logger()


async def main():
    """主函数
    
    流程: 创建宠物 → 后台预热(LLM+记忆) → 就绪后显示
    """
    # 1. 创建宠物但先不显示
    pet = NuanbaoPet()
    logger.info("[Main] Pet created (waiting for warmup)")

    # 2. 预热完成信号
    warmup_done = asyncio.Event()
    warmup_timeout = 10  # 10秒超时

    # 3. 在后台线程初始化 Agent + 记忆系统
    main_loop = asyncio.get_running_loop()
    chat_agent = None
    
    def init_agent_in_background():
        """后台线程: 预热 LLM + 记忆系统"""
        nonlocal chat_agent
        success = False
        
        try:
            # 3a. 初始化 ChatAgent（内部会预热 LLM）
            from agent import ChatAgent
            chat_agent = ChatAgent(event_loop=main_loop)
            
            # 等待 LLM 预热完成（简单轮询，最多 8 秒）
            for i in range(8):
                if chat_agent._llm_warmed:
                    break
                if i < 7:
                    import time
                    time.sleep(1)
            
            logger.info(f"[Main] ChatAgent ready (llm_warmed={chat_agent._llm_warmed})")
            
            # 3b. 预热记忆系统（失败不阻塞）
            try:
                from core.long_memory_base import get_memory_manager
                mem_mgr = get_memory_manager()
                mem_mgr.initialize()
                logger.info("[Main] Memory system ready")
            except Exception as e:
                logger.warning(f"[Main] Memory system init failed (non-critical): {e}")
            
            success = True
            
        except Exception as e:
            logger.error(f"[Main] ChatAgent init failed: {e}")
            chat_agent = None
        
        finally:
            # 通知主线程：预热完成（无论成功失败）
            main_loop.call_soon_threadsafe(warmup_done.set)
            logger.info(f"[Main] Warmup done (success={success})")
    
    # 启动后台预热线程
    thread = threading.Thread(target=init_agent_in_background, daemon=True)
    thread.start()
    logger.info("[Main] Warmup thread started")

    # 4. 等待预热完成（带超时）
    try:
        await asyncio.wait_for(warmup_done.wait(), timeout=warmup_timeout)
        logger.info("[Main] Warmup completed, showing pet")
    except asyncio.TimeoutError:
        logger.warning("[Main] Warmup timeout ({warmup_timeout}s), showing pet anyway")

    # 5. 显示宠物
    pet.show()
    QApplication.processEvents()
    logger.info("[Main] Pet shown")

    # 6. 发布就绪事件
    event_bus.publish(
        EventCategory.SYSTEM,
        SystemEvent.AGENT_READY,
        {"chat_agent": chat_agent is not None}
    )

    # 7. 等待退出
    logger.info("[Main] Waiting for shutdown...")
    await shutdown_event.wait()
    logger.info("[Main] Shutdown event received")

    # 8. 清理资源
    logger.info("[Main] Shutting down...")
    if chat_agent:
        chat_agent.cleanup()
    logger.info("[Main] Cleanup complete")


def run():
    """启动应用 (唯一入口)"""
    # 1. 创建 Qt 应用
    qt_app = QApplication(sys.argv)
    qt_app.setFont(get_default_font(10))

    # 2. 初始化配置系统 (在 UI 之前)
    _init_config_system()

    # 3. 使用 qasync 将 Qt EventLoop 和 asyncio 结合
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    # 4. 重新初始化 shutdown_event，确保绑定到正确的事件循环
    reinit_shutdown_event()

    # 5. 运行主函数
    try:
        with loop:
            loop.run_until_complete(main())
    except RuntimeError as e:
        if "Event loop stopped" in str(e):
            logger.warning("[Main] Event loop stopped (app is closing)")
        else:
            raise

    logger.info("[Main] Exit")


def _init_config_system():
    """初始化配置系统"""
    from core.logger import logger  # 确保 logger 可用
    try:
        # 延迟导入 (避免循环依赖)
        from config import config_manager, secure_storage
        
        # 加载配置
        config_manager.load()
        logger.info("[Config] Config loaded")
        
        # 迁移 API Key (如果旧配置有但新存储没有)
        from settings import Settings
        old_settings = Settings()
        if old_settings.openai_api_key and not secure_storage.has_api_key():
            secure_storage.save_api_key(old_settings.openai_api_key)
            logger.info("[Config] API key migrated to secure storage")
        
        # 初始化 LLM 配置监听器
        from settings import init_llm_config_listener
        init_llm_config_listener()
        logger.info("[Config] Config system initialized")
        
    except Exception as e:
        logger.error(f"[Config] Failed to init config system: {e}")
        logger.warning("[Config] Using default config")


if __name__ == "__main__":
    run()
