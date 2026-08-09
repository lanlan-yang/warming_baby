"""
core/paths.py - 路径管理

处理开发模式和 PyInstaller 打包模式的路径差异:
    - 开发模式: 直接使用项目根目录
    - 打包模式: 使用 sys._MEIPASS 临时目录作为资源根

用法:
    from core.paths import get_resource_path, get_app_dir
    icon_path = get_resource_path('assets/icons/icon.png')
    user_config = get_app_dir() / 'config.json'
"""
import sys
from pathlib import Path

from core.platform import IS_MAC, IS_WINDOWS


def _get_base_dir() -> Path:
    """获取资源根目录
    
    - PyInstaller 打包: sys._MEIPASS 临时解压目录
    - 开发模式: 当前文件所在目录的父目录 (项目根)
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包模式
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    else:
        # 开发模式
        return Path(__file__).resolve().parent.parent


def get_resource_path(relative_path: str) -> Path:
    """获取打包后资源的绝对路径
    
    Args:
        relative_path: 相对于项目根的路径，如 'assets/icons/icon.png'
    
    Returns:
        绝对路径的 Path 对象
    """
    base = _get_base_dir()
    path = base / relative_path
    if not path.exists():
        # 开发模式下的回退：相对于项目根
        project_root = Path(__file__).resolve().parent.parent
        alt = project_root / relative_path
        if alt.exists():
            return alt
    return path


def get_app_dir() -> Path:
    """获取应用数据目录 (用户配置、记忆存储、日志等)

    开发环境（非 frozen）: 项目根目录下 tmp/，与 get_config_dir() 一致
    打包后（frozen）: 系统标准目录
        - macOS: ~/Library/Application Support/WarmBaby/
        - Windows: %APPDATA%/Roaming/WarmBaby/
        - Linux: 项目根目录 data/（打包后理论上不会走到）

    Returns:
        应用数据目录的 Path 对象
    """
    if not is_frozen():
        # 开发环境：项目根目录下的 tmp/
        project_root = Path(__file__).resolve().parent.parent
        base = project_root / 'tmp'
    else:
        # 打包后：系统标准目录
        if IS_MAC:
            base = Path.home() / 'Library' / 'Application Support' / 'WarmBaby'
        elif IS_WINDOWS:
            base = Path.home() / 'AppData' / 'Roaming' / 'WarmBaby'
        else:
            base = Path(__file__).resolve().parent.parent / 'data'

    base.mkdir(parents=True, exist_ok=True)
    return base


def is_frozen() -> bool:
    """判断是否为 PyInstaller 打包模式"""
    return getattr(sys, 'frozen', False)
