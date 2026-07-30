"""
全局枚举定义
"""
from enum import StrEnum


class AnimationType(StrEnum):
    """动画类型"""
    WALK = 'walk'
    STAND = 'stand'
    FLY = 'fly'
    TOUCH = 'touch'
    CONFUSED = 'confused'


class PetState(StrEnum):
    """宠物状态"""
    WALKING = 'walking'
    IDLE = 'idle'
    FLYING = 'flying'
    TOUCHED = 'touched'
    HOVERING = 'hovering'

class LLMModel(StrEnum):
    """LLM 模型"""
    LLM_MODEL_CHAT = 'deepseek-v4-flash'
    LLM_MODEL_GENERATE = 'deepseek-v4-pro'
