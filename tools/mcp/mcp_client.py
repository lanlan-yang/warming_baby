"""
tools.mcp.mcp_client - MCP Client 管理器（按 server 粒度的状态机）

重构自旧版"一次性全量启动"的 MCPClientManager，核心变化:
    1. 每个 server 一条状态机: DISABLED/IDLE/STARTING/RUNNING/STOPPING/FAILED
       （状态转移表见 mcp_schema.McpServerState，非法转移抛 McpManagerError）
    2. 支持动态增删改、启停、测试连接（UI「MCP 管理器」直接消费本类 API）
    3. stdio + remote（Streamable HTTP）双传输
    4. 每 server 一把 asyncio.Lock 串行化生命周期操作
    5. 断连被动检测: 工具调用抛连接级异常 → RUNNING 转 FAILED

跨平台兼容:
    - macOS/Linux: stdio 命令经 runtime_detect 分层探测（GUI 进程无登录 shell PATH）
    - Windows:     .cmd/.bat 解析 + UTF-8 编码 + 退出时进程树兜底清理

使用示例:
    from tools.mcp import mcp_client_manager

    await mcp_client_manager.load()          # 启动时加载配置（不启动 server）
    await mcp_client_manager.start_all()     # 并行启动所有已启用且已授权的 server
    ...
    await mcp_client_manager.shutdown_all()  # 退出时优雅关闭
"""
import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

from core import event_bus, EventCategory, SystemEvent
from core.logger import logger
from core.platform import IS_WINDOWS
from .mcp_schema import (
    McpErrorCode,
    McpManagerError,
    McpServerConfig,
    McpServerState,
    McpServerStatus,
    McpTestResult,
    McpTransportType,
    RemoteTransport,
    StdioTransport,
)
from .mcp_store import load_servers, save_servers
from . import runtime_detect
from .mcp_bridge import McpToolWrapper
from ..tool_base import tool_registry


# 启动整体超时（spawn + 握手 + 工具发现）。npx 冷启动要下载包，给足余量
START_TIMEOUT_S = 20


# ============================================================
# 状态转移表（状态机的"法律"）
# ============================================================
_ALLOWED_TRANSITIONS: dict[McpServerState, set[McpServerState]] = {
    McpServerState.DISABLED: {McpServerState.IDLE},
    McpServerState.IDLE: {McpServerState.DISABLED, McpServerState.STARTING},
    McpServerState.STARTING: {McpServerState.RUNNING, McpServerState.FAILED},
    McpServerState.RUNNING: {McpServerState.STOPPING, McpServerState.FAILED},
    McpServerState.STOPPING: {McpServerState.IDLE},
    McpServerState.FAILED: {
        McpServerState.STARTING,   # 重试
        McpServerState.STOPPING,   # stop 一个失败残留的 server
        McpServerState.DISABLED,   # 直接禁用
    },
}


def _sanitize_tool_name(name: str) -> str:
    """工具名合法化: 只保留字母/数字/下划线/中划线（LLM bind_tools 对名字有要求）"""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in name)


@asynccontextmanager
async def _remote_streamable_http(url: str, headers: dict[str, str] | None):
    """
    remote 传输上下文（mcp 2.0 API）

    mcp 2.0 中 headers 不再是 streamable_http_client 的独立参数，
    需通过预配置的 httpx AsyncClient 传入；且 http client 生命周期
    必须覆盖传输层，故包成一个上下文统一进出。
    """
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    async with create_mcp_http_client(headers=headers or None) as http_client:
        async with streamable_http_client(url, http_client=http_client) as streams:
            yield streams


def _build_remote_transport(url: str, headers: dict[str, str] | None):
    """构造 remote 传输上下文（返回带 __aenter__/__aexit__ 的对象，与 stdio_client 同构）"""
    return _remote_streamable_http(url, headers)


