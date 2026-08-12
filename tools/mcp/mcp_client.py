"""
tools.mcp.mcp_client - MCP Client 管理器

管理所有 MCP Server 的连接生命周期和工具注册。

核心职责:
    1. 启动 MCP Server 子进程（stdio 模式）
    2. 握手初始化 + 拉取工具列表
    3. 把 MCP 工具包装成 AgentTool 注册到 tool_registry
    4. 应用退出时优雅关闭所有连接

跨平台兼容:
    - macOS/Linux: 直接用 npx 启动
    - Windows:  自动解析 npx.cmd，UTF-8 编码，进程树清理

使用示例:
    from tools.mcp import mcp_client_manager

    # 启动时（在 asyncio 事件循环里）
    await mcp_client_manager.start()

    # 工具已自动注册进 tool_registry，直接用
    # ...

    # 退出时
    await mcp_client_manager.shutdown()

设计说明:
    - stdio 模式: Client 启动 Server 子进程，通过 stdin/stdout 通信
    - 一个 Server 可以暴露多个工具，全部自动注册
    - Server 启动失败不影响其他 Server 和主程序
"""
import asyncio
import sys
from typing import Any, Optional

from core.logger import logger
from core.platform import IS_WINDOWS
from .mcp_config import MCP_SERVERS
from .mcp_bridge import McpToolWrapper
from ..tool_base import tool_registry


def _resolve_command(command: str) -> str:
    """
    跨平台解析命令路径

    Windows:
        MCP SDK 内部已通过 _get_executable_command 处理了 npx → npx.cmd
        这里再加一层保险，用 shutil.which 显式解析。
        优先尝试命令全名，然后尝试 .cmd / .bat / .exe 扩展名。

    macOS/Linux:
        直接返回原命令，shell 会自动处理 PATH 查找。
    """
    if not IS_WINDOWS:
        return command

    import shutil

    # 1. 直接解析（npx 在 Windows 上可能返回 npx.cmd 的完整路径）
    resolved = shutil.which(command)
    if resolved:
        return resolved

    # 2. 尝试常见扩展名
    for ext in [".cmd", ".bat", ".exe", ".ps1"]:
        ext_path = shutil.which(f"{command}{ext}")
        if ext_path:
            return ext_path

    # 3. 兜底返回原命令（MCP SDK 内部还有一层处理）
    logger.warning(f"[MCPClient] Windows: 未在 PATH 中找到 '{command}'，兜底使用原命令")
    return command


