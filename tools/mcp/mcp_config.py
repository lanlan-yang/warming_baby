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
    Windows:    代码会自动处理 npx → npx.cmd 路径解析和 UTF-8 编码
                如需手动指定 cmd 启动方式，可在 config 中覆盖:
                {
                    "command": "cmd",
                    "args": ["/c", "npx", "-y", "bing-cn-mcp"]
                }
"""

# MCP Server 配置表
# enabled=False 的 Server 不会被加载
MCP_SERVERS = {
    "bing-search": {
        "command": "npx",
        "args": ["-y", "bing-cn-mcp"],
        "enabled": True,
    },
    # 后续按需添加:
    # "fetch": {
    #     "command": "npx",
    #     "args": ["-y", "@modelcontextprotocol/server-fetch"],
    #     "enabled": False,
    # },
}
