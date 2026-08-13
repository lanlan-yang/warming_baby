"""
agent.chat.chat_schema - 聊天模块 Schema

核心数据模型:
- 枚举类: Emotion
- 数据模型: ChatResponse, MemoryExtract
"""
from enum import StrEnum

from pydantic import Field, field_validator

from core.logger import setup_logger
from core.schemas import BaseSchema

logger = setup_logger()


# ============================================================================
# 1. 枚举类
# ============================================================================

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
        FULL: 吃饱了/吃撑了
        TOUCH: 被抚摸/撒娇
        NEUTRAL: 普通/无情绪
        HUNGRY: 饥饿/肚子饿
        BORING: 无聊/发呆
        DOZE_OFF: 犯困/打盹 (体力低, 比 SLEEP 更轻微)
    """
    HAPPY = "happy"
    ANGRY = "angry"
    SAD = "sad"
    CONFUSED = "confused"
    SLEEP = "sleep"
    PLAY = "play"
    EATING = "eating"
    FULL = "full"
    TOUCH = "touch"
    NEUTRAL = "neutral"
    HUNGRY = "hungry"
    BORING = "boring"
    DOZE_OFF = "doze_off"


# ============================================================================
# 1.1 Emotion 场景描述（单一数据源：schema & role prompt 都从此引用）
# ============================================================================

EMOTION_DESCRIPTIONS: dict[Emotion, str] = {
    Emotion.HAPPY: "用户夸奖、问候、说好听的话、感谢、普通开心话题",
    Emotion.PLAY: "用户想玩游戏、提到玩具、邀请玩耍",
    Emotion.SAD: "宠物心情低(<30)或用户难过、生病、告别、心情不好",
    Emotion.ANGRY: "用户生气、批评、威胁、发脾气",
    Emotion.SLEEP: "用户说困了、要睡觉、时间很晚",
    Emotion.EATING: "给宠物投喂食物、零食、水果、饮品，或提到吃的东西（饱食度不高时）",
    Emotion.FULL: "饱食度已高(>90)时被投喂，吃撑了、吃不下了",
    Emotion.TOUCH: "用户抚摸、摸头、抱抱、揉一揉等亲昵动作",
    Emotion.CONFUSED: "不理解用户问题、需要思考、听不懂",
    Emotion.NEUTRAL: "普通对话、回答问题、陈述事实",
    Emotion.HUNGRY: "饱食度低(<30)，饥饿、肚子饿、想求投喂",
    Emotion.BORING: "长时间无互动，无聊、发呆、想找人陪",
    Emotion.DOZE_OFF: "体力低(<20)，犯困、打盹、眼皮重 (比 SLEEP 更轻微)",
}
"""
Emotion 枚举 → 自然语言场景描述。

