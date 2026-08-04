"""
tools/tool_memory - 记忆工具集

提供三个记忆相关的工具，让 LLM 可以主动管理用户记忆：

1. query_memory   - 查询记忆（LLM 需要知道用户信息时调用）
2. add_memory     - 添加记忆（LLM 发现新信息时调用）
3. update_memory  - 修改记忆（用户更正信息时调用，自动处理）

与静态注入的区别：
    静态注入：每次对话预检索 1 条最相关的记忆
    LLM 工具：按需查询、添加、修改，更精准更灵活

典型场景：
    用户: "我叫小明"
    LLM: [add_memory("用户叫小明", "fact")] 自动保存

    用户: "我叫什么来着？"
    LLM: [query_memory("用户名字")] 主动查询 → "你叫小明呀"

    用户: "我之前说喜欢桃子，但其实我不喜欢"
    LLM: [update_memory("用户喜欢桃子", "用户不喜欢桃子", "preference")] 自动替换
"""

import asyncio
from typing import Optional

from pydantic import Field

from tools.tool_base import AgentTool, BaseToolArgs
from memory import MemoryManager
from memory.types import MemoryType
from core.logger import logger


# ============================================================================
# 1. Args Schema 定义（LLM 看到的参数说明）
# ============================================================================

class QueryMemoryArgs(BaseToolArgs):
    """查询记忆的参数"""
    query: str = Field(description="要查询的关键词或问题，如'用户名字'、'用户喜好'")
    memory_type: Optional[str] = Field(
        default=None,
        description="记忆类型过滤（可选）：fact=事实, preference=喜好, event=事件, context=上下文, skill=技能"
    )
    max_results: int = Field(default=3, ge=1, le=10, description="返回结果数量")


class AddMemoryArgs(BaseToolArgs):
    """添加记忆的参数"""
    content: str = Field(description="要记忆的内容，如'用户叫小明'、'用户喜欢打篮球'")
    memory_type: str = Field(
        default="fact",
        description="记忆类型：fact=事实(姓名、年龄等), preference=喜好(喜欢什么), event=事件(经历), context=上下文(话题), skill=技能(会什么)"
    )
    importance: str = Field(
        default="normal",
        description="重要程度：high=重要, normal=普通, low=不重要"
    )


class UpdateMemoryArgs(BaseToolArgs):
    """修改记忆的参数"""
    old_content: str = Field(description="要被修改的旧记忆内容，如'用户喜欢桃子'")
    new_content: str = Field(description="新的记忆内容，如'用户不喜欢桃子'")
    memory_type: str = Field(
        default="preference",
        description="记忆类型：fact=事实, preference=喜好, event=事件, context=上下文, skill=技能"
    )


# ============================================================================
# 2. 记忆类型映射
# ============================================================================

MEMORY_TYPE_MAP = {
    "fact": MemoryType.FACT,
    "preference": MemoryType.PREFERENCE,
    "event": MemoryType.EVENT,
    "context": MemoryType.CONTEXT,
    "skill": MemoryType.SKILL,
}


# ============================================================================
# 3. 工具实现
# ============================================================================

