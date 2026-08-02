"""
全局枚举定义

Note:
    AnimationType 已迁移至 core/animations.py
    此处 re-export 保持向后兼容, 新代码建议从 core.animations 导入
"""
from enum import StrEnum

class ModelTask(StrEnum):
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



