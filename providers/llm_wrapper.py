"""
llm_wrapper - LLM 包装器

在 BaseChatModel 之上添加日志、计时和异步重试。

- _generate / _stream: 同步调用，仅记录日志，不重试
- _agenerate / _astream: 异步调用，日志 + 指数退避重试（asyncio.sleep）

注意: 不继承 BaseChatModel，而是包装底层 LLM，避免启动时加载 langchain
"""
import asyncio
import time
from typing import Optional

from core.logger import setup_logger

logger = setup_logger()


class LLMWrapper:
    """
    LLM 包装器 - 日志 + 计时 + 异步重试
    
    采用组合模式而非继承，避免启动时加载 langchain 库
    
    代理的方法：
    - ainvoke / invoke: 标准调用接口
    - _agenerate / _generate: 内部实现
    - _astream / _stream: 流式调用
    - with_structured_output: 结构化输出
    """

    def __init__(self, llm, max_retries: int = 3):
        self._wrapped = llm
        self._max_retries = max_retries

    @property
    def _llm_type(self) -> str:
        return f"wrapper({self._wrapped._llm_type})"

    @property
    def _identifying_params(self) -> dict:
        return {
            "wrapped_type": self._wrapped._llm_type,
            "max_retries": self._max_retries,
        }

    async def ainvoke(self, input, **kwargs):
        """异步调用 - 带重试"""
        from langchain_core.messages import HumanMessage
        
        start = time.perf_counter()
        if isinstance(input, str):
            messages = [HumanMessage(content=input)]
        else:
            messages = input
        
        logger.info(f"[LLM] ainvoke: 输入类型={type(input).__name__}")
        
        last_error = None
        for attempt in range(self._max_retries):
            try:
                result = await self._wrapped.ainvoke(input, **kwargs)
                logger.info(f"[LLM] ainvoke 完成: {time.perf_counter() - start:.2f}s")
                return result
            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"[LLM] ainvoke 重试 {attempt + 1}/{self._max_retries}: "
                        f"{type(e).__name__}: {e}, {wait}s 后重试"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"[LLM] ainvoke {self._max_retries} 次全失败: "
                        f"{type(e).__name__}: {e}"
                    )
        
        raise last_error

    def invoke(self, input, **kwargs):
        """同步调用"""
        start = time.perf_counter()
        logger.info(f"[LLM] invoke: 输入类型={type(input).__name__}")
        
        try:
            result = self._wrapped.invoke(input, **kwargs)
            logger.info(f"[LLM] invoke 完成: {time.perf_counter() - start:.2f}s")
            return result
        except Exception as e:
            logger.error(
                f"[LLM] invoke 失败 ({time.perf_counter() - start:.2f}s): "
                f"{type(e).__name__}: {e}"
            )
            raise

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """同步生成 - 仅记录日志"""
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

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        """异步生成 - 日志 + 指数退避重试"""
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

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        """同步流式 - 仅记录日志"""
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

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        """异步流式 - 日志 + 退避重试"""
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

    def with_structured_output(self, schema, **kwargs):
        """
        委托给底层 LLM 的 with_structured_output 方法
        
        Args:
            schema: Pydantic schema 或 TypedDict
            **kwargs: 传递给底层 LLM 的参数
            
        Returns:
            Runnable: 包装后的结构化输出接口
        """
        if hasattr(self._wrapped, 'with_structured_output'):
            logger.debug(f"[LLM] with_structured_output: schema={schema.__name__ if hasattr(schema, '__name__') else schema}")
            return self._wrapped.with_structured_output(schema, **kwargs)
        else:
            raise NotImplementedError(
                f"Underlying LLM {type(self._wrapped).__name__} does not support with_structured_output"
            )

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        """
        委托给底层 LLM 的 bind_tools 方法
        
        将工具绑定到 LLM，使 LLM 能够在调用时使用这些工具。
        
        Args:
            tools: 工具列表，可以是 BaseTool 实例或 JSON Schema
            tool_choice: 工具选择策略 ('auto', 'required', 'none')
            **kwargs: 传递给底层 LLM 的参数
            
        Returns:
            Runnable: 绑定工具后的 LLM 接口
        """
        if hasattr(self._wrapped, 'bind_tools'):
            tool_names = self._extract_tool_names(tools)
            logger.debug(f"[LLM] bind_tools: tools={tool_names}, tool_choice={tool_choice}")
            return self._wrapped.bind_tools(tools, tool_choice=tool_choice, **kwargs)
        else:
            raise NotImplementedError(
                f"Underlying LLM {type(self._wrapped).__name__} does not support bind_tools"
            )
    
    @staticmethod
    def _extract_tool_names(tools) -> list:
        """从工具列表中提取工具名称（用于日志）"""
        names = []
        for t in tools:
            if hasattr(t, 'name'):
                # BaseTool 对象
                names.append(t.name)
            elif isinstance(t, dict):
                # JSON Schema 格式
                names.append(t.get('function', {}).get('name', 'unknown'))
            else:
                # 其他格式，转字符串
                names.append(str(t))
        return names

    @staticmethod
    def _count_chars(messages) -> int:
        """计算消息中的字符数"""
        return sum(
            len(m.content) if isinstance(m.content, str) else 0 for m in messages
        )

    def __repr__(self) -> str:
        return f"LLMWrapper({self._wrapped}, retries={self._max_retries})"
