"""
llm_wrapper - LLM 包装器

在 BaseChatModel 之上添加日志、计时和异步重试。

- _generate / _stream: 同步调用，仅记录日志，不重试
- _agenerate / _astream: 异步调用，日志 + 指数退避重试（asyncio.sleep）

Usage:
    from providers.llm import LLMProvider
    from providers.llm_wrapper import LLMWrapper

    llm = LLMWrapper(LLMProvider.get("chat"), max_retries=2)
    response = await llm.ainvoke("你好")
"""
import asyncio
import time
from typing import AsyncIterator, Iterator, Optional

from core.logger import setup_logger
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)

logger = setup_logger()

class LLMWrapper(BaseChatModel):
    """
    LLM 包装器 — 日志 + 计时 + 异步重试

    同步路径 (_generate / _stream): 仅日志，不阻塞
    异步路径 (_agenerate / _astream): 日志 + 指数退避重试
    """

    _wrapped: BaseChatModel
    _max_retries: int

    def __init__(self, llm: BaseChatModel, max_retries: int = 3):
        super().__init__()
        self._wrapped = llm
        self._max_retries = max_retries

    # ---- 必须实现的抽象属性 ----

    @property
    def _llm_type(self) -> str:
        return f"wrapper({self._wrapped._llm_type})"

    @property
    def _identifying_params(self) -> dict:
        return {
            "wrapped_type": self._wrapped._llm_type,
            "max_retries": self._max_retries,
        }

    # ---- 同步生成 (仅日志) ----

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs,
    ) -> ChatResult:
        start = time.perf_counter()
        msg_len = self._count_chars(messages)
        logger.info(f"[LLM] _generate: {len(messages)} 条, {msg_len} 字符")

        try:
            result = self._wrapped._generate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
            logger.info(
                f"[LLM] _generate 完成: {time.perf_counter() - start:.2f}s"
            )
            return result
        except Exception as e:
            logger.error(
                f"[LLM] _generate 失败 ({time.perf_counter() - start:.2f}s): "
                f"{type(e).__name__}: {e}"
            )
            raise

    # ---- 异步生成 (日志 + 指数退避重试) ----

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs,
    ) -> ChatResult:
        start = time.perf_counter()
        msg_len = self._count_chars(messages)
        logger.info(f"[LLM] _agenerate: {len(messages)} 条, {msg_len} 字符")

        last_error = None
        for attempt in range(self._max_retries):
            try:
                result = await self._wrapped._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
                logger.info(
                    f"[LLM] _agenerate 完成: {time.perf_counter() - start:.2f}s"
                )
                return result

            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"[LLM] _agenerate 重试 {attempt + 1}/{self._max_retries}: "
                        f"{type(e).__name__}: {e}, {wait}s 后重试"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"[LLM] _agenerate {self._max_retries} 次全失败: "
                        f"{type(e).__name__}: {e}"
                    )

        raise last_error

    # ---- 同步流式 (仅日志) ----

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs,
    ) -> Iterator[ChatGenerationChunk]:
        start = time.perf_counter()
        logger.info(f"[LLM] _stream: {len(messages)} 条")
        chunk_count = 0

        try:
            for chunk in self._wrapped._stream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                chunk_count += 1
                yield chunk
            logger.info(
                f"[LLM] _stream 完成: {time.perf_counter() - start:.2f}s, "
                f"{chunk_count} chunks"
            )
        except Exception as e:
            logger.error(
                f"[LLM] _stream 失败 ({time.perf_counter() - start:.2f}s): "
                f"{type(e).__name__}: {e}"
            )
            raise

    # ---- 异步流式 (日志 + 退避重试) ----

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs,
    ) -> AsyncIterator[ChatGenerationChunk]:
        start = time.perf_counter()
        logger.info(f"[LLM] _astream: {len(messages)} 条")

        last_error = None
        for attempt in range(self._max_retries):
            try:
                chunk_count = 0
                async for chunk in self._wrapped._astream(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                ):
                    chunk_count += 1
                    yield chunk
                logger.info(
                    f"[LLM] _astream 完成: {time.perf_counter() - start:.2f}s, "
                    f"{chunk_count} chunks"
                )
                return

            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"[LLM] _astream 重试 {attempt + 1}/{self._max_retries}: "
                        f"{type(e).__name__}: {e}, {wait}s 后重试"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"[LLM] _astream {self._max_retries} 次全失败: "
                        f"{type(e).__name__}: {e}"
                    )

        raise last_error

    # ---- 工具 ----

    @staticmethod
    def _count_chars(messages: list[BaseMessage]) -> int:
        return sum(
            len(m.content) if isinstance(m.content, str) else 0 for m in messages
        )

    def __repr__(self) -> str:
        return f"LLMWrapper({self._wrapped}, retries={self._max_retries})"
