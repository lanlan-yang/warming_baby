"""
app.py - Application 类

应用主类，封装完整生命周期:
    run() -> _setup() -> _start() -> _warmup() -> _run() -> _cleanup()
"""
import os
import sys
import asyncio
import threading

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from qasync import QEventLoop

from version import __version__, __app_name__
from core.logger import logger
from core import event_bus, EventCategory, SystemEvent, shutdown_event, reinit_shutdown_event
from pet.pet import NuanbaoPet


class Application:
    """应用主类 - 封装完整生命周期
    
    Attributes:
        qt_app: Qt 应用实例
        loop: asyncio 事件循环
        pet: 宠物窗口
        tray: 菜单栏图标
        chat_agent: AI Agent
    """
    
    def __init__(self, qt_app: QApplication, loop: QEventLoop):
        self.qt_app = qt_app
        self.loop = loop
        self.pet = None
        self.tray = None
        self.chat_agent = None
    
    async def run(self):
        """完整生命周期"""
        await self._setup()
        await self._start()
        await self._warmup()
        await self._run()
        await self._cleanup()
    
    # ========================================================================
    # 1. 初始化
    # ========================================================================
    
    async def _setup(self):
        """初始化配置和平台设置"""
        # 设置为后台应用 (macOS 不在 Dock 显示)
        self._set_background_mode()
        
        # 初始化配置系统
        self._init_config_system()
        
        # 重置 shutdown_event
        reinit_shutdown_event()
        
        logger.info("[App] Setup complete")
    
    def _set_background_mode(self):
        """设置应用为后台模式 (不在 Dock 显示，可在菜单栏显示)"""
        if sys.platform != 'darwin':
            return
        
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            logger.info("[App] Set to accessory mode (not in Dock, can have focus)")
        except Exception as e:
            logger.warning(f"[App] Failed to set background mode: {e}")
    
    def _init_config_system(self):
        """初始化配置系统"""
        try:
            from config import config_manager, secure_storage
            
            config_manager.load()
            logger.info("[Config] Config loaded")
            
            # 迁移 API Key
            from settings import Settings
            old_settings = Settings()
            if old_settings.openai_api_key and not secure_storage.has_api_key():
                secure_storage.save_api_key(old_settings.openai_api_key)
                logger.info("[Config] API key migrated")
            
            # 初始化 LLM 配置监听器
            from settings import init_llm_config_listener
            init_llm_config_listener()
            logger.info("[Config] Config system ready")
            
        except Exception as e:
            logger.error(f"[Config] Failed to init: {e}")
            logger.warning("[Config] Using default config")
    
    # ========================================================================
    # 2. 启动
    # ========================================================================
    
    async def _start(self):
        """创建宠物和托盘"""
        # 创建宠物 (不显示)
        self.pet = NuanbaoPet()
        logger.info("[App] Pet created")
        
        # 创建菜单栏图标
        self.tray = self._create_system_tray()
        self.tray.show()
        logger.info("[App] System tray created")
    
    def _create_system_tray(self) -> QSystemTrayIcon:
        """创建菜单栏图标"""
        QApplication.setQuitOnLastWindowClosed(False)
        
        tray_dir = os.path.join(os.path.dirname(__file__), 'assets', 'icons', 'tray')
        
        # 加载多尺寸图标，Qt 自动选择合适的
        icon = QIcon()
        icon.addFile(os.path.join(tray_dir, 'tray_16.png'), QSize(16, 16))
        icon.addFile(os.path.join(tray_dir, 'tray_16@2x.png'), QSize(32, 32))
        icon.addFile(os.path.join(tray_dir, 'tray_16@3x.png'), QSize(48, 48))
        icon.addFile(os.path.join(tray_dir, 'tray_32.png'), QSize(32, 32))
        icon.addFile(os.path.join(tray_dir, 'tray_32@2x.png'), QSize(64, 64))
        icon.addFile(os.path.join(tray_dir, 'tray_32@3x.png'), QSize(96, 96))
        icon.addFile(os.path.join(tray_dir, 'tray_128.png'), QSize(128, 128))
        icon.addFile(os.path.join(tray_dir, 'tray_128@2x.png'), QSize(256, 256))
        icon.addFile(os.path.join(tray_dir, 'tray_256.png'), QSize(256, 256))
        icon.addFile(os.path.join(tray_dir, 'tray_256@2x.png'), QSize(512, 512))
        icon.addFile(os.path.join(tray_dir, 'tray_512.png'), QSize(512, 512))
        icon.addFile(os.path.join(tray_dir, 'tray_512@2x.png'), QSize(1024, 1024))
        
        # macOS: 设置为模板图标，自动适配深浅色
        if sys.platform == 'darwin':
            icon.setIsMask(True)
        
        tray = QSystemTrayIcon(icon)
        tray.setToolTip(f'{__app_name__} v{__version__} - 你的桌宠')
        
        menu = QMenu()
        
        toggle_action = QAction('显示/隐藏暖宝', menu)
        toggle_action.triggered.connect(lambda: self.pet.setVisible(not self.pet.isVisible()))
        menu.addAction(toggle_action)
        
        menu.addSeparator()
        
        settings_action = QAction('设置...', menu)
        settings_action.triggered.connect(self.pet.open_settings)
        menu.addAction(settings_action)
        
        menu.addSeparator()
        
        quit_action = QAction('退出暖宝', menu)
        quit_action.triggered.connect(self.pet._exit_with_animation)
        menu.addAction(quit_action)
        
        menu.addSeparator()
        
        star_action = QAction('⭐ 给我个 Star 吧！', menu)
        star_action.triggered.connect(self.pet.show_github_star)
        menu.addAction(star_action)
        
        tray.setContextMenu(menu)
        
        tray.activated.connect(lambda reason: self.pet.setVisible(not self.pet.isVisible())
                              if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        
        return tray
    
    # ========================================================================
    # 3. 预热
    # ========================================================================
    
    async def _warmup(self, timeout: int = 10):
        """后台预热 LLM 和记忆系统"""
        warmup_done = asyncio.Event()
        main_loop = asyncio.get_running_loop()
        
        def init_agent():
            """后台线程: 初始化 Agent 和记忆系统"""
            try:
                from agent import ChatAgent
                self.chat_agent = ChatAgent(event_loop=main_loop)
                
                # 等待 LLM 预热
                for _ in range(8):
                    if self.chat_agent._llm_warmed:
                        break
                    import time
                    time.sleep(1)
                
                logger.info("[Warmup] ChatAgent ready")
                
                # 预热记忆系统
                try:
                    from core.long_memory_base import get_memory_manager
                    get_memory_manager().initialize()
                    logger.info("[Warmup] Memory system ready")
                except Exception as e:
                    logger.warning(f"[Warmup] Memory init failed (non-critical): {e}")
                    
            except Exception as e:
                logger.error(f"[Warmup] Agent init failed: {e}")
                self.chat_agent = None
            
            finally:
                main_loop.call_soon_threadsafe(warmup_done.set)
        
        thread = threading.Thread(target=init_agent, daemon=True)
        thread.start()
        logger.info("[Warmup] Thread started")
        
        # 等待预热完成
        try:
            await asyncio.wait_for(warmup_done.wait(), timeout=timeout)
            logger.info("[Warmup] Complete")
        except asyncio.TimeoutError:
            logger.warning(f"[Warmup] Timeout ({timeout}s)")
    
    # ========================================================================
    # 4. 运行
    # ========================================================================
    
    async def _run(self):
        """显示宠物并等待退出"""
        # 显示宠物
        self.pet.show()
        QApplication.processEvents()
        logger.info("[App] Pet shown")
        
        # 发布就绪事件
        event_bus.publish(
            EventCategory.SYSTEM,
            SystemEvent.AGENT_READY,
            {"chat_agent": self.chat_agent is not None}
        )
        
        # 等待退出
        logger.info("[App] Waiting for shutdown...")
        await shutdown_event.wait()
        logger.info("[App] Shutdown signal received")
    
    # ========================================================================
    # 5. 清理
    # ========================================================================
    
    async def _cleanup(self):
        """清理资源"""
        logger.info("[App] Cleaning up...")
        
        if self.chat_agent:
            self.chat_agent.cleanup()
            logger.info("[App] ChatAgent cleaned up")
        
        logger.info("[App] Cleanup complete")
