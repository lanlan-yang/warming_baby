"""
manager.py - 配置管理器

提供统一的配置访问接口，支持:
1. 配置的加载和保存
2. 嵌套配置的访问 (使用点号分隔)
3. 配置变更的事件通知 (观察者模式)
4. 配置的合并和重置

使用示例:
    from config import config_manager

    # 加载配置
    config_manager.load()

    # 获取配置
    api_key = config_manager.get("llm.api_key")
    temperature = config_manager.get("llm.temperature", default=0.7)

    # 设置配置
    config_manager.set("llm.temperature", 0.8)
    config_manager.save()

    # 监听配置变更
    def on_change(key, value):
        print(f"{key} changed to {value}")

    config_manager.add_listener(on_change)

    # 重置配置
    config_manager.reset()
"""
from typing import Any, Callable, Optional
from copy import deepcopy

from .storage import load_config, save_config
from .secure import secure_storage


# 默认配置
DEFAULT_CONFIG = {
    "version": 1,
    "llm": {
        "api_key": "",  # 从 secure 存储读取
        "default_provider": "deepseek",
        "temperature": 0.7,
        "max_tokens": 2048,
        "timeout": 30,
        "max_retries": 3,
        "models": {
            "chat": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com",
            },
            "complex": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "base_url": "https://api.deepseek.com",
            },
            "vision": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "base_url": "",
            },
        },
    },
    "appearance": {
        "opacity": 1.0,
        "scale": 1.0,
        "always_on_top": True,
        "show_in_dock": True,
    },
    "behavior": {
        "auto_speak_enabled": True,
        "auto_speak_interval_min": 5,
        "idle_to_sleep_min": 5,
        "sleep_duration_min": 1,
    },
}


