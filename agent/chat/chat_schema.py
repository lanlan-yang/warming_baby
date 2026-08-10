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
    
    @field_validator('new_memories', mode='before')
    @classmethod
    def validate_new_memories(cls, v):
        """
        验证 new_memories 字段
        
        LLM 可能返回字符串列表，如 ["用户的名字是小明"]
        需要转换为 MemoryExtract 对象列表
        """
        if v is None:
            return []
        
        result = []
        for item in v:
            if isinstance(item, str):
                # 字符串 -> MemoryExtract
                result.append(MemoryExtract(
                    content=item,
                    memory_type="fact"
                ))
            elif isinstance(item, dict):
                # 字典 -> MemoryExtract
                result.append(MemoryExtract(**item))
            elif isinstance(item, MemoryExtract):
                # 已经是 MemoryExtract
                result.append(item)
        
        return result
    
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
        获取 Format 节点的结构化提取指令。

        用途：
            agent_node 已生成回复文本 → format_node 再独立调用一次 LLM，
            从「AI回复」中判断 emotion，从「用户消息」中提取 new_memories。

        Emotion 描述统一使用模块级 `EMOTION_DESCRIPTIONS` 常量，
        与 System Prompt（prompts.get_role_prompt）共享同一数据源。

        Returns:
            给 Format 节点 LLM 的 System Prompt 内容（emotion 规则 + 记忆提取规则 + 示例）
        """
        # 1. emotion 可选值列表（引用 EMOTION_DESCRIPTIONS，与其他处一致）
        #    format 节点的提取视角：从「AI回复内容」判断 → 描述要对应用场景
        emotion_lines = [
            f"- {emotion.value}: {desc}"
            for emotion, desc in EMOTION_DESCRIPTIONS.items()
        ]

        # 2. eating 的补充说明（format 从 AI 回复提取，需要额外提示"提到食物"）
        eating_extra = (
            "\n判断 eating 的场景：AI回复中提到食物、零食、饮品、瓜子、苹果、奶茶等，"
            "或表现出吃东西的样子"
        )

        # 3. new_memories 规则
        memory_rules = (
            "\nnew_memories 规则：\n"
            "- 只从【用户消息】中提取新信息（如姓名、喜好、习惯）\n"
            "- 绝对不要从 AI 回复中提取\n"
            "- 用户消息里没有的信息不要提取\n"
            "- 如无则返回空数组"
        )

        # 4. 示例
        memory_examples = (
            "\n示例：\n"
            '- 用户消息"我叫小明"，AI回复"小明你好！" → new_memories: ["用户叫小明"]\n'
            '- 用户消息"我喜欢吃苹果"，AI回复"好的！" → new_memories: ["用户喜欢吃苹果"]\n'
            '- 用户消息"你好"，AI回复"你好呀！" → new_memories: [] (无新信息)'
        )

        return (
            "你是一个分析器，需要从给定的内容中提取情绪和可能的用户新信息。\n\n"
            "情绪从【AI回复】中判断，记忆从【用户消息】中提取。\n\n"
            "请按 JSON 格式返回：\n"
            "{\n"
            '    "emotion": "情绪类型",\n'
            '    "new_memories": ["提取的用户信息"]\n'
            "}\n\n"
            "emotion 可选值：\n"
            + "\n".join(emotion_lines)
            + eating_extra
            + memory_rules
            + memory_examples
        )
