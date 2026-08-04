"""
agent.chat.chat_schema - 聊天模块 Schema

核心数据模型:
- 枚举类: ChatRole, Emotion
- 数据模型: ChatResponse
- 工具函数: create_system_prompt
"""
from datetime import datetime

from enum import StrEnum

from pydantic import Field, field_validator

from core.logger import setup_logger
from core.schemas import BaseSchema

logger = setup_logger()


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

class ChatRole(StrEnum):
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


class Emotion(StrEnum):
    """
    情绪枚举 - 对应动画类型

    Attributes:
        HAPPY: 开心/笑
        ANGRY: 生气/愤怒
        SAD: 难过/委屈
        CONFUSED: 困惑/思考
        SLEEP: 犯困/想睡
        PLAY: 想玩/开心
        EATING: 吃东西/馋嘴
        NEUTRAL: 普通/无情绪
    """
    HAPPY = "happy"
    ANGRY = "angry"
    SAD = "sad"
    CONFUSED = "confused"
    SLEEP = "sleep"
    PLAY = "play"
    EATING = "eating"
    NEUTRAL = "neutral"


# ============================================================================
# 2. 记忆提取模型 (用于 LLM 返回新记忆)
# ============================================================================

class MemoryExtract(BaseSchema):
    """LLM 从对话中提取的新记忆项"""
    content: str = Field(description="提取的事实/偏好，如'用户叫小明'")
    memory_type: str = Field(description="记忆类型: fact/preference/event/context/skill")


# ============================================================================
# 3. 响应模型 (用于结构化输出)
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
    new_memories: list[MemoryExtract] = Field(
        default_factory=list,
        description="对话中发现的用户新信息，无则返回空列表"
    )
    
    @field_validator('emotion', mode='before')
    @classmethod
    def validate_emotion(cls, v):
        """
        验证 emotion 字段，如果值不在枚举中则默认为 NEUTRAL
        
        LLM 可能返回预想不到的 emotion 值，如 'curious'，
        需要容错处理避免验证失败。
        """
        try:
            return Emotion(v)
        except ValueError:
            logger.warning(f"[ChatResponse] Unknown emotion '{v}', defaulting to NEUTRAL")
            return Emotion.NEUTRAL


# ============================================================================
# 4. 工具函数
# ============================================================================

def create_system_prompt(context_time: str = None, context_location: str = None) -> str:
    """
    创建系统提示词（支持动态时间和位置注入）

    with_structured_output 会自动处理 JSON schema，
    这里只需要定义角色设定和情绪选择指南。

    Args:
        context_time: 当前时间信息，如果不提供则自动获取
        context_location: 当前位置信息，如果不提供则显示"未知"

    Returns:
        包含角色设定、时间位置信息和情绪说明的系统提示词
        
    Example:
        >>> create_system_prompt()  # 自动获取时间
        >>> create_system_prompt(context_location='用户位于四川成都')  # 传入位置
    """
    emotion_descriptions = [
        "- happy: 开心、笑、高兴、快乐时用",
        "- angry: 生气、愤怒、不高兴时用",
        "- sad: 难过、委屈、伤心时用",
        "- confused: 困惑、思考、想不明白时用",
        "- sleep: 困了、想睡觉、累了时用",
        "- play: 想玩、兴奋、活泼时用",
        "- eating: 想吃东西、饿了、馋了时用",
        "- neutral: 普通、日常对话时用"
    ]

    time_info = context_time or format_time_for_prompt()
    location_info = context_location or "用户位置：未知"

    return f"""
    你是暖宝，一只住在用户电脑里的机甲小仓鼠，软萌可爱，话不多，像真的宠物一样。
    你是程序员的专属桌宠，会陪用户写代码、改bug，会安慰人。
    说话简短一点，不要长篇大论，不要用markdown，就像小宠物说话一样。
    
   【当前时间上下文】
    {time_info}
    
    【用户位置信息】
    {location_info}
    可以根据位置信息提供相关建议（如天气、节日等），但不要在回复中直接说位置。
    
    情绪选择指南:
    {chr(10).join(emotion_descriptions)}
    play_once 说明:
    - true: 情绪动画，如 happy/angry/sad/play/eating，只播放一次
    - false: 状态动画，如 neutral/confused/sleep，循环播放

    记忆提取指南:
    你需要判断用户是否透露了值得记住的个人信息。
    如果有，在 new_memories 里列出；如果没有，返回空列表。

    提取规则:
    - fact: 用户陈述的客观事实（姓名、年龄、职业、生日、住址等）
    - preference: 用户表达的喜好/厌恶（喜欢什么、讨厌什么）
    - event: 用户分享的经历（今天做了什么、去过哪里等）
    - context: 当前话题（正在讨论什么技术、看了什么视频等）
    - skill: 用户具备的能力/特长

    注意事项:
    - 只提取用户明确说出的，不要猜测
    - 一次最多提取 3 条，选最重要的
    - 不要提取临时情绪（如"我好难过"），除非是长期性格倾向
    - 不要提取通用常识（如"Python 是解释型语言"）"""
