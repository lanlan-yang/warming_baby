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
        await self._show_pet_with_warming()  # 先显示宠物，播放预热动画
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
    # 3. 显示并预热
    # ========================================================================
    
    async def _show_pet_with_warming(self):
        """先显示宠物，然后异步预热
        
        流程:
        1. 立即显示宠物，播放 SEARCHING 等待动画
        2. 立即显示"正在加载..."提示
        3. 后台异步预热 LLM 和记忆系统
        4. 预热完成后切换回正常状态
        """
        # 1. 立即显示宠物
        self.pet.show()
        QApplication.processEvents()
        logger.info("[App] Pet shown immediately")
        
        # 2. 设置预热状态，播放等待动画
        self.pet.start_warming_up()
        logger.info("[App] Warming up animation started")
        
        # 3. 后台异步预热（不阻塞）
        asyncio.create_task(self._warmup_in_background())
        logger.info("[App] Background warmup started")

    async def _warmup_in_background(self, timeout: int = 10):
        """后台异步预热

        只需要初始化记忆系统（加载本地模型），LLM 是云端 API 不需要预热。

        Args:
            timeout: 超时时间（秒）
        """
        main_loop = asyncio.get_running_loop()
        warmup_success = {'success': False}

        async def _init_async():
            """异步初始化 - 创建 Agent 和初始化记忆"""
            try:
                # 创建 Agent（很快，因为是云端 API）
                from agent import ChatAgent
                self.chat_agent = ChatAgent(event_loop=main_loop)
                logger.info("[Warmup] ChatAgent created")

                # 初始化记忆系统（加载本地 Embedding 模型，需要时间）
                try:
                    from memory import get_memory_manager
                    await asyncio.to_thread(get_memory_manager().initialize)
                    logger.info("[Warmup] Memory ready")
                    warmup_success['success'] = True
                except Exception as e:
                    logger.warning(f"[Warmup] Memory init failed (non-critical): {e}")
                    warmup_success['success'] = True  # 记忆失败不影响主流程

            except Exception as e:
                logger.error(f"[Warmup] Agent init failed: {e}")
                warmup_success['success'] = False
                self.chat_agent = None

        try:
            await asyncio.wait_for(_init_async(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[Warmup] Timeout ({timeout}s)")
        
        # 预热完成，通知 pet 切换回正常状态
        self.pet.finish_warming_up(warmup_success['success'])
        
        # 发布就绪事件
        event_bus.publish(
            EventCategory.SYSTEM,
            SystemEvent.AGENT_READY,
            {"chat_agent": self.chat_agent is not None, "success": warmup_success['success']}
        )
        
        if warmup_success['success']:
            logger.info("[Warmup] Complete")
        else:
            logger.warning("[Warmup] Failed")
    
    # ========================================================================
    # 4. 运行
    # ========================================================================
    
    async def _run(self):
        """显示宠物并等待退出
        
        注意: 宠物已在 _show_pet_with_warming 中显示
        AGENT_READY 事件已在 _warmup_in_background 中发布
        """
        logger.info("[App] Running - waiting for shutdown...")
        
        # 等待退出
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