单一数据源：
- ChatResponse.get_extraction_instruction()（Format 节点提取指令）
- prompts.get_role_prompt()（System Prompt 中的 emotion 规则）
均引用此字典，保证一致，改一处两边同步。
"""


# ============================================================================
# 2. 记忆提取模型 (用于 LLM 返回新记忆)
# ============================================================================

class MemoryExtract(BaseSchema):
    """LLM 从对话中提取的新记忆项"""
    content: str = Field(description="提取的事实/偏好，如'用户叫小明'")
    memory_type: str = Field(description="记忆类型: fact/preference/event/context/skill")
    field: str = Field(
        default="",
        description=(
            "记忆的去重键（字段名），相同 field 的新记忆会替换旧记忆。"
            "命名需稳定、语义化，例如：姓名=name、生日=birthday、本人住址=location、"
            "妈妈住址=mother_location、过敏=allergy；"
            "preference 用喜好对象核心词（如'桃子'/'打篮球'）；skill 用技能名（如'弹吉他'）。"
            "不同主体必须用不同 field 区分。"
        )
    )


class MemoryExtraction(BaseSchema):
    """记忆提取节点的结构化输出"""
    memories: list[MemoryExtract] = Field(
        default_factory=list,
        description="从完整对话中提取的用户信息列表，无则返回空列表"
    )


class EmotionExtraction(BaseSchema):
    """情绪提取节点的结构化输出（format 节点专用）"""
    emotion: str = Field(
        default=Emotion.NEUTRAL,
        description=f"emotion值: {'/'.join(e.value for e in Emotion)}"
    )


def get_memory_extraction_instruction() -> str:
    """
    获取记忆提取节点的提示词。

    与 format 节点的情绪提取解耦，专门从完整对话中提取用户信息，
    理解时间变化、多主体等复杂语义，不依赖关键词模板。
    """
    return (
        "你是一个用户信息提取器。请阅读完整对话，提取所有与用户相关的稳定信息。\n\n"
        "【提取原则】\n"
        "1. 只提取用户主动透露的、长期稳定的个人信息（事实、偏好、技能、关系等）\n"
        "2. 不要提取临时的、一次性的信息（如'今天天气不错'、'我现在有点饿'）\n"
        "3. 理解时间变化：如果用户改变了某信息（如'我以前住成都，现在搬上海'），只提取最新状态\n"
        "4. 区分主体：用户本人、用户的家人/朋友/宠物等是不同主体，分别提取，field 必须不同\n"
        "5. 综合整段对话理解语义，不要套用固定句式模板\n\n"
        "【memory_type 可选值】\n"
        "- fact: 稳定事实（姓名/生日/住址/家庭成员/过敏等）\n"
        "- preference: 喜欢或讨厌的事物\n"
        "- skill: 会/擅长/不会的技能\n"
        "- event: 已发生的事件\n"
        "- context: 上下文信息\n\n"
        "【field 说明（去重键）】\n"
        "- 相同 field 的新记忆会替换旧记忆，所以 field 命名要稳定、语义化\n"
        "- fact 类命名示例：姓名=name、生日=birthday、本人住址=location、妈妈住址=mother_location、过敏=allergy\n"
        "- preference 类：用喜好对象的核心词（如'桃子'、'打篮球'），喜欢和讨厌同一对象 field 相同\n"
        "- skill 类：用技能名（如'弹吉他'、'游泳'、'Python'）\n"
        "- 不同主体的同一属性，field 必须不同（如本人住址=location，妈妈住址=mother_location）\n\n"
        "【输出格式】\n"
        "请严格按 JSON 返回：\n"
        '{"memories": [{"content": "提取的信息", "memory_type": "类型", "field": "字段"}]}\n'
        '没有新信息时返回 {"memories": []}\n\n'
        "【示例】\n"
        '对话："我以前住在成都，现在搬去上海了，我妈妈现在住在北京"\n'
        '输出：{"memories": ['
        '{"content": "用户住在上海", "memory_type": "fact", "field": "location"},'
        '{"content": "用户的妈妈住在北京", "memory_type": "fact", "field": "mother_location"}'
        ']}\n'
        '对话："我喜欢吃桃子"\n'
        '输出：{"memories": [{"content": "用户喜欢吃桃子", "memory_type": "preference", "field": "桃子"}]}\n'
    )


# ============================================================================
# 3. 响应模型 (用于结构化输出)
# ============================================================================

class ChatResponse(BaseSchema):
    """
    聊天响应 - LLM 返回的结构化数据

    这个 Schema 定义了：
    1. LLM 必须返回的数据结构
    2. 给 Format 节点的提取指令（通过 get_extraction_instruction 方法）

    两者放在一起，确保修改字段时提取指令同步更新。

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

    @field_validator('text', mode='before')
    @classmethod
    def validate_text(cls, v):
        """
        验证 text 字段
        
        处理过长的文本，自动截断并添加省略号
        """
        if v is None or not isinstance(v, str):
            return "抱歉，我没听清你说的什么..."
        
        # 如果文本超过 500 字符，截断
        MAX_LENGTH = 500
        if len(v) > MAX_LENGTH:
            # 尝试在句子边界截断
            truncated = v[:MAX_LENGTH]
            last_punct = max(
                truncated.rfind('。'),
                truncated.rfind('！'),
                truncated.rfind('？'),
                truncated.rfind('.'),
                truncated.rfind('!'),
                truncated.rfind('?'),
            )
            if last_punct > MAX_LENGTH * 0.5:  # 至少保留一半
                truncated = v[:last_punct + 1]
            else:
                truncated = v[:MAX_LENGTH - 3] + '...'
            return truncated
        
        return v

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

    @classmethod
    def get_emotion_value_list(cls) -> str:
        """获取 emotion 可选值的斜杠分隔字符串（用于 Schema description 等场景）"""
        return "/".join(e.value for e in Emotion)

    @classmethod
    def get_extraction_instruction(cls) -> str:
        """
        获取 Format 节点的情绪提取指令。

        用途：
            agent_node 已生成回复文本 → format_node 再独立调用一次 LLM，
            从「AI回复」+「宠物状态」中判断 emotion。

        记忆提取已拆分到独立的 memory_extract 节点，format 只负责 emotion。

        Emotion 描述统一使用模块级 `EMOTION_DESCRIPTIONS` 常量，
        与 System Prompt（prompts.get_role_prompt）共享同一数据源。

        Returns:
            给 Format 节点 LLM 的 System Prompt 内容（emotion 规则）
        """
        emotion_lines = [
            f"- {emotion.value}: {desc}"
            for emotion, desc in EMOTION_DESCRIPTIONS.items()
        ]

        eating_extra = (
            "\n判断 eating 的场景：AI回复中提到食物、零食、饮品、瓜子、苹果、奶茶等，"
            "或表现出吃东西的样子"
        )

        return (
            "你是一个情绪分析器，请从AI回复内容和宠物状态中判断情绪。\n\n"
            "请按 JSON 格式返回：\n"
            '{"emotion": "情绪类型"}\n\n'
            "emotion 可选值：\n"
            + "\n".join(emotion_lines)
            + eating_extra
        )
