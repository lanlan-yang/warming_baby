"""
agent/chat/nodes.py - LangGraph 节点定义

所有节点只负责：
    1. 从 State 读取数据
    2. 执行逻辑
    3. 返回要更新的 State 字段

节点列表：
    - agent_node: LLM 决策节点，调用 LLM
    - CustomToolNode: 自定义工具执行节点（仅查询类工具）
    - format_node: 格式化节点，生成最终的 ChatResponse
    - memory_node: 确定性记忆节点，提取并存储用户记忆

条件边：
    - route_tools: 判断是继续循环还是结束
"""

import asyncio
import json
from typing import Any, Callable, Awaitable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models import BaseChatModel

from core.logger import setup_logger
from .state import ChatState
from .chat_schema import ChatResponse, Emotion

logger = setup_logger()


async def _retry_llm_call(func, max_retries: int = 3, name: str = "LLM"):
    """
    LLM 调用重试（指数退避）

    Args:
        func: 异步函数
        max_retries: 最大重试次数
        name: 调用名称（用于日志）

    Returns:
        func 的返回值

    Raises:
        最后一次的异常
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    f"[{name}] 重试 {attempt + 1}/{max_retries}: {type(e).__name__}, {wait}s 后重试"
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    f"[{name}] {max_retries} 次全失败: {type(e).__name__}: {e}"
                )
    raise last_error


class CustomToolNode:
    """
    自定义工具执行节点

    从最后一条 AIMessage 中提取 tool_calls，执行对应的工具，
    并将结果包装成 ToolMessage 返回。

    注意：此节点只执行查询类工具（query_memory, weather 等）。
    记忆的添加/修改由 memory_node 确定性节点处理。
    """

    def __init__(self, tools: list) -> None:
        """
        初始化工具节点

        Args:
            tools: 工具列表，每个工具需要有 name 和 invoke 方法
        """
        self.tools_by_name = {tool.name: tool for tool in tools}
        logger.info(f"[CustomToolNode] 初始化，工具数量: {len(tools)}")

    async def __call__(self, inputs: dict) -> dict:
        """
        执行工具调用

        Args:
            inputs: 包含 messages 的字典

        Returns:
            dict: {"messages": [ToolMessage, ...]}
        """
        messages = inputs.get("messages", [])
        if not messages:
            raise ValueError("No message found in input")

        message = messages[-1]
        outputs = []

        for tool_call in message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_call_id = tool_call["id"]

            logger.info(
                f"[CustomToolNode] 执行工具: {tool_name}, args={tool_args}"
            )

            try:
                tool = self.tools_by_name.get(tool_name)
                if tool is None:
                    tool_result = {"error": f"未知工具: {tool_name}"}
                else:
                    tool_result = await tool.ainvoke(tool_args)

                content = json.dumps(tool_result, ensure_ascii=False)

            except Exception as e:
                logger.error(
                    f"[CustomToolNode] 工具执行失败: {tool_name}, error={e}"
                )
                content = json.dumps({"error": str(e)}, ensure_ascii=False)

            tool_message = ToolMessage(
                content=content,
                name=tool_name,
                tool_call_id=tool_call_id,
            )
            outputs.append(tool_message)

        logger.info(f"[CustomToolNode] 执行完成，共 {len(outputs)} 个工具调用")
        return {"messages": outputs}


def create_agent_node(llm: BaseChatModel) -> Callable[[ChatState], Awaitable[dict]]:
    """
    创建 Agent 节点

    职责：
        1. 从 state["messages"] 读取历史
        2. 调用 LLM（已绑定工具）
        3. 返回 {"messages": [llm_response], "iteration": state["iteration"] + 1, "status": "thinking"}

    Args:
        llm: 已绑定工具的 LLM 实例
    """

    async def agent_node(state: ChatState) -> dict[str, Any]:
        messages = state["messages"]
        current_iteration = state.get("iteration", 0)
        max_iterations = state.get("max_iterations", 5)

        logger.info(f"[AgentNode] 第 {current_iteration + 1} 次 LLM 调用")

        response = await _retry_llm_call(
            lambda: llm.ainvoke(messages),
            name="AgentNode",
        )

        new_iteration = current_iteration + 1
        has_tools = bool(response.tool_calls)

        logger.info(
            f"[AgentNode] LLM 响应: {'有工具调用' if has_tools else '无工具调用'} "
            f"(迭代 {new_iteration}/{max_iterations})"
        )

        return {
            "messages": [response],
            "iteration": new_iteration,
            "status": "calling_tools" if has_tools else "formatting",
        }

    return agent_node


def route_tools(state: ChatState) -> str:
    """
    条件边：判断是去执行工具还是格式化

    逻辑参考 LangChain 官方示例 route_tools：
    - 如果最后一条 AIMessage 有 tool_calls → 去 tools 节点
    - 否则 → 去 format 节点生成最终响应

    Args:
        state: 当前状态

    Returns:
        "tools" 或 "format"
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 5)

    # 检查最大迭代次数
    if iteration >= max_iterations:
        logger.warning(f"[route_tools] 达到最大迭代次数 {max_iterations}")
        return "format"

    # 检查最后一条消息
    if not messages:
        logger.warning("[route_tools] 无消息")
        return "format"

    last_message = messages[-1]

    if hasattr(last_message, "tool_calls") and len(last_message.tool_calls) > 0:
        logger.info(f"[route_tools] 有 {len(last_message.tool_calls)} 个工具调用")
        return "tools"

    logger.info("[route_tools] 无工具调用，准备格式化")
    return "format"


