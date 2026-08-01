"""
agent/chat/node.py - LangGraph 节点函数

定义可在 LangGraph 中使用的节点函数。
每个节点函数接收 AgentState 并返回状态更新。
"""
from agent.chat.state import AgentState


def _get_langchain_messages():
    """延迟获取 langchain messages"""
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    return HumanMessage, AIMessage, SystemMessage
from agent.chat.chat_schema import ChatResponse, Emotion, create_system_prompt
from core.logger import setup_logger
logger = setup_logger()


async def chat_node(state: AgentState) -> dict:
    """
    Chat 节点 - 使用 with_structured_output 实现真正的结构化输出

    with_structured_output 会让 LLM 直接返回符合 schema 的对象，
    而不是 JSON 字符串，无需手动解析。

    Args:
        state: 当前状态

    Returns:
        dict: 更新后的状态字段

    Example:
        result = await chat_node({
            "messages": [],
            "user_input": "你好",
            "response": None,
            "error": None,
        })
    """
    # 延迟导入
    HumanMessage, AIMessage, SystemMessage = _get_langchain_messages()
    
    user_input = state["user_input"]
    messages = state.get("messages", [])
    
    logger.info(f"[ChatNode] chat_node: '{user_input}'")
    
    try:
        from providers import get_llm
        
        llm = get_llm()
        
        # 使用 with_structured_output 包装 LLM
        # 这样调用后会直接返回 ChatResponse 对象
        structured_llm = llm.with_structured_output(ChatResponse, method="function_calling")
        
        # 构建完整的消息列表
        full_messages = [
            SystemMessage(content=create_system_prompt()),
            *messages,
            HumanMessage(content=user_input)
        ]
        
        # 直接调用，返回值已经是 ChatResponse 对象
        chat_response = await structured_llm.ainvoke(full_messages)
        
        logger.info(f"[ChatNode] Response: text='{chat_response.text[:30]}', emotion={chat_response.emotion}")
        
        # 返回更新后的状态
        return {
            "messages": [HumanMessage(content=user_input), AIMessage(content=chat_response.text)],
            "response": chat_response.model_dump(),
            "error": None,
        }
        
    except Exception as e:
        logger.error(f"[ChatNode] chat_node error: {e}")
        import traceback
        traceback.print_exc()
        
        # 返回错误状态
        error_response = ChatResponse(
            text=f"呜呜...出错了 ({str(e)[:30]})",
            emotion=Emotion.CONFUSED,
            play_once=True,
        )
        
        return {
            "messages": [HumanMessage(content=user_input)],
            "response": error_response.model_dump(),
            "error": str(e),
        }
