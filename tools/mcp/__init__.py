"""
tools.mcp - MCP (Model Context Protocol) 工具集成模块

将 MCP Server 暴露的工具动态包装成项目的 AgentTool，
自动注册进 tool_registry，无缝融入 LangGraph 工具链。

支持:
    - stdio / remote（Streamable HTTP）双传输
    - 按 server 粒度的动态启停 / 测试连接 / 状态机管理
    - Claude Desktop 配置（mcpServers JSON）批量导入

Usage:
    from tools.mcp import mcp_client_manager
    await mcp_client_manager.load()        # 加载配置
    await mcp_client_manager.start_all()   # 启动所有已启用且已授权的 server
"""
from .mcp_bridge import McpToolWrapper
from .mcp_client import MCPClientManager, mcp_client_manager
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
from .mcp_store import load_servers, save_servers, parse_claude_config

__all__ = [
    "McpToolWrapper",
    "MCPClientManager",
    "mcp_client_manager",
    "McpErrorCode",
    "McpManagerError",
    "McpServerConfig",
    "McpServerState",
    "McpServerStatus",
    "McpTestResult",
    "McpTransportType",
    "RemoteTransport",
    "StdioTransport",
    "load_servers",
    "save_servers",
    "parse_claude_config",
]
