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
import re
from typing import Any, Callable, Awaitable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

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


# ============================================================================
# Format 节点的模块级 Schema 与辅助函数（消除 format_node 闭包内部定义）
# ============================================================================

class ChatMetadata(BaseModel):
    """聊天元数据 - Format 节点只提取 emotion 和 new_memories"""
    emotion: str = Field(
        default=Emotion.NEUTRAL,
        description=f"emotion值: {ChatResponse.get_emotion_value_list()}"
    )
    new_memories: list[str] = Field(
        default_factory=list,
        description="从用户消息中发现的新信息，如无则返回空数组"
    )


def _find_last_messages(messages: list[BaseMessage]) -> tuple[AIMessage | None, HumanMessage | None]:
    """
    从消息历史找最后一条 AIMessage 和 HumanMessage

    Returns:
        (last_ai, last_human)
    """
    last_ai = None
    last_human = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and last_ai is None:
            last_ai = msg
        if isinstance(msg, HumanMessage) and last_human is None:
            last_human = msg
        if last_ai and last_human:
            break
    return last_ai, last_human


def _extract_message_content(msg: BaseMessage | None) -> str:
    """提取消息中的纯文本（兼容 content 为 list[str|dict] 的情况）"""
    if msg is None:
        return ""
    content = msg.content
    if isinstance(content, list):
        return " ".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return str(content)


# 暗示"工具已执行"的关键词 —— 没调工具时出现这些词就改写
_TOOL_EXECUTED_KEYWORDS = [
    "弹出来", "弹出了", "已弹出", "打开啦", "打开了", "已打开",
    "已为你打开", "已经打开", "为你弹出", "帮你打开了",
    "已查询", "已为你查询", "查到了", "查好了",
    "已经帮你查", "已经查到",
]


def _guard_unexecuted_tool_claims(messages: list[BaseMessage], ai_content: str) -> str:
    """
    兜底检查：如果对话中没有 ToolMessage（工具未被调用过），
    但 AI 回复中出现了暗示工具已执行的关键词，则改写为引导语。

    这能防止 LLM 在未调用工具时谎称"弹出来了""已打开"等。
    """
    # 检查是否有 ToolMessage —— 只要有一个就说明工具被调用过
    has_tool_result = any(isinstance(msg, ToolMessage) for msg in messages)
    if has_tool_result:
        return ai_content  # 工具确实调了，不用改

    # 没调工具，检查 AI 回复是否有"已执行"暗示
    has_claim = any(kw in ai_content for kw in _TOOL_EXECUTED_KEYWORDS)
    if not has_claim:
        return ai_content  # 没有谎称，不用改

    logger.warning(
        f"[FormatNode] 检测到未调用工具但AI声称已执行，改写回复。原文: {ai_content[:80]}"
    )
    return "我去帮你查一下，稍等哦~"


def _build_extraction_messages(
    user_content: str,
    ai_content: str,
    pet_status: str = "",
) -> list[BaseMessage]:
    """
    构建 Format 节点提取 emotion/memories 用的消息列表

    结构：
        [SystemMessage(提取指令), HumanMessage(用户消息 + AI回复 + 宠物状态)]
    """
    system_msg = SystemMessage(content=ChatResponse.get_extraction_instruction())

    input_text = (
        f"【用户消息】\n{user_content}\n\n"
        f"【AI回复】\n{ai_content}"
    )
    if pet_status:
        input_text += f"\n\n【宠物状态】\n{pet_status}"

    return [system_msg, HumanMessage(content=input_text)]


