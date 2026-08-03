"""
tools.tool_base - LangChain 工具基类、注册器、参数规范

三层结构:
    BaseToolArgs   ->  参数规范基类 (Pydantic 模型, 自动生成 JSON Schema 给 LLM)
    AgentTool      ->  工具基类 (继承 langchain BaseTool, 集成事件总线 + 日志)
    ToolRegistry   ->  工具注册中心 (类方法风格, 对齐 LLMProvider)

Usage:
    from tools.tool_base import BaseToolArgs, AgentTool, tool_registry

    # 1. 定义参数
    class WeatherArgs(BaseToolArgs):
        city: str = Field(description="城市名称")
        days: int = Field(default=1, ge=1, le=7, description="预报天数")

    # 2. 定义工具
    class WeatherTool(AgentTool):
        name: str = "get_weather"
        description: str = "查询指定城市的天气"
        args_schema: type[BaseToolArgs] = WeatherArgs

        async def _execute(self, city: str, days: int = 1) -> str:
            return f"{city} 今天晴, 未来 {days} 天均温"

    # 3. 注册
    tool_registry.register(WeatherTool)

    # 4. 给 LLM 绑定
    tools = tool_registry.get_tools()
"""
from typing import Any, Optional

from langchain_core.tools import BaseTool as LCBaseTool
from pydantic import Field

from core import event_bus, EventCategory, AgentEvent
from core.logger import logger
from core.schemas import BaseSchema


# ============================================================
# 1. 参数规范基类
# ============================================================
class BaseToolArgs(BaseSchema):
    """
    所有工具参数的基类

    子类用 Pydantic Field 声明参数, LangChain 会自动转成 JSON Schema
    喂给 LLM 做 function calling.

    规范:
    - 每个字段必须写 description (LLM 靠它判断何时调用)
    - 有约束用 Field 的 ge/le/max_length 等 (减少 LLM 乱传参)
    - 可选参数给默认值

    Example:
        class SearchArgs(BaseToolArgs):
            query: str = Field(description="搜索关键词", min_length=1)
            limit: int = Field(default=5, ge=1, le=20, description="返回条数")
    """


