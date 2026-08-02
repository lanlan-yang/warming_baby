"""
agent/chat/nodes/intent.py - Intent 节点

职责：判断是否需要查询用户记忆。
包含两关卡机制：关键词快速匹配 + LLM 兜底。
"""
from pydantic import BaseModel

from agent.chat.state import AgentState
from core.logger import setup_logger

logger = setup_logger()


class IntentResult(BaseModel):
    """LLM 返回的意图判断结果"""
    need_memory: bool


def _quick_intent_check(user_input: str) -> bool:
    """快速意图判断：纯关键词匹配，0ms"""
    # 任务关键词 → 不查
    skip_keywords = ["写", "解释", "什么是", "怎么", "如何", "帮我", "def ", "import ",
                     "代码", "报错", "bug", "错误", "调试", "实现"]
    if any(kw in user_input for kw in skip_keywords):
        return False
    
    # 记忆关键词 → 查
    # 覆盖：名字、身体属性、年龄生日、偏好、过去行为
    memory_keywords = [
        # 名字相关
        "我叫", "我的名字", "我是谁", "你知道我", "认识我",
        # 身体属性
        "身高", "体重", "多高", "多重",
        # 年龄生日
        "年龄", "生日", "多少岁", "多大", "几岁",
        # 偏好
        "我喜欢", "我爱吃", "我讨厌", "我不喜欢",
        # 技能能力
        "我会", "我能",
        # 过去行为
        "我之前", "我以前", "上次", "之前说",
        # 记忆唤醒
        "记得我", "记得你", "还记得", "记不记得",
    ]
    if any(kw in user_input for kw in memory_keywords):
        return True
    
    # 短消息（< 5字）如果没有关键词，默认不查
    # 避免 "你好"、"谢谢" 这类短句触发向量搜索
    if len(user_input.strip()) < 5:
        return False
    
    # 默认不查（避免过多调用）
    return False


async def _llm_intent_check(user_input: str) -> bool:
    """
    LLM 意图判断：判断用户是否在询问关于自己的信息

    Args:
        user_input: 用户输入的文本

    Returns:
        bool: True 表示需要查记忆
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    from providers import get_llm

    llm = get_llm(temperature=0)
    structured_llm = llm.with_structured_output(IntentResult, method="function_calling")

    prompt = SystemMessage(content="""
        你是一个意图识别助手。请判断用户的问题是否在询问"关于他们自己的信息"（如姓名、年龄、身高、喜好、过去说过的话等）。
        判断标准：
        - True: 用户在询问自己的个人信息、喜好、历史记录等
        - False: 其他任何情况（问候、闲聊、任务请求、无关问题等）
        示例：
        用户: 我叫什么名字? -> True
        用户: 你好 -> False
        用户: 帮我写代码 -> False
        用户: 我之前说过什么? -> True
        用户: 我喜欢吃什么? -> True
        用户: 今天天气怎么样? -> False""")

    result = await structured_llm.ainvoke([prompt, HumanMessage(content=user_input)])
    return result.need_memory


async def intent_node(state: AgentState) -> dict:
    """
    意图识别节点：判断是否需要查询用户记忆

    逻辑（两关卡）：
    1. 第一关：关键词快速匹配（0ms）- 精确命中直接返回
    2. 第二关：LLM 判断（~300ms）- 兜底处理模糊意图

    Args:
        state: 当前状态

    Returns:
        {"need_memory": bool}
    """
    user_input = state["user_input"]

    # 第一关：快速关键词判断
    quick_result = _quick_intent_check(user_input)
    logger.info(f"[IntentNode] quick check: need_memory={quick_result}, input='{user_input[:30]}'")

    if quick_result:
        return {"need_memory": True}

    # 第二关：LLM 兜底判断（处理模糊意图）
    try:
        llm_result = await _llm_intent_check(user_input)
        logger.info(f"[IntentNode] llm check: need_memory={llm_result}, input='{user_input[:30]}'")
        return {"need_memory": llm_result}
    except Exception as e:
        logger.warning(f"[IntentNode] llm check failed: {e}, fallback to False")
        return {"need_memory": False}
