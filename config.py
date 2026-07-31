from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel, Field, AliasChoices
from core.enums import ModelTask

from pathlib import Path
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
    move_speed: int = 2                # 水平移动速度
    move_y_speed: int = 1              # 垂直移动速度
    drag_threshold: int = 5            # 拖拽判定阈值（像素）
    walking_dir_change_prob: float = 0.005   # 方向改变概率（水平）
    walking_y_dir_change_prob: float = 0.003 # 方向改变概率（垂直）


class BubbleConfig(BaseModel):
    """气泡配置"""
    padding: int = 12                  # 内边距
    min_width: int = 80                # 最小宽度
    max_width: int = 200               # 最大宽度
    min_height: int = 30               # 最小高度
    tail_height: int = 10              # 尾巴高度
    tail_width: int = 12               # 尾巴宽度
    corner_radius: int = 15            # 圆角半径
    fade_in_duration: int = 200        # 淡入时长（毫秒）
    fade_out_duration: int = 300       # 淡出时长（毫秒）
    auto_hide_delay: int = 3000        # 自动隐藏延迟（毫秒）
    max_lines: int = 2                 # 最大显示行数


class InputConfig(BaseModel):
    """输入框配置"""
    input_height: int = 36             # 输入框高度
    button_height: int = 36           # 按钮高度
    button_min_width: int = 46        # 按钮最小宽度（高度+10）
    max_text_length: int = 100         # 最大字符数


class ChatConfig(BaseModel):
    """聊天 UI 位置配置"""
    bubble_offset_y: int = 50          # 气泡在宠物上方的偏移
    input_offset_y: int = 10           # 输入框在气泡下方的偏移
    default_auto_hide_duration: int = 3000  # 默认自动隐藏时长


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
    },
    ModelTask.COMPLEX: {
        "provider": "openai",
        "model": "deepseek-v4-pro",          # 深度推理 (思考模式)
        "base_url": "https://api.deepseek.com",
    },
    ModelTask.VISION: {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base_url": "",
    },
    ModelTask.CODE: {
        "provider": "openai",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
    },
    ModelTask.EMBEDDING: {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "base_url": "",
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

    # UI 子模块配置
    pet: PetConfig = Field(default_factory=PetConfig)
    bubble: BubbleConfig = Field(default_factory=BubbleConfig)
    input_panel: InputConfig = Field(default_factory=InputConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)


# 全局配置实例
settings = Settings()

