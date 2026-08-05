"""
tools.tool_base - 工具基类和注册中心

支持两种工具定义方式:
1. @tool decorator (推荐, 简单工具)
2. AgentTool 子类 (复杂工具, 需要状态或依赖)

Usage:
    from tools.tool_base import tool_registry

    # 方式1: @tool decorator
    @tool
    def get_weather(city: str) -> str:
        '''查询天气'''
        return f"{city} 晴天"

    tool_registry.register(get_weather)

    # 方式2: AgentTool 子类 (复杂逻辑)
    class MemoryTool(AgentTool):
        name = "memory"
        ...
    tool_registry.register(MemoryTool)

    # 获取所有工具给 LLM
    tools = tool_registry.get_tools()
"""
from typing import Any, Optional

from langchain_core.tools import BaseTool as LCBaseTool
from pydantic import Field

from core.logger import logger
from core import event_bus, EventCategory, AgentEvent
from core.schemas import BaseSchema


# ============================================================
# 1. 参数基类 (兼容旧代码)
# ============================================================
class BaseToolArgs(BaseSchema):
    """所有工具参数的基类 (兼容旧的 AgentTool)"""
    pass


# ============================================================
# 2. AgentTool 基类 (复杂工具用)
# ============================================================
class AgentTool(LCBaseTool):
    """
    复杂工具的基类 - 支持异步、事件、日志

    简单工具建议用 @tool decorator。
    只有需要依赖注入或复杂逻辑时才继承这个类。

    子类需要:
    - 定义 name, description
    - 实现 async _execute(**kwargs) -> str
    """

    name: str = ""
    description: str = ""
    args_schema: type[BaseToolArgs] = BaseToolArgs

    async def _execute(self, **kwargs: Any) -> str:
        """子类实现实际逻辑"""
        raise NotImplementedError

    async def _arun(self, **kwargs: Any) -> str:
        """LangChain 入口 - 添加日志"""
        logger.info(f"[Tool] {self.name}: {kwargs}")
        try:
            result = await self._execute(**kwargs)
            logger.info(f"[Tool] {self.name} 完成")
            return result
        except Exception as e:
            logger.error(f"[Tool] {self.name} 失败: {e}")
            raise

    def _run(self, **kwargs: Any) -> str:
        """同步入口 (兜底)"""
        import asyncio
        return asyncio.run(self._arun(**kwargs))


# ============================================================
# 3. 工具注册中心
# ============================================================
class ToolRegistry:
    """
    工具注册中心

    - register: 注册 @tool 或 AgentTool
    - get_tools: 获取所有工具给 llm.bind_tools()
    - list_names: 列出所有工具名

    Example:
        tool_registry.register(get_weather)  # @tool
        tool_registry.register(MemoryTool)   # AgentTool (类或实例)
        tools = tool_registry.get_tools()    # 给 LLM 用
    """

    _tools: dict[str, LCBaseTool] = {}

    @classmethod
    def register(cls, tool: LCBaseTool) -> LCBaseTool:
        """
        注册工具

        Args:
            tool: @tool 创建的工具, 或 AgentTool 类/实例
        Returns:
            注册的工具
        """
        # 处理 AgentTool 类 (自动实例化)
        if isinstance(tool, type):
            tool = tool()

        if not hasattr(tool, 'name') or not tool.name:
            raise ValueError(f"工具未设置 name")

        if tool.name in cls._tools:
            logger.warning(f"[ToolRegistry] 覆盖: {tool.name}")

        cls._tools[tool.name] = tool
        logger.debug(f"[ToolRegistry] 注册: {tool.name}")
        return tool

    @classmethod
    def get_tools(cls) -> list[LCBaseTool]:
        """获取所有工具 (给 llm.bind_tools() 用)"""
        return list(cls._tools.values())

    @classmethod
    def get_tool(cls, name: str) -> Optional[LCBaseTool]:
        """按名称获取工具"""
        return cls._tools.get(name)

    @classmethod
    def list_names(cls) -> list[str]:
        """列出所有工具名"""
        return list(cls._tools.keys())

    @classmethod
    def clear(cls) -> None:
        """清空注册表"""
        cls._tools.clear()
        logger.info("[ToolRegistry] 已清空")


# 全局注册器
tool_registry = ToolRegistry
