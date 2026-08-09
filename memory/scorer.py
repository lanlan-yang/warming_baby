"""
memory/scorer.py - 记忆重要性评分

使用 LLM 对记忆内容进行重要性评分，用于检索时的加权排序。
"""
import re
from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage

from core.logger import setup_logger
from .types import MemoryType

logger = setup_logger()

# 重要性评分的 System Prompt
IMPORTANCE_PROMPT = """你是一个记忆重要性评估器。请根据记忆内容判断其重要性（0.0-1.0）。

【评分标准】
0.0-0.3: 不重要、易变、可能是随口说的
  - 示例: "今天天气不错"、"我刚才吃了个橘子"、"这个视频很好笑"

0.3-0.6: 一般重要，属于普通对话内容
  - 示例: "我喜欢看科幻电影"、"周末经常去公园"、"正在学英语"

0.6-0.8: 较重要，有持久价值
  - 示例: "我叫小明"、"喜欢吃川菜"、"想成为产品经理"

0.8-1.0: 非常重要，核心身份或关键偏好
  - 示例: "我叫杨程巍"、"我最喜欢的食物是火锅"、"我的生日是1月1日"

【判断维度】
1. 这个信息一个月后还有用吗？
2. 这个信息是用户稳定的特征吗？
3. 用户会因为忘记这个信息而失望吗？
4. 这个信息是用户主动强调的吗？

请直接输出一个数字（0.0-1.0），不要解释。"""

# 预筛规则：命中这些模式的直接用默认分，不调 LLM
_SKIP_LLM_PATTERNS = [
    r'今天|现在|刚才|刚刚|马上|暂时',   # 时间类（瞬时信息）
    r'天气|温度|气温|℃|度',              # 天气类（易变）
    r'好像|可能|似乎|大概|也许',          # 推测类（不可靠）
    r'觉得|感觉|心情',                    # 主观感受（易变）
]

# 明显重要的高分模式：命中直接给高分，不调 LLM
_HIGH_SCORE_PATTERNS = [
    (r'我叫|我的名字|我是.*?我叫', 0.9),      # 姓名
    (r'我的生日|我出生于', 0.95),              # 生日
    (r'我住在|我家在|我在.*?住', 0.85),        # 住址
    (r'我的电话|我的手机|我的微信', 0.9),      # 联系方式
    (r'我.*?过敏|我对.*?过敏', 0.95),         # 过敏（安全信息）
]


def _should_skip_llm(content: str) -> Optional[float]:
    """
    预筛：判断是否可以跳过 LLM 评分

    Returns:
        None:  需要调 LLM
        float: 直接用这个分数，不调 LLM
    """
    # 1. 内容太短，不值得调 LLM
    if len(content) < 4:
        return 0.3

    # 2. 命中低分模式 → 直接返回低分
    for pattern in _SKIP_LLM_PATTERNS:
        if re.search(pattern, content):
            return 0.2

    # 3. 命中高分模式 → 直接返回高分
    for pattern, score in _HIGH_SCORE_PATTERNS:
        if re.search(pattern, content):
            return score

    return None  # 需要调 LLM


def evaluate_importance_sync(
    content: str,
    memory_type: MemoryType,
    llm=None
) -> float:
    """
    使用 LLM 评估记忆的重要性（同步版本）

    流程：
    1. 预筛：明显不重要/重要的直接返回，不调 LLM
    2. LLM 评分：预筛无法判断的才调 LLM

    Args:
        content: 记忆内容
        memory_type: 记忆类型
        llm: LLM 实例，如果为 None 则使用默认

    Returns:
        重要性分数 (0.0-1.0)
    """
    # 1. 预筛
    skip_score = _should_skip_llm(content)
    if skip_score is not None:
        logger.info(f"[MemoryScorer] 预筛命中: '{content[:20]}...' -> {skip_score} (跳过 LLM)")
        return skip_score

    # 2. 调 LLM 评分
    from providers.llm import get_llm

    try:
        if llm is None:
            llm = get_llm(thinking_enabled=False)

        prompt = f"""记忆内容: {content}
记忆类型: {memory_type.value}

参考评分示例:
- "我叫杨程巍" (fact) -> 0.9
- "我的生日是1月1日" (fact) -> 0.95
- "我喜欢打网球" (preference) -> 0.7
- "我讨厌香菜" (preference) -> 0.65
- "昨天去公园" (event) -> 0.4
- "今天天气不错" (context) -> 0.2

请根据 IMPORTANCE_PROMPT 的标准，对上面的记忆内容输出 0.0-1.0 的分数，只输出数字:"""

        response = llm.invoke([
            SystemMessage(content=IMPORTANCE_PROMPT),
            HumanMessage(content=prompt)
        ])

        text = response.content.strip()

        number_match = re.search(r'(\d+\.?\d*)', text)
        if number_match:
            score = float(number_match.group(1))
            score = max(0.0, min(1.0, score))
            logger.debug(f"[MemoryScorer] LLM评分: {content[:20]}... -> {score}")
            return score

        logger.warning(f"[MemoryScorer] 无法解析 LLM 响应: {text[:50]}")
        return _get_default_score(memory_type)

    except Exception as e:
        logger.error(f"[MemoryScorer] LLM 评分失败: {e}")
        return _get_default_score(memory_type)


def _get_default_score(memory_type: MemoryType) -> float:
    """
    获取默认评分（LLM 调用失败时的降级策略）

    Args:
        memory_type: 记忆类型

    Returns:
        默认评分
    """
    # 基于类型的默认评分
    default_scores = {
        MemoryType.FACT: 0.7,        # 事实通常比较重要
        MemoryType.PREFERENCE: 0.6,  # 偏好次之
        MemoryType.SKILL: 0.8,       # 技能很重要
        MemoryType.EVENT: 0.4,       # 事件可能过时
        MemoryType.CONTEXT: 0.5,     # 上下文中等
    }
    
    score = default_scores.get(memory_type, 0.5)
    logger.info(f"[MemoryScorer] 使用默认评分: {memory_type.value} -> {score}")
    return score
