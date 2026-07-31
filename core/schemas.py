from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Any, ClassVar

# 兼容 Python 3.10+ 的 Self 类型导入
try:
    from typing import Self
except ImportError:
    from typing_extensions import Self  # type: ignore

# ---------------- 消息角色枚举 ----------------
class ChatRole:
    """聊天角色常量 (非 Pydantic 模型)"""
    USER: ClassVar[str] = "user"
    ASSISTANT: ClassVar[str] = "assistant"
    SYSTEM: ClassVar[str] = "system"
    TOOL: ClassVar[str] = "tool"

# 为了向后兼容，也让它像之前一样能当字符串比较
ChatRoleType = str
    
# ---------------- 基础模型，加通用配置 ----------------
class BaseSchema(BaseModel):
    """所有业务模型的基类，统一配置"""
    model_config = ConfigDict(
        use_enum_values=True,  # 枚举自动转成字符串，序列化方便
        arbitrary_types_allowed=True,  # 允许放任意类型
        from_attributes=True,  # 支持从对象属性直接转模型
    )