class ConfigManager:
    """
    配置管理器 (单例)

    提供统一的配置访问和管理接口
    """

    def __init__(self):
        self._config = deepcopy(DEFAULT_CONFIG)
        self._listeners: list = []
        self._loaded = False

    # ==================== 生命周期 ====================

    def load(self) -> dict:
        """
        加载配置

        合并默认配置和用户配置，从 secure 存储读取 API Key

        Returns:
            dict: 合并后的配置
        """
        # 加载用户配置
        user_config = load_config(DEFAULT_CONFIG)

        # 合并配置 (用户配置覆盖默认配置)
        self._config = self._merge_configs(DEFAULT_CONFIG, user_config)

        # 从 secure 存储读取 API Key
        api_key = secure_storage.load_api_key()
        if api_key:
            self._config["llm"]["api_key"] = api_key

        self._loaded = True
        return self._config

    def save(self, notify: bool = True) -> bool:
        """
        保存配置

        注意: API Key 会从配置中移除，单独保存到 secure 存储

        Args:
            notify: 是否通知监听者

        Returns:
            bool: 保存是否成功
        """
        # 分离 API Key
        api_key = self._config.get("llm", {}).get("api_key", "")
        if api_key:
            secure_storage.save_api_key(api_key)

        # 创建要保存的配置 (不包含 api_key)
        config_to_save = deepcopy(self._config)
        if "api_key" in config_to_save.get("llm", {}):
            config_to_save["llm"]["api_key"] = ""

        # 保存到文件
        result = save_config(config_to_save)

        # 通知监听者
        if result and notify:
            self._notify_listeners("*", self._config)

        return result

    def reload(self) -> dict:
        """
        重新加载配置

        Returns:
            dict: 加载后的配置
        """
        return self.load()

    def reset(self) -> dict:
        """
        重置为默认配置

        Returns:
            dict: 默认配置
        """
        self._config = deepcopy(DEFAULT_CONFIG)
        self.save()
        self._notify_listeners("*", self._config)
        return self._config

    # ==================== 配置访问 ====================

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值 (支持点号分隔的嵌套访问)

        Args:
            key: 配置键 (如 "llm.temperature")
            default: 默认值

        Returns:
            Any: 配置值
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any, auto_save: bool = True) -> bool:
        """
        设置配置值 (支持点号分隔的嵌套访问)

        Args:
            key: 配置键 (如 "llm.temperature")
            value: 新值
            auto_save: 是否自动保存

        Returns:
            bool: 设置是否成功
        """
        keys = key.split(".")
        target = self._config

        # 导航到目标位置
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]

        # 设置值
        old_value = target.get(keys[-1])
        target[keys[-1]] = value

        # 保存
        if auto_save:
            self.save()

        # 通知监听者
        if old_value != value:
            self._notify_listeners(key, value)

        return True

    def update(self, updates: dict, auto_save: bool = True) -> bool:
        """
        批量更新配置

        Args:
            updates: 更新字典 (可以是嵌套结构)
            auto_save: 是否自动保存

        Returns:
            bool: 更新是否成功
        """
        old_config = deepcopy(self._config)

        # 应用更新
        self._config = self._deep_update(self._config, updates)

        # 保存
        if auto_save:
            self.save()

        # 找出变化的键并通知
        changed_keys = self._find_changes(old_config, self._config)
        for key in changed_keys:
            self._notify_listeners(key, self.get(key))

        return True

    def delete(self, key: str, auto_save: bool = True) -> bool:
        """
        删除配置项

        Args:
            key: 配置键
            auto_save: 是否自动保存

        Returns:
            bool: 删除是否成功
        """
        keys = key.split(".")
        target = self._config

        # 导航到父位置
        for k in keys[:-1]:
            if k not in target:
                return False
            target = target[k]

        # 删除键
        if keys[-1] in target:
            del target[keys[-1]]

            if auto_save:
                self.save()

            self._notify_listeners(key, None)
            return True

        return False

    def all(self) -> dict:
        """
        获取完整配置副本

        Returns:
            dict: 完整配置
        """
        return deepcopy(self._config)

    # ==================== 事件通知 ====================

    def add_listener(self, callback) -> None:
        """
        添加配置变更监听者

        Args:
            callback: 回调函数 (key, value) -> None
        """
        self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        """
        移除配置变更监听者

        Args:
            callback: 回调函数
        """
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self, key: str, value: Any) -> None:
        """
        通知所有监听者

        Args:
            key: 变更的键
            value: 新值
        """
        for listener in self._listeners:
            try:
                listener(key, value)
            except Exception as e:
                print(f"Warning: Listener error: {e}")

    # ==================== 内部方法 ====================

    def _merge_configs(self, default: dict, user: dict) -> dict:
        """
        合并配置 (用户配置覆盖默认配置)

        Args:
            default: 默认配置
            user: 用户配置

        Returns:
            dict: 合并后的配置
        """
        result = deepcopy(default)

        for key, value in user.items():
            if (key in result and
                isinstance(result[key], dict) and
                isinstance(value, dict)):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value

        return result

    def _deep_update(self, target: dict, updates: dict) -> dict:
        """
        深度更新字典

        Args:
            target: 目标字典
            updates: 更新字典

        Returns:
            dict: 更新后的字典
        """
        for key, value in updates.items():
            if (key in target and
                isinstance(target[key], dict) and
                isinstance(value, dict)):
                self._deep_update(target[key], value)
            else:
                target[key] = value

        return target

    def _find_changes(self, old: dict, new: dict, prefix: str = "") -> list[str]:
        """
        找出两个配置之间的变化

        Args:
            old: 旧配置
            new: 新配置
            prefix: 键前缀

        Returns:
            list: 变化的键列表
        """
        changes = []

        all_keys = set(list(old.keys()) + list(new.keys()))

        for key in all_keys:
            full_key = f"{prefix}.{key}" if prefix else key
            old_val = old.get(key)
            new_val = new.get(key)

            if isinstance(old_val, dict) and isinstance(new_val, dict):
                changes.extend(self._find_changes(old_val, new_val, full_key))
            elif old_val != new_val:
                changes.append(full_key)

        return changes


# 单例实例
config_manager = ConfigManager()
