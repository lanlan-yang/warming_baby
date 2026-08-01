"""
config - 配置管理模块

提供跨平台的配置存储、安全存储和配置管理功能。

使用方式:
    from config import config_manager, secure_storage
    
    # 加载配置
    config = config_manager.load()
    
    # 保存配置
    config["llm"]["temperature"] = 0.8
    config_manager.save(config)
    
    # 安全存储 API Key
    secure_storage.save_api_key("sk-xxx")
    api_key = secure_storage.load_api_key()
"""

from .storage import (
    get_config_dir,
    get_config_file,
    load_config,
    save_config,
    export_config,
    import_config,
    get_config_info,
)

from .secure import secure_storage, SecureStorage
from .manager import config_manager, ConfigManager

__all__ = [
    # storage
    'get_config_dir',
    'get_config_file',
    'load_config',
    'save_config',
    'export_config',
    'import_config',
    'get_config_info',
    # secure
    'secure_storage',
    'SecureStorage',
    # manager
    'config_manager',
    'ConfigManager',
]

# 注意: 不要在这里导入 settings, 会导致循环导入
# 如果需要使用旧的 Settings 类, 请从 config.py 导入
# 例如: from config import settings (从根目录导入)
# 或者: from ..config import settings (从子目录导入)
