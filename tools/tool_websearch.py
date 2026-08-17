"""
tools/tool_websearch - 智能网页搜索工具

使用 uapis.cn /api/v1/search/aggregate 实时网页搜索，替代原 MCP bing-search。
搜索结果会以 Tab 页形式追加到热榜看板弹窗展示（每个搜索词一个 Tab），
同时返回摘要给 LLM 用于组织回答。

API 文档：https://uapis.cn/docs/api-reference/post-search-aggregate

MCP 说明：tools/mcp/ 代码完整保留，仅在 mcp_config.py 中 enabled=False
停用注册，需要时改回 True 即可恢复。

缓存策略：
- 缓存时间：5分钟
- 缓存键：query

LLM 使用建议：
- 用户说"搜一下/查一下/搜索xxx" → 调用本工具
- 用户问需要最新信息的问题（新闻、版本、价格） → 先调用本工具
"""
import json

from pydantic import Field

from tools.tool_base import AgentTool, BaseToolArgs
from tools.cache import cache
from tools.http_client import http_post
from core.logger import setup_logger

logger = setup_logger()

SEARCH_API_URL = "https://uapis.cn/api/v1/search/aggregate"

# 请求条数上限（API 未公开但实测支持，多拿一些供看板完整展示）
SEARCH_LIMIT = 30
# 单 Tab 保留条数上限（内存保险：看板控件随条数增长，超出的截断）
MAX_ITEMS = 100
# 返回给 LLM 的摘要条数（上下文有限，看板仍展示全部）
LLM_DIGEST_ITEMS = 8


class WebSearchArgs(BaseToolArgs):
    """网页搜索参数"""
    query: str = Field(..., description="搜索关键词，使用简洁的关键词组合，避免完整问句。例如：'2025年中国GDP增速' 而不是 '请告诉我2025年中国GDP增速是多少'")


class WebSearchTool(AgentTool):
    """
    智能网页搜索

    实时搜索网页，获取最新信息（按相关性排序）。

    搜索结果会自动以 Tab 页形式追加到看板窗口展示给用户，
    用户可直接点击条目打开原文链接。

    LLM 使用建议：
    - 用户说"搜一下/查一下/搜索xxx" → 用用户的关键词调用
    - 用户问需要最新信息的问题 → 先搜索再回答
    """

    name: str = "websearch"
    description: str = (
        "【高优先级工具】实时网页搜索，获取最新信息。"
        "触发条件：用户提到搜索/查找/搜一下/网上查等关键词，或问任何可能需要最新信息的问题"
        "（新闻、时事、版本号、价格、攻略等）时调用。"
        "参数：query(搜索关键词，必填)。"
        "搜索成功后会自动在看板窗口展示结果，用户可点击查看原文。"
        "返回内容包含结果摘要，请基于摘要回答用户问题。"
    )
    args_schema: type[BaseToolArgs] = WebSearchArgs

    @staticmethod
    @cache(
        ttl=300,  # 5分钟缓存
        cache_name="websearch",
        key_func=lambda query, **kw: query,
    )
    async def _fetch_search_results(query: str) -> list:
        """调用聚合搜索 API（带缓存）"""
        body = {"query": query, "fetch_full": False, "limit": SEARCH_LIMIT}

        raw = await http_post(SEARCH_API_URL, json=body)
        data = json.loads(raw)

        # API 返回格式: {"query": "...", "total_results": N, "results": [...]}
        if isinstance(data, dict):
            return data.get("results", []) or []
        if isinstance(data, list):
            return data
        return []

    async def _execute(self, query: str, **kwargs) -> str:
        """
        执行网页搜索

        Returns:
            结果摘要文本（LLM 基于摘要回答；看板弹窗另行展示详情）
        """
        query = (query or "").strip()
        if not query:
            return "搜索关键词为空，请告诉我想搜什么~"

        logger.info(f"[WebSearch] 搜索: {query}")

        try:
            results = await self._fetch_search_results(query)
        except Exception as e:
            logger.error(f"[WebSearch] 搜索失败: {query}, {e}")
            # 兜底发空事件，确保看板有反馈
            try:
                from core import event_bus, EventCategory, AgentEvent
                event_bus.publish(
                    EventCategory.AGENT,
                    AgentEvent.HOTBOARD,
                    type=f"search:{query}",
                    type_display=f"🔍 {query}",
                    board_title="🔍 搜索看板",
                    items=[],
                )
            except Exception:
                pass
            return f"抱歉，搜索'{query}'失败: {e}"

        # 内存保险：超出上限截断（LLM 摘要只用前几条，后面价值极低）
        if len(results) > MAX_ITEMS:
            logger.debug(f"[WebSearch] 结果 {len(results)} 条超出上限，截断至 {MAX_ITEMS}")
            results = results[:MAX_ITEMS]

        # 发布事件：搜索结果以 Tab 页追加到热榜看板（全部展示，不截断）
        display_items = [
            {
                "title": r.get("title", "未知"),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
                "domain": r.get("domain", ""),
                "publish_time": (r.get("publish_time") or "")[:10],  # 只取日期部分
            }
            for r in results
        ]
        from core import event_bus, EventCategory, AgentEvent
        event_bus.publish(
            EventCategory.AGENT,
            AgentEvent.HOTBOARD,
            type=f"search:{query}",       # 同关键词复用 Tab，新关键词新 Tab
            type_display=f"🔍 {query}",
            board_title="🔍 搜索看板",     # 看板标题跟随需求变化
            items=display_items,
        )

        if not display_items:
            return f"搜索'{query}'没有找到结果，可以换个关键词试试~"

        # 给 LLM 的摘要（看板展示全部，摘要仅取前 N 条节省上下文）
        lines = [
            f"搜索'{query}'共 {len(results)} 条结果，已全部在看板展示，以下是前 {LLM_DIGEST_ITEMS} 条摘要："
        ]
        for i, r in enumerate(results[:LLM_DIGEST_ITEMS], 1):
            title = r.get("title", "")
            snippet = (r.get("snippet") or "")[:120]
            lines.append(f"{i}. {title}\n   {snippet}")
        return "\n".join(lines)


def clear_websearch_cache():
    """清除所有搜索缓存"""
    from tools.cache import clear_cache
    clear_cache("websearch")
