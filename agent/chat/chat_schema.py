"""
agent.chat.chat_schema - 聊天模块 Schema

核心数据模型:
- 枚举类: ChatRole, Emotion
- 数据模型: ChatResponse
- 工具函数: create_system_prompt
"""
from datetime import datetime

from enum import Enum

from pydantic import Field

from core.schemas import BaseSchema


def get_current_time_info() -> dict:
    """
    获取当前时间的基础信息
    
    LLM 本身就有日期/节日知识，不需要我们重复告诉它。
    只需要给它最基础的时间信息即可。
    
    Returns:
        包含日期、时间、星期的简洁字典
    """
    now = datetime.now()
    weekday_names = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
    
    # 判断时段（简单分段）
    hour = now.hour
    if 5 <= hour < 12:
        period = '早上'
    elif 12 <= hour < 14:
        period = '中午'
    elif 14 <= hour < 18:
        period = '下午'
    elif 18 <= hour < 22:
        period = '晚上'
    else:
        period = '深夜'
    
    return {
        'date': f'{now.year}年{now.month}月{now.day}日',
        'time': now.strftime('%H:%M'),
        'weekday': weekday_names[now.weekday()],
        'period': period,
    }


def format_time_for_prompt() -> str:
    """
    格式化当前时间为 LLM 易读的文本
    
    简洁原则：LLM 有足够的知识理解日期含义，
    只需要给它基础时间信息即可。
    
    Returns:
        简洁的时间描述
        
    Example:
        >>> format_time_for_prompt()
        '当前：2024年1月15日 星期一 下午 14:30'
    """
    info = get_current_time_info()
    
    return f"当前：{info['date']} {info['weekday']} {info['time']} ({info['period']})"



# ============================================================================
# 1. 枚举类
# ============================================================================

class ChatRole(str, Enum):
    """
    聊天角色枚举 (为未来扩展保留)

    Attributes:
        USER: 用户消息
        ASSISTANT: AI 助手消息
        SYSTEM: 系统消息
        TOOL: 工具调用结果
    """
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Emotion(str, Enum):
    """
    情绪枚举 - 对应动画类型

    Attributes:
        HAPPY: 开心/笑
        ANGRY: 生气/愤怒
        SAD: 难过/委屈
        CONFUSED: 困惑/思考
        SLEEP: 犯困/想睡
        PLAY: 想玩/开心
        NEUTRAL: 普通/无情绪
    """
    HAPPY = "happy"
    ANGRY = "angry"
    SAD = "sad"
    CONFUSED = "confused"
    SLEEP = "sleep"
    PLAY = "play"
    NEUTRAL = "neutral"


# ============================================================================
# 2. 响应模型 (用于结构化输出)
# ============================================================================

class ChatResponse(BaseSchema):
    """
    聊天响应 - LLM 返回的结构化数据

    这个 Schema 定义了 LLM 必须返回的结构，
    配合 with_structured_output 实现真正的类型安全。

    Attributes:
        text: LLM 生成的回复文本
        emotion: 对应的情绪 (用于动画)
        play_once: 是否单次播放动画

    Example:
        response = ChatResponse(
            text="你好呀~",
            emotion=Emotion.HAPPY,
            play_once=True
        )
        print(response.emotion)  # "happy"
    """
    text: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="回复的内容，简短自然，像小宠物说话"
    )
    emotion: Emotion = Field(
        default=Emotion.NEUTRAL,
        description="根据回复内容选择的情绪"
    )
    play_once: bool = Field(
        default=True,
        description="动画是否单次播放。情绪动画(true)，状态动画(false)"
    )


# ============================================================================
# 3. 工具函数
# ============================================================================

def create_system_prompt(context_time: str = None) -> str:
    """
    创建系统提示词（支持动态时间注入）

    with_structured_output 会自动处理 JSON schema，
    这里只需要定义角色设定和情绪选择指南。

    Args:
        context_time: 当前时间信息，如果不提供则自动获取

    Returns:
        包含角色设定、时间信息和情绪说明的系统提示词
        
    Example:
        >>> create_system_prompt()  # 自动获取时间
        >>> create_system_prompt('当前时间：...')  # 传入特定时间
    """
    emotion_descriptions = [
        f"- {e.value}: {e.name.lower()}"
        for e in Emotion
    ]

    # 获取或使用传入的时间信息
    time_info = context_time or format_time_for_prompt()

    return f"""你是暖宝，一只住在用户电脑里的机甲小仓鼠，软萌可爱，话不多，像真的宠物一样。
你是程序员的专属桌宠，会陪用户写代码、改bug，会安慰人。
说话简短一点，不要长篇大论，不要用markdown，就像小宠物说话一样。

【当前时间上下文】
{time_info}

情绪选择指南:
{chr(10).join(emotion_descriptions)}

play_once 说明:
- true: 情绪动画，如 happy/angry/sad/play，只播放一次
- false: 状态动画，如 neutral/confused/sleep，循环播放"""
