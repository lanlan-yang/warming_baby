"""
tools.play_animation - 控制桌面宠物动画的 LLM 工具

让 AI Agent 能够根据对话内容触发宠物的动画表现:
- 用户说"你好可爱" -> 播放 happy/touch
- 用户说"你在干嘛" -> 播放 walk
- 用户说"加油" -> 播放 fly
- Agent 思考中 -> 播放 confused

Usage:
    # 1. 注册到工具中心 (在 main.py 启动时)
    from tools.play_animation import PlayAnimationTool
    from core import tool_registry
    tool_registry.register(PlayAnimationTool)

    # 2. Pet 端订阅事件 (已在 pet.py 中实现)
    event_bus.subscribe(EventCategory.PET, PetEvent.ANIMATION_REQUEST, self._on_animation_request)

    # 3. 让 LLM 使用 (在 ChatAgent 中)
    llm_with_tools = llm.bind_tools(tool_registry.get_tools())
"""
from pydantic import Field

from core.tool_base import BaseToolArgs, AgentTool
from core import (
    event_bus, EventCategory, PetEvent,
    AnimationRegistry,
)


# ============================================================================
# 参数定义
# ============================================================================
class PlayAnimationArgs(BaseToolArgs):
    """
    播放动画的参数

    动画类型说明见 AnimationRegistry.get_llm_description()
    """

    animation_type: str = Field(
        description="""要播放的动画类型 (支持别名):
- walk: 闲逛/走路 (默认状态)
  别名: wander, walk_around, stroll, move
- stand: 站立/发呆/等待
  别名: idle, stand_still, waiting, stop
- fly: 飞起来/很激动
  别名: flying, fly_away, excited, cheerful, happy
- touch: 开心/被抚摸 (单次播放)
  别名: hug, pet_touch, love, greet
- confused: 困惑/思考中
  别名: thinking, wonder, question, puzzled
""",
    )

    play_once: bool = Field(
        default=False,
        description="是否只播放一次后自动恢复。touch/happy 类型默认单次播放。",
    )


# ============================================================================
# 工具实现
# ============================================================================
class PlayAnimationTool(AgentTool):
    """
    动画控制工具

    AI Agent 可以调用此工具来让桌面宠物做出各种表情动画。
    所有动画名称和别名统一由 AnimationRegistry 管理。
    """

    name: str = "play_animation"
    description: str = (
        "控制桌面宠物播放动画表情。"
        "当对话涉及情绪表达、或想用动画来回应时调用此工具。\n"
        f"{AnimationRegistry.get_llm_description()}"
    )
    args_schema: type[BaseToolArgs] = PlayAnimationArgs

    async def _execute(self, animation_type: str, play_once: bool = False) -> str:
        """
        执行动画播放

        通过事件总线发布 PET.ANIMATION_REQUEST，让 Pet 组件在主线程中执行。
        动画名称解析由 AnimationRegistry 统一处理。
        """
        # 1. 解析动画类型 (支持所有别名)
        anim_enum = AnimationRegistry.resolve(animation_type)
        if not anim_enum:
            available = AnimationRegistry.get_llm_description()
            return f"未知动画类型 '{animation_type}'。{available}"

        # 2. 检查配置
        config = AnimationRegistry.get_config(anim_enum)
        is_once = play_once or config.play_once

        # 3. 发布事件
        event_bus.publish(
            EventCategory.PET,
            PetEvent.ANIMATION_REQUEST,
            animation=anim_enum.value,
            play_once=is_once,
        )

        # 4. 返回结果给 LLM
        extra = " (单次播放)" if is_once else ""
        return f"已播放动画 '{anim_enum.value}'{extra}"
