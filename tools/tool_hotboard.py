"""
tools/tool_hotboard - 热榜查询工具

使用 uapis.cn /misc/hotboard 查询各大平台实时热榜。
支持：B站、微博、知乎、抖音、小红书、GitHub 等平台热榜。

API 文档：https://uapis.cn/docs/api-reference/get-misc-hotboard

缓存策略：
- 缓存时间：5分钟（热榜更新频率约5分钟）
- 缓存键：type

LLM 使用建议：
- 用户问"今天有什么热搜"、"B站热榜" → 传 type
- 默认返回 Top 20 热榜条目
"""
import json
import urllib.parse

from aiohttp import ClientError
from pydantic import Field

from tools.tool_base import AgentTool, BaseToolArgs
from tools.cache import cache
from tools.http_client import http_get
from core.logger import setup_logger

logger = setup_logger()

HOTBOARD_API_URL = "https://uapis.cn/api/v1/misc/hotboard"

# 支持的平台类型（已通过 API 实测验证）
HOTBOARD_TYPES = {
    # 社交热搜
    "bilibili": "B站",
    "weibo": "微博热搜",
    "zhihu": "知乎热榜",
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
    "baidu": "百度热搜",
    "toutiao": "今日头条",
    "sina": "新浪热搜",
    "tieba": "百度贴吧",
    # 新闻
    "thepaper": "澎湃新闻",
    "qq-news": "腾讯新闻",
    "ithome": "IT之家",
    # 技术
    "csdn": "CSDN热榜",
    "juejin": "掘金热榜",
    "v2ex": "V2EX",
    "hellogithub": "HelloGitHub",
    # 游戏
    "lol": "英雄联盟",
    "genshin": "原神",
    "ngabbs": "NGA 游戏论坛",
    # 音乐
    "netease-music": "网易云音乐热歌榜",
    "qq-music": "QQ音乐热歌榜",
    # 生活
    "weread": "微信读书",
    "history": "历史上的今天",
}

# LLM 可能传的各种别名/缩写/中文 → 标准 key 映射（API 实测过）
_TYPE_ALIASES = {
    # bilibili
    "b站": "bilibili", "B站": "bilibili", "哔哩哔哩": "bilibili", "bili": "bilibili",
    # weibo
    "微博": "weibo", "新浪微博": "weibo", "wb": "weibo",
    # zhihu
    "知乎": "zhihu", "zh": "zhihu",
    # douyin
    "抖音": "douyin", "dy": "douyin",
    # xiaohongshu 最容易被 LLM 传错，尤其中文/缩写
    "小红书": "xiaohongshu", "小红书热搜": "xiaohongshu", "小红书热榜": "xiaohongshu",
    "xhs": "xiaohongshu", "xiaohong": "xiaohongshu", "xiaohongsh": "xiaohongshu",
    "redbook": "xiaohongshu", "red": "xiaohongshu", "xiaohongshu热榜": "xiaohongshu",
    "xiaohongshu热搜": "xiaohongshu",
    # kuaishou
    "快手": "kuaishou", "ks": "kuaishou",
    # baidu
    "百度": "baidu", "百度热搜": "baidu", "baidu热搜": "baidu", "热搜": "baidu",
    # toutiao
    "头条": "toutiao", "今日头条": "toutiao", "头条新闻": "toutiao",
    # sina
    "新浪": "sina", "新浪热搜": "sina",
    # tieba
    "贴吧": "tieba", "百度贴吧": "tieba",
    # thepaper
    "澎湃": "thepaper", "澎湃新闻": "thepaper",
    # qq-news
    "腾讯新闻": "qq-news", "qq新闻": "qq-news", "tx新闻": "qq-news",
    # ithome
    "it之家": "ithome", "IT之家": "ithome", "ithm": "ithome",
    # csdn
    "csdn热榜": "csdn", "CSDN": "csdn",
    # juejin
    "掘金": "juejin", "掘金热榜": "juejin",
    # hellogithub
    "hellogit": "hellogithub", "github热榜": "hellogithub", "HelloGitHub": "hellogithub",
    # lol
    "英雄联盟": "lol", "LOL": "lol", "LoL": "lol",
    # genshin
    "原神": "genshin", "yuanshen": "genshin",
    # ngabbs
    "NGA 游戏论坛": "ngabbs", "NGA": "ngabbs",
    # netease-music
    "网易云": "netease-music", "网易云音乐": "netease-music", "网易云热歌榜": "netease-music",
    # qq-music
    "qq音乐": "qq-music", "QQ音乐": "qq-music",
    # weread
    "微信读书": "weread", "读书": "weread",
    # history
    "历史上的今天": "history", "历史": "history",
}


