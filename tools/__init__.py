"""
tools/__init__.py - 工具模块入口

注册所有可用的工具
"""
from .play_animation import PlayAnimationTool
from core import tool_registry

# 自动注册工具
tool_registry.register(PlayAnimationTool)


def get_all_tools():
    """获取所有已注册的工具"""
    return tool_registry.get_tools()


def get_tool_descriptions() -> str:
    """获取工具描述，用于生成系统提示"""
    tools = get_all_tools()
    descriptions = []
    
    for tool in tools:
        descriptions.append(f"- {tool.name}: {tool.description}")
    
    return "\n".join(descriptions)
