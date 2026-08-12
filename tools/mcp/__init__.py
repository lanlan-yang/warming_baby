"""
tools.mcp - MCP (Model Context Protocol) 工具集成模块

将 MCP Server 暴露的工具动态包装成项目的 AgentTool，
自动注册进 tool_registry，无缝融入 LangGraph 工具链。

Usage:
    from tools.mcp import mcp_client_manager
    from tools.mcp import McpToolWrapper, MCPClientManager
    from tools.mcp.mcp_config import MCP_SERVERS
"""
from .mcp_bridge import McpToolWrapper
from .mcp_client import MCPClientManager, mcp_client_manager

__all__ = [
    "McpToolWrapper",
    "MCPClientManager",
    "mcp_client_manager",
]