@dataclass
class ManagedServer:
    """一个 server 的运行时记录（配置之外的全部易变状态，不持久化）"""
    config: McpServerConfig
    state: McpServerState = McpServerState.IDLE
    error: Optional[str] = None
    error_code: Optional[McpErrorCode] = None

    session: Any = None                        # mcp.ClientSession
    _transport_ctx: Any = None                 # stdio_client / streamablehttp_client 的 async CM
    _session_ctx: Any = None                   # ClientSession 的 async CM
    _stop_event: Optional[asyncio.Event] = None  # 通知监督任务收尾
    _conn_task: Optional[asyncio.Task] = None    # 连接监督任务（上下文在其内 enter/exit）

    tool_registry_names: list[str] = field(default_factory=list)  # 注册进 tool_registry 的带前缀名
    mcp_tools: list[Any] = field(default_factory=list)            # server 暴露的 mcp Tool 对象
    mcp_tool_names: list[str] = field(default_factory=list)       # server 暴露的原始工具名
    started_at: Optional[float] = None
    last_test: Optional[McpTestResult] = None

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def is_alive(self) -> bool:
        """是否有需要清理的连接上下文"""
        return self._session_ctx is not None or self._transport_ctx is not None


def _classify_error(e: Exception, stage: str, transport_type: McpTransportType) -> McpErrorCode:
    """
    异常 → McpErrorCode（按启动阶段分类）

    Args:
        stage: "connect" | "initialize" | "tools"
    """
    if isinstance(e, asyncio.TimeoutError):
        return McpErrorCode.START_TIMEOUT

    if stage == "connect":
        if isinstance(e, (FileNotFoundError, NotADirectoryError, PermissionError)):
            return McpErrorCode.RUNTIME_NOT_FOUND
        if transport_type == McpTransportType.REMOTE:
            return McpErrorCode.HTTP_ERROR
        return McpErrorCode.HANDSHAKE_FAILED

    if stage == "initialize":
        return McpErrorCode.HANDSHAKE_FAILED

    return McpErrorCode.DISCOVERY_FAILED


