"""
tools.mcp.mcp_bridge - MCP 工具 → AgentTool 桥接器

将 MCP Server 暴露的工具动态包装成项目的 AgentTool，
自动注册进 tool_registry，无缝融入 LangGraph 工具链。

核心流程:
    MCP Server ──tools/list──→ [Tool(name, description, input_schema)]
                                        │
                                   McpToolWrapper.from_mcp_tool()
                                        │
                                   AgentTool 子类实例
                                        │
                                   tool_registry.register()
                                        │
                                   LangGraph bind_tools() + CustomToolNode

设计要点:
    - input_schema (JSON Schema) → Pydantic args_schema 动态创建
    - _execute() 里调 session.call_tool() 跨进程执行
    - 一个通用 Wrapper 类包装任意 MCP 工具，无需为每个工具写子类
"""
from typing import Any, Optional
from pydantic import Field, create_model

from core.logger import logger
from ..tool_base import AgentTool, BaseToolArgs


# JSON Schema type → Python type 映射
_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_schema_to_pydantic(tool_name: str, schema: dict) -> type:
    """
    将 MCP 工具的 input_schema (JSON Schema) 转成 Pydantic 模型

    Args:
        tool_name: 工具名（用于生成类名）
        schema: MCP 返回的 input_schema 字典

    Returns:
        动态创建的 Pydantic 模型类
    """
    if not schema:
        return BaseToolArgs

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    fields = {}
    for prop_name, prop_def in properties.items():
        json_type = prop_def.get("type", "string")
        py_type = _JSON_TYPE_MAP.get(json_type, str)

        description = prop_def.get("description", "")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(..., description=description))
        else:
            default = prop_def.get("default", None)
            fields[prop_name] = (Optional[py_type], Field(default=default, description=description))

    model_name = f"{tool_name}_Args"
    return create_model(model_name, __base__=BaseToolArgs, **fields)


class McpToolWrapper(AgentTool):
    """
    通用 MCP 工具包装器

    将任意 MCP Server 暴露的工具包装成 AgentTool。
    不需要为每个 MCP 工具单独写子类——from_mcp_tool() 自动完成所有适配。

    使用示例:
        # 在 MCPClientManager 中:
        for mcp_tool in await session.list_tools().tools:
            wrapper = McpToolWrapper.from_mcp_tool(session, mcp_tool, "bing-search")
            tool_registry.register(wrapper)

    设计说明:
        - _session 和 _mcp_name 用 PrivateAttr 存储，不参与 Pydantic 序列化
        - args_schema 通过 from_mcp_tool() 动态设置，适配任意 MCP 工具参数
    """
    _session: Any = None       # mcp.ClientSession
    _mcp_name: str = ""        # MCP 工具原始名称

    @classmethod
    def from_mcp_tool(cls, session: Any, mcp_tool: Any, server_name: str = "") -> "McpToolWrapper":
        """
        从 MCP Tool 对象创建 AgentTool 实例

        Args:
            session: mcp.ClientSession 实例（用于调用工具）
            mcp_tool: mcp Tool 对象（含 name, description, input_schema）
            server_name: MCP Server 名称（用于日志标识）

        Returns:
            McpToolWrapper 实例，可直接注册到 tool_registry
        """
        args_schema = _json_schema_to_pydantic(mcp_tool.name, mcp_tool.input_schema)

        instance = cls(
            name=mcp_tool.name,
            description=mcp_tool.description or f"MCP tool from {server_name}",
            args_schema=args_schema,
        )

        instance._session = session
        instance._mcp_name = mcp_tool.name

        logger.debug(
            f"[McpBridge] 包装工具: {mcp_tool.name} "
            f"(from {server_name}, args: {list(args_schema.model_fields.keys())})"
        )
        return instance

    async def _execute(self, **kwargs: Any) -> str:
        """
        调用 MCP Server 执行工具

        通过 session.call_tool() 发送 JSON-RPC 请求到 MCP Server 子进程，
        等待结果并返回文本内容。
        """
        if self._session is None:
            raise RuntimeError(f"MCP session not initialized for tool: {self.name}")

        filtered_args = {k: v for k, v in kwargs.items() if v is not None}

        result = await self._session.call_tool(self._mcp_name, filtered_args)

        texts = []
        for content in result.content:
            if hasattr(content, "text"):
                texts.append(content.text)

        return "\n".join(texts) if texts else "（无返回内容）"