def create_format_node(llm: BaseChatModel) -> Callable[[ChatState], Awaitable[dict]]:
    """
    创建 Format 节点（闭包形式，绑定 llm）

    职责：
        1. 从 state["messages"] 找最后一条 AIMessage
        2. 用 LLM 进行结构化提取（emotion, new_memories）
        3. 写入 state["final_response"]
        4. 返回 {"final_response": chat_response, "status": "done"}

    注意：记忆提取只从 HumanMessage 中提取，防止 AI 编造内容。
    实际存储由 memory_node 处理。
    """

    async def format_node(state: ChatState) -> dict[str, Any]:
        messages = state["messages"]

        # 找最后一条 AIMessage (用于获取 AI 回复文本)
        last_ai_message = None
        # 找最后一条 HumanMessage (用于提取记忆，确保记忆来自用户而非 AI)
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and last_ai_message is None:
                last_ai_message = msg
            if isinstance(msg, HumanMessage) and last_human_message is None:
                last_human_message = msg
            if last_ai_message and last_human_message:
                break

        if not last_ai_message:
            logger.warning("[FormatNode] 没有找到 AIMessage")
            return {
                "final_response": ChatResponse(
                    text="抱歉，我没听清你说的什么...",
                    emotion="confused",
                ),
                "status": "done",
            }

        # 用 LLM 进行结构化提取（带重试）
        try:
            from pydantic import BaseModel, Field

            # 创建简化的 Schema - 只提取 emotion 和 new_memories
            # emotion 可选值从 Emotion 枚举动态生成，与 EMOTION_DESCRIPTIONS 保持一致
            class ChatMetadata(BaseModel):
                """聊天元数据 - 只提取情绪和记忆"""
                emotion: str = Field(
                    default=Emotion.NEUTRAL,
                    description=f"emotion值: {ChatResponse.get_emotion_value_list()}"
                )
                new_memories: list[str] = Field(
                    default_factory=list,
                    description="从用户消息中发现的新信息，如无则返回空数组"
                )

            # 情绪从 AI 回复提取，记忆从用户消息提取
            ai_content = last_ai_message.content
            if isinstance(ai_content, list):
                ai_content = " ".join(
                    item.get("text", "")
                    for item in ai_content
                    if isinstance(item, dict) and item.get("type") == "text"
                )

            # 记忆提取基于用户消息，而非 AI 回复
            # 防止 AI 编造内容被当成用户信息存储
            user_content = ""
            if last_human_message:
                user_content = last_human_message.content
                if isinstance(user_content, list):
                    user_content = " ".join(
                        item.get("text", "")
                        for item in user_content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )

            if not ai_content:
                ai_content = "抱歉，我没听清你说的什么..."

            # 创建提取元数据的 prompt（指令统一从 ChatSchema 获取，保证与其它处一致）
            extraction_system = SystemMessage(
                content=ChatResponse.get_extraction_instruction()
            )
            extraction_input = (
                f"【用户消息】\n{user_content}\n\n"
                f"【AI回复】\n{ai_content}"
            )
            user_message = HumanMessage(content=extraction_input)
            extraction_messages = [extraction_system, user_message]

            chat_response = None
            errors = []

            # 判断是否是永久性错误（不支持的方法）
            def is_permanent_error(e: Exception) -> bool:
                err_msg = str(e).lower()
                return any(
                    keyword in err_msg
                    for keyword in ["does not support", "not supported"]
                )

            # 尝试方法 1: 使用简化的 Schema
            try:
                structured_llm = llm.with_structured_output(
                    ChatMetadata, method="function_calling"
                )
                metadata = await _retry_llm_call(
                    lambda: structured_llm.ainvoke(extraction_messages),
                    name="FormatNode-Metadata-FC",
                    max_retries=1,
                )
                # 用 AI 回复内容创建 ChatResponse
                chat_response = ChatResponse(
                    text=ai_content,
                    emotion=metadata.emotion,
                    new_memories=[
                        {"content": m, "memory_type": "fact"}
                        for m in metadata.new_memories
                    ],
                )
            except Exception as e:
                if is_permanent_error(e):
                    logger.info("[FormatNode] function_calling 不支持，跳过")
                errors.append(f"function_calling: {e}")

            # 尝试方法 2: JSON 解析
            if chat_response is None:
                try:
                    response = await _retry_llm_call(
                        lambda: llm.ainvoke(extraction_messages),
                        name="FormatNode-Metadata-Raw",
                        max_retries=1,
                    )
                    # 尝试提取 JSON
                    import re
                    raw_content = response.content
                    json_match = re.search(r'```json\s*(.*?)\s*```', raw_content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                    else:
                        json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
                        json_str = json_match.group(0) if json_match else raw_content

                    json_data = json.loads(json_str)

                    # 用原始内容创建 ChatResponse
                    chat_response = ChatResponse(
                        text=ai_content,
                        emotion=json_data.get("emotion", "neutral"),
                        new_memories=[
                            {"content": m, "memory_type": "fact"}
                            for m in json_data.get("new_memories", [])
                        ],
                    )
                    logger.info("[FormatNode] JSON 解析成功")
                except Exception as e:
                    errors.append(f"json_parse: {e}")

            if chat_response is None:
                raise Exception(f"所有方法都失败: {', '.join(errors)}")

            logger.info(
                f"[FormatNode] 结构化提取完成: emotion={chat_response.emotion}, "
                f"memories={len(chat_response.new_memories)}"
            )

            return {
                "final_response": chat_response,
                "status": "done",
            }

        except Exception as e:
            logger.error(f"[FormatNode] 结构化提取失败，使用 fallback: {e}")

            return {
                "final_response": ChatResponse(
                    text=last_ai_message.content or "抱歉，我处理你的消息时遇到了问题...",
                    emotion="neutral",
                ),
                "status": "done",
            }

    return format_node


def create_memory_node() -> Callable[[ChatState], Awaitable[dict]]:
    """
    创建确定性记忆节点

    此节点在 format_node 之后运行，负责：
        1. 从 final_response.new_memories 获取提取的记忆
        2. 对每条记忆进行类型修正和字段提取
        3. 更新 CoreMemoryCache（乐观更新，立即生效）
        4. 后台异步存储到数据库（不阻塞响应）

    设计原则：
        - 确定性：每次对话结束都会运行，不依赖 LLM 决策
        - 非阻塞：存储在后台执行，不影响响应速度
        - 来源安全：FormatNode 已确保记忆只从 HumanMessage 提取
    """

    async def memory_node(state: ChatState) -> dict[str, Any]:
        final_response = state.get("final_response")
        if not final_response or not final_response.new_memories:
            return {}

        try:
            from memory import get_memory_manager, get_core_cache
            from memory.normalizer import get_normalizer
            from memory.types import MemoryType

            manager = get_memory_manager()
            if not manager or not manager.is_ready:
                logger.warning("[MemoryNode] MemoryManager 未就绪，跳过存储")
                return {}

            cache = get_core_cache()
            normalizer = get_normalizer()

            type_map = {
                "fact": MemoryType.FACT,
                "preference": MemoryType.PREFERENCE,
                "event": MemoryType.EVENT,
                "context": MemoryType.CONTEXT,
                "skill": MemoryType.SKILL,
            }

            for mem in final_response.new_memories:
                content = mem.content
                mtype = type_map.get(mem.memory_type, MemoryType.FACT)

                # 1. 类型修正
                corrected_type = normalizer.correct_type(content, mtype)
                if corrected_type != mtype:
                    logger.info(
                        f"[MemoryNode] 类型修正: [{mtype.value}] -> [{corrected_type.value}] "
                        f"内容: {content}"
                    )

                # 2. 字段提取
                field = normalizer.extract_field(content, corrected_type)

                # 3. 乐观更新缓存（立即生效，下次对话即可使用）
                cache.update(corrected_type.value, field, content)

                # 4. 后台存储（不阻塞响应）
                metadata = {"field": field}
                asyncio.create_task(
                    asyncio.to_thread(
                        manager.smart_add_memory,
                        content, corrected_type, metadata
                    )
                )
                logger.info(
                    f"[MemoryNode] 记忆存储中: [{corrected_type.value}] [{field}] {content}"
                )

        except Exception as e:
            logger.error(f"[MemoryNode] 记忆存储异常: {e}")

        return {}

    return memory_node
