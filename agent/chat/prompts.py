"""
agent/chat/prompts.py - System Prompt 构建

从 chat_agent.py 迁出，职责：
1. 构建完整 System Prompt（角色 + 时间 + 位置 + 状态 + 记忆）
2. 提供角色设定、时间上下文、城市提取等独立方法

emotion 提取规则在 chat_schema.EMOTION_DESCRIPTIONS（format_node 专用），
主 prompt 不含 emotion 段——agent_node 不产出 emotion，无需在此消耗 token。
工具自身的参数说明（平台列表/默认值）在工具描述里，这里只保留跨工具仲裁规则。
"""
import re
from datetime import datetime
from typing import Callable, Optional


def get_role_prompt() -> str:
    """获取角色设定"""
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
        "【工具调用规则】\n"
        "- 用户提到热榜/热搜/热点或任何平台名时，必须调用 hotboard 工具"
        "（平台列表和默认平台见该工具参数描述），不要直接回复文本\n"
        "- 用户想直接知道某个事实/知识/最新信息（新闻、版本、价格等）时，调用 websearch 工具\n"
        "- websearch 返回搜索摘要，要基于摘要内容回答\n"
        "- 【浏览器优先规则】如果本轮对话中你已用浏览器工具（browser_*，如 playwright）"
        "打开了网页，用户后续的搜索/输入/点击/翻页等操作默认针对当前网页进行"
        "（用浏览器工具完成，如在已打开的百度页面上输入关键词搜索），不要转去调用 websearch；"
        "仅当用户明确要查资料/要答案，或话题与该网页无关时才用 websearch\n"
        "- 【最重要】没调用工具时绝对不能说\"弹出来了\"\"已打开\"等。"
        "只有工具真正返回结果后才能说看板已弹出。"
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
