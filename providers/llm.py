"""
providers.llm - 大模型提供者

基于 LangChain 1.x 的 init_chat_model，按任务类型获取模型。
返回的模型默认带 LLMWrapper (日志 + 异步重试)。

Usage:
    from providers import get_llm, LLMProvider
    from core import ModelTask

    # 推荐: get_llm 返回已包装模型
    llm = get_llm(ModelTask.CHAT)
    response = await llm.ainvoke("你好")

    # 或用 LLMProvider (支持更多参数)
    llm = LLMProvider.get(ModelTask.COMPLEX, temperature=0.5)
    response = await llm.ainvoke("分析代码")
"""
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from core.enums import ModelTask
from core.logger import logger
from providers.llm_wrapper import LLMWrapper
from config import settings, MODEL_REGISTRY


class LLMProvider:
    """
    大模型提供者 - 单例模式

    特点:
    - 按任务类型从 MODEL_REGISTRY 取配置
    - 按 (task, temperature) 缓存实例
    - 默认返回 LLMWrapper (日志 + 异步重试)

    Example:
        llm = LLMProvider.get(ModelTask.CHAT)
        response = await llm.ainvoke("你好")
    """

    # cache_key -> BaseChatModel (raw)
    _cache: dict[str, BaseChatModel] = {}

    @classmethod
    def _resolve_task(cls, task: str | ModelTask) -> ModelTask:
        if isinstance(task, str):
            try:
                return ModelTask(task)
            except ValueError:
                logger.error(
                    f"[LLM] 未知任务类型: '{task}', "
                    f"可用: {[t.value for t in ModelTask]}"
                )
                raise ValueError(
                    f"未知任务类型: '{task}'\n可用任务: {[t.value for t in ModelTask]}"
                )
        return task

    @classmethod
    def _get_task_config(cls, task: ModelTask) -> dict:
        config = MODEL_REGISTRY.get(task)
        if not config:
            logger.error(f"[LLM] 任务 '{task.value}' 未在 MODEL_REGISTRY 中配置")
            raise ValueError(
                f"任务 '{task.value}' 未配置，请在 config.py 补充"
            )
        return config

    @classmethod
    def _build_kwargs(cls, task_config: dict, temperature: float) -> dict:
        if not settings.openai_api_key:
            logger.error("[LLM] API Key 未配置")
            raise ValueError(
                "API Key 未配置! 请在 .env 设置 LLM_API_KEY=sk-xxx"
            )

        kwargs = {
            "model": task_config["model"],
            "model_provider": task_config.get("provider", "openai"),
            "temperature": temperature,
            "max_tokens": settings.llm_max_tokens,
            "timeout": settings.llm_timeout,
            "api_key": settings.openai_api_key,
        }
        base_url = task_config.get("base_url", "")
        if base_url:
            kwargs["base_url"] = base_url

        return kwargs

    @classmethod
    def get(
        cls,
        task: str | ModelTask = ModelTask.CHAT,
        temperature: Optional[float] = None,
        wrap: bool = True,
        max_retries: Optional[int] = None,
    ) -> BaseChatModel:
        """
        获取 LLM 实例 (带缓存)

        Args:
            task: 任务类型 (str 或 ModelTask)
            temperature: 温度 (None 用配置默认值)
            wrap: 是否用 LLMWrapper 包装 (默认 True)
            max_retries: 包装器重试次数 (None 用配置默认值)

        Returns:
            BaseChatModel (已包装, 支持 ainvoke)

        Example:
            llm = LLMProvider.get("chat")                    # 默认包装
            llm = LLMProvider.get("chat", wrap=False)        # 裸模型
            llm = LLMProvider.get("chat", max_retries=5)     # 自定义重试
        """
        task_enum = cls._resolve_task(task)
        temp = temperature if temperature is not None else settings.llm_temperature
        cache_key = f"{task_enum.value}_{temp}"

        if cache_key in cls._cache:
            logger.debug(f"[LLM] 命中缓存: {cache_key}")
            raw = cls._cache[cache_key]
        else:
            task_config = cls._get_task_config(task_enum)
            kwargs = cls._build_kwargs(task_config, temp)
            try:
                raw = init_chat_model(**kwargs)
                cls._cache[cache_key] = raw
                logger.info(
                    f"[LLM] 初始化: task={task_enum.value}, "
                    f"model={task_config['model']}, temp={temp}"
                )
            except Exception as e:
                logger.error(f"[LLM] 初始化失败: {e}")
                raise

        if not wrap:
            return raw
        retries = max_retries or settings.llm_max_retries
        return LLMWrapper(raw, max_retries=retries)

    @classmethod
    def reset(cls) -> None:
        """清空缓存"""
        cls._cache.clear()
        logger.info("[LLM] 缓存已清空")


# ============================================================
# 便捷函数
# ============================================================

def get_llm(
    task: str | ModelTask = ModelTask.CHAT,
    temperature: Optional[float] = None,
) -> BaseChatModel:
    """
    获取已包装的 LLM 实例

    Example:
        from providers import get_llm
        from core import ModelTask

        llm = get_llm(ModelTask.CHAT)
        response = await llm.ainvoke("你好")
    """
    return LLMProvider.get(task, temperature)
