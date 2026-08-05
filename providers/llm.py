"""
providers.llm - 大模型提供者

基于 LangChain init_chat_model 创建 LLM，返回 BaseChatModel。
使用 LangChain 原生 with_retry() 添加重试功能。

Usage:
    from providers import get_llm
    from core.enums import ModelTask

    llm = get_llm(ModelTask.CHAT)
    response = await llm.ainvoke("你好")

    # 绑定工具
    llm_with_tools = llm.bind_tools([tool1, tool2])

    # 结构化输出
    structured_llm = llm.with_structured_output(Schema)
"""
from typing import Optional, TYPE_CHECKING

from core.enums import ModelTask
from core.logger import logger
from settings import settings, MODEL_REGISTRY, LLMConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def _lazy_import():
    """延迟导入 - 避免启动时加载 langchain"""
    from langchain.chat_models import init_chat_model
    from langchain_core.language_models import BaseChatModel
    return init_chat_model, BaseChatModel


class LLMProvider:
    """
    大模型提供者 - 单例模式

    特点:
    - 按任务类型从 MODEL_REGISTRY 取配置
    - 按 (task, temperature, thinking) 缓存实例
    - 支持动态控制思考模式
    
    使用示例:
        # 使用默认配置
        llm = LLMProvider.get(ModelTask.CHAT)
        
        # 强制禁用思考
        llm = LLMProvider.get(ModelTask.CHAT, thinking_enabled=False)
        
        # 强制启用思考
        llm = LLMProvider.get(ModelTask.CHAT, thinking_enabled=True)

    Example:
        llm = LLMProvider.get(ModelTask.CHAT)
        response = await llm.ainvoke("你好")
    """

    _cache: dict[str, "BaseChatModel"] = {}

    @classmethod
    def _resolve_task(cls, task: str | ModelTask) -> ModelTask:
        """解析任务类型"""
        if isinstance(task, str):
            try:
                return ModelTask(task)
            except ValueError:
                raise ValueError(
                    f"未知任务类型: '{task}'\n"
                    f"可用任务: {[t.value for t in ModelTask]}"
                )
        return task

    @classmethod
    def _get_task_config(cls, task_enum: ModelTask) -> dict:
        """
        获取任务配置 - 优先从用户配置读取，回退到 MODEL_REGISTRY
        
        Args:
            task_enum: 任务枚举
            
        Returns:
            dict: 任务配置 (provider, model, base_url, llm_config)
        """
        # 1. 尝试从用户配置读取
        try:
            from config import config_manager
            config_manager.load()
            user_config = config_manager.get(f"llm.models.{task_enum.value}")
            
            if user_config and user_config.get("model"):
                logger.debug(f"[LLM] 使用用户配置: {task_enum.value}")
                return user_config
        except Exception as e:
            logger.debug(f"[LLM] 用户配置读取失败: {e}")
        
        # 2. 回退到 MODEL_REGISTRY
        default_config = MODEL_REGISTRY.get(task_enum)
        if default_config:
            logger.debug(f"[LLM] 使用默认配置: {task_enum.value}")
            return default_config
        
        raise ValueError(f"任务 '{task_enum.value}' 未配置")

    @classmethod
    def _get_api_key(cls) -> str:
        """
        获取 API Key - 优先从安全存储读取，回退到环境变量
        
        Returns:
            str: API Key
        """
        # 1. 尝试从安全存储读取
        try:
            from config import secure_storage
            api_key = secure_storage.load_api_key()
            if api_key:
                return api_key
        except Exception:
            pass
        
        # 2. 回退到 settings (从环境变量读取)
        return settings.openai_api_key

    @classmethod
    def _resolve_llm_config(
        cls, 
        task_config: dict, 
        thinking_enabled: Optional[bool] = None
    ) -> Optional[LLMConfig]:
        """
        解析 LLM 配置 - 根据参数覆盖默认配置
        
        Args:
            task_config: 任务配置 (包含 llm_config)
            thinking_enabled: 是否启用思考模式 (None 用默认)
            
        Returns:
            Optional[LLMConfig]: 最终的 LLM 配置
        """
        # 如果指定了 thinking_enabled，创建新配置
        if thinking_enabled is not None:
            return LLMConfig(thinking_enabled=thinking_enabled)
        
        # 否则返回默认配置
        default_llm_config = task_config.get("llm_config")
        return default_llm_config

    @classmethod
    def get(
        cls, 
        task: str | ModelTask = ModelTask.CHAT, 
        temperature: Optional[float] = None,
        thinking_enabled: Optional[bool] = None,
    ) -> "BaseChatModel":
        """
        获取 LLM 实例（带缓存和重试）

        Args:
            task: 任务类型
            temperature: 温度（None 用默认值）
            thinking_enabled: 是否启用思考模式
                - None: 使用配置中的默认值
                - True: 强制启用思考模式
                - False: 强制禁用思考模式

        Returns:
            BaseChatModel（带 with_retry）

        Example:
            # 使用默认配置
            llm = get_llm(ModelTask.CHAT)
            
            # 强制禁用思考
            llm = get_llm(ModelTask.CHAT, thinking_enabled=False)
            
            # 强制启用思考
            llm = get_llm(ModelTask.CHAT, thinking_enabled=True)
            
            response = await llm.ainvoke("你好")
        """
        task_enum = cls._resolve_task(task)
        temp = temperature if temperature is not None else settings.llm_temperature
        
        # 缓存 key 包含 thinking_enabled
        thinking_str = f"thinking_{thinking_enabled}" if thinking_enabled is not None else "thinking_default"
        cache_key = f"{task_enum.value}_{temp}_{thinking_str}"

        if cache_key in cls._cache:
            return cls._cache[cache_key]

        # 获取配置 (优先用户配置)
        task_config = cls._get_task_config(task_enum)

        # 获取 API Key (优先安全存储)
        api_key = cls._get_api_key()
        if not api_key:
            raise ValueError("API Key 未配置，请在设置中添加或设置 LLM_API_KEY 环境变量")

        # 解析 LLM 配置
        llm_config = cls._resolve_llm_config(task_config, thinking_enabled)
        extra_body = llm_config.get_extra_body() if llm_config else None

        # provider 映射
        provider_map = {
            "deepseek": "openai",
            "openai": "openai",
            "qwen": "openai",
            "custom": "openai",
        }
        user_provider = task_config.get("provider", "openai")
        actual_provider = provider_map.get(user_provider, "openai")

        kwargs = {
            "model": task_config["model"],
            "model_provider": actual_provider,
            "temperature": temp,
            "max_tokens": settings.llm_max_tokens,
            "timeout": settings.llm_timeout,
            "api_key": api_key,
        }

        base_url = task_config.get("base_url")
        if base_url:
            kwargs["base_url"] = base_url

        # 添加额外参数 (如思考模式)
        if extra_body:
            kwargs["extra_body"] = extra_body

        # 创建模型（原始 BaseChatModel，保留所有方法）
        init_chat_model, _ = _lazy_import()
        llm = init_chat_model(**kwargs)

        cls._cache[cache_key] = llm
        
        # 构建日志
        thinking_info = f", thinking={thinking_enabled}" if thinking_enabled is not None else ""
        logger.info(
            f"[LLM] 初始化: task={task_enum.value}, "
            f"model={task_config['model']}, temp={temp}, "
            f"provider={user_provider}{thinking_info}"
        )

        return llm

    @classmethod
    def reset(cls) -> None:
        """清空缓存"""
        cls._cache.clear()
        logger.info("[LLM] 缓存已清空")


def get_llm(
    task: str | ModelTask = ModelTask.CHAT, 
    temperature: Optional[float] = None,
    thinking_enabled: Optional[bool] = None,
) -> "BaseChatModel":
    """
    获取 LLM 实例（便捷函数）

    Args:
        task: 任务类型
        temperature: 温度
        thinking_enabled: 是否启用思考模式
            - None: 使用配置中的默认值
            - True: 强制启用思考模式
            - False: 强制禁用思考模式

    Returns:
        BaseChatModel（带重试）

    Example:
        from providers import get_llm
        
        # 使用默认配置
        llm = get_llm(ModelTask.CHAT)
        
        # 强制禁用思考
        llm = get_llm(ModelTask.CHAT, thinking_enabled=False)
        
        # 强制启用思考
        llm = get_llm(ModelTask.CHAT, thinking_enabled=True)
    """
    return LLMProvider.get(task, temperature, thinking_enabled)
