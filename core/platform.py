"""
core/platform.py - 跨平台检测与全局常量

集中管理系统平台判断，避免到处写 `if sys.platform == 'xxx'`。

使用示例:
    from core.platform import IS_MAC, IS_WINDOWS, IS_LINUX, PLATFORM

    if IS_MAC:
        # macOS 特有逻辑
    elif IS_WINDOWS:
        # Windows 特有逻辑
"""
import sys
from typing import Literal


# ======== 平台名称 ========
PLATFORM: Literal["windows", "macos", "linux", "unknown"]
"""平台名称，全局常量，应用启动时确定"""

if sys.platform == "darwin":
    PLATFORM = "macos"
elif sys.platform == "win32":
    PLATFORM = "windows"
elif sys.platform.startswith("linux"):
    PLATFORM = "linux"
else:
    PLATFORM = "unknown"


# ======== 常用布尔开关 ========
IS_MAC: bool = PLATFORM == "macos"
"""是否运行在 macOS"""

IS_WINDOWS: bool = PLATFORM == "windows"
"""是否运行在 Windows"""

IS_LINUX: bool = PLATFORM == "linux"
"""是否运行在 Linux"""

IS_UNIX_LIKE: bool = IS_MAC or IS_LINUX
"""是否是类 Unix 系统（macOS / Linux，可用 fcntl 等）"""


# ======== 辅助函数 ========
def get_platform_display_name() -> str:
    """
    获取用于日志/提示的平台显示名

    Returns:
        "macOS" / "Windows" / "Linux" / "Unknown"
    """
    return {
        "macos": "macOS",
        "windows": "Windows",
        "linux": "Linux",
        "unknown": "Unknown",
    }[PLATFORM]


__all__ = [
    "PLATFORM",
    "IS_MAC",
    "IS_WINDOWS",
    "IS_LINUX",
    "IS_UNIX_LIKE",
    "get_platform_display_name",
]
