"""
storage.py - 配置存储层

负责:
1. 跨平台配置目录查找 (macOS/Windows/Linux)
2. JSON 配置文件的读写
3. 配置文件的备份和恢复

配置位置:
- macOS: ~/Library/Application Support/WarmBaby/
- Windows: %APPDATA%/WarmBaby/
- Linux: ~/.config/WarmBaby/
"""
import json
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any

from core.platform import IS_MAC, IS_WINDOWS, IS_LINUX

# 应用名称 (用于配置目录)
APP_NAME = "WarmBaby"


def get_config_dir() -> Path:
    """
    获取跨平台的配置目录

    Returns:
        Path: 配置目录路径
    """
    if IS_MAC:
        # macOS: ~/Library/Application Support/WarmBaby/
        base = Path.home() / 'Library' / 'Application Support'
    elif IS_WINDOWS:
        # Windows: %APPDATA%/WarmBaby/
        base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
    else:
        # Linux: ~/.config/WarmBaby/
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))

    config_dir = base / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_file() -> Path:
    """
    获取配置文件路径

    Returns:
        Path: 配置文件路径
    """
    return get_config_dir() / 'config.json'


def get_backup_dir() -> Path:
    """
    获取备份目录路径

    Returns:
        Path: 备份目录路径
    """
    backup_dir = get_config_dir() / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def load_config(default_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    加载配置文件

    Args:
        default_config: 默认配置 (当文件不存在时使用)

    Returns:
        dict: 配置字典
    """
    config_file = get_config_file()

    if not config_file.exists():
        # 文件不存在，返回默认配置
        return default_config or {}

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except (json.JSONDecodeError, IOError) as e:
        # 读取失败，尝试从备份恢复
        print(f"Warning: Failed to load config: {e}")
        backup_config = _try_restore_from_backup()
        if backup_config is not None:
            return backup_config
        return default_config or {}


def save_config(config: dict[str, Any], create_backup: bool = True) -> bool:
    """
    保存配置文件

    Args:
        config: 配置字典
        create_backup: 是否创建备份

    Returns:
        bool: 保存是否成功
    """
    config_file = get_config_file()

    try:
        # 如果需要备份且文件存在
        if create_backup and config_file.exists():
            _create_backup(config_file)

        # 写入新配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True

    except IOError as e:
        print(f"Error: Failed to save config: {e}")
        return False


def _create_backup(config_file: Path):
    """
    创建配置文件备份

    Args:
        config_file: 配置文件路径
    """
    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = backup_dir / f'config_{timestamp}.json'

    try:
        shutil.copy2(config_file, backup_file)
        # 清理旧备份 (保留最近 10 个)
        _cleanup_old_backups(backup_dir, max_count=10)
    except IOError as e:
        print(f"Warning: Failed to create backup: {e}")


def _cleanup_old_backups(backup_dir: Path, max_count: int = 10):
    """
    清理旧备份文件

    Args:
        backup_dir: 备份目录
        max_count: 最大保留数量
    """
    try:
        backups = sorted(backup_dir.glob('config_*.json'), reverse=True)
        for old_backup in backups[max_count:]:
            old_backup.unlink()
    except IOError:
        pass


def _try_restore_from_backup() -> dict[str, Any] | None:
    """
    尝试从最近的备份恢复配置

    Returns:
        dict 或 None: 恢复的配置或 None
    """
    backup_dir = get_backup_dir()
    backups = sorted(backup_dir.glob('config_*.json'), reverse=True)

    if not backups:
        return None

    # 尝试每个备份，直到成功
    for backup_file in backups:
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 恢复成功，也恢复主文件
            config_file = get_config_file()
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"Restored config from backup: {backup_file.name}")
            return config
        except (json.JSONDecodeError, IOError):
            continue

    return None


def export_config(export_path: Path) -> bool:
    """
    导出配置到指定路径

    Args:
        export_path: 导出路径

    Returns:
        bool: 导出是否成功
    """
    config_file = get_config_file()
    if not config_file.exists():
        return False

    try:
        shutil.copy2(config_file, export_path)
        return True
    except IOError:
        return False


def import_config(import_path: Path) -> dict[str, Any] | None:
    """
    从指定路径导入配置

    Args:
        import_path: 导入路径

    Returns:
        dict 或 None: 导入的配置或 None
    """
    if not import_path.exists():
        return None

    try:
        with open(import_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        save_config(config, create_backup=True)
        return config
    except (json.JSONDecodeError, IOError):
        return None


def clear_all_backups():
    """清除所有备份"""
    backup_dir = get_backup_dir()
    for backup in backup_dir.glob('config_*.json'):
        backup.unlink()


def get_config_info() -> dict[str, Any]:
    """
    获取配置文件信息

    Returns:
        dict: 配置信息
    """
    config_file = get_config_file()
    backup_dir = get_backup_dir()

    info = {
        'config_dir': str(get_config_dir()),
        'config_file_exists': config_file.exists(),
        'backup_dir': str(backup_dir),
        'backup_count': len(list(backup_dir.glob('config_*.json'))),
    }

    if config_file.exists():
        stat = config_file.stat()
        info['file_size'] = stat.st_size
        info['last_modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()

    return info
