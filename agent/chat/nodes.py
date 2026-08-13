"""
agent/chat/nodes.py - LangGraph 节点定义

所有节点只负责：
    1. 从 State 读取数据
    2. 执行逻辑
    3. 返回要更新的 State 字段

节点列表：
    - agent_node: LLM 决策节点，调用 LLM
    - CustomToolNode: 自定义工具执行节点（仅查询类工具）
    - memory_extract_node: 记忆提取节点，从完整对话中提取用户信息
    - format_node: 格式化节点，从 AI 回复中判断 emotion
    - memory_node: 确定性记忆节点，存储提取的记忆

条件边：
    - route_tools: 判断是继续循环还是结束
"""

import asyncio
import json
import re
from typing import Any, Callable, Awaitable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models import BaseChatModel

from core.logger import setup_logger
from .state import ChatState
from .chat_schema import (
    ChatResponse,
    Emotion,
    MemoryExtract,
    MemoryExtraction,
    EmotionExtraction,
    get_memory_extraction_instruction,
)

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
# 共用辅助函数
# ============================================================================

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


def _build_emotion_extraction_messages(
    ai_content: str,
    pet_status: str = "",
) -> list[BaseMessage]:
    """
    构建 Format 节点提取 emotion 用的消息列表

    结构：
        [SystemMessage(情绪提取指令), HumanMessage(AI回复 + 宠物状态)]
    """
    system_msg = SystemMessage(content=ChatResponse.get_extraction_instruction())

    input_text = f"【AI回复】\n{ai_content}"
    if pet_status:
        input_text += f"\n\n【宠物状态】\n{pet_status}"

    return [system_msg, HumanMessage(content=input_text)]


async def _extract_emotion_via_function_calling(
    llm: BaseChatModel,
    extraction_messages: list[BaseMessage],
    ai_content: str,
) -> ChatResponse | None:
    """
    Emotion 提取方法 1: function_calling 结构化输出

    失败返回 None，成功返回 ChatResponse。
    对 "不支持" 的错误直接跳过，不重试。
    """
    def is_permanent_error(e: Exception) -> bool:
        err_msg = str(e).lower()
        return any(k in err_msg for k in ["does not support", "not supported"])

    try:
        structured_llm = llm.with_structured_output(
            EmotionExtraction, method="function_calling"
        )
        result = await _retry_llm_call(
            lambda: structured_llm.ainvoke(extraction_messages),
            name="FormatNode-Emotion-FC",
            max_retries=1,
        )
        return ChatResponse(
            text=ai_content,
            emotion=result.emotion,
        )
    except Exception as e:
        if is_permanent_error(e):
            logger.info("[FormatNode] function_calling 不支持，跳过")
        return None