# ============================================================
# 2. 工具基类
# ============================================================
class AgentTool(LCBaseTool):
    """
    项目工具基类 - 在 LangChain BaseTool 之上统一做三件事:
    1. 事件总线集成: 调用前后自动发 TOOL_CALL / TOOL_RESULT
    2. 日志记录: 调用参数、结果、异常全打日志
    3. 异步优先: 子类只实现 _execute, _arun/_run 自动包装

    子类必须:
    - 声明 name (唯一标识, 全小写下划线)
    - 声明 description (写给 LLM 看的, 说清何时用这个工具)
    - 指定 args_schema (继承 BaseToolArgs)
    - 实现 _execute (异步, 实际业务逻辑)

    Note:
    不要直接重写 _arun / _run, 那样会绕过事件和日志.
    只实现 _execute 即可.
    """

    name: str = ""
    description: str = ""
    args_schema: type[BaseToolArgs] = BaseToolArgs

    # ---- 公共执行接口 ----
    async def execute(self, **kwargs: Any) -> str:
        """
        执行工具 (公共接口)

        Args:
            **kwargs: 工具参数

        Returns:
            str: 工具执行结果
        """
        return await self._arun(**kwargs)

    # ---- 子类实现这个 ----
    async def _execute(self, **kwargs: Any) -> str:
        """
        实际工具逻辑 (子类必须覆盖)

        Returns:
            str: 工具执行结果, 会作为 ToolMessage 内容返回给 LLM
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须实现 _execute"
        )

    # ---- LangChain 入口: 异步 (主路径) ----
    async def _arun(self, **kwargs: Any) -> str:
        self._emit_call(kwargs)
        try:
            result = await self._execute(**kwargs)
            self._emit_result(result)
            return result
        except Exception as e:
            self._emit_result(str(e), error=str(e))
            raise

    # ---- LangChain 入口: 同步 (兜底, 项目以异步为主) ----
    def _run(self, **kwargs: Any) -> str:
        import asyncio
        return asyncio.run(self._arun(**kwargs))

    # ---- 事件 + 日志 ----
    def _emit_call(self, args: dict) -> None:
        logger.info(f"[Tool] 调用 {self.name}: {args}")
        event_bus.publish(
            EventCategory.AGENT, AgentEvent.TOOL_CALL,
            tool_name=self.name, arguments=args,
        )

    def _emit_result(self, result: str, error: Optional[str] = None) -> None:
        if error:
            logger.error(f"[Tool] {self.name} 失败: {error}")
        else:
            preview = result[:100] + ("..." if len(result) > 100 else "")
            logger.info(f"[Tool] {self.name} 完成: {preview}")
        event_bus.publish(
            EventCategory.AGENT, AgentEvent.TOOL_RESULT,
            tool_name=self.name, result=result, error=error,
        )


# ============================================================
# 3. 工具注册中心
# ============================================================
class ToolRegistry:
    """
    工具注册中心 (类方法风格, 对齐 LLMProvider)

    - register: 注册工具类或实例
    - get_tool: 按名字取实例
    - get_tools: 取全部 (给 LLM bind_tools 用)
    - list_names: 列出所有工具名

    Example:
        tool_registry.register(WeatherTool)           # 注册类
        tool_registry.register(WeatherTool())          # 或实例

        tool = tool_registry.get_tool("get_weather")
        all_tools = tool_registry.get_tools()          # 给 LLM 绑定
    """

    _tools: dict[str, AgentTool] = {}

    @classmethod
    def register(cls, tool) -> AgentTool:
        """
        注册工具 (可传类或实例)

        Args:
            tool: AgentTool 子类, 或 AgentTool 实例
        Returns:
            AgentTool: 注册后的实例
        """
        if isinstance(tool, type) and issubclass(tool, AgentTool):
            instance = tool()
        elif isinstance(tool, AgentTool):
            instance = tool
        else:
            raise TypeError(
                f"只能注册 AgentTool 子类或实例, 收到: {type(tool).__name__}"
            )

        if not instance.name:
            raise ValueError(
                f"{instance.__class__.__name__} 未设置 name"
            )

        if instance.name in cls._tools:
            logger.warning(f"[ToolRegistry] 覆盖已存在工具: {instance.name}")

        cls._tools[instance.name] = instance
        logger.debug(f"[ToolRegistry] 注册: {instance.name}")
        return instance

    @classmethod
    def get_tool(cls, name: str) -> Optional[AgentTool]:
        """按名字取工具实例, 不存在返回 None"""
        return cls._tools.get(name)

    @classmethod
    def get_tools(cls) -> list[AgentTool]:
        """取全部工具 (给 llm.bind_tools() 用)"""
        return list(cls._tools.values())

    @classmethod
    def get_tool_descriptions(cls) -> str:
        """获取所有工具的描述 (用于 system prompt)"""
        descriptions = []
        
        for tool_name, tool in cls._tools.items():
            # 从 args_schema 获取参数信息
            params = []
            if tool.args_schema:
                schema = tool.args_schema.model_json_schema()
                for prop_name, prop_info in schema.get('properties', {}).items():
                    params.append(f"  - {prop_name}: {prop_info.get('description', '')}")
            
            desc = f"### {tool_name}\n"
            desc += f"描述: {tool.description}\n"
            desc += f"参数:\n" + "\n".join(params)
            descriptions.append(desc)
        
        return "\n\n".join(descriptions)

    @classmethod
    def list_names(cls) -> list[str]:
        """列出所有已注册工具名"""
        return list(cls._tools.keys())

    @classmethod
    def clear(cls) -> None:
        """清空注册表"""
        cls._tools.clear()
        logger.info("[ToolRegistry] 已清空")


# 全局注册器 (直接用类, 不实例化, 和 LLMProvider 风格一致)
tool_registry = ToolRegistry