class MCPClientManager:
    """
    MCP Client 生命周期管理器（单例）

    管理 N 个 MCP Server 的 ClientSession，
    自动把 Server 暴露的工具注册到 tool_registry。

    Attributes:
        _sessions: {server_name: ClientSession} 活跃的 MCP 会话
        _cleanup_funcs: 清理函数列表（逆序执行）
        _started: 是否已启动
    """

    def __init__(self):
        self._sessions: dict[str, Any] = {}      # server_name → ClientSession
        self._cleanup_funcs: list = []            # 清理函数列表
        self._started: bool = False

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def server_count(self) -> int:
        return len(self._sessions)

    async def start(self) -> int:
        """
        启动所有已配置且 enabled 的 MCP Server，注册工具

        Returns:
            成功注册的工具总数
        """
        if self._started:
            logger.warning("[MCPClient] 已启动，跳过重复初始化")
            return 0

        total_tools = 0

        for server_name, config in MCP_SERVERS.items():
            if not config.get("enabled", True):
                logger.debug(f"[MCPClient] 跳过已禁用的 Server: {server_name}")
                continue

            try:
                tool_count = await self._start_server(server_name, config)
                total_tools += tool_count
            except Exception as e:
                logger.warning(f"[MCPClient] Server '{server_name}' 启动失败: {e}")

        self._started = True
        logger.info(f"[MCPClient] 启动完成: {len(self._sessions)} 个 Server, {total_tools} 个工具")
        return total_tools

    async def _start_server(self, server_name: str, config: dict) -> int:
        """
        启动单个 MCP Server 并注册其工具

        Args:
            server_name: Server 名称（用于日志标识）
            config: Server 配置 (command, args, env)

        Returns:
            注册的工具数量
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # 跨平台解析命令路径
        command = _resolve_command(config["command"])

        # Windows: 强制 UTF-8 编码，避免中文工具描述乱码
        # macOS/Linux: 默认就是 utf-8，显式指定更安全
        encoding = config.get("encoding", "utf-8")

        server_params = StdioServerParameters(
            command=command,
            args=config.get("args", []),
            env=config.get("env"),
            encoding=encoding,
            encoding_error_handler=config.get("encoding_error_handler", "replace"),
        )

        platform_tag = " [Windows]" if IS_WINDOWS else ""
        logger.info(
            f"[MCPClient] 正在启动 Server: {server_name}"
            f" ({command} {' '.join(config.get('args', []))})"
            f"{platform_tag}"
        )

        # stdio 模式: 启动子进程，建立 read/write 管道
        ctx = stdio_client(server_params)
        read, write = await ctx.__aenter__()
        self._cleanup_funcs.append(lambda: ctx.__aexit__(None, None, None))

        # 在管道上建立 JSON-RPC 会话
        session_ctx = ClientSession(read, write)
        session = await session_ctx.__aenter__()
        self._cleanup_funcs.append(lambda: session_ctx.__aexit__(None, None, None))

        # 握手初始化
        await session.initialize()
        logger.info(f"[MCPClient] Server '{server_name}' 连接成功")

        # 发现工具
        tools_result = await session.list_tools()
        tools = tools_result.tools
        logger.info(f"[MCPClient] Server '{server_name}' 暴露 {len(tools)} 个工具")

        # 包装并注册每个工具
        for mcp_tool in tools:
            try:
                wrapper = McpToolWrapper.from_mcp_tool(session, mcp_tool, server_name)
                tool_registry.register(wrapper)
            except Exception as e:
                logger.warning(f"[MCPClient] 注册工具 '{mcp_tool.name}' 失败: {e}")

        self._sessions[server_name] = session

        return len(tools)

    async def shutdown(self) -> None:
        """优雅关闭所有 MCP Server 连接"""
        if not self._started:
            return

        logger.info(f"[MCPClient] 正在关闭 {len(self._sessions)} 个 Server...")

        # 逆序清理（先关 session，再关 stdio_client）
        for cleanup_func in reversed(self._cleanup_funcs):
            try:
                await cleanup_func()
            except Exception as e:
                logger.warning(f"[MCPClient] 清理连接时出错: {e}")

        # Windows: 清理可能残留的子进程树
        if IS_WINDOWS:
            self._kill_orphan_servers()

        self._sessions.clear()
        self._cleanup_funcs.clear()
        self._started = False
        logger.info("[MCPClient] 所有 Server 已关闭")

    def _kill_orphan_servers(self) -> None:
        """
        Windows 专用: 清理可能残留的 MCP Server 子进程树

        Windows 上 process.kill() 不会递归终止子进程
        （npx → node → mcp-server 子进程链），
        容易产生僵尸进程。用 taskkill /F /T 强制杀掉整棵进程树。

        MCP SDK 的 stdio_client 关闭时会尝试 process.kill(),
        但它只杀父进程，不递归杀子进程。这里做兜底清理。
        """
        try:
            import subprocess
            import os

            # 查找残留的 npx/node 进程
            # 用 wmic 或 tasklist 找包含 bing-cn-mcp 关键字的进程
            for server_name in self._sessions:
                try:
                    # 用 taskkill 按进程名关键字模糊清理
                    # /F: 强制  /T: 杀掉子进程树
                    result = subprocess.run(
                        [
                            "taskkill", "/F", "/T",
                            "/FI", f"WINDOWTITLE eq *{server_name}*",
                        ],
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        logger.info(f"[MCPClient] Windows: 已终止 '{server_name}' 进程树")
                except Exception:
                    pass

            # 兜底: 清理所有 npx/node 僵尸进程（仅限我们的 mcp 相关）
            # 用 PowerShell 查找父进程已退出的 node 进程
            try:
                subprocess.run(
                    [
                        "powershell", "-Command",
                        "Get-Process node -ErrorAction SilentlyContinue | "
                        "Where-Object { $_.StartTime -lt (Get-Date).AddMinutes(-5) } | "
                        "Stop-Process -Force -ErrorAction SilentlyContinue",
                    ],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"[MCPClient] Windows 子进程清理异常（不影响主流程）: {e}")

    def get_session(self, server_name: str) -> Optional[Any]:
        """获取指定 Server 的 ClientSession"""
        return self._sessions.get(server_name)


# 全局单例
mcp_client_manager = MCPClientManager()