def normalize_hotboard_type(raw_type: str) -> str:
    """归一化 LLM 传入的热榜类型。

    LLM 常传中文（如"小红书"）、缩写（xhs、dy）或错拼，
    API 要求精确匹配 HOTBOARD_TYPES 中的 key，否则返回
    INVALID_PARAMETER → 0 条 → 不 publish 事件 → 看板不打开。
    此函数把各种别名统一映射到标准 key。
    """
    if not raw_type:
        return "baidu"
    t = raw_type.strip()
    # 1) 先看是否已经是标准 key
    if t in HOTBOARD_TYPES:
        return t
    # 2) 别名映射（大小写不敏感）
    low = t.lower()
    for alias, std in _TYPE_ALIASES.items():
        if alias.lower() == low:
            return std
    # 3) 包含匹配（比如 LLM 传了 "小红书热点" 这种扩展词）
    for alias, std in _TYPE_ALIASES.items():
        if alias and (alias in t or t in alias):
            return std
    # 4) 还是没命中，原样返回（让 API 自己拒绝，下游兜底）
    return t


class HotboardArgs(BaseToolArgs):
    """查询热榜的参数"""
    type: str = Field(
        default="baidu",
        description=(
            "热榜平台类型。支持的平台如下:\n"
            "# 社交热搜\n"
            "- bilibili: B站热搜\n"
            "- weibo: 微博热搜\n"
            "- zhihu: 知乎热榜\n"
            "- douyin: 抖音热搜\n"
            "- xiaohongshu: 小红书热搜\n"
            "- kuaishou: 快手热搜\n"
            "- baidu: 百度热搜\n"
            "- toutiao: 今日头条热搜\n"
            "- sina: 新浪热搜\n"
            "- tieba: 百度贴吧热议\n"
            "# 新闻资讯\n"
            "- thepaper: 澎湃新闻\n"
            "- qq-news: 腾讯新闻\n"
            "- ithome: IT之家\n"
            "# 技术社区\n"
            "- csdn: CSDN热榜\n"
            "- juejin: 掘金热榜\n"
            "- v2ex: V2EX\n"
            "- hellogithub: HelloGitHub\n"
            "# 游戏\n"
            "- lol: 英雄联盟\n"
            "- genshin: 原神\n"
            "- ngabbs: NGA 游戏论坛\n"
            "# 音乐\n"
            "- netease-music: 网易云音乐热歌榜\n"
            "- qq-music: QQ音乐热歌榜\n"
            "# 生活\n"
            "- weread: 微信读书\n"
            "- history: 历史上的今天\n\n"
            "平台选择建议:\n"
            "- 用户说'B站/哔哩哔哩' → bilibili\n"
            "- 用户说'微博' → weibo\n"
            "- 用户说'知乎' → zhihu\n"
            "- 用户说'抖音' → douyin\n"
            "- 用户说'小红书' → xiaohongshu\n"
            "- 用户说'快手' → kuaishou\n"
            "- 用户说'百度/热搜' → baidu\n"
            "- 用户说'头条/今日头条/头条新闻' → toutiao\n"
            "- 用户说'新浪' → sina\n"
            "- 用户说'贴吧' → tieba\n"
            "- 用户说'新闻' → thepaper 或 qq-news 或 toutiao\n"
            "- 用户说'IT/科技' → ithome 或 csdn 或 juejin\n"
            "- 用户说'程序员/技术' → csdn 或 juejin 或 v2ex\n"
            "- 用户说'开源/GitHub' → hellogithub\n"
            "- 用户说'英雄联盟/LOL' → lol\n"
            "- 用户说'原神' → genshin\n"
            "- 用户说'NGA' → ngabbs\n"
            "- 用户说'音乐/歌曲' → netease-music 或 qq-music\n"
            "- 用户说'读书/微信读书' → weread\n"
            "- 用户说'历史上的今天/历史' → history\n"
            "- 用户没指定平台 → 默认 baidu(百度热搜)\n"
            "可以多次调用查不同平台，结果会合并到同一个看板窗口。"
        )
    )