class QueryMemoryTool(AgentTool):
    """
    查询用户记忆

    LLM 在需要知道用户信息时调用此工具。
    比如：用户问"我叫什么"、"我之前说过什么"等。
    """

    name: str = "query_memory"
    description: str = (
        "查询我对用户的记忆，了解用户的基本信息、喜好、习惯等。"
        "当你需要知道用户的某个信息时调用，比如用户的名字、喜好、之前说过的话。"
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

        # 类型转换
        mtype = MEMORY_TYPE_MAP.get(memory_type) if memory_type else None

        # 查询记忆 - 使用 to_thread 避免阻塞 event loop
        results = await asyncio.to_thread(
            memory_manager.search,
            query=query,
            n_results=max_results,
            memory_type=mtype,
        )

        if not results:
            logger.info(f"[QueryMemory] 无结果: query='{query}'")
            return f"没有找到关于'{query}'的记忆"

        # 格式化结果
        lines = []
        for i, item in enumerate(results, 1):
            content = item.get("content", "")
            mtype_str = item.get("metadata", {}).get("type", "unknown")
            similarity = item.get("similarity", 0)
            lines.append(f"{i}. [{mtype_str}] {content} (置信度 {similarity:.0%})")

        result_text = "\n".join(lines)
        logger.info(f"[QueryMemory] 找到 {len(results)} 条记忆: {result_text[:50]}...")
        return result_text


class AddMemoryTool(AgentTool):
    """
    添加新记忆

    LLM 在发现用户透露新信息时调用。
    比如：用户说"我叫小明"、"我喜欢打篮球"等。
    """

    name: str = "add_memory"
    description: str = (
        "添加用户的新信息到记忆中。当用户透露了新的个人信息时调用，"
        "比如用户告诉你他的名字、喜好、习惯、经历等。"
        "只在确认是新信息时才调用，不要重复添加已知信息。"
    )
    args_schema: type[BaseToolArgs] = AddMemoryArgs

    async def _execute(
        self,
        content: str,
        memory_type: str = "fact",
        importance: str = "normal",
    ) -> str:
        """
        执行记忆添加

        使用 smart_add_memory，自动检测相似记忆并替换。
        比如：用户先说"我喜欢苹果"，后来又说"其实我不喜欢苹果"，会自动替换。

        Args:
            content: 记忆内容
            memory_type: 记忆类型
            importance: 重要程度（仅记录）

        Returns:
            添加结果提示
        """
        memory_manager = MemoryManager.get_instance()
        
        if not memory_manager.is_ready:
            return "记忆系统还没准备好"

        # 类型转换
        mtype = MEMORY_TYPE_MAP.get(memory_type, MemoryType.FACT)

        # 添加记忆（使用 smart_add，自动处理相似替换）
        # 使用 to_thread 避免阻塞 event loop
        memory_id = await asyncio.to_thread(
            memory_manager.smart_add_memory, content, mtype
        )

        if memory_id:
            logger.info(f"[AddMemory] 添加成功: [{memory_type}] {content} (id={memory_id})")
            return f"已添加到记忆：{content}"
        else:
            logger.warning(f"[AddMemory] 添加失败: {content}")
            return f"添加失败，可能已存在相似记忆"


class UpdateMemoryTool(AgentTool):
    """
    修改现有记忆

    当用户更正之前的信息时调用。
    比如：用户说"之前说我喜欢桃子，但其实我不喜欢"。
    """

    name: str = "update_memory"
    description: str = (
        "修改或更新已有的记忆。当用户更正了之前说过的信息时调用，"
        "比如用户说'之前说我喜欢桃子，但其实我不喜欢'。"
        "系统会自动找到相似的旧记忆并替换为新内容。"
    )
    args_schema: type[BaseToolArgs] = UpdateMemoryArgs

    async def _execute(
        self,
        old_content: str,
        new_content: str,
        memory_type: str = "preference",
    ) -> str:
        """
        执行记忆修改

        流程：
        1. 搜索相似的旧记忆
        2. 如果找到，删除旧记忆并添加新记忆
        3. 如果没找到，直接添加新记忆

        Args:
            old_content: 旧内容（用于找到要替换的记忆）
            new_content: 新内容（替换旧内容）
            memory_type: 记忆类型

        Returns:
            修改结果提示
        """
        memory_manager = MemoryManager.get_instance()
        
        if not memory_manager.is_ready:
            return "记忆系统还没准备好"

        # 类型转换
        mtype = MEMORY_TYPE_MAP.get(memory_type, MemoryType.FACT)

        # 1. 先搜索是否有相似的旧记忆 - 使用 to_thread
        similar = await asyncio.to_thread(
            memory_manager.find_similar,
            query=old_content,
            memory_type=mtype,
            n_results=3,
            min_score=0.5,
        )

        if similar:
            # 找到相似记忆，记录 ID
            similar_ids = [item["id"] for item in similar]
            logger.info(f"[UpdateMemory] 找到 {len(similar_ids)} 条相似记忆: {old_content}")
            
            # 删除旧记忆 - 使用 to_thread
            await asyncio.to_thread(memory_manager.delete_by_ids, similar_ids)

        # 2. 添加新记忆 - 使用 to_thread
        memory_id = await asyncio.to_thread(
            memory_manager.add_memory, new_content, mtype
        )

        if memory_id:
            if similar:
                logger.info(f"[UpdateMemory] 修改成功: '{old_content}' → '{new_content}'")
                return f"已更新记忆：'{old_content}' → '{new_content}'"
            else:
                logger.info(f"[UpdateMemory] 添加新记忆: {new_content}")
                return f"未找到相似旧记忆，已添加新记忆：{new_content}"
        else:
            logger.warning(f"[UpdateMemory] 操作失败: {old_content} → {new_content}")
            return f"操作失败，请重试"


# ============================================================================
# 4. 便捷函数：批量注册
# ============================================================================

def register_memory_tools() -> list[AgentTool]:
    """
    注册所有记忆工具到 ToolRegistry

    Returns:
        注册的工具列表

    使用位置：app.py 的预热阶段
    """
    from tools.tool_base import tool_registry

    tools = [
        QueryMemoryTool(),
        AddMemoryTool(),
        UpdateMemoryTool(),
    ]

    for tool in tools:
        tool_registry.register(tool)
        logger.info(f"[MemoryTools] 已注册: {tool.name}")

    return tools
