"""
tools.mcp.mcp_config - MCP Server 配置

配置所有通过 stdio 模式连接的 MCP Server。
每项配置对应一个 MCP Server 子进程。

格式与 Claude Desktop 的 claude_desktop_config.json 一致:
    {
        "command": "npx",
        "args": ["-y", "package-name"],
        "env": {...}  # 可选环境变量
    }

跨平台说明:
    macOS/Linux: 直接用 npx 即可
    Windows:     MCP SDK 无法直接 spawn .cmd 文件时，
                改为 command="cmd" + args=["/c", "npx", ...] 让 cmd.exe 解释执行，
                见文件底部 IS_WINDOWS 覆盖逻辑。
"""

from core.platform import IS_WINDOWS


# MCP Server 配置表（macOS / Linux 基础配置）
# enabled=False 的 Server 不会被加载
MCP_SERVERS = {
    "bing-search": {
        "command": "npx",
        "args": ["-y", "bing-cn-mcp"],
        # 搜索能力已由 tools/tool_websearch.py（uapis.cn 聚合搜索 API）替代
        # MCP 代码完整保留，需要时改回 True 即可恢复注册
        "enabled": False,
    },
    # 后续按需添加:
    # "fetch": {
    #     "command": "npx",
    #     "args": ["-y", "@modelcontextprotocol/server-fetch"],
    #     "enabled": False,
    # },
}

# Windows 覆盖: 通过 cmd /c 启动 npx，避免 SDK 直接 spawn .cmd 失败
if IS_WINDOWS:
    MCP_SERVERS["bing-search"]["command"] = "cmd"
    MCP_SERVERS["bing-search"]["args"] = ["/c", "npx", "-y", "bing-cn-mcp"]
