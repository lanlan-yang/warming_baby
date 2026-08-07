"""
tools/cache.py - 通用缓存模块

提供线程安全的内存缓存和装饰器，可用于任何需要缓存的场景。

特性：
- 线程安全（使用锁）
- 支持 TTL（生存时间）
- 自动清理过期数据
- 函数级装饰器
- 支持自定义缓存键生成

Usage:
    from tools.cache import cache, get_cache, clear_cache

    # 方式1：使用装饰器（推荐）
    @cache(ttl=1800, key_func=lambda *args, **kwargs: f"{args[0]}_{kwargs.get('lang', 'zh')}")
    async def fetch_data(url: str, lang: str = 'zh'):
        ...
        return result

    # 方式2：使用全局缓存实例
    cache_instance = get_cache("data_cache")
    result = cache_instance.get(key)
    if result is None:
        result = await expensive_operation()
        cache_instance.set(key, result)

    # 方式3：清除缓存
    clear_cache("data_cache")
"""

import asyncio
import functools
import hashlib
import inspect
import threading
import time
from typing import Any, Callable, Optional


class MemoryCache:
    """
    线程安全的内存缓存
    
    特性：
    - 支持 TTL（生存时间）
    - 自动清理过期数据
    - 限制最大缓存数量
    """
    
    def __init__(self, ttl: int = 1800, max_size: int = 100, name: str = "default"):
        """
        初始化缓存
        
        Args:
            ttl: 缓存生存时间（秒），默认 1800 秒（30分钟）
            max_size: 最大缓存条目数，默认 100
            name: 缓存名称，用于日志
        """
        self.ttl = ttl
        self.max_size = max_size
        self.name = name
        self._cache = {}
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在或已过期返回 None
        """
        with self._lock:
            if key not in self._cache:
                return None
            
            cached_value, cached_time = self._cache[key]
            
            # 检查是否过期
            if time.time() - cached_time > self.ttl:
                del self._cache[key]
                return None
            
            return cached_value
    
    def set(self, key: str, value: Any) -> None:
        """
        设置缓存
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        with self._lock:
            # 如果缓存已满，删除最旧的条目
            if len(self._cache) >= self.max_size and key not in self._cache:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            
            self._cache[key] = (value, time.time())
    
    def delete(self, key: str) -> None:
        """
        删除缓存
        
        Args:
            key: 缓存键
        """
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()
    
    def size(self) -> int:
        """
        获取有效缓存大小
        
        Returns:
            有效的缓存条目数（已清理过期数据）
        """
        with self._lock:
            current_time = time.time()
            expired_keys = [
                key for key, (_, cached_time) in self._cache.items()
                if current_time - cached_time > self.ttl
            ]
            for key in expired_keys:
                del self._cache[key]
            
            return len(self._cache)
    
    def has(self, key: str) -> bool:
        """
        检查缓存是否存在（包括过期检查）
        
        Args:
            key: 缓存键
            
        Returns:
            是否存在有效的缓存
        """
        return self.get(key) is not None


# ============================================================================
# 全局缓存管理
# ============================================================================

_caches = {}
_caches_lock = threading.Lock()


def get_cache(name: str = "default", ttl: int = 1800, max_size: int = 100) -> MemoryCache:
    """
    获取或创建全局缓存实例
    
    Args:
        name: 缓存名称
        ttl: 缓存生存时间（秒）
        max_size: 最大缓存条目数
        
    Returns:
        MemoryCache 实例
    """
    with _caches_lock:
        if name not in _caches:
            _caches[name] = MemoryCache(ttl=ttl, max_size=max_size, name=name)
        return _caches[name]


def clear_cache(name: Optional[str] = None) -> None:
    """
    清除缓存
    
    Args:
        name: 缓存名称，如果为 None 则清除所有缓存
    """
    with _caches_lock:
        if name is None:
            for cache in _caches.values():
                cache.clear()
        elif name in _caches:
            _caches[name].clear()


def get_cache_stats() -> dict:
    """
    获取所有缓存的统计信息
    
    Returns:
        缓存统计信息字典
    """
    with _caches_lock:
        stats = {}
        for name, cache in _caches.items():
            stats[name] = {
                "size": cache.size(),
                "ttl": cache.ttl,
                "max_size": cache.max_size,
            }
        return stats


# ============================================================================
# 缓存键生成
# ============================================================================

def generate_cache_key(*args, **kwargs) -> str:
    """
    根据函数参数生成缓存键
    
    Args:
        *args: 位置参数
        **kwargs: 关键字参数
        
    Returns:
        缓存键字符串
    """
    # 将参数转换为可哈希的字符串
    key_parts = []
    
    for arg in args:
        key_parts.append(str(arg))
    
    for key, value in sorted(kwargs.items()):
        key_parts.append(f"{key}={value}")
    
    key_str = "|".join(key_parts)
    
    # 使用哈希缩短键长度
    return hashlib.md5(key_str.encode()).hexdigest()


# ============================================================================
# 缓存装饰器
# ============================================================================

def cache_result(
    ttl: int = 1800,
    cache_name: str = "default",
    key_func: Optional[Callable] = None,
    skip_if_none: bool = True,
):
    """
    缓存装饰器
    
    支持同步和异步函数。
    
    Args:
        ttl: 缓存生存时间（秒），默认 1800 秒（30分钟）
        cache_name: 缓存名称，不同名称的缓存相互独立
        key_func: 自定义缓存键生成函数，签名为 func(*args, **kwargs) -> str
        skip_if_none: 如果结果为 None 是否跳过缓存，默认 True
        
    Returns:
        装饰器函数
        
    Usage:
        # 使用默认缓存键（基于 MD5）
        @cache_result(ttl=300, cache_name="api_cache")
        async def fetch_data(url: str):
            ...
            return result
        
        # 使用自定义缓存键
        @cache_result(
            ttl=1800,
            cache_name="weather_cache",
            key_func=lambda city, forecast=False, indices=False: f"{city}|{forecast}|{indices}"
        )
        async def get_weather(city: str, forecast: bool = False, indices: bool = False):
            ...
            return weather_data
    """
    def decorator(func: Callable) -> Callable:
        cache_instance = get_cache(cache_name, ttl=ttl)
        is_async = inspect.iscoroutinefunction(func)
        
        if is_async:
            # 异步函数装饰器
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                # 生成缓存键
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    cache_key = generate_cache_key(*args, **kwargs)
                
                # 尝试从缓存获取
                cached_result = cache_instance.get(cache_key)
                if cached_result is not None:
                    return cached_result
                
                # 调用原函数
                result = await func(*args, **kwargs)
                
                # 缓存结果
                if result is not None or not skip_if_none:
                    cache_instance.set(cache_key, result)
                
                return result
            
            return async_wrapper
        else:
            # 同步函数装饰器
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                # 生成缓存键
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    cache_key = generate_cache_key(*args, **kwargs)
                
                # 尝试从缓存获取
                cached_result = cache_instance.get(cache_key)
                if cached_result is not None:
                    return cached_result
                
                # 调用原函数
                result = func(*args, **kwargs)
                
                # 缓存结果
                if result is not None or not skip_if_none:
                    cache_instance.set(cache_key, result)
                
                return result
            
            return sync_wrapper
    
    return decorator


# 便捷别名
cache = cache_result
