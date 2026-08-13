"""
memory/ - 长记忆管理模块

模块结构:
    types.py       - 记忆类型和数据结构 (MemoryType, MemoryItem)
    normalizer.py  - 记忆内容归一化器 (MemoryNormalizer)
    store.py       - ChromaDB 向量存储 (MemoryStore)
    manager.py     - 记忆管理器 (MemoryManager, 单例)

使用示例:
    from memory import MemoryManager, MemoryType, get_memory_manager

    # 方式 1: 使用全局单例
    manager = get_memory_manager()
    manager.initialize()

    # 方式 2: 创建新实例 (带自定义路径)
    manager = MemoryManager(
        storage_path='/custom/path'
    )
    manager.initialize()

    # 添加和检索
    manager.add_memory('我叫小明', MemoryType.FACT)
    manager.add_memory('我喜欢吃苹果', MemoryType.PREFERENCE)

    results = manager.search('我叫什么名字')
    print(results[0]['content'])  # '我叫小明'

    # 获取格式化的记忆 (给 LLM)
    memory_text = manager.get_relevant_memories('我喜欢吃什么')
    print(memory_text)
    # - [preference] (置信度 85%) 我喜欢吃苹果
"""
from .types import MemoryType, MemoryItem
from .normalizer import MemoryNormalizer, get_normalizer
from .store import MemoryStore
from .manager import (
    MemoryManager,
    get_memory_manager,
    init_memory,
)
from .core_cache import CoreMemoryCache, get_core_cache

__all__ = [
    'MemoryType',
    'MemoryItem',
    'MemoryNormalizer',
    'get_normalizer',
    'MemoryStore',
    'MemoryManager',
    'get_memory_manager',
    'init_memory',
    'CoreMemoryCache',
    'get_core_cache',
]
