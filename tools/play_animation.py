"""
tools.play_animation - 控制桌面宠物动画的 LLM 工具

让 AI Agent 能够根据对话内容触发宠物的各种动画表现

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

    所有可用动画类型和别名详见 AnimationRegistry
    """

    animation_type: str = Field(
        description="""要播放的动画类型，支持以下选项：

基础状态 (循环播放):
- walk: 走路/闲逛 (默认状态)
- stand: 站立/发呆
- fly: 飞起来/很激动
- confused: 困惑/思考中

情绪反应 (单次播放):
- touch: 被抚摸/撒娇 (可称呼"pet"、"hug"触发)
- happy: 开心/兴奋 (可称呼"joyful"、"smile"触发)

特定状态 (循环播放):
- sleep: 睡觉/犯困 (可称呼"zzz"、"tired"触发)
- playing: 玩游戏/娱乐 (可称呼"game"触发)
- searching: 搜索/寻找 (可称呼"find"、"look"触发)

特定动作 (单次播放):
- leave: 离开/道别 (可称呼"bye"、"goodbye"触发)
- drag: 被拖拽/抱起

注意：AI可使用自然语言描述触发动画，系统会自动匹配最合适的动画类型。""",
    )

    play_once: bool = Field(
        default=False,
        description="""是否只播放一次后自动恢复之前的状态。
对于情绪类动画 (touch/happy/leave/drag) 会自动单次播放，无需设置。
如果希望状态类动画 (walk/stand/sleep) 只播放一次，可以设置为 true。""",
    )


# ============================================================================
# 工具实现
# ============================================================================
class PlayAnimationTool(AgentTool):
    """
    动画控制工具

    AI Agent 可以调用此工具来让桌面宠物做出各种动画。

    典型场景：
    - 用户说"你好可爱" -> play happy
    - 用户说"摸摸头" -> play touch
    - 用户打哈欠 -> play sleep
    - 用户说再见 -> play leave
    - 用户问"帮我找找" -> play searching
    """

    name: str = "play_animation"
    description: str = (
        "控制桌面宠物的动画表现。"
        "根据对话内容选择合适的动画来回应。\n\n"
        f"{AnimationRegistry.get_llm_description()}\n\n"
        "你可以根据用户的情绪、话题或指令，选择最适合的动画来增强互动。"
    )
    args_schema: type[BaseToolArgs] = PlayAnimationArgs

    async def _execute(self, animation_type: str, play_once: bool = False) -> str:
        """
        执行动画播放

        通过事件总线发布动画请求，让 Pet 组件在主线程中执行。
        """
        # 1. 解析动画类型
        anim_enum = AnimationRegistry.resolve(animation_type)
        if not anim_enum:
            available = AnimationRegistry.get_llm_description()
            return f"未找到动画类型 '{animation_type}'。可用动画：\n{available}"

        # 2. 检查是否需要单次播放
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
        extra = " (单次播放)" if is_once else " (循环播放)"
        aliases_str = "、".join(config.aliases[:3]) if config.aliases else ""
        return (
            f"已成功播放动画 '{anim_enum.value}'{extra}。"
            f"这个动画表示：{config.description}。"
            f"(支持的别名：{aliases_str})"
        )
