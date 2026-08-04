"""
agent/chat/response_extractor.py - 响应提取器

将 LLM 的自然语言输出转换为 ChatResponse 格式。
在 OpenWorker 架构中，LLM 先自由输出（可能经过多轮工具调用），
然后用这个模块做最后的结构化提取。

核心功能：
    1. 提取 emotion：从自然语言判断对应的情绪
    2. 提取 new_memories：识别对话中的用户信息
    3. 组装完整的 ChatResponse

为什么不直接用 LLM 的 tool_calls？
    - tool_calls 是 LLM 用来调用外部工具的，不是输出格式
    - 我们需要的是"最终回复 + 情绪 + 记忆"，这三个是输出属性
    - 用 with_structured_output 做轻量提取，比让 LLM 一次性输出更稳定

Usage:
    extractor = ResponseExtractor(llm)
    chat_response = await extractor.extract(
        llm_content=llm_reply.content,  # 自然语言
        user_input="你好",
    )
"""

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from .chat_schema import ChatResponse, Emotion, MemoryExtract
from core.logger import setup_logger
logger = setup_logger()


class ResponseExtractor:
    """
    LLM 响应提取器

    将 LLM 的自由输出转换为 ChatResponse 格式。
    使用一个轻量的 LLM 调用做结构化提取，速度快（只有几十个 token）。
    """

    # 提取用的 System Prompt
    EXTRACT_SYSTEM_PROMPT = """
你是一个响应格式化器。从 AI 的回复内容中提取以下信息：

1. emotion: 根据 AI 回复的语气选择最匹配的情绪
   - happy: 开心、笑、高兴
   - angry: 生气、不满
   - sad: 难过、委屈
   - confused: 困惑、思考
   - sleep: 困倦、疲惫
   - play: 兴奋、活泼
   - eating: 馋嘴、想吃
   - neutral: 普通、日常

2. new_memories: 从整个对话（用户输入 + AI回复）中提取用户透露的新信息
   - 只提取用户明确说的，不要猜测
   - 类型: fact(事实), preference(喜好), event(事件), context(话题), skill(技能)
   - 没有就返回空列表
"""

    def __init__(self, llm: BaseChatModel):
        """
        初始化提取器

        Args:
            llm: LLM 实例，必须支持 with_structured_output
                 （通常和 ChatEngine 用同一个 LLM）
        """
        self.llm = llm

        # 预构建结构化提取器（绑定一次，复用）
        self._structured_llm = llm.with_structured_output(
            ChatResponse, method="function_calling"
        )

    async def extract(
        self,
        llm_content: str,
        user_input: str,
    ) -> ChatResponse:
        """
        从 LLM 输出中提取 ChatResponse

        Args:
            llm_content: LLM 的自然语言回复内容
            user_input: 用户的原始输入（用于判断记忆）

        Returns:
            ChatResponse: 结构化的聊天响应

        处理流程：
            1. 用 with_structured_output 调 LLM，让它按 ChatResponse 返回
            2. 如果 LLM 返回异常，用 fallback 规则生成
            3. text 字段直接取 llm_content（不依赖 LLM 提取）
        """
        try:
            messages = [
                SystemMessage(content=self.EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=f"用户说: {user_input}\nAI回复: {llm_content}"),
            ]

            # 轻量提取：LLM 只需要输出 JSON 格式的 emotion 和 new_memories
            result = await self._structured_llm.ainvoke(messages)

            # 确保 text 字段使用原始内容（不依赖 LLM 的提取）
            chat_response = ChatResponse(
                text=llm_content,
                emotion=result.emotion,
                new_memories=result.new_memories,
                play_once=self._is_emotion_play_once(result.emotion),
            )

            logger.info(
                f"[ResponseExtractor] 提取完成: emotion={chat_response.emotion}, "
                f"memories={len(chat_response.new_memories)}"
            )
            return chat_response

        except Exception as e:
            logger.error(f"[ResponseExtractor] 结构化提取失败，使用 fallback: {e}")
            return self._fallback(llm_content, user_input)

    def _fallback(
        self,
        llm_content: str,
        user_input: str,
    ) -> ChatResponse:
        """
        Fallback 提取器：不用 LLM，用简单规则

        当 LLM 结构化提取失败时调用，保证总能返回一个 ChatResponse。
        规则很简单：
            - emotion: 关键词匹配
            - new_memories: 返回空（没有 LLM 能力）
        """
        emotion = self._keyword_emotion(llm_content)

        return ChatResponse(
            text=llm_content,
            emotion=emotion,
            new_memories=[],
            play_once=self._is_emotion_play_once(emotion),
        )

    def _keyword_emotion(self, text: str) -> Emotion:
        """
        关键词匹配情绪（Fallback 用）

        匹配规则很简单，覆盖常见情况：
            - 开心: 哈哈、嘻嘻、开心、高兴、😊
            - 难过: 呜呜、难过、伤心、😢
            - 生气: 哼、讨厌、😠
            - 困: 困、睡、😴
            - 馋: 吃、饿、😋
        """
        text_lower = text.lower()

        keywords = {
            Emotion.HAPPY: ["哈哈", "嘻嘻", "开心", "高兴", "😊", "😄"],
            Emotion.SAD: ["呜呜", "难过", "伤心", "😢", "😭"],
            Emotion.ANGRY: ["哼", "讨厌", "😠", "生气"],
            Emotion.SLEEP: ["困", "睡", "😴", "累"],
            Emotion.EATING: ["吃", "饿", "😋", "馋"],
            Emotion.PLAY: ["玩", "游戏", "🎉"],
        }

        for emotion, words in keywords.items():
            if any(word in text_lower for word in words):
                return emotion

        return Emotion.NEUTRAL

    def _is_emotion_play_once(self, emotion: Emotion) -> bool:
        """
        判断动画是否只播放一次

        情绪动画（一次）: happy, angry, sad, play, eating
        状态动画（循环）: neutral, confused, sleep
        """
        play_once_emotions = {
            Emotion.HAPPY,
            Emotion.ANGRY,
            Emotion.SAD,
            Emotion.PLAY,
            Emotion.EATING,
        }
        return emotion in play_once_emotions