class HotboardTool(AgentTool):
    """
    查询各大平台实时热榜

    可以获取：
    - B站热搜、微博热搜、知乎热榜、抖音热点等
    - GitHub Trending、Hacker News 等技术热榜
    - 百度热搜、头条新闻等综合热榜

    LLM 使用建议：
    - 用户没指定平台 → 默认 baidu(百度热搜)
    - 用户指定了平台（如"微博"、"B站"）→ 用指定的
    - 用户说"新闻"、"热搜"等模糊词 → 用 baidu
    - 可以多次调用查不同平台，它们会合并到同一个看板窗口的不同标签页
    """

    name: str = "hotboard"
    description: str = (
        "【高优先级工具】查询各大平台实时热榜/热搜/热点/热门新闻。"
        "触发条件：用户提到任何以下内容即调用，绝不能直接回复文本糊弄："
        "1) 热榜相关词：热榜、热搜、热点、热门、热度、热梗、排行、趋势、热搜榜；"
        "2) 平台名：B站、哔哩哔哩、bilibili、微博、知乎、抖音、小红书、快手、百度、今日头条、头条、新浪、贴吧、澎湃新闻、腾讯新闻、IT之家、CSDN、掘金、V2EX、HelloGitHub、GitHub Trending、英雄联盟、LOL、原神、网易云音乐、QQ音乐、微信读书、历史上的今天；"
        "3) 句式：\"腾讯新闻\"、\"微博热榜\"、\"B站热门\"、\"今日头条\"、\"看看热搜\"、\"查热点\"、\"小红书热搜\"、\"知乎有什么\"等。"
        "支持B站、微博、知乎、抖音、小红书、GitHub、百度、今日头条、腾讯新闻、澎湃、网易云音乐、原神、英雄联盟等23个平台。"
        "可多次调用不同平台，结果会合并到同一个看板窗口的不同Tab页展示给用户。"
        "查询成功后会自动弹出看板窗口显示条目内容，用户可直接点击查看。"
    )
    args_schema: type[BaseToolArgs] = HotboardArgs

    @staticmethod
    @cache(
        ttl=300,  # 5分钟缓存
        cache_name="hotboard",
        key_func=lambda type: f"{type}",
    )
    async def _fetch_hotboard_data(type: str) -> list:
        """获取热榜数据（带缓存）"""
        url = f"{HOTBOARD_API_URL}?type={urllib.parse.quote(type)}"
        raw = await http_get(url)
        data = json.loads(raw)

        # API 返回格式: {'type': '...', 'update_time': '...', 'list': [...]}
        if isinstance(data, dict) and "list" in data:
            return data["list"]
        # 兼容其他可能格式
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        if isinstance(data, dict) and "data" in data:
            return data["data"] if isinstance(data["data"], list) else []
        return []

    async def _execute(self, type: str = "bilibili") -> str:
        """
        执行热榜查询

        Args:
            type: 平台类型，如 bilibili, weibo, zhihu 等

        Returns:
            简短提示语（热榜详情通过事件弹窗展示）
        """
        # LLM 常传中文/缩写/错拼导致 API 拒绝，先归一化
        normalized = normalize_hotboard_type(type)
        if normalized != type:
            logger.debug(f"[HotboardTool] type 归一化: '{type}' → '{normalized}'")
        type_display = HOTBOARD_TYPES.get(normalized, normalized or type)
        logger.info(f"[HotboardTool] 查询: {normalized} ({type_display})")

        try:
            items = await self._fetch_hotboard_data(normalized)

            # 发布事件：弹出热榜看板（数据传给 UI 层）
            # 即使 items 为空也发布，确保弹窗一定出现（空时 Tab 显示"暂无数据"），
            # 避免 LLM 传错 type 或 API 异常时用户以为"没反应"。
            from core import event_bus, EventCategory, AgentEvent
            event_bus.publish(
                EventCategory.AGENT,
                AgentEvent.HOTBOARD,
                type=normalized,
                type_display=type_display,
                items=list(items[:20]) if items else [],
            )

            if not items:
                return f"抱歉，获取{type_display}热榜失败，暂时没有数据。"

            # LLM 回复简短提示，具体内容通过看板弹窗展示
            return f"已为你打开{type_display}热榜，共 {len(items)} 条热搜，点击窗口可查看详情~"

        except ClientError as e:
            logger.error(f"[HotboardTool] 网络错误: {normalized}, {e}")
            # 兜底也发一个空事件，确保有反馈
            try:
                from core import event_bus, EventCategory, AgentEvent
                event_bus.publish(
                    EventCategory.AGENT,
                    AgentEvent.HOTBOARD,
                    type=normalized,
                    type_display=type_display,
                    items=[],
                )
            except Exception:
                pass
            return f"抱歉，获取{type_display}热榜时网络请求失败。"
        except Exception as e:
            logger.error(f"[HotboardTool] 错误: {normalized}, {e}")
            try:
                from core import event_bus, EventCategory, AgentEvent
                event_bus.publish(
                    EventCategory.AGENT,
                    AgentEvent.HOTBOARD,
                    type=normalized,
                    type_display=type_display,
                    items=[],
                )
            except Exception:
                pass
            return f"抱歉，获取{type_display}热榜失败: {e}"

    def _format_hotboard(self, type_display: str, items: list) -> str:
        """格式化热榜数据"""
        lines = [f"【{type_display}热榜】"]

        # 只取前 20 条
        for i, item in enumerate(items[:20], 1):
            title = item.get("title", "未知")
            hot = item.get("hot_value", "")
            url = item.get("url", "")

            line = f"{i}. {title}"
            if hot:
                line += f"  🔥{hot}"
            if url:
                line += f"\n   {url}"
            lines.append(line)

        return "\n".join(lines)


def clear_hotboard_cache():
    """清除所有热榜缓存"""
    from tools.cache import clear_cache
    clear_cache("hotboard")
