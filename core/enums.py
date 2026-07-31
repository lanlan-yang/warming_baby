"""
全局枚举定义

Note:
    AnimationType 已迁移至 core/animations.py
    此处 re-export 保持向后兼容, 新代码建议从 core.animations 导入
"""
from enum import Enum

# AnimationType re-export (已迁移至 core.animations)
from core.animations import AnimationType  # noqa: F401


class PetState(str, Enum):
    """宠物状态"""
    WALKING = 'walking'
    IDLE = 'idle'
    FLYING = 'flying'
    TOUCHED = 'touched'
    HOVERING = 'hovering'


class ModelTask(str, Enum):
    """
    模型任务类型 - 用业务语义代替模型名

    换模型只改 config.py 的 MODEL_REGISTRY，业务代码不写死模型名。

    Example:
        from core import ModelTask
        from providers.llm import get_llm

        llm = get_llm(ModelTask.CHAT)      # 用聊天模型
        llm = get_llm(ModelTask.COMPLEX)   # 用推理模型
    """
    CHAT = "chat"           # 日常对话 (快速、低成本)
    COMPLEX = "complex"     # 复杂推理/深度生成
    VISION = "vision"       # 多模态 (图片理解)
    CODE = "code"           # 代码生成
    EMBEDDING = "embedding" # 向量嵌入


# 保持旧代码兼容 (deprecated)
class LLMModel(str, Enum):
    """LLM 模型常量 (legacy, 新代码请用 ModelTask)"""
    LLM_MODEL_CHAT = "deepseek-v4-flash"
    LLM_MODEL_REASONER = "deepseek-v4-pro"
