"""
memory/core_cache.py - 核心记忆缓存

启动时从数据库加载核心记忆，常驻内存。
LLM 无需调用工具即可获取用户基本信息。

缓存内容:
    - FACT: 全部加载（name/birthday/location 等）
    - PREFERENCE: 加载 importance >= 0.6 的
    - SKILL: 加载 importance >= 0.6 的

使用示例:
    cache = get_core_cache()
    cache.load(manager)           # 启动时加载
    prompt = cache.get_prompt_text()  # 注入系统提示词
    cache.update(...)             # 新记忆添加时更新
"""
from typing import Dict, List, Optional, Any
from pathlib import Path

from core.logger import setup_logger
from .types import MemoryType

logger = setup_logger()


class CoreMemoryCache:
    """
    核心记忆缓存 (单例)

    启动时从 ChromaDB 加载核心记忆到内存，
    对话时直接注入系统提示词，无需查库。

    更新时机: memory_node 存储新记忆后同步更新缓存
    """

    _instance: Optional["CoreMemoryCache"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = False
        # field -> content (如 "name" -> "用户叫小明")
        self._facts: Dict[str, str] = {}
        # ["用户喜欢苹果", "用户讨厌香菜"]
        self._preferences: List[str] = []
        # ["用户会Python"]
        self._skills: List[str] = []

    @classmethod
    def get_instance(cls) -> "CoreMemoryCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self, manager) -> None:
        """
        从数据库加载核心记忆

        Args:
            manager: MemoryManager 实例
        """
        if not manager or not manager.is_ready:
            logger.warning("[CoreCache] MemoryManager 未就绪，跳过加载")
            return

        self._facts.clear()
        self._preferences.clear()
        self._skills.clear()

        try:
            all_memories = manager.get_all_memories()
            for mem in all_memories:
                mtype = mem.get("metadata", {}).get("type", "")
                field = mem.get("metadata", {}).get("field", "other")
                content = mem.get("content", "")
                importance = mem.get("importance", 0.5)

                if mtype == "fact":
                    self._facts[field] = content
                elif mtype == "preference" and importance >= 0.6:
                    if content not in self._preferences:
                        self._preferences.append(content)
                elif mtype == "skill" and importance >= 0.6:
                    if content not in self._skills:
                        self._skills.append(content)

            self._initialized = True
            total = len(self._facts) + len(self._preferences) + len(self._skills)
            logger.info(
                f"[CoreCache] 加载完成: {len(self._facts)} 事实, "
                f"{len(self._preferences)} 偏好, {len(self._skills)} 技能"
            )
        except Exception as e:
            logger.error(f"[CoreCache] 加载失败: {e}")

    def get_prompt_text(self) -> str:
        """
        格式化为系统提示词文本

        Returns:
            格式化的记忆文本，如:
            【用户信息】
            - 用户叫小明
            - 用户住在成都

            【用户喜好】
            - 用户喜欢苹果

            如果没有记忆，返回空字符串
        """
        if not self._facts and not self._preferences and not self._skills:
            return ""

        parts = []

        if self._facts:
            parts.append("【用户信息】")
            for content in self._facts.values():
                parts.append(f"- {content}")

        if self._preferences:
            parts.append("【用户喜好】")
            for pref in self._preferences:
                parts.append(f"- {pref}")

        if self._skills:
            parts.append("【用户技能】")
            for skill in self._skills:
                parts.append(f"- {skill}")

        return "\n".join(parts)

    def update(
        self,
        memory_type: str,
        field: str,
        content: str,
        importance: float = 0.5,
    ) -> None:
        """
        新记忆存储后更新缓存

        Args:
            memory_type: 记忆类型 ("fact"/"preference"/"skill"/...)
            field: 字段类别
            content: 记忆内容
            importance: 重要性分数
        """
        if memory_type == "fact":
            self._facts[field] = content
            logger.info(f"[CoreCache] 更新事实: [{field}] {content}")
        elif memory_type == "preference" and importance >= 0.6:
            if content not in self._preferences:
                self._preferences.append(content)
                logger.info(f"[CoreCache] 更新偏好: {content}")
        elif memory_type == "skill" and importance >= 0.6:
            if content not in self._skills:
                self._skills.append(content)
                logger.info(f"[CoreCache] 更新技能: {content}")

    def is_ready(self) -> bool:
        """是否已加载"""
        return self._initialized


def get_core_cache() -> CoreMemoryCache:
    """获取全局 CoreMemoryCache 实例"""
    return CoreMemoryCache.get_instance()