async def _extract_via_function_calling(
    llm: BaseChatModel,
    extraction_messages: list[BaseMessage],
    ai_content: str,
) -> ChatResponse | None:
    """
    Format 提取方法 1: function_calling 结构化输出

    失败返回 None，成功返回 ChatResponse。
    对 "不支持" 的错误直接跳过，不重试。
    """
    def is_permanent_error(e: Exception) -> bool:
        err_msg = str(e).lower()
        return any(k in err_msg for k in ["does not support", "not supported"])

    try:
        structured_llm = llm.with_structured_output(
            ChatMetadata, method="function_calling"
        )
        metadata = await _retry_llm_call(
            lambda: structured_llm.ainvoke(extraction_messages),
            name="FormatNode-Metadata-FC",
            max_retries=1,
        )
        return ChatResponse(
            text=ai_content,
            emotion=metadata.emotion,
            new_memories=[{"content": m, "memory_type": "fact"} for m in metadata.new_memories],
        )
    except Exception as e:
        if is_permanent_error(e):
            logger.info("[FormatNode] function_calling 不支持，跳过")
        return None


async def _extract_via_json_parse(
    llm: BaseChatModel,
    extraction_messages: list[BaseMessage],
    ai_content: str,
) -> ChatResponse | None:
    """
    Format 提取方法 2: 普通 LLM 调用 + JSON 正则解析

    失败返回 None。
    """
    try:
        response = await _retry_llm_call(
            lambda: llm.ainvoke(extraction_messages),
            name="FormatNode-Metadata-Raw",
            max_retries=1,
        )
        raw_content = response.content
        json_match = re.search(r'```json\s*(.*?)\s*```', raw_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
            json_str = json_match.group(0) if json_match else raw_content

        json_data = json.loads(json_str)
        logger.info("[FormatNode] JSON 解析成功")
        return ChatResponse(
            text=ai_content,
            emotion=json_data.get("emotion", "neutral"),
            new_memories=[
                {"content": m, "memory_type": "fact"}
                for m in json_data.get("new_memories", [])
            ],
        )
    except Exception:
        return None


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


def create_format_node(
    llm: BaseChatModel,
) -> Callable[[ChatState], Awaitable[dict]]:
    """
    创建 Format 节点（闭包形式，绑定 llm）

    职责：
        1. 从 state["messages"] 找最后一条 AIMessage
        2. 用 LLM 进行结构化提取（emotion, new_memories）
        3. 写入 state["final_response"]
        4. 返回 {"final_response": chat_response, "status": "done"}

    注意：记忆提取只从 HumanMessage 中提取，防止 AI 编造内容。
    实际存储由 memory_node 处理。

    宠物状态从 state["pet_status"] 读取，由调用方在 run_chat 入口写入。
    """

    async def format_node(state: ChatState) -> dict[str, Any]:
        messages = state["messages"]

        # 1. 找最后两条消息
        last_ai, last_human = _find_last_messages(messages)
        if not last_ai:
            logger.warning("[FormatNode] 没有找到 AIMessage")
            return {
                "final_response": ChatResponse(
                    text="抱歉，我没听清你说的什么...",
                    emotion="confused",
                ),
                "status": "done",
            }

        # 2. 提取纯文本
        ai_content = _extract_message_content(last_ai) or "抱歉，我没听清你说的什么..."
        user_content = _extract_message_content(last_human)
        pet_status = state.get("pet_status", "") or ""

        # 2.5 兜底：如果整个对话没有 ToolMessage（工具未被调用），
        # 但 AI 回复里却暗示工具已执行（如"弹出来了""已打开"），强制改写。
        # 防止 LLM 在没调工具时谎称已执行。
        ai_content = _guard_unexecuted_tool_claims(messages, ai_content)

        # 3. 构建提取消息
        extraction_messages = _build_extraction_messages(
            user_content=user_content,
            ai_content=ai_content,
            pet_status=pet_status,
        )

        # 4. 尝试两种提取方法
        chat_response = None
        errors = []
        try:
            # 方法 1: function_calling
            chat_response = await _extract_via_function_calling(
                llm, extraction_messages, ai_content
            )
            if chat_response is None:
                errors.append("function_calling: 失败或不支持")

            # 方法 2: JSON 解析
            if chat_response is None:
                chat_response = await _extract_via_json_parse(
                    llm, extraction_messages, ai_content
                )
                if chat_response is None:
                    errors.append("json_parse: 失败")

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
                    text=ai_content or "抱歉，我处理你的消息时遇到了问题...",
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
