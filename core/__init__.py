import asyncio

from .animations import AnimationType, AnimationConfig, AnimationRegistry
from .enums import PetState, ModelTask, LLMModel
from .event_bus import (
    EventBus, EventCategory, event_bus,
    SystemEvent, UIEvent, AgentEvent, PetEvent
)
from .tool_base import BaseToolArgs, AgentTool, ToolRegistry, tool_registry
from .schemas import BaseSchema

# 全局 shutdown event - 用于协调应用退出
# 在 main() 中 await，在 _do_exit() 中 set
# 注意：需要在 QEventLoop 设置后调用 reinit_shutdown_event()
shutdown_event = asyncio.Event()

def reinit_shutdown_event():
    """
    重新初始化 shutdown_event
    
    在 QEventLoop 设置后调用，确保 event 绑定到正确的事件循环
    """
    global shutdown_event
    try:
        loop = asyncio.get_event_loop()
        # 创建一个新的 event 绑定到当前循环
        new_event = asyncio.Event()
        shutdown_event = new_event
        print(f"[core] shutdown_event reinitialized for loop: {loop}")
    except Exception as e:
        print(f"[core] Error reinitializing shutdown_event: {e}")

# PyQt6 可选导入 (非 UI 环境不需要)
try:
    from .fonts import get_default_font, get_font
    _has_fonts = True
except ImportError:
    _has_fonts = False
    get_default_font = None  # type: ignore
    get_font = None  # type: ignore

# 注意: 聊天相关的 Schema 请直接从 agent.chat.chat_schema 导入
# 例如: from agent.chat.chat_schema import ChatResponse, Emotion

__all__ = [
    'AnimationType', 'AnimationConfig', 'AnimationRegistry',
    'PetState', 'ModelTask', 'LLMModel',
    'EventBus', 'EventCategory', 'event_bus',
    'SystemEvent', 'UIEvent', 'AgentEvent', 'PetEvent',
    'get_default_font', 'get_font',
    'BaseToolArgs', 'AgentTool', 'ToolRegistry', 'tool_registry',
    'BaseSchema',
    'shutdown_event', 'reinit_shutdown_event',
]
