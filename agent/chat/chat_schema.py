"""
agent.chat.chat_schema - 聊天模块 Schema

核心数据模型:
- 枚举类: Emotion
- 数据模型: ChatResponse, MemoryExtract
"""
from enum import StrEnum

from pydantic import Field, field_validator

from core.logger import setup_logger
from core.schemas import BaseSchema

logger = setup_logger()


# ============================================================================
# 1. 枚举类
# ============================================================================

class Emotion(StrEnum):
    """
    情绪枚举 - 对应动画类型

    Attributes:
        HAPPY: 开心/笑
        ANGRY: 生气/愤怒
        SAD: 难过/委屈
        CONFUSED: 困惑/思考
        SLEEP: 犯困/想睡
        PLAY: 想玩/开心
        EATING: 吃东西/馋嘴
        NEUTRAL: 普通/无情绪
    """
    HAPPY = "happy"
    ANGRY = "angry"
    SAD = "sad"
    CONFUSED = "confused"
    SLEEP = "sleep"
    PLAY = "play"
    EATING = "eating"
    NEUTRAL = "neutral"


# ============================================================================
# 2. 记忆提取模型 (用于 LLM 返回新记忆)
# ============================================================================

class MemoryExtract(BaseSchema):
    """LLM 从对话中提取的新记忆项"""
    content: str = Field(description="提取的事实/偏好，如'用户叫小明'")
    memory_type: str = Field(description="记忆类型: fact/preference/event/context/skill")


# ============================================================================
# 3. 响应模型 (用于结构化输出)
# ============================================================================

class ChatResponse(BaseSchema):
    """
    聊天响应 - LLM 返回的结构化数据

    这个 Schema 定义了 LLM 必须返回的结构，
    配合 with_structured_output 实现真正的类型安全。

    Attributes:
        text: LLM 生成的回复文本
        emotion: 对应的情绪 (用于动画)
        play_once: 是否单次播放动画

    Example:
        response = ChatResponse(
            text="你好呀~",
            emotion=Emotion.HAPPY,
            play_once=True
        )
        print(response.emotion)  # "happy"
    """
    text: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="回复的内容，简短自然，像小宠物说话"
    )
    emotion: Emotion = Field(
        default=Emotion.NEUTRAL,
        description="根据回复内容选择的情绪"
    )
    play_once: bool = Field(
        default=True,
        description="动画是否单次播放。情绪动画(true)，状态动画(false)"
    )
    new_memories: list[MemoryExtract] = Field(
        default_factory=list,
        description="对话中发现的用户新信息，无则返回空列表"
    )
    
    @field_validator('emotion', mode='before')
    @classmethod
    def validate_emotion(cls, v):
        """
        验证 emotion 字段，如果值不在枚举中则默认为 NEUTRAL
        
        LLM 可能返回预想不到的 emotion 值，如 'curious'，
        需要容错处理避免验证失败。
        """
        try:
            return Emotion(v)
        except ValueError:
            logger.warning(f"[ChatResponse] Unknown emotion '{v}', defaulting to NEUTRAL")
            return Emotion.NEUTRAL
