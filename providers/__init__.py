"""
providers - LLM Provider 模块

所有操作走协程 (async / await)。

Usage:
    from providers import get_llm, LLMProvider
    from core import ModelTask

    llm = get_llm(ModelTask.CHAT)
    response = await llm.ainvoke("你好")
"""
from .llm import LLMProvider, get_llm

__all__ = ["LLMProvider", "get_llm"]
