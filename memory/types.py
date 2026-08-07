"""
memory/types.py - 记忆类型和数据结构

定义记忆系统的基础类型:
    - MemoryType: 记忆类型枚举 (事实、偏好、事件等)
    - MemoryItem: 记忆项数据结构
"""
import time
import uuid
from enum import StrEnum
from dataclasses import dataclass, field
from typing import Dict, Any


class MemoryType(StrEnum):
    """
    记忆类型枚举

    用于对记忆进行分类存储和检索，不同类型的记忆在检索时可以单独过滤。

    类型说明:
        - FACT:      事实信息，如"我叫小明"、"我的生日是1月1日"
        - PREFERENCE: 偏好信息，如"我喜欢吃苹果"、"我讨厌香菜"
        - EVENT:     事件记录，如"昨天去公园玩了"、"今天买了新衣服"
        - CONTEXT:   上下文信息，如"最近在聊机器学习"、"刚看完一部电影"
        - SKILL:     技能信息，如"我会Python编程"、"我会弹吉他"

    使用示例:
        MemoryType.FACT          # 返回 'fact' 字符串
        MemoryType.FACT.value    # 返回 'fact' (和上面一样)
        MemoryType.get_display_name(MemoryType.FACT)  # 返回 '事实'
    """
    
    FACT = "fact"               # 事实: 我叫小明、我的生日是1月1日
    PREFERENCE = "preference"   # 偏好: 我喜欢吃苹果、我讨厌香菜
    EVENT = "event"             # 事件: 昨天去公园、今天买了新衣服
    CONTEXT = "context"         # 上下文: 最近在聊什么话题
    SKILL = "skill"             # 技能: 我会Python、我会弹吉他
    
    @classmethod
    def get_display_name(cls, mtype: 'MemoryType') -> str:
        """
        获取记忆类型的中文显示名称

        Args:
            mtype: MemoryType 枚举值

        Returns:
            中文名称字符串，如 '事实'、'偏好' 等
        """
        names = {
            cls.FACT: "事实",
            cls.PREFERENCE: "偏好",
            cls.EVENT: "事件",
            cls.CONTEXT: "上下文",
            cls.SKILL: "技能",
        }
        return names.get(mtype, "未知")


@dataclass
class MemoryItem:
    """
    记忆项数据结构

    每条记忆包含以下信息:
        - content:       记忆内容 (文本)
        - memory_type:   记忆类型 (MemoryType 枚举)
        - memory_id:     唯一标识 (自动生成 UUID)
        - metadata:      额外元数据 (如来源、标签等)
        - importance:    重要性 (0-1，LLM打分，用于检索加权)
        - created_at:    创建时间戳
        - updated_at:    更新时间戳
        - access_count:  被检索次数 (用于统计)

    重要性说明:
        - 0.0-0.3: 不重要，可能会被遗忘
        - 0.3-0.6: 一般重要，常见的记忆
        - 0.6-0.8: 较重要，会优先检索
        - 0.8-1.0: 非常重要，如用户名字、核心偏好

    使用示例:
        item = MemoryItem(
            content="我叫小明",
            memory_type=MemoryType.FACT,
            importance=0.9  # LLM 打分后设置
        )
        item.to_dict()  # 转换为字典便于存储
    """
    
    content: str                                              # 记忆内容文本
    memory_type: MemoryType                                   # 记忆类型
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))  # 唯一 ID
    metadata: Dict[str, Any] = field(default_factory=dict)   # 额外元数据
    importance: float = 0.5                                  # 重要性 (0-1，默认0.5)
    created_at: float = field(default_factory=time.time)    # 创建时间戳
    updated_at: float = field(default_factory=time.time)    # 更新时间戳
    access_count: int = 0                                     # 被检索次数
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将记忆项转换为字典格式 (用于存储到 ChromaDB)

        Returns:
            包含所有字段的字典
        """
        return {
            "id": self.memory_id,
            "content": self.content,
            "type": self.memory_type.value,  # 转为字符串存储
            "metadata": self.metadata,
            "importance": self.importance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
        }
