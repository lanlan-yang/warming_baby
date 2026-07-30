from pydantic_settings import BaseSettings
from pydantic import BaseModel, Field

from pathlib import Path
# 反推项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class PetConfig(BaseModel):
    """宠物基础配置"""
    display_height: int = 120          # 显示高度
    move_speed: int = 2                # 水平移动速度
    move_y_speed: int = 1              # 垂直移动速度
    drag_threshold: int = 5            # 拖拽判定阈值（像素）
    touch_duration: int = 4340         # touch 动画时长（毫秒）
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


class Settings(BaseSettings):
    """全局配置类"""
    # ── 大模型（DeepSeek）──
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/"

    # ── UI 子模块配置 ──
    pet: PetConfig = Field(default_factory=PetConfig)
    bubble: BubbleConfig = Field(default_factory=BubbleConfig)
    input_panel: InputConfig = Field(default_factory=InputConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)

    model_config = {
        "env_file": str(ENV_FILE),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


# 全局配置实例
settings = Settings()

