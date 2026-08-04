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

    这个 Schema 定义了：
    1. LLM 必须返回的数据结构
    2. 给 LLM 的生成指令（通过 get_generation_instruction 方法）

    两者放在一起，确保修改字段时生成指令同步更新。

    Attributes:
        text: LLM 生成的回复文本
        emotion: 对应的情绪 (用于动画)
        play_once: 是否单次播放动画
        new_memories: 从对话中提取的新记忆

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
    
    @classmethod
    def get_generation_instruction(cls) -> str:
        """
        获取给 LLM 的生成指令
        
        这个方法会根据 Emotion 枚举自动生成说明，
        确保 Schema 字段和生成指令保持同步。
        """
        # 构建 emotion 说明
        emotion_descriptions = {
            Emotion.HAPPY: "用户夸奖、问候、说好听的话、感谢、普通开心话题",
            Emotion.PLAY: "用户想玩游戏、提到玩具、邀请玩耍",
            Emotion.SAD: "用户难过、生病、告别、心情不好",
            Emotion.ANGRY: "用户生气、批评、威胁、发脾气",
            Emotion.SLEEP: "用户说困了、要睡觉、时间很晚",
            Emotion.EATING: "给宠物投喂食物、零食、水果、饮品，或提到吃的东西",
            Emotion.CONFUSED: "不理解用户问题、需要思考、听不懂",
            Emotion.NEUTRAL: "普通对话、回答问题、陈述事实",
        }
        
        emotion_lines = []
        for emotion, desc in emotion_descriptions.items():
            emotion_lines.append(f"  - {emotion.value}: {desc}")

        # 构建示例 - 覆盖更多场景帮助 LLM 准确判断
        examples = [
            # HAPPY 场景
            ("用户说'你好呀'", "happy"),
            ("用户说'你真可爱'", "happy"),
            # PLAY 场景
            ("用户说'我们玩游戏吧'", "play"),
            ("用户说'想出去玩吗'", "play"),
            # EATING 场景
            ("用户说'给你瓜子吃'", "eating"),
            ("用户说'来吃苹果'", "eating"),
            ("用户说'请你喝奶茶'", "eating"),
            # SAD 场景
            ("用户说'我今天好累'", "sad"),
            ("用户说'别离开我'", "sad"),
            # ANGRY 场景
            ("用户说'你怎么这么笨'", "angry"),
            # SLEEP 场景
            ("用户说'我困了，晚安'", "sleep"),
            # CONFUSED 场景
            ("用户问了一个复杂的技术问题，你不懂", "confused"),
            # NEUTRAL 场景
            ("用户说'帮我查天气'", "neutral"),
            ("用户说'今天星期几'", "neutral"),
        ]
        example_lines = [f"  - {input} → emotion: {output}" for input, output in examples]
        
        return (
            "你现在需要根据对话历史，生成最终的回复内容。\n\n"
            "请严格按照以下 JSON 格式输出，不要添加其他内容：\n"
            "```json\n"
            "{\n"
            '  "text": "你的回复内容",\n'
            '  "emotion": "emotion_value",\n'
            '  "play_once": true,\n'
            '  "new_memories": []\n'
            "}\n"
            "```\n\n"
            "emotion 值选择指南：\n"
            + "\n".join(emotion_lines) +
            "\n\n示例：\n"
            + "\n".join(example_lines) +
            "\n\n"
            "play_once: 单次动作用 true，持续状态用 false\n"
            "new_memories: 记住用户提到的重要信息，没有则为空数组\n\n"
            "重要：\n"
            "1. 只输出 JSON，不要其他内容\n"
            "2. text 要短，像小宠物说话\n"
            "3. emotion 要准确！"
        )
