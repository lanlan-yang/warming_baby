"""
tools.mcp.mcp_schema - MCP Server 配置与状态 Schema

纯类型定义模块，不做任何 I/O：
- McpServerConfig: 一个 MCP Server 的持久化配置（stdio / remote 两种传输）
- McpServerState:  生命周期状态机枚举
- McpErrorCode:    Manager 异常与测试结果共用的错误码词表
- McpServerStatus: 某个 server 的运行时快照（事件 payload / UI 渲染共用）

存储持久化见 mcp_store.py，生命周期管理见 mcp_client.py。
"""
import re
from enum import StrEnum
from typing import Literal, Optional, Union

from pydantic import Field, field_validator

from core.schemas import BaseSchema


# ============================================================
# 枚举
# ============================================================
class McpTransportType(StrEnum):
    """传输类型"""
    STDIO = "stdio"    # 本地子进程（command + args）
    REMOTE = "remote"  # 远程 Streamable HTTP（mcp 2.0）


class McpServerState(StrEnum):
    """
    Server 生命周期状态机

    状态转移表（非法转移一律拒绝）:
        IDLE     --start-->      STARTING
        STARTING --成功-->        RUNNING   (注册工具)
        STARTING --失败/超时-->   FAILED
        FAILED   --start重试-->   STARTING
        RUNNING  --stop-->        STOPPING
        FAILED   --stop-->        STOPPING
        STOPPING --清理完成-->    IDLE      (注销工具)
        RUNNING  --断连-->        FAILED    (被动检测)
        IDLE     <--set_enabled--> DISABLED
    """
    DISABLED = "disabled"  # 已配置但被禁用（enabled=False），不可启动
    IDLE = "idle"          # 已启用，未运行
    STARTING = "starting"  # 启动中（spawn + 握手 + 发现工具）
    RUNNING = "running"    # 运行中，工具已注册进 tool_registry
    STOPPING = "stopping"  # 停止中（注销工具 + 关闭连接）
    FAILED = "failed"      # 启动失败或运行中断连，可重试


class McpErrorCode(StrEnum):
    """错误码：Manager 异常与测试结果共用一套词表"""
    INVALID_CONFIG = "invalid_config"        # schema 校验失败 / JSON 解析失败
    DUPLICATE_NAME = "duplicate_name"        # name 与已有 server 冲突
    NOT_FOUND = "not_found"                  # server 不存在
    NOT_TRUSTED = "not_trusted"              # 未完成安装授权，禁止启动
    RUNTIME_NOT_FOUND = "runtime_not_found"  # stdio: command 解析不到可执行文件
    START_TIMEOUT = "start_timeout"          # 启动流程超时
    HANDSHAKE_FAILED = "handshake_failed"    # initialize 握手失败
    DISCOVERY_FAILED = "discovery_failed"    # tools/list 失败
    CONNECTION_LOST = "connection_lost"      # 运行中连接断开
    HTTP_ERROR = "http_error"                # remote: 连接 / HTTP 层错误
    INVALID_STATE = "invalid_state"          # 状态机拒绝当前操作


# ============================================================
# 错误异常
# ============================================================
class McpManagerError(Exception):
    """MCP 管理操作失败，code 为 McpErrorCode"""

    def __init__(self, code: McpErrorCode, message: str = ""):
        self.code = code
        self.message = message or code.value
        super().__init__(f"[{code.value}] {self.message}")


# ============================================================
# 传输配置（判别联合，transport.type 区分）
# ============================================================
class StdioTransport(BaseSchema):
    """
    stdio 传输：Client spawn Server 子进程，stdin/stdout 走 JSON-RPC

    resolved_path:
        探测/用户选定后的可执行文件绝对路径缓存。
        存在则优先于 command 使用，避免每次启动都探测。
    """
    type: Literal["stdio"] = "stdio"

    command: str = Field("npx", description="启动命令：npx / node / uvx / python / docker ...")
    args: list[str] = Field(default_factory=list, description="命令行参数")
    env: dict[str, str] = Field(default_factory=dict, description="注入子进程的环境变量")
    encoding: str = "utf-8"
    resolved_path: Optional[str] = None

    @property
    def effective_command(self) -> str:
        """实际执行用的命令（resolved_path 优先）"""
        return self.resolved_path or self.command


class RemoteTransport(BaseSchema):
    """remote 传输：Streamable HTTP（mcp 2.0 streamablehttp_client）"""
    type: Literal["remote"] = "remote"

    url: str = Field(..., description="MCP Server URL，如 https://host/mcp")
    headers: dict[str, str] = Field(default_factory=dict, description="附加请求头，如 Authorization")
    connect_timeout: float = Field(10.0, description="建连 + 握手超时（秒）")

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return v.strip()


TransportConfig = Union[StdioTransport, RemoteTransport]


# ============================================================
# Server 配置（持久化的最小单元）
# ============================================================
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class McpServerConfig(BaseSchema):
    """
    一个 MCP Server 的完整配置

    字段语义:
        name:     全局唯一标识，同时用作工具名前缀（命名空间）
        enabled:  总开关。禁用 = 应用启动不加载 + 手动启动也被拒绝
        trusted:  安装时一次性授权标记。False 时 start_server 直接拒绝
    """
    name: str = Field(..., description="唯一标识，小写字母/数字/-/_，1-64 字符")
    description: str = ""
    transport: TransportConfig = Field(..., discriminator="type")
    enabled: bool = True
    trusted: bool = False

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        """
        名称净化 + 校验（Claude 导入的配置常有 "My Server!" 之类名字）

        净化规则: 转小写 → 空格转 - → 剔除其余非法字符；
        净化后为空则报错（如原名是 "!!!"）
        """
        v = v.strip().lower().replace(" ", "-")
        v = "".join(c for c in v if c.isalnum() or c in "_-")
        if not _NAME_RE.match(v):
            raise ValueError(
                "名称只允许小写字母/数字/-/_，长度 1-64，以字母或数字开头"
            )
        return v


# ============================================================
# 测试结果与状态快照（给 UI 用）
# ============================================================
class McpTestResult(BaseSchema):
    """「测试连接」的结果：临时连接测试，不改变 server 生命周期状态"""
    ok: bool
    error_code: str = ""          # McpErrorCode 值，ok=True 时为空
    message: str = ""             # 人类可读，直接显示在 UI 状态栏
    tool_count: int = 0
    tool_names: list[str] = Field(default_factory=list)
    duration_ms: int = 0


class McpServerStatus(BaseSchema):
    """某个 server 当前的完整快照（UI 渲染 + 事件 payload 共用）"""
    name: str
    state: McpServerState = McpServerState.IDLE
    transport_type: McpTransportType = McpTransportType.STDIO
    enabled: bool = True
    trusted: bool = False
    error: Optional[str] = None
    error_code: Optional[str] = None
    tool_count: int = 0
    tool_names: list[str] = Field(default_factory=list)  # 原始 MCP 工具名（不带前缀）
    started_at: Optional[float] = None
    last_test: Optional[McpTestResult] = None
