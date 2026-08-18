"""
tools.mcp.mcp_store - MCP Server 配置持久化

职责:
    1. mcp_servers.json 的读写（位于 config.storage.get_config_dir()）
    2. 内置默认 server 的 merge（用户配置优先）
    3. Claude Desktop 的 claude_desktop_config.json 格式解析（批量导入）

存储格式（list 而非 dict，name 在配置内部，model_validate 直接吃）:
    {
        "version": 1,
        "servers": [
            {"name": "github", "trusted": true,
             "transport": {"type": "remote", "url": "https://..."}}
        ]
    }
"""
import json
from pathlib import Path
from typing import Any

from core.logger import logger
from core.platform import IS_WINDOWS
from config.storage import get_config_dir
from .mcp_schema import McpServerConfig, StdioTransport, RemoteTransport


# ============================================================
# 内置默认 Server（v0.7.2 起为空：搜索已由 tools/tool_websearch.py 替代，
# 第三方能力全部通过 MCP 管理器动态添加）
# ============================================================
_BUILTIN_SERVERS: list[dict[str, Any]] = []

STORE_VERSION = 1


def get_store_file() -> Path:
    """获取 mcp_servers.json 路径（与主 config.json 同目录）"""
    return get_config_dir() / "mcp_servers.json"


def load_servers() -> list[McpServerConfig]:
    """
    加载所有 server 配置：内置默认 + 用户配置（用户优先，按 name 合并）

    单条配置损坏时跳过该条，不影响其余加载。
    """
    merged: dict[str, dict[str, Any]] = {
        s["name"]: dict(s) for s in _BUILTIN_SERVERS
    }

    store_file = get_store_file()
    if store_file.exists():
        try:
            with open(store_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for raw in data.get("servers", []):
                name = raw.get("name")
                if name:
                    merged[name] = raw  # 用户配置覆盖同名的内置默认
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"[McpStore] 配置文件读取失败（使用内置默认）: {e}")

    configs: list[McpServerConfig] = []
    for name, raw in merged.items():
        try:
            configs.append(McpServerConfig.model_validate(raw))
        except Exception as e:
            logger.warning(f"[McpStore] 跳过无效配置 '{name}': {e}")
    return configs


def save_servers(configs: list[McpServerConfig]) -> bool:
    """保存所有 server 配置到 mcp_servers.json"""
    store_file = get_store_file()
    data = {
        "version": STORE_VERSION,
        "servers": [c.model_dump() for c in configs],
    }
    try:
        with open(store_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        logger.error(f"[McpStore] 保存失败: {e}")
        return False


def reset_servers() -> bool:
    """清空用户配置，恢复为内置默认"""
    configs = [McpServerConfig.model_validate(s) for s in _BUILTIN_SERVERS]
    return save_servers(configs)


# ============================================================
# Claude Desktop 配置解析（批量导入）
# ============================================================
def parse_claude_config(text: str) -> tuple[list[McpServerConfig], list[str]]:
    """
    解析 Claude Desktop 的 claude_desktop_config.json 片段，批量导入。

    规则:
        1. 顶层 {"mcpServers": {...}} 或直接的 server map，两种都接受
        2. entry 含 "command" → StdioTransport；含 "url" → RemoteTransport
        3. "type": "sse"/"http" 的 entry 也按 url 处理
        4. 单条解析失败 → 跳过并记录错误，不影响其余条目

    Returns:
        (可导入的配置列表, 每条失败原因的列表)  # UI 逐条展示
    """
    errors: list[str] = []
    configs: list[McpServerConfig] = []

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [f"JSON 解析失败: {e}"]

    if not isinstance(data, dict):
        return [], ["顶层必须是 JSON 对象"]

    server_map = data.get("mcpServers", data)
    if not isinstance(server_map, dict):
        return [], ["mcpServers 字段必须是对象（server 名 → 配置）"]

    for name, entry in server_map.items():
        if not isinstance(entry, dict):
            errors.append(f"'{name}': 配置必须是对象")
            continue
        try:
            config = _claude_entry_to_config(name, entry)
            configs.append(config)
        except Exception as e:
            errors.append(f"'{name}': {e}")

    return configs, errors


def _claude_entry_to_config(name: str, entry: dict[str, Any]) -> McpServerConfig:
    """单个 Claude entry → McpServerConfig（stdio 或 remote 二选一）"""
    common = {
        "name": name,
        "description": entry.get("description", f"从 Claude 配置导入"),
        "trusted": False,  # 导入的 server 需要用户授权后才能启动
    }

    if entry.get("command"):
        # Windows 兼容: Claude 配置常见 "cmd" + ["/c", "npx", ...]，直接原样保留即可
        transport = StdioTransport(
            command=entry["command"],
            args=entry.get("args", []),
            env=entry.get("env", {}),
        )
        return McpServerConfig(transport=transport, **common)

    url = entry.get("url")
    if url:
        transport = RemoteTransport(
            url=url,
            headers=entry.get("headers", {}),
        )
        return McpServerConfig(transport=transport, **common)

    raise ValueError("缺少 command（stdio）或 url（remote）字段")


# Windows 说明（与原 mcp_config.py 的覆盖逻辑一致）:
# MCP SDK 无法直接 spawn .cmd 文件时，导入的配置可在 UI 里手动
# 把 command 改为 "cmd" + args 前置 "/c"。
if IS_WINDOWS:  # pragma: no cover
    logger.debug("[McpStore] Windows 平台: stdio command 由运行时探测层负责解析 .cmd")
