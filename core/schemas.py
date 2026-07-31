"""
core.schemas - 基础 Schema 定义

只放项目级别的基础类，业务相关的 Schema 放在对应的模块下：
- 聊天相关 -> agent/chat/chat_schema.py
- 其他业务 -> 对应模块的 schema 文件
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Any

# 兼容 Python 3.10+ 的 Self 类型导入
try:
    from typing import Self
except ImportError:
    from typing_extensions import Self  # type: ignore


class BaseSchema(BaseModel):
    """所有业务模型的基类，统一配置"""
    model_config = ConfigDict(
        use_enum_values=True,  # 枚举自动转成字符串
        arbitrary_types_allowed=True,  # 允许放任意类型
        from_attributes=True,  # 支持从对象属性直接转模型
        extra="allow",  # 允许额外字段
    )