async def _extract_emotion_via_json_parse(
    llm: BaseChatModel,
    extraction_messages: list[BaseMessage],
    ai_content: str,
) -> ChatResponse | None:
    """
    Emotion 提取方法 2: 普通 LLM 调用 + JSON 正则解析

    失败返回 None。
    """
    try:
        response = await _retry_llm_call(
            lambda: llm.ainvoke(extraction_messages),
            name="FormatNode-Emotion-Raw",
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


def route_tools(state: ChatState) -> str | list[str]:
    """
    条件边：判断是去执行工具还是并行进入记忆提取+格式化

    逻辑参考 LangChain 官方示例 route_tools：
    - 如果最后一条 AIMessage 有 tool_calls → 去 tools 节点
    - 否则 → fan-out: 并行触发 memory_extract 和 format

    LangGraph fan-out: 返回 list[str] 时，所有节点同时执行
    LangGraph barrier: 多条边指向同一节点时，该节点等待所有上游完成

    Args:
        state: 当前状态

    Returns:
        "tools" 或 ["memory_extract", "format"]
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 5)

    # 检查最大迭代次数
    if iteration >= max_iterations:
        logger.warning(f"[route_tools] 达到最大迭代次数 {max_iterations}")
        return ["memory_extract", "format"]

    # 检查最后一条消息
    if not messages:
        logger.warning("[route_tools] 无消息")
        return ["memory_extract", "format"]

    last_message = messages[-1]

    if hasattr(last_message, "tool_calls") and len(last_message.tool_calls) > 0:
        logger.info(f"[route_tools] 有 {len(last_message.tool_calls)} 个工具调用")
        return "tools"

    logger.info("[route_tools] 无工具调用，并行执行记忆提取和格式化")
    return ["memory_extract", "format"]


def create_memory_extract_node(
    llm: BaseChatModel,
) -> Callable[[ChatState], Awaitable[dict]]:
    """
    创建记忆提取节点

    职责：
        1. 从 state["messages"] 读取完整对话历史
        2. 构建 LLM 消息，让 LLM 从完整对话中提取用户信息
        3. 将提取结果写入 state["extracted_memories"]

    设计原则：
        - 拿到完整对话生命周期内的所有消息，理解上下文
        - 能处理时间变化（"以前住成都，现在搬上海"）、多主体（"我妈妈住北京"）
        - 不依赖关键词模板，由 LLM 理解语义后提取 field
    """

    async def memory_extract_node(state: ChatState) -> dict[str, Any]:
        messages = state["messages"]

        # 构建对话摘要：只保留 HumanMessage 和 AIMessage 的文本内容
        conversation_parts = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                text = _extract_message_content(msg)
                if text:
                    conversation_parts.append(f"用户: {text}")
            elif isinstance(msg, AIMessage):
                text = _extract_message_content(msg)
                if text:
                    conversation_parts.append(f"宠物: {text}")

        if not conversation_parts:
            logger.info("[MemoryExtract] 无对话内容，跳过记忆提取")
            return {"extracted_memories": []}

        conversation_text = "\n".join(conversation_parts)

        system_msg = SystemMessage(content=get_memory_extraction_instruction())
        user_msg = HumanMessage(content=f"【完整对话】\n{conversation_text}")
        extraction_messages = [system_msg, user_msg]

        # 尝试 function_calling
        memories: list[MemoryExtract] = []
        try:
            structured_llm = llm.with_structured_output(
                MemoryExtraction, method="function_calling"
            )
            result = await _retry_llm_call(
                lambda: structured_llm.ainvoke(extraction_messages),
                name="MemoryExtract-FC",
                max_retries=1,
            )
            memories = result.memories
            logger.info(f"[MemoryExtract] 提取完成: {len(memories)} 条记忆")
        except Exception as e:
            err_msg = str(e).lower()
            if "does not support" in err_msg or "not supported" in err_msg:
                logger.info("[MemoryExtract] function_calling 不支持，尝试 JSON 解析")
            else:
                logger.warning(f"[MemoryExtract] function_calling 失败: {e}")

            # fallback: JSON 解析
            try:
                response = await _retry_llm_call(
                    lambda: llm.ainvoke(extraction_messages),
                    name="MemoryExtract-Raw",
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
                raw_memories = json_data.get("memories", [])
                memories = [
                    MemoryExtract(**item) if isinstance(item, dict) else MemoryExtract(content=str(item))
                    for item in raw_memories
                ]
                logger.info(f"[MemoryExtract] JSON 解析完成: {len(memories)} 条记忆")
            except Exception as e2:
                logger.error(f"[MemoryExtract] 所有提取方法失败: {e2}")
                memories = []

        for mem in memories:
            logger.info(
                f"[MemoryExtract] 记忆: [{mem.memory_type}] [{mem.field}] {mem.content}"
            )

        return {"extracted_memories": memories}

    return memory_extract_node


def create_format_node(
    llm: BaseChatModel,
) -> Callable[[ChatState], Awaitable[dict]]:
    """
    创建 Format 节点（闭包形式，绑定 llm）

    职责：
        1. 从 state["messages"] 找最后一条 AIMessage
        2. 用 LLM 从 AI 回复中判断 emotion
        3. 写入 state["final_response"]
        4. 返回 {"final_response": chat_response, "status": "done"}

    记忆提取已拆分到 memory_extract 节点，format 只负责 emotion。

    宠物状态从 state["pet_status"] 读取，由调用方在 run_chat 入口写入。
    """

    async def format_node(state: ChatState) -> dict[str, Any]:
        messages = state["messages"]

        # 1. 找最后一条 AIMessage
        last_ai, _ = _find_last_messages(messages)
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
        pet_status = state.get("pet_status", "") or ""

        # 2.5 兜底：如果整个对话没有 ToolMessage（工具未被调用），
        # 但 AI 回复里却暗示工具已执行（如"弹出来了""已打开"），强制改写。
        ai_content = _guard_unexecuted_tool_claims(messages, ai_content)

        # 3. 构建 emotion 提取消息
        extraction_messages = _build_emotion_extraction_messages(
            ai_content=ai_content,
            pet_status=pet_status,
        )

        # 4. 尝试两种提取方法
        chat_response = None
        errors = []
        try:
            # 方法 1: function_calling
            chat_response = await _extract_emotion_via_function_calling(
                llm, extraction_messages, ai_content
            )
            if chat_response is None:
                errors.append("function_calling: 失败或不支持")

            # 方法 2: JSON 解析
            if chat_response is None:
                chat_response = await _extract_emotion_via_json_parse(
                    llm, extraction_messages, ai_content
                )
                if chat_response is None:
                    errors.append("json_parse: 失败")

            if chat_response is None:
                raise Exception(f"所有方法都失败: {', '.join(errors)}")

            logger.info(f"[FormatNode] emotion 提取完成: {chat_response.emotion}")
            return {
                "final_response": chat_response,
                "status": "done",
            }

        except Exception as e:
            logger.error(f"[FormatNode] emotion 提取失败，使用 fallback: {e}")
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
        1. 从 state["extracted_memories"] 获取记忆提取节点提取的记忆
        2. 对每条记忆进行类型修正和字段提取
        3. 更新 CoreMemoryCache（乐观更新，立即生效）
        4. 同步存储到数据库

    设计原则：
        - 确定性：每次对话结束都会运行，不依赖 LLM 决策
        - 来源安全：memory_extract 节点已从完整对话中提取
    """

    async def memory_node(state: ChatState) -> dict[str, Any]:
        extracted_memories = state.get("extracted_memories", [])
        if not extracted_memories:
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

            for mem in extracted_memories:
                content = mem.content
                mtype = type_map.get(mem.memory_type, MemoryType.FACT)

                # 1. 类型修正 (LLM 已提取类型，normalizer 作确定性兜底)
                corrected_type = normalizer.correct_type(content, mtype)
                if corrected_type != mtype:
                    logger.info(
                        f"[MemoryNode] 类型修正: [{mtype.value}] -> [{corrected_type.value}] "
                        f"内容: {content}"
                    )

                # 2. 字段提取 (优先用 LLM 提取的 field，normalizer 作 fallback)
                field = mem.field if mem.field else normalizer.extract_field(content, corrected_type)

                # 3. 乐观更新缓存（立即生效，下次对话即可使用）
                cache.update(corrected_type.value, field, content)

                # 4. 同步存储（等待完成，确保不丢失）
                metadata = {"field": field}
                logger.info(
                    f"[MemoryNode] 记忆存储中: [{corrected_type.value}] [{field}] {content}"
                )
                await asyncio.to_thread(
                    manager.smart_add_memory,
                    content, corrected_type, metadata
                )
                logger.info(
                    f"[MemoryNode] 记忆存储完成: [{corrected_type.value}] [{field}] {content}"
                )

        except Exception as e:
            logger.error(f"[MemoryNode] 记忆存储异常: {e}")

        return {}

    return memory_node
