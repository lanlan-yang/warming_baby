"""
LLM Agent — 通过 EventBus 与宠物通信
流程: USER_MESSAGE → call LLM → THINKING → RESPONSE → 宠物动画+气泡
"""
import threading

from core import event_bus, EventCategory, AgentEvent
from config import settings
from core.logger import setup_logger


logger = setup_logger()


class LLMAgent:
    """订阅 USER_MESSAGE，调用大模型，发布 RESPONSE 驱动宠物"""

    def __init__(self):
        self._enabled = bool(settings.deepseek_api_key)
        self._client = None

        if self._enabled:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url,
                )
                logger.info("[LLM] DeepSeek client initialized")
            except Exception as e:
                logger.error(f"[LLM] Failed to init client: {e}")
                self._enabled = False
        else:
            logger.info("[LLM] No API key configured, running in mock mode")

        event_bus.subscribe(EventCategory.AGENT, AgentEvent.USER_MESSAGE, self._on_user_message)

    def _on_user_message(self, message: str):
        """收到用户消息，异步调用 LLM"""
        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)
        threading.Thread(target=self._call_llm, args=(message,), daemon=True).start()

    def _call_llm(self, message: str):
        """调用大模型，无 API key 时回退到 mock"""
        if self._enabled and self._client:
            try:
                resp = self._client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": message}],
                )
                text = resp.choices[0].message.content or ""
                event_bus.publish(
                    EventCategory.AGENT, AgentEvent.RESPONSE,
                    response={"text": text, "emotion": "happy", "play_once": True},
                )
                return
            except Exception as e:
                logger.error(f"[LLM] API error: {e}")
                event_bus.publish(
                    EventCategory.AGENT, AgentEvent.RESPONSE,
                    response={"text": f"API错误: {e}", "emotion": "idle", "play_once": True},
                )
                return

        # Mock 模式（无 API key 或 API 失败）
        mock_replies = [
            "好的，我来帮你~",
            "嗯嗯，我明白了",
            "让我想想...",
            "这个有点难哦",
            "没问题！",
        ]
        reply = mock_replies[hash(message) % len(mock_replies)]
        event_bus.publish(
            EventCategory.AGENT, AgentEvent.RESPONSE,
            response={"text": reply, "emotion": "happy", "play_once": True},
        )