class MCPClientManager:
    """
    MCP Client 生命周期管理器（单例，按 server 粒度）

    对外 API 分四组:
        配置加载:   load()
        应用级:     start_all() / shutdown_all()
        单 server:  start_server / stop_server / restart_server / test_config / test_server
        CRUD+查询:  add_server / update_server / remove_server / set_enabled /
                    set_trusted / get_status / list_statuses
    """

    def __init__(self):
        self._servers: dict[str, ManagedServer] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ============================================================
    # 配置加载
    # ============================================================
    def load(self) -> None:
        """
        从 mcp_store 读取配置填充 _servers（只建记录，不启动）

        状态初始化: enabled=True → IDLE, enabled=False → DISABLED
        app.py 启动时调用。
        """
        if self._loaded:
            logger.warning("[MCPClient] 已加载，跳过重复初始化")
            return

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        for config in load_servers():
            self._servers[config.name] = ManagedServer(
                config=config,
                state=McpServerState.IDLE if config.enabled else McpServerState.DISABLED,
            )

        self._loaded = True
        logger.info(
            f"[MCPClient] 配置已加载: {len(self._servers)} 个 server "
            f"({sum(1 for s in self._servers.values() if s.config.enabled)} 个启用)"
        )

    def _ensure_loaded(self) -> None:
        """CRUD 前确保配置已加载（UI 可能在 app 未 load 时先打开管理器）"""
        if not self._loaded:
            self.load()

    def _persist(self) -> None:
        save_servers([s.config for s in self._servers.values()])

    # ============================================================
    # 应用级生命周期
    # ============================================================
    async def start_all(self) -> dict[str, Any]:
        """
        并行启动所有 IDLE 且 trusted 的 server

        Returns:
            {name: 工具数 或 McpErrorCode 值}，单 server 失败不影响其他
        """
        self._ensure_loaded()
        targets = [
            name for name, s in self._servers.items()
            if s.state == McpServerState.IDLE and s.config.trusted
        ]
        if not targets:
            logger.info("[MCPClient] 无可启动的 server")
            return {}

        logger.info(f"[MCPClient] 并行启动 {len(targets)} 个 server: {targets}")

        async def _start_one(name: str) -> tuple[str, Any]:
            try:
                return name, await self.start_server(name)
            except McpManagerError as e:
                return name, e.code.value

        results = dict(await asyncio.gather(*[_start_one(n) for n in targets]))
        ok = sum(1 for v in results.values() if isinstance(v, int))
        logger.info(f"[MCPClient] start_all 完成: {ok}/{len(results)} 成功: {results}")
        return results

    async def shutdown_all(self) -> None:
        """应用退出: 逐个走 stop 流程 + Windows 进程树兜底"""
        if not self._servers:
            return

        logger.info(f"[MCPClient] 正在关闭 {len(self._servers)} 个 server...")
        for name in list(self._servers.keys()):
            try:
                await self.stop_server(name)
            except McpManagerError:
                pass  # IDLE/DISABLED 等静态态，无需停止
            except Exception as e:
                logger.warning(f"[MCPClient] 关闭 '{name}' 出错: {e}")

        if IS_WINDOWS:
            self._kill_orphan_servers()

        logger.info("[MCPClient] 所有 server 已关闭")

    # ============================================================
    # 单 server 生命周期
    # ============================================================
    async def start_server(self, name: str) -> int:
        """
        IDLE/FAILED → STARTING → RUNNING，返回注册的工具数

        流程: lock → 守卫检查 → 运行时解析(stdio) → spawn → initialize
              → list_tools → 注册工具 → 发事件
        Raises:
            McpManagerError: 守卫失败或启动失败（含错误码）
        """
        self._ensure_loaded()
        entry = self._require(name)

        async with entry.lock:
            # ---- 守卫检查 ----
            if entry.state not in (McpServerState.IDLE, McpServerState.FAILED):
                raise McpManagerError(McpErrorCode.INVALID_STATE, f"当前状态 {entry.state} 不允许启动")
            if not entry.config.enabled:
                raise McpManagerError(McpErrorCode.INVALID_STATE, "server 已禁用，请先启用")
            if not entry.config.trusted:
                raise McpManagerError(McpErrorCode.NOT_TRUSTED, "未授权，请先在授权确认后启动")

            config = entry.config
            transport_type = (
                McpTransportType.STDIO
                if isinstance(config.transport, StdioTransport)
                else McpTransportType.REMOTE
            )

            self._transition(entry, McpServerState.STARTING)

            try:
                timeout = (
                    START_TIMEOUT_S
                    if transport_type == McpTransportType.STDIO
                    else config.transport.connect_timeout + 5
                )
                # 连接监督任务：上下文在同一 task 内 enter/exit
                # （anyio cancel scope 绑定 task，跨 task 退出会抛
                #  "Attempted to exit cancel scope in a different task"）
                entry._stop_event = asyncio.Event()
                ready = asyncio.Event()
                holder: dict = {}
                entry._conn_task = asyncio.create_task(
                    self._supervise_connection(entry, config, ready, holder)
                )

                await asyncio.wait_for(ready.wait(), timeout=timeout)
                if (open_error := holder.get("error")) is not None:
                    raise open_error
                session = entry.session

                try:
                    await session.initialize()
                except Exception as e:
                    e._mcp_stage = "initialize"  # type: ignore[attr-defined]
                    raise

                try:
                    tools = (await session.list_tools()).tools
                except Exception as e:
                    e._mcp_stage = "tools"  # type: ignore[attr-defined]
                    raise
            except (Exception, asyncio.TimeoutError) as e:
                # 启动失败: 通知监督任务收尾（同 task 退出上下文）→ FAILED
                await self._close_connection(entry)
                code = _classify_error(e, getattr(e, "_mcp_stage", "connect"), transport_type)
                self._transition(
                    entry, McpServerState.FAILED,
                    error=str(e) or type(e).__name__, error_code=code,
                )
                raise McpManagerError(code, f"启动 '{name}' 失败: {e}") from e

            # ---- 成功: 注册工具（session 已由监督任务挂到 entry 上） ----
            entry.started_at = time.time()
            entry.mcp_tools = list(tools)
            entry.mcp_tool_names = [t.name for t in tools]
            entry.tool_registry_names = self._register_tools(entry, session)

            self._transition(entry, McpServerState.RUNNING)
            logger.info(f"[MCPClient] '{name}' 启动成功，注册 {len(tools)} 个工具")
            return len(tools)

    async def _supervise_connection(
        self, entry: ManagedServer, config: McpServerConfig,
        ready: asyncio.Event, holder: dict,
    ) -> None:
        """连接监督任务：本 task 内打开上下文并驻留，收到 stop_event 后在同一 task 内退出"""
        try:
            session, t_ctx, s_ctx = await self._open_session(config)
        except Exception as e:
            holder["error"] = e
            ready.set()
            return

        entry.session = session
        entry._transport_ctx = t_ctx
        entry._session_ctx = s_ctx
        ready.set()

        try:
            # 驻留直到被要求停止（stop_server / 启动失败收尾）
            await entry._stop_event.wait()
        except asyncio.CancelledError:
            # 远端断连会触发 mcp 内部 anyio cancel scope 取消并传播到本 task；
            # 吞掉异常继续统一收尾（上下文退出必须与 enter 同 task）
            logger.debug(f"[MCPClient] '{config.name}' 监督任务被取消，转收尾")

        # 退出必须与 enter 同 task（finally 保证异常路径也退出）
        try:
            for ctx_close in (s_ctx.__aexit__, t_ctx.__aexit__):
                try:
                    await ctx_close(None, None, None)
                except (Exception, asyncio.CancelledError) as e:
                    # 粘性取消可能导致退出再次被打断：尽力而为，不让异常逃逸卡死状态机
                    logger.warning(f"[MCPClient] 关闭 '{config.name}' 连接时出错: {e}")
        finally:
            entry.session = None
            entry._transport_ctx = None
            entry._session_ctx = None

    async def _close_connection(self, entry: ManagedServer) -> None:
        """请求监督任务收尾并等待其结束；无监督任务时回退直接清理

        任何情况下都不抛异常（含 CancelledError），保证调用方状态机一定走完。
        """
        task = entry._conn_task
        stop_event = entry._stop_event
        # 先唤醒监督任务（其驻留在该事件上），再清引用（下次 start 会建新事件）
        if stop_event is not None:
            stop_event.set()
        entry._stop_event = None

        if task is None:
            await self._cleanup_contexts(entry)  # 历史半开上下文兜底
            return

        try:
            await asyncio.wait_for(asyncio.shield(task), 10)
        except BaseException:
            # 超时未收尾，或监督任务被 anyio cancel scope 取消而以
            # CancelledError 结束（不属于 Exception，必须按 BaseException 接）→ 强制取消兜底
            task.cancel()
            try:
                await task
            except BaseException:
                pass
        entry._conn_task = None
        entry.session = None

    async def stop_server(self, name: str) -> None:
        """RUNNING/FAILED → STOPPING → IDLE。注销工具，清理连接"""
        self._ensure_loaded()
        entry = self._require(name)

        async with entry.lock:
            if entry.state not in (McpServerState.RUNNING, McpServerState.FAILED):
                raise McpManagerError(McpErrorCode.INVALID_STATE, f"当前状态 {entry.state} 不允许停止")

            self._transition(entry, McpServerState.STOPPING)

            self._unregister_tools(entry)
            await self._close_connection(entry)
            entry.started_at = None

            self._transition(entry, McpServerState.IDLE)
            logger.info(f"[MCPClient] '{name}' 已停止")

    async def restart_server(self, name: str) -> int:
        """stop + start 的原子组合（同一把 lock 内依次执行）"""
        self._require(name)
        try:
            await self.stop_server(name)
        except McpManagerError:
            pass  # 静态态直接 start
        return await self.start_server(name)

    # ============================================================
    # 测试连接（临时连接，不碰状态机、不注册工具、不落盘）
    # ============================================================
    async def test_config(self, config: McpServerConfig) -> McpTestResult:
        """
        用一份配置建立临时连接完成 initialize + list_tools 后立刻销毁

        stdio 测试成功时顺带做运行时探测，把 resolved_path 写回传入的 config。
        """
        start_ms = time.time() * 1000
        transport_type = (
            McpTransportType.STDIO
            if isinstance(config.transport, StdioTransport)
            else McpTransportType.REMOTE
        )
        timeout = (
            START_TIMEOUT_S
            if transport_type == McpTransportType.STDIO
            else config.transport.connect_timeout + 5
        )

        try:
            result = await asyncio.wait_for(
                self._test_once(config), timeout=timeout
            )
        except (Exception, asyncio.TimeoutError) as e:
            code = _classify_error(e, getattr(e, "_mcp_stage", "connect"), transport_type)
            return McpTestResult(
                ok=False,
                error_code=code.value,
                message=f"{code.value}: {e}",
                duration_ms=int(time.time() * 1000 - start_ms),
            )

        result.duration_ms = int(time.time() * 1000 - start_ms)
        return result

    async def test_server(self, name: str) -> McpTestResult:
        """对已保存的 server 执行 test_config，结果记入 last_test"""
        entry = self._require(name)
        entry.last_test = await self.test_config(entry.config)
        self._publish_state(entry)
        return entry.last_test

    async def _test_once(self, config: McpServerConfig) -> McpTestResult:
        """单次临时连接测试（test_config 的无超时内核）"""
        session, t_ctx, s_ctx = await self._open_session(config)

        try:
            try:
                await session.initialize()
            except Exception as e:
                e._mcp_stage = "initialize"  # type: ignore[attr-defined]
                raise

            try:
                tools = (await session.list_tools()).tools
            except Exception as e:
                e._mcp_stage = "tools"  # type: ignore[attr-defined]
                raise
        finally:
            # 无论成败都立刻销毁临时连接
            for ctx_close in (s_ctx.__aexit__, t_ctx.__aexit__):
                try:
                    await ctx_close(None, None, None)
                except Exception:
                    pass

        return McpTestResult(
            ok=True,
            message=f"连接成功，暴露 {len(tools)} 个工具",
            tool_count=len(tools),
            tool_names=[t.name for t in tools],
        )

    # ============================================================
    # 连接建立（start 监督任务与 test 共用）
    # ============================================================
    async def _open_session(self, config: McpServerConfig):
        """
        打开传输 + 建立 ClientSession（不握手）

        stdio:  spawn 子进程，命令经 runtime_detect 解析
        remote: Streamable HTTP 连接
        """
        from mcp import ClientSession

        if isinstance(config.transport, StdioTransport):
            t = config.transport
            command, detected = runtime_detect.resolve_stdio_command(
                t.command, t.resolved_path
            )
            if detected and detected != t.resolved_path:
                t.resolved_path = detected  # 探测成功，写回配置持久化
                self._persist()

            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            server_params = StdioServerParameters(
                command=command,
                args=list(t.args),
                env=t.env or None,
                encoding=t.encoding,
                encoding_error_handler="replace",
            )
            logger.info(f"[MCPClient] '{config.name}' stdio 启动: {command} {' '.join(t.args)}")
            t_ctx = stdio_client(server_params)
        else:
            t = config.transport
            logger.info(f"[MCPClient] '{config.name}' remote 连接: {t.url}")
            t_ctx = _build_remote_transport(t.url, t.headers)

        read, write = await t_ctx.__aenter__()

        s_ctx = ClientSession(read, write)
        session = await s_ctx.__aenter__()
        return session, t_ctx, s_ctx

    async def _cleanup_contexts(self, entry: ManagedServer) -> None:
        """逆序关闭该 server 的 session 与 transport 上下文"""
        for ctx_close in (
            entry._session_ctx.__aexit__ if entry._session_ctx else None,
            entry._transport_ctx.__aexit__ if entry._transport_ctx else None,
        ):
            if ctx_close is None:
                continue
            try:
                await ctx_close(None, None, None)
            except (Exception, asyncio.CancelledError) as e:
                logger.warning(f"[MCPClient] 清理 '{entry.config.name}' 连接时出错: {e}")
        entry._session_ctx = None
        entry._transport_ctx = None

    # ============================================================
    # 工具注册 / 注销（带命名空间前缀）
    # ============================================================
    def _register_tools(self, entry: ManagedServer, session: Any) -> list[str]:
        """把 server 暴露的工具包装注册进 tool_registry，返回注册名列表"""
        registered: list[str] = []
        prefix = _sanitize_tool_name(entry.config.name)
        existing = set(tool_registry.list_names())

        for mcp_tool in entry.mcp_tools:
            registry_name = f"{prefix}_{_sanitize_tool_name(mcp_tool.name)}"
            # 极端冲突: 两个 server 前缀+工具名撞车 → 加后缀
            while registry_name in existing:
                registry_name += "_x"

            try:
                wrapper = McpToolWrapper.from_mcp_tool(
                    session,
                    mcp_tool,
                    server_name=entry.config.name,
                    registry_name=registry_name,
                    on_disconnect=self._on_disconnect,
                )
                tool_registry.register(wrapper)
                registered.append(registry_name)
                existing.add(registry_name)
            except Exception as e:
                logger.warning(f"[MCPClient] 注册工具 '{registry_name}' 失败: {e}")

        return registered

    def _unregister_tools(self, entry: ManagedServer) -> None:
        """注销该 server 注册的全部工具"""
        for registry_name in entry.tool_registry_names:
            tool_registry.unregister(registry_name)
        entry.tool_registry_names.clear()
        entry.mcp_tools.clear()
        entry.mcp_tool_names.clear()

    # ============================================================
    # 断连被动检测
    # ============================================================
    async def _on_disconnect(self, server_name: str) -> None:
        """McpToolWrapper 调用工具发现连接级异常时回调: RUNNING → FAILED"""
        entry = self._servers.get(server_name)
        if entry is None or entry.state != McpServerState.RUNNING:
            return

        logger.warning(f"[MCPClient] 检测到 '{server_name}' 断连，转入 FAILED")
        self._unregister_tools(entry)
        await self._close_connection(entry)
        self._transition(
            entry, McpServerState.FAILED,
            error="连接断开（工具调用时检测到）",
            error_code=McpErrorCode.CONNECTION_LOST,
        )

    # ============================================================
    # CRUD（同步方法，均落盘）
    # ============================================================
    def add_server(self, config: McpServerConfig) -> None:
        """新增 server 配置。重名抛 DUPLICATE_NAME"""
        self._ensure_loaded()
        if config.name in self._servers:
            raise McpManagerError(McpErrorCode.DUPLICATE_NAME, f"'{config.name}' 已存在")
        self._servers[config.name] = ManagedServer(
            config=config,
            state=McpServerState.IDLE if config.enabled else McpServerState.DISABLED,
        )
        self._persist()
        self._publish_state(self._servers[config.name])
        logger.info(f"[MCPClient] 已添加 server '{config.name}'")

    def update_server(self, config: McpServerConfig) -> None:
        """
        更新 server 配置。运行中 → 自动 stop → 落盘 → 自动重启（后台任务）
        """
        self._ensure_loaded()
        entry = self._require(config.name)
        was_running = entry.state == McpServerState.RUNNING

        async def _update_flow():
            if entry.state in (McpServerState.RUNNING, McpServerState.FAILED):
                try:
                    await self.stop_server(config.name)
                except McpManagerError:
                    pass
            entry.config = config
            self._persist()
            self._publish_state(entry)
            if was_running:
                try:
                    await self.start_server(config.name)
                except McpManagerError as e:
                    logger.warning(f"[MCPClient] 更新后自动重启 '{config.name}' 失败: {e}")

        self._run_background(_update_flow())
        logger.info(f"[MCPClient] 已更新 server '{config.name}' (was_running={was_running})")

    def remove_server(self, name: str) -> None:
        """删除 server。仅 DISABLED/IDLE/FAILED 允许（运行中请先停止）"""
        self._ensure_loaded()
        entry = self._require(name)
        if entry.state in (McpServerState.STARTING, McpServerState.RUNNING, McpServerState.STOPPING):
            raise McpManagerError(McpErrorCode.INVALID_STATE, f"server 正在 {entry.state}，请先停止")
        self._unregister_tools(entry)  # FAILED 残留时兜底清理
        del self._servers[name]
        self._persist()
        logger.info(f"[MCPClient] 已删除 server '{name}'")

    def set_enabled(self, name: str, enabled: bool) -> None:
        """启用/禁用（总开关）。运行中被禁用 → 后台自动 stop"""
        self._ensure_loaded()
        entry = self._require(name)
        entry.config.enabled = enabled
        self._persist()

        if enabled:
            if entry.state == McpServerState.DISABLED:
                self._transition(entry, McpServerState.IDLE)
        else:
            if entry.state == McpServerState.IDLE:
                self._transition(entry, McpServerState.DISABLED)
            elif entry.state == McpServerState.FAILED:
                self._transition(entry, McpServerState.DISABLED)
            elif entry.state in (McpServerState.RUNNING, McpServerState.STARTING):
                async def _stop_flow():
                    try:
                        await self.stop_server(name)
                    except McpManagerError:
                        pass
                    if entry.state in (McpServerState.IDLE, McpServerState.FAILED):
                        self._transition(entry, McpServerState.DISABLED)

                self._run_background(_stop_flow())
                return

        self._publish_state(entry)

    def set_trusted(self, name: str, trusted: bool) -> None:
        """授权标记（UI 授权对话框确认后调用）"""
        self._ensure_loaded()
        entry = self._require(name)
        entry.config.trusted = trusted
        self._persist()
        self._publish_state(entry)

    # ============================================================
    # 查询
    # ============================================================
    def get_status(self, name: str) -> Optional[McpServerStatus]:
        entry = self._servers.get(name)
        return self._build_status(entry) if entry else None

    def get_config(self, name: str) -> Optional[McpServerConfig]:
        """获取指定 server 的完整配置（UI 编辑表单用）"""
        entry = self._servers.get(name)
        return entry.config if entry else None

    def list_statuses(self) -> list[McpServerStatus]:
        return [self._build_status(e) for e in self._servers.values()]

    def get_session(self, name: str):
        """获取指定 server 的 ClientSession（兼容旧接口）"""
        entry = self._servers.get(name)
        return entry.session if entry else None

    def get_display_name(self, name: str) -> str:
        """
        获取 server 的展示名（供 UI 过程提示显示，如"正在用 必应搜索 查询…"）

        优先取 description 的首个括号前片段（如"必应搜索（内置…）" → "必应搜索"），
        无 description 则返回 name 原值。server 不存在也返回 name。
        """
        entry = self._servers.get(name)
        if entry is None:
            return name
        desc = entry.config.description or ""
        first_seg = desc.split("（")[0].split("(")[0].strip()
        return first_seg or name

    # ============================================================
    # 内部工具
    # ============================================================
    def _require(self, name: str) -> ManagedServer:
        entry = self._servers.get(name)
        if entry is None:
            raise McpManagerError(McpErrorCode.NOT_FOUND, f"server '{name}' 不存在")
        return entry

    def _run_background(self, coro) -> None:
        """在主事件循环上跑后台任务（qasync 下 Qt 主线程即 loop 线程）"""
        if self._loop and not self._loop.is_closed():
            task = self._loop.create_task(coro)
            task.add_done_callback(self._log_task_error)
        else:
            logger.warning("[MCPClient] 无可用事件循环，后台任务被丢弃")

    @staticmethod
    def _log_task_error(task: asyncio.Task) -> None:
        if task.cancelled():
            return  # 取消不是错误（task.exception() 对已取消任务会抛 CancelledError）
        if task.exception():
            logger.error(f"[MCPClient] 后台任务错误: {task.exception()}")

    def _transition(
        self,
        entry: ManagedServer,
        new_state: McpServerState,
        error: Optional[str] = None,
        error_code: Optional[McpErrorCode] = None,
    ) -> None:
        """
        统一状态转移入口: 校验合法性 → 更新 → 发事件

        禁止直接赋值 entry.state，保证事件一定发出来。
        """
        if new_state not in _ALLOWED_TRANSITIONS.get(entry.state, set()):
            raise McpManagerError(
                McpErrorCode.INVALID_STATE,
                f"非法状态转移: {entry.state} → {new_state} ('{entry.config.name}')",
            )

        entry.state = new_state
        if new_state == McpServerState.FAILED:
            entry.error = error
            entry.error_code = error_code
        elif new_state in (McpServerState.IDLE, McpServerState.RUNNING, McpServerState.DISABLED):
            entry.error = None
            entry.error_code = None

        logger.debug(f"[MCPClient] '{entry.config.name}' 状态: {new_state.value}")
        self._publish_state(entry)

    def _build_status(self, entry: ManagedServer) -> McpServerStatus:
        t = entry.config.transport
        return McpServerStatus(
            name=entry.config.name,
            state=entry.state,
            transport_type=(
                McpTransportType.STDIO if isinstance(t, StdioTransport) else McpTransportType.REMOTE
            ),
            enabled=entry.config.enabled,
            trusted=entry.config.trusted,
            error=entry.error,
            error_code=entry.error_code.value if entry.error_code else None,
            tool_count=len(entry.tool_registry_names),
            tool_names=list(entry.mcp_tool_names),
            started_at=entry.started_at,
            last_test=entry.last_test,
        )

    def _publish_state(self, entry: ManagedServer) -> None:
        """发布状态快照事件（UI 订阅刷新 / ChatAgent 订阅刷新工具绑定）"""
        event_bus.publish(
            EventCategory.SYSTEM,
            SystemEvent.MCP_SERVER_STATE,
            self._build_status(entry).model_dump(),
        )

    # ============================================================
    # Windows 兜底: 残留进程树清理
    # ============================================================
    def _kill_orphan_servers(self) -> None:
        """
        Windows 专用: 清理可能残留的 MCP Server 子进程树

        Windows 上 process.kill() 不会递归终止子进程
        （npx → node → mcp-server 子进程链），容易产生僵尸进程。
        """
        try:
            import subprocess

            for name in self._servers:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/FI", f"WINDOWTITLE eq *{name}*"],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass

            subprocess.run(
                [
                    "powershell", "-Command",
                    "Get-Process node -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.StartTime -lt (Get-Date).AddMinutes(-5) } | "
                    "Stop-Process -Force -ErrorAction SilentlyContinue",
                ],
                capture_output=True, timeout=5,
            )
        except Exception as e:
            logger.warning(f"[MCPClient] Windows 子进程清理异常（不影响主流程）: {e}")


# 全局单例
mcp_client_manager = MCPClientManager()
