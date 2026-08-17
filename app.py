"""
app.py - Application 类

应用主类，封装完整生命周期:
    run() -> _setup() -> _start() -> _warmup() -> _run() -> _cleanup()
"""
import os
import asyncio
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QAction, QPixmap, QCursor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from qasync import QEventLoop

from version import __version__, __app_name__
from core.logger import setup_logger
from core import event_bus, EventCategory, SystemEvent, shutdown_event, reinit_shutdown_event, IS_MAC
from pet.pet import NuanbaoPet

logger = setup_logger()

if TYPE_CHECKING:
    from agent.chat.chat_agent import ChatAgent


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
        self.qt_app: QApplication = qt_app
        self.loop: QEventLoop = loop
        self.pet: Optional[NuanbaoPet] = None
        self.tray: Optional[QSystemTrayIcon] = None
        self.chat_agent: Optional[ChatAgent] = None
    
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
        if IS_MAC:
            try:
                from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
                app = NSApplication.sharedApplication()
                app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                logger.info("[App] Set to accessory mode (not in Dock, can have focus)")
            except Exception as e:
                logger.warning(f"[App] Failed to set background mode: {e}")

        # 设置应用图标
        # macOS: 必须在 setActivationPolicy 之后，否则 Dock 图标会被重置为默认
        # Windows: 设置 Qt 窗口图标即可
        try:
            from ui.base.managed_dialog import ManagedDialog
            ManagedDialog.setup_app_icon()
        except Exception as e:
            logger.warning(f"[App] Failed to set app icon: {e}")
    
    def _init_config_system(self):
        """初始化配置系统"""
        try:
            from config import config_manager
            
            config_manager.load()
            logger.info("[Config] Config loaded")

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
        from ui.widgets.menu import create_tray_icon
        return create_tray_icon(self.pet)
    
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

    async def _warmup_in_background(self, timeout: int = 30):
        """后台异步预热

        预热内容：
            1. Embedding 客户端初始化（云端 API，毫秒级）
            2. 注册工具（很快）
            3. 创建 ChatAgent（很快，LLM 延迟加载）

        LLM 和 Embedding 都是云端 API，不需要预热，
        第一次调用时会有冷启动时间。
        位置获取是异步后台任务，不阻塞预热流程。

        Args:
            timeout: 超时时间（秒）
        """
        main_loop = asyncio.get_running_loop()
        warmup_success = {'success': False}

        async def _init_async():
            """异步初始化 - 按依赖顺序执行"""
            try:
                # Step 1: 并行初始化 Embedding 客户端 + ChatGraph
                #   - Embedding: 云端 API 客户端，毫秒级初始化
                #   - ChatGraph: langchain 冷 import + init_chat_model + bind_tools (~1.5s)
                embedding_ok = True
                llm_init_ok = True

                async def _init_embedding():
                    nonlocal embedding_ok
                    try:
                        from memory import get_memory_manager
                        mgr = get_memory_manager()
                        await asyncio.to_thread(mgr.initialize)
                        if mgr.is_ready:
                            logger.info("[Warmup] Embedding client ready")
                        else:
                            # 初始化返回 False（如 key 错误），记录原因
                            embedding_ok = False
                            logger.warning(
                                f"[Warmup] Embedding init failed: {mgr.init_error}"
                            )
                    except Exception as e:
                        logger.warning(f"[Warmup] Embedding init failed (non-critical): {e}")
                        embedding_ok = False

                async def _prebuild_chat_graph():
                    """ChatGraph pre-build（需要 ChatAgent + tools 先就绪）"""
                    nonlocal llm_init_ok
                    try:
                        from config import secure_storage
                        if secure_storage.has_api_key():
                            await asyncio.to_thread(self.chat_agent._ensure_chat_graph)
                            logger.info("[Warmup] ChatGraph pre-built (LLM + tools + format_llm)")
                        else:
                            logger.info("[Warmup] No API Key, skip ChatGraph pre-build")
                            llm_init_ok = False
                    except Exception as e:
                        logger.warning(f"[Warmup] ChatGraph pre-build failed: {e}")
                        self._llm_init_error = str(e)
                        llm_init_ok = False

                # Step 2: 注册工具（需要在 ChatAgent 之前，很快 <1ms）
                from tools.tool_base import tool_registry

                try:
                    from tools.tool_weather import WeatherTool
                    tool_registry.register(WeatherTool)
                    logger.info("[Warmup] Weather tool registered")
                except Exception as e:
                    logger.warning(f"[Warmup] Weather tool register failed: {e}")

                try:
                    from tools.tool_location import get_current_location
                    tool_registry.register(get_current_location)
                    logger.info("[Warmup] Location tool registered")
                except Exception as e:
                    logger.warning(f"[Warmup] Location tool register failed: {e}")

                try:
                    from tools.tool_memory import register_memory_tools
                    register_memory_tools()
                    logger.info("[Warmup] Memory tools registered")
                except Exception as e:
                    logger.warning(f"[Warmup] Memory tools register failed: {e}")

                try:
                    from tools.tool_hotboard import HotboardTool
                    tool_registry.register(HotboardTool)
                    logger.info("[Warmup] Hotboard tool registered")
                except Exception as e:
                    logger.warning(f"[Warmup] Hotboard tool register failed: {e}")

                try:
                    from tools.tool_websearch import WebSearchTool
                    tool_registry.register(WebSearchTool)
                    logger.info("[Warmup] WebSearch tool registered")
                except Exception as e:
                    logger.warning(f"[Warmup] WebSearch tool register failed: {e}")

                # Step 2b: 启动 MCP Server，自动注册外部工具
                # （搜索已由 uapis.cn 聚合搜索 API 工具替代，MCP Server 在
                #   mcp_config.py 中 enabled=False，此处启动会跳过注册）
                try:
                    from tools.mcp import mcp_client_manager
                    mcp_tool_count = await mcp_client_manager.start()
                    if mcp_tool_count > 0:
                        logger.info(f"[Warmup] MCP tools registered: {mcp_tool_count}")
                except Exception as e:
                    logger.warning(f"[Warmup] MCP tools register failed: {e}")

                # Step 3: 创建 ChatAgent（很快，LLM 延迟加载）
                from agent import ChatAgent
                self.chat_agent = ChatAgent(event_loop=main_loop)
                logger.info("[Warmup] ChatAgent created")

                # Step 4: 并行执行 Embedding 加载 + ChatGraph pre-build
                await asyncio.gather(
                    _init_embedding(),
                    _prebuild_chat_graph(),
                )

                # 即使 embedding 失败，ChatAgent 也能用（只是没有记忆功能）
                warmup_success['success'] = True
                logger.info(f"[Warmup] Ready (embedding={'ok' if embedding_ok else 'disabled'})")

            except Exception as e:
                logger.error(f"[Warmup] Critical init failed: {e}")
                warmup_success['success'] = False
                self.chat_agent = None

        try:
            await asyncio.wait_for(_init_async(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[Warmup] Timeout ({timeout}s)")
        
        # 预热完成，通知 pet 切换回正常状态
        self.pet.finish_warming_up(warmup_success['success'])

        # 注入宠物状态提供者（ChatAgent 有了之后，把 PetStats 拼进 system prompt）
        if warmup_success['success'] and self.chat_agent is not None:
            self.chat_agent.set_status_provider(
                lambda: self.pet.stats.to_prompt()
            )

        # 首次运行检测：无 API Key 时提示用户配置
        self._check_first_run()
        
        # 发布就绪事件
        event_bus.publish(
            EventCategory.SYSTEM,
            SystemEvent.AGENT_READY,
            {"chat_agent": self.chat_agent is not None, "success": warmup_success['success']}
        )
        
        if warmup_success['success']:
            logger.info("[Warmup] Complete")
            
            # Warmup 完成后再启动位置获取，避免与正在执行的任务冲突
            # 这样可以确保 asyncio.to_thread 正常工作
            if self.chat_agent:
                self.chat_agent.start_location_fetch()
                logger.info("[Warmup] Location fetch started (post-warmup)")
        else:
            logger.warning("[Warmup] Failed")
    
    def _check_first_run(self):
        """首次运行检测：无 API Key 或初始化失败时提示用户右键配置"""
        try:
            from config import secure_storage
            has_llm_key = secure_storage.has_api_key()
            has_emb_key = secure_storage.has_embedding_api_key()

            if not has_llm_key:
                logger.info("[FirstRun] No API key configured, showing setup hint")
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(1500, lambda: self.pet.show_message(
                    "嗨～我是暖宝 🐹\n"
                    "第一次见面吧？\n"
                    "请右键我 → 「设置」配置 API Key\n"
                    "这样我才能陪你聊天哦！",
                    auto_hide=True,
                    is_auto_speak=True
                ))
                return

            # LLM Key 存在但初始化失败（如 key 错误/模型名错/网络问题）
            llm_err = getattr(self, "_llm_init_error", None)
            if llm_err:
                logger.warning(f"[FirstRun] LLM init failed: {llm_err}")
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(1500, lambda: self.pet.show_message(
                    "对话模型好像有点问题，我现在还不能说话……\n"
                    f"原因：{llm_err}\n"
                    "右键我 → 「设置」→「对话模型」→ 检查 API Key 和模型名是否正确。",
                    auto_hide=True,
                    is_auto_speak=True
                ))
                return

            # Embedding Key 缺失或初始化失败时，给精确提示
            if not has_emb_key:
                logger.info("[FirstRun] No Embedding key configured, showing hint")
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(1500, lambda: self.pet.show_message(
                    "对了，还需要配置一下「记忆模型」的 API Key\n"
                    "右键我 → 「设置」→「记忆模型」\n"
                    "这样我才能记住你说过的话哦！",
                    auto_hide=True,
                    is_auto_speak=True
                ))
                return

            # Key 存在但初始化失败（如 key 错误/网络问题）→ 检查 memory_manager 状态
            from memory import get_memory_manager
            mgr = get_memory_manager()
            if not mgr.is_ready:
                init_err = mgr.init_error or "未知原因"
                logger.warning(f"[FirstRun] Embedding init failed: {init_err}")
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(1500, lambda: self.pet.show_message(
                    "记忆模型好像有点问题，我记不住新东西了……\n"
                    f"原因：{init_err}\n"
                    "右键我 → 「设置」→「记忆模型」→ 检查 API Key 是否正确。",
                    auto_hide=True,
                    is_auto_speak=True
                ))
        except Exception as e:
            logger.warning(f"[FirstRun] Check failed: {e}")
    
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

        # 关闭 MCP Server 连接
        try:
            from tools.mcp import mcp_client_manager
            await mcp_client_manager.shutdown()
            logger.info("[App] MCP servers closed")
        except Exception as e:
            logger.warning(f"[App] Failed to close MCP servers: {e}")

        # 关闭 HTTP 客户端
        try:
            from tools.http_client import close_http_client
            await close_http_client()
            logger.info("[App] HTTP client closed")
        except Exception as e:
            logger.warning(f"[App] Failed to close HTTP client: {e}")

        logger.info("[App] Cleanup complete")
