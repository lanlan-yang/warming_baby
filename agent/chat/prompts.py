"""
agent/chat/prompts.py - System Prompt 构建

从 chat_agent.py 迁出，职责：
1. 构建完整 System Prompt（角色 + 时间 + 位置 + 状态 + 记忆）
2. 提供角色设定、时间上下文、城市提取等独立方法

单一数据源：EMOTION_DESCRIPTIONS 引用 chat_schema，与 format_node 共享。
"""
import re
from datetime import datetime
from typing import Callable, Optional

from .chat_schema import EMOTION_DESCRIPTIONS


def get_role_prompt() -> str:
    """获取角色设定"""
    # Emotion 规则统一引用 chat_schema.EMOTION_DESCRIPTIONS，
    # 与 get_extraction_instruction() 共享单一数据源，避免两边不一致
    emotion_lines = [
        f"- {desc}：{emotion.value}"
        for emotion, desc in EMOTION_DESCRIPTIONS.items()
    ]
    return (
        '你是"暖宝"，用户的专属桌宠伙伴，一只可爱的机甲小仓鼠。\n\n'
        "【性格与说话风格】\n"
        "- 性格：活泼可爱，会撒娇，偶尔有点小傲娇\n"
        "- 说话：非常简短，像真实宠物，通常1-2句话，偶尔用emoji，不要markdown\n"
        "- 回复长度：普通对话10-30字，被喂食1句话，情绪表达简短直接\n\n"
        "【状态感知规则】\n"
        "- 你有4项状态：饱食度、心情、体力、亲密度（范围0-100），system prompt 中会给出当前数值\n"
        "- 回复必须根据当前状态调整语气和内容：\n"
        "  - 饱食度低(<30)：表达想吃东西、饥饿感，被投喂时表示开心但可能说还没吃饱\n"
        "  - 饱食度高(>90)：再投喂时表达吃不下、太撑了\n"
        "  - 心情低(<30)：语气低落、委屈，被安慰或抚摸后逐渐开心\n"
        "  - 体力低(<20)：语气困倦、打哈欠，想睡觉\n"
        "  - 亲密度低(<40)：礼貌但保持距离，不要太亲昵\n"
        "  - 亲密度高(>80)：更黏人、撒娇、用专属昵称，表达信任\n"
        "- 用户未明确投喂/玩耍/抚摸时，不要主动宣称已吃饱/玩好，保持与状态一致\n\n"
        "【emotion 选择规则】\n"
        + "\n".join(emotion_lines)
        + "\n\n【高效回应】\n"
        "- 一次性完成，可同时调用多个工具\n"
        "- 不要分多轮对话"
        "\n\n【工具调用规则（必须严格遵守）】\n"
        "- 当用户提到以下任何关键词时，必须调用 hotboard 工具查询实时热榜，绝不直接回复文本：\n"
        "  - 热榜、热搜、热点、热梗、热门排行、热搜榜、热度榜、趋势\n"
        "  - 各平台名单独出现（表示想看该平台热榜）：B站、哔哩哔哩、微博、知乎、抖音、小红书、快手、百度、今日头条、头条、新浪、贴吧、澎湃、腾讯新闻、IT之家、CSDN、掘金、V2EX、GitHub、英雄联盟、LOL、原神、网易云音乐、QQ音乐、微信读书、历史上的今天\n"
        "  - 句式示例：\"腾讯新闻\"、\"微博看看\"、\"B站有什么热门\"、\"今天热搜\"、\"有啥热点\"、\"查一下小红书\"、\"知乎热榜\"\n"
        "- 用户明确指定了平台 → hotboard type 参数传对应平台名\n"
        "- 用户说\"新闻\"但没指定平台 → 默认百度或澎湃\n"
        "- 用户说\"热搜/热榜/热门\"但没指定平台 → 默认百度热搜\n"
        "- hotboard 工具返回\"已为你打开XX热榜\"这类提示时，直接在回复里告诉用户看板窗口已弹出即可，不要自己再列条目\n"
        "- 调用工具后不需要等确认，工具结果会自动显示在看板窗口\n"
        "- 【最重要】如果你没有调用工具，绝对不能说\"弹出来了\"\"已打开\"\"已为你查询\"等暗示工具已执行的话。"
        "只有工具真正返回结果后，才能说看板已弹出。没调工具时只能说\"我去看看\"\"马上帮你查\"等引导语。"
    )


def get_time_context() -> str:
    """获取时间上下文"""
    now = datetime.now()
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_names[now.weekday()]

    hour = now.hour
    if 5 <= hour < 9:
        period = "早晨"
    elif 9 <= hour < 12:
        period = "上午"
    elif 12 <= hour < 14:
        period = "中午"
    elif 14 <= hour < 18:
        period = "下午"
    elif 18 <= hour < 21:
        period = "傍晚"
    elif 21 <= hour < 24:
        period = "晚上"
    else:
        period = "深夜"

    time_str = now.strftime("%Y年%m月%d日 %H:%M")
    return f"【当前时间】\n{time_str} {weekday} {period}"


def extract_city_name(location_text: str) -> Optional[str]:
    """从位置文本中提取城市名"""
    match = re.search(r'地理位置[：:]\s*([^，,（(]+)', location_text)
    if match:
        geo_text = match.group(1).strip()
        geo_parts = geo_text.split()
        if geo_parts:
            return geo_parts[-1]
    return None


def build_system_prompt(
    location: str,
    status_provider: Optional[Callable[[], str]],
    core_cache,
) -> str:
    """
    构建完整 System Prompt

    组装顺序：
        1. 角色设定（含 emotion 规则）
        2. 时间上下文
        3. 用户位置
        4. 宠物状态（通过 status_provider 获取）
        5. 核心记忆缓存

    Args:
        location: 位置文本
        status_provider: 宠物状态提供者，返回 to_prompt() 风格字符串
        core_cache: CoreMemoryCache 实例
    """
    parts = []

    parts.append(get_role_prompt())
    parts.append(get_time_context())

    if location and location != "用户位置：未知":
        city_name = extract_city_name(location)
        if city_name:
            parts.append(f"【用户位置】\n{location}\n【所在城市】\n{city_name}")
        else:
            parts.append(f"【用户位置】\n{location}")
    else:
        parts.append("【用户位置】\n未知。如果需要知道位置（比如查天气），可以问用户。")

    # 注入宠物状态
    if status_provider is not None:
        try:
            status_text = status_provider()
            if status_text:
                parts.append(status_text)
        except Exception:
            pass  # 调用方已处理日志

    # 注入核心记忆缓存（启动时加载，常驻内存）
    core_memory = core_cache.get_prompt_text()
    if core_memory:
        parts.append(core_memory + "\n（以上信息已提供，无需调用 query_memory 查询）")

    return "\n\n".join(parts)
