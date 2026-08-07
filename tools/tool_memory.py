"""
tools/tool_memory - 记忆工具

只提供查询工具给 LLM，记忆的添加/修改由 memory_node 确定性节点处理。

工具列表：
    query_memory - 查询记忆（LLM 需要用户信息时调用）

架构说明：
    - 核心记忆（FACT + 高重要性 PREFERENCE/SKILL）启动时加载到 CoreMemoryCache，
      直接注入系统提示词，LLM 无需调用工具即可获取
    - 非核心记忆通过 query_memory 工具按需查询
    - 记忆存储由 graph 中的 memory_node 确定性节点自动处理

典型场景：
    用户: "我叫什么来着？"
    LLM: [query_memory("用户名字")] 主动查询 → "你叫小明呀"

    用户: "我叫小明"
    （memory_node 自动提取并存储，LLM 不参与存储决策）
"""

import asyncio
from typing import Optional

from pydantic import Field

from tools.tool_base import AgentTool, BaseToolArgs
from memory import MemoryManager
from memory.types import MemoryType
from core.logger import logger


# ============================================================================
# Args Schema 定义
# ============================================================================

class QueryMemoryArgs(BaseToolArgs):
    """查询记忆的参数"""
    query: str = Field(description="要查询的关键词或问题，如'用户名字'、'用户喜好'")
    memory_type: Optional[str] = Field(
        default=None,
        description="记忆类型过滤（可选）：fact=事实, preference=喜好, event=事件, context=上下文, skill=技能"
    )
    max_results: int = Field(default=3, ge=1, le=10, description="返回结果数量")


# ============================================================================
# 记忆类型映射
# ============================================================================

MEMORY_TYPE_MAP = {
    "fact": MemoryType.FACT,
    "preference": MemoryType.PREFERENCE,
    "event": MemoryType.EVENT,
    "context": MemoryType.CONTEXT,
    "skill": MemoryType.SKILL,
}


# ============================================================================
# 工具实现
# ============================================================================

class QueryMemoryTool(AgentTool):
    """
    查询用户记忆

    LLM 在需要知道用户信息时调用此工具。
    比如：用户问"我叫什么"、"我之前说过什么"等。
    """

    name: str = "query_memory"
    description: str = (
        "查询用户的长期记忆（事件经历、上下文话题等）。"
        "只在确实需要时才调用，不要每轮都查。"
        "【适用场景】用户问之前说过的事、过去的经历（如'我上次说的电影呢'）。"
        "【不要调用】系统提示词中【用户信息】【用户喜好】【用户技能】已提供的内容，"
        "用户刚在对话中说过的信息。"
    )
    args_schema: type[BaseToolArgs] = QueryMemoryArgs

    async def _execute(
        self,
        query: str,
        memory_type: Optional[str] = None,
        max_results: int = 3,
    ) -> str:
        """
        执行记忆查询

        Args:
            query: 查询关键词
            memory_type: 可选的类型过滤
            max_results: 最大结果数

        Returns:
            查询结果文本（如果没有记忆则返回提示）
        """
        memory_manager = MemoryManager.get_instance()

        if not memory_manager.is_ready:
            return "记忆系统还没准备好，请稍后再试"

        mtype = MEMORY_TYPE_MAP.get(memory_type) if memory_type else None

        results = await asyncio.to_thread(
            memory_manager.search,
            query=query,
            n_results=max_results,
            memory_type=mtype,
        )

        if not results:
            logger.info(f"[QueryMemory] 无结果: query='{query}'")
            return f"没有找到关于'{query}'的记忆"

        lines = []
        for i, item in enumerate(results, 1):
            content = item.get("content", "")
            mtype_str = item.get("metadata", {}).get("type", "unknown")
            similarity = item.get("similarity", 0)
            lines.append(f"{i}. [{mtype_str}] {content} (置信度 {similarity:.0%})")

        result_text = "\n".join(lines)
        logger.info(f"[QueryMemory] 找到 {len(results)} 条记忆: {result_text[:50]}...")
        return result_text


# ============================================================================
# 便捷函数：批量注册
# ============================================================================

def register_memory_tools() -> list[AgentTool]:
    """
    注册记忆工具到 ToolRegistry

    只注册查询工具给 LLM，添加/修改由 memory_node 确定性节点处理。

    Returns:
        注册的工具列表

    使用位置：app.py 的预热阶段
    """
    from tools.tool_base import tool_registry

    tools = [
        QueryMemoryTool(),
    ]

    for tool in tools:
        tool_registry.register(tool)
        logger.info(f"[MemoryTools] 已注册: {tool.name}")

    return tools
