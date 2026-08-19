"""
tools.mcp.runtime_detect - stdio 运行时（node/npx 等）跨平台探测

解决的核心问题:
    macOS 上从 Finder/Dock 启动的 GUI 应用不继承登录 shell 的 PATH，
    nvm/homebrew 安装的 node/npx 探测不到（终端里正常，GUI 里 shutil.which 返回 None）。

探测策略（分层兜底）:
    第 1 层  shutil.which              —— 吃当前进程 PATH
    第 2 层  登录 shell 查询（macOS）   —— zsh -l -c 'command -v npx'，拿真实用户 PATH
    第 3 层  常见安装目录扫描           —— homebrew / nvm / volta / 官方安装器等
    第 4 层  用户在 UI 手动指定         —— 「浏览」文件选择器写入 resolved_path

探测成本控制:
    每个命令的结果做进程内缓存；探测成功后由调用方写入
    StdioTransport.resolved_path 持久化，之后不再探测。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from core.logger import logger
from core.platform import IS_MAC, IS_WINDOWS


# 进程内缓存: command → 绝对路径（None = 探测过但没找到，同样缓存避免重复探测）
_detect_cache: dict[str, Optional[str]] = {}

# 第 3 层扫描的常见安装目录
_COMMON_BIN_DIRS: list[Path] = [
    Path("/opt/homebrew/bin"),            # macOS Apple Silicon homebrew
    Path("/usr/local/bin"),               # macOS Intel homebrew / 手动安装
    Path.home() / ".volta" / "bin",       # volta
    Path.home() / ".local" / "bin",       # pipx / 手动安装
]

# node 系运行时的官方/版本管理器安装位置（做一层展开）
_NODE_DIR_GLOBS: list[str] = [
    ".nvm/versions/node/*/bin",           # nvm
    "Library/pnpm/*",                     # pnpm 全局（macOS）
    ".bun/bin",                           # bun
]

# UI 展示「这台机器能跑什么生态」用
COMMON_RUNTIMES = ["node", "npx", "uvx", "python", "docker"]


def _expand_node_dirs() -> list[Path]:
    """展开 nvm 等带版本号通配的目录"""
    dirs: list[Path] = []
    home = Path.home()
    for pattern in _NODE_DIR_GLOBS:
        try:
            dirs.extend(sorted(home.glob(pattern), reverse=True))  # 新版本优先
        except Exception:
            pass
    return dirs


def detect_command(command: str, use_cache: bool = True) -> Optional[str]:
    """
    分层探测一个命令的可执行文件绝对路径

    Args:
        command: 命令名（npx / node / uvx / python / docker 或绝对路径）
        use_cache: 是否使用进程内缓存

    Returns:
        绝对路径，探测不到返回 None
    """
    # 绝对路径直接校验
    if os.path.isabs(command):
        if os.path.isfile(command) and os.access(command, os.X_OK):
            return command
        return None

    if use_cache and command in _detect_cache:
        return _detect_cache[command]

    found = (
        _which_with_extensions(command)
        or _which_from_login_shell(command)
        or _which_from_common_dirs(command)
    )

    _detect_cache[command] = found
    if found:
        logger.debug(f"[RuntimeDetect] '{command}' → {found}")
    else:
        logger.debug(f"[RuntimeDetect] '{command}' 未找到")
    return found


def _which_with_extensions(command: str) -> Optional[str]:
    """第 1 层: 当前进程 PATH + Windows 扩展名"""
    resolved = shutil.which(command)
    if resolved:
        return resolved

    if IS_WINDOWS:
        for ext in (".cmd", ".bat", ".exe", ".ps1"):
            resolved = shutil.which(f"{command}{ext}")
            if resolved:
                return resolved
    return None


def _which_from_login_shell(command: str) -> Optional[str]:
    """
    第 2 层（仅 macOS）: 登录 shell 的真实 PATH

    Finder/Dock 启动的 GUI 进程 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，
    nvm、homebrew 的路径都在登录 shell 的 rc 文件里，必须用 -l 模拟登录。
    """
    if not IS_MAC:
        return None

    shell = os.environ.get("SHELL", "/bin/zsh")
    try:
        result = subprocess.run(
            [shell, "-l", "-c", f"command -v {command}"],
            capture_output=True, text=True, timeout=5,
        )
        path = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"[RuntimeDetect] 登录 shell 探测 '{command}' 失败: {e}")
    return None


def _which_from_common_dirs(command: str) -> Optional[str]:
    """第 3 层: 扫描常见安装目录"""
    candidates = [*_COMMON_BIN_DIRS, *_expand_node_dirs()]
    for d in candidates:
        p = d / command
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)

    # Windows: 常见 nodejs 安装目录
    if IS_WINDOWS:
        for base in (
            os.environ.get("ProgramFiles", r"C:\\Program Files"),
            os.environ.get("APPDATA", ""),
        ):
            if not base:
                continue
            for sub in ("nodejs", "npm"):
                p = Path(base) / sub / f"{command}.cmd"
                if p.is_file():
                    return str(p)
    return None


def detect_common_runtimes() -> dict[str, Optional[str]]:
    """
    探测常用运行时的安装情况（UI 展示生态可用性用）

    Returns:
        {命令名: 绝对路径 or None}
    """
    return {cmd: detect_command(cmd) for cmd in COMMON_RUNTIMES}


def clear_cache() -> None:
    """清空探测缓存（「重新探测」按钮用）"""
    _detect_cache.clear()
    logger.debug("[RuntimeDetect] 缓存已清空")


def resolve_stdio_command(command: str, resolved_path: Optional[str]) -> tuple[str, Optional[str]]:
    """
    为 stdio server 解析实际执行的命令

    优先级:
        1. resolved_path（已持久化的探测结果，最高，不再探测）
        2. 分层探测 command
        3. 兜底返回原命令（让 spawn 报出真实错误，用户可看到原因）

    Returns:
        (实际命令, 新探测到的路径 or None)
        返回的路径非空时调用方应写回 StdioTransport.resolved_path 持久化
    """
    if resolved_path:
        if os.path.isfile(resolved_path):
            return resolved_path, None
        logger.warning(f"[RuntimeDetect] resolved_path 已失效: {resolved_path}，重新探测")

    found = detect_command(command)
    if found:
        return found, found
    return command, None


# 模块自测: python -m tools.mcp.runtime_detect
if __name__ == "__main__":
    print(f"platform: {sys.platform}")
    for name, path in detect_common_runtimes().items():
        print(f"  {name:8s} → {path or '未找到'}")
