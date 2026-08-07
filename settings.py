"""
config.py - 配置入口文件

此文件定义了 Pydantic 配置模型，并作为旧配置系统的入口。
新的配置系统在 config/ 目录下，提供更灵活的配置管理。

使用方式:
    # 旧方式 (向后兼容)
    from config import settings
    api_key = settings.openai_api_key

    # 新方式 (推荐)
    from config import config_manager
    config_manager.load()
    api_key = config_manager.get("llm.api_key")
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel, Field, AliasChoices
from core.enums import ModelTask

from pathlib import Path
from core.logger import logger

# 项目根目录 (config.py 所在目录)
PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"


class PetConfig(BaseModel):
    """
    宠物通用配置

    Note:
    动画相关配置 (时长、文件路径、别名) 已迁移至 core.animations.AnimationRegistry
    """
    display_height: int = 120          # 显示高度
    move_speed: int = 2            # 水平移动速度
    move_y_speed: int = 1              # 垂直移动速度
    drag_threshold: int = 5            # 拖拽判定阈值（像素）
    walking_dir_change_prob: float = 0.005   # 方向改变概率（水平）
    walking_y_dir_change_prob: float = 0.003 # 方向改变概率（垂直）
    
    # 睡眠相关配置
    idle_to_sleep_seconds: int = 300   # 空闲多久后进入睡眠（秒），默认5分钟
    sleep_duration_seconds: int = 60   # 睡眠时间（秒），默认1分钟
    idle_check_interval_ms: int = 10000  # 检查空闲状态的间隔（毫秒），默认10秒


class BubbleConfig(BaseModel):
    """气泡配置"""
    padding: int = 16                  # 内边距（增加让文字更舒适）
    min_width: int = 120               # 最小宽度
    max_width: int = 320               # 最大宽度（增大以显示更多文字）
    min_height: int = 48               # 最小高度
    tail_height: int = 14              # 尾巴高度（增加让尾巴更明显）
    tail_width: int = 16               # 尾巴宽度
    corner_radius: int = 24            # 圆角半径（增大更圆滑）
    fade_in_duration: int = 200        # 淡入时长（毫秒）
    fade_out_duration: int = 300       # 淡出时长（毫秒）
    
    # 动态自动隐藏配置（根据文字长度计算）
    auto_hide_base_delay: int = 2000   # 基础延迟（毫秒）- 给用户2秒阅读时间
    auto_hide_per_char: int = 100      # 每个字符增加的延迟（毫秒）- 约10字/秒
    auto_hide_min_delay: int = 2500    # 最小延迟（毫秒）
    auto_hide_max_delay: int = 20000   # 最大延迟（毫秒）- 20秒足够看完长文
    max_lines: int = 4                 # 最大显示行数（增加到4行）
    
    def calculate_hide_delay(self, text_length: int, is_auto_speak: bool = False) -> int:
        """
        根据文字长度计算气泡显示时间
        
        Args:
            text_length: 文字长度
            is_auto_speak: 是否为自动说话（给予更长时间）
        """
        # 自动说话的基础时间更长 (+2秒)
        base = self.auto_hide_base_delay + (2000 if is_auto_speak else 0)
        
        # 根据文字长度计算
        delay = base + (text_length * self.auto_hide_per_char)
        
        return max(self.auto_hide_min_delay, min(delay, self.auto_hide_max_delay))


class InputConfig(BaseModel):
    """输入框配置"""
    input_height: int = 36             # 输入框高度
    button_height: int = 36            # 按钮高度
    button_min_width: int = 46        # 按钮最小宽度（高度+10）
    max_text_length: int = 100         # 最大字符数


class ChatConfig(BaseModel):
    """聊天 UI 位置配置"""
    bubble_offset_y: int = 20          # 气泡在宠物上方的偏移（减小让气泡更靠近）
    input_offset_y: int = 5            # 输入框在气泡下方的偏移（减小间距）
    default_auto_hide_duration: int = 3000  # 默认自动隐藏时长


class LLMConfig(BaseModel):
    """
    LLM 高级配置

    用于控制 LLM 的行为特性，如思考模式等。
    通过 extra_body 传递给 API，不直接作为 SDK 参数。

    Attributes:
        thinking_enabled: 是否启用思考模式
            - True: 启用思考 (extra_body.thinking.type = "enabled")
            - False: 禁用思考 (extra_body.thinking.type = "disabled")
        thinking_type: 思考模式类型
            - "enabled": 强制启用思考
            - "disabled": 强制禁用思考
            - "auto": 自动 (让模型自行判断)
            - None: 使用模型默认行为
    """
    thinking_enabled: bool = False  # 默认禁用思考
    thinking_type: str | None = None  # 可选: "enabled", "disabled", "auto"

    def get_extra_body(self) -> dict | None:
        """
        生成 API 的 extra_body 参数

        Returns:
            dict 或 None: 包含 thinking 配置的 extra_body
            如果 thinking_type 为 None 且 thinking_enabled 为 False，返回 None
        """
        # 如果明确指定了 thinking_type，优先使用
        if self.thinking_type is not None:
            return {"thinking": {"type": self.thinking_type}}

        # 如果只设置了 thinking_enabled，根据布尔值推断
        if self.thinking_enabled:
            return {"thinking": {"type": "enabled"}}
        else:
            return {"thinking": {"type": "disabled"}}



# ============================================================
# LLM 模型注册表 - 不同任务用不同模型
# 换模型只改这里，业务代码不用动
# ============================================================
# Key: ModelTask (任务类型)
# Value: dict (模型配置)
#   - provider: str    - LangChain provider (openai/anthropic/...)
#   - model: str       - 模型名称
#   - base_url: str    - API URL (空字符串用默认)
#
# 示例:
#   换千问: {"provider": "openai", "model": "qwen-plus",
#            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"}
#   换 GPT: {"provider": "openai", "model": "gpt-4o-mini"}
#   换 Claude: {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
# ============================================================
# deepseek-chat / deepseek-reasoner 已于 2026-07-24 停用，使用 V4 新名称
MODEL_REGISTRY: dict[ModelTask, dict] = {
    ModelTask.CHAT: {
        "provider": "openai",
        "model": "deepseek-v4-flash",       # 快速/低成本 (非思考模式)
        "base_url": "https://api.deepseek.com",
        "llm_config": LLMConfig(thinking_enabled=False),  # 默认禁用思考
    },
    ModelTask.COMPLEX: {
        "provider": "openai",
        "model": "deepseek-v4-pro",          # 深度推理 (思考模式)
        "base_url": "https://api.deepseek.com",
        "llm_config": LLMConfig(thinking_enabled=True),   # 启用思考
    },
    ModelTask.VISION: {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base_url": "",
        "llm_config": None,  # GPT 不需要此配置
    },
    ModelTask.CODE: {
        "provider": "openai",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "llm_config": LLMConfig(thinking_enabled=False),
    },
    ModelTask.EMBEDDING: {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "base_url": "",
        "llm_config": None,  # Embedding 不需要此配置
    },
}


class Settings(BaseSettings):
    """
    全局配置类

    API Key 从 .env 或环境变量读取，不要硬编码！

    .env 示例:
        LLM_API_KEY=sk-xxx
        OPENAI_API_KEY=sk-xxx
    """
    # API Key - 支持多种环境变量名
    # 优先从 LLM_API_KEY 读取，其次 OPENAI_API_KEY
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
    )

    openai_api_key: str = Field(
        default='',
        validation_alias=AliasChoices('LLM_API_KEY', 'OPENAI_API_KEY', 'DEEPSEEK_API_KEY'),
    )

    # LLM 通用参数
    llm_temperature: float = 0.7
    llm_max_tokens: int = 2048
    llm_timeout: int = 30
    llm_max_retries: int = 3

    # LLM 高级配置 (全局默认，可被 MODEL_REGISTRY 覆盖)
    llm_default_config: LLMConfig = Field(default_factory=LLMConfig)

    # UI 子模块配置
    pet: PetConfig = Field(default_factory=PetConfig)
    bubble: BubbleConfig = Field(default_factory=BubbleConfig)
    input_panel: InputConfig = Field(default_factory=InputConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)


def load_config_from_store() -> dict:
    """
    从新配置系统加载配置

    Returns:
        dict: 配置字典
    """
    try:
        from config import config_manager
        config_manager.load()
        return config_manager.all()
    except Exception:
        return {}


def migrate_api_key_to_store():
    """
    迁移 API Key 到安全存储

    如果旧配置有 API Key 但新存储没有，自动迁移
    """
    try:
        from config import config_manager, secure_storage

        # 加载旧配置
        old_settings = Settings()

        # 如果旧配置有 API Key 且新存储没有
        if old_settings.openai_api_key and not secure_storage.has_api_key():
            secure_storage.save_api_key(old_settings.openai_api_key)
            print("[Config] API Key migrated to secure storage")

    except Exception as e:
        print(f"[Config] Migration failed: {e}")


# 全局配置实例
# 注意: 旧配置系统仍然可用，但新代码建议使用 config_manager
settings = Settings()


def init_llm_config_listener():
    """
    初始化 LLM 配置监听器
    
    当 LLM 相关配置变化时，自动重置 LLM 缓存
    
    注意: 此函数应该在应用主入口调用，不要在模块加载时自动调用
    """
    try:
        from providers.llm import LLMProvider
        
        def on_config_change(key, value):
            """配置变化回调"""
            if key.startswith("llm"):
                LLMProvider.reset()
        
        # 添加监听器
        from config import config_manager
        config_manager.add_listener(on_config_change)
        logger.info("[Config] LLM config listener initialized")
        
    except Exception as e:
        logger.debug(f"[Config] Failed to init LLM config listener: {e}")


# 注意: 不要在这里自动调用 init_llm_config_listener()
# 避免循环导入问题 (settings -> providers.llm -> settings)
# 应该在应用主入口手动调用
