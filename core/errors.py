"""
core.errors - Agent 统一错误分类与面向用户的提示

设计目标:
    1. 任何 LLM / 工具 / 图执行层抛的原始异常 (AuthenticationError / TimeoutError / ...)
       统一用 AgentError.classify(e) 归类成结构化枚举 + 用户可读提示 + 可操作建议
    2. 对话 UI 层只看 AgentError.error_code + user_message + action_hint，
       不再根据异常名 / 原始字符串做猜测性判断，避免提示不精确
    3. 新增错误类型时，只加枚举项 + 映射器增加一条即可，无需改 UI 层

使用示例:
    try:
        await llm.ainvoke(...)
    except Exception as e:
        ae = AgentError.classify(e)
        # ae.code = ErrorCode.LLM_AUTH_INVALID
        # ae.user_message = "我的 API Key 好像失效了..."
        # ae.action_hint = "右键我 → 设置 → 对话模型 → 检查 API Key 是否正确 / 过期"
        # ae.emotion = Emotion.CONFUSED
        raise ae from e

ChatAgent 层:
    try:
        ...
    except AgentError as ae:
        return ChatResponse(text=f"{ae.user_message}\n建议: {ae.action_hint}",
                            emotion=ae.emotion)
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from core.logger import logger


class ErrorCode(str, Enum):
    """
    Agent 运行过程中可能出现的所有可识别错误

    命名约定: {模块}_{问题}，例如:
        LLM_AUTH_INVALID      - LLM 鉴权失败 (API Key 错/过期)
        LLM_QUOTA_EXHAUSTED   - LLM 额度用光
        LLM_TIMEOUT           - LLM 请求超时
        LLM_RATE_LIMIT        - LLM 限流 (429)
        EMBED_AUTH_INVALID    - Embedding 鉴权失败
        EMBED_QUOTA_EXHAUSTED - Embedding 额度用光
        NETWORK_OFFLINE       - 网络不可达 (DNS 失败 / 无网络)
        NETWORK_SSL_ERROR     - HTTPS 证书错误
        NETWORK_PROXY         - 代理/端口连接失败
        TOOL_HTTP_FAILURE     - 工具 HTTP 请求失败 (热榜/天气/搜索)
        TOOL_MCP_FAILURE      - MCP Server 启动或调用失败
        MEMORY_CHROMA              - ChromaDB 读写异常
        CONFIG_MISSING_LLM_KEY     - 未配置 LLM API Key
        CONFIG_MISSING_EMBED_KEY   - 未配置 Embedding API Key
        GRAPH_NODE_ERROR           - LangGraph 节点未知异常
        UNKNOWN               - 兜底未分类
    """

    # ---------- LLM 对话模型 ----------
    LLM_AUTH_INVALID = "llm_auth_invalid"
    LLM_AUTH_EXPIRED = "llm_auth_expired"
    LLM_QUOTA_EXHAUSTED = "llm_quota_exhausted"
    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_TIMEOUT = "llm_timeout"
    LLM_MODEL_NOT_FOUND = "llm_model_not_found"
    LLM_SERVER_ERROR = "llm_server_error"
    LLM_BAD_REQUEST = "llm_bad_request"
    LLM_CONTEXT_TOO_LONG = "llm_context_too_long"

    # ---------- Embedding 记忆模型 ----------
    EMBED_AUTH_INVALID = "embed_auth_invalid"
    EMBED_QUOTA_EXHAUSTED = "embed_quota_exhausted"
    EMBED_TIMEOUT = "embed_timeout"
    EMBED_SERVER_ERROR = "embed_server_error"

    # ---------- 网络 / 代理 ----------
    NETWORK_OFFLINE = "network_offline"
    NETWORK_SSL_ERROR = "network_ssl_error"
    NETWORK_PROXY = "network_proxy"
    NETWORK_DNS_FAIL = "network_dns_fail"

    # ---------- 工具层 ----------
    TOOL_HTTP_FAILURE = "tool_http_failure"
    TOOL_MCP_FAILURE = "tool_mcp_failure"
    TOOL_UNKNOWN = "tool_unknown"

    # ---------- 存储/配置 ----------
    MEMORY_CHROMA = "memory_chroma"
    CONFIG_MISSING_LLM_KEY = "config_missing_llm_key"
    CONFIG_MISSING_EMBED_KEY = "config_missing_embed_key"

    # ---------- Graph / 未知 ----------
    GRAPH_NODE_ERROR = "graph_node_error"
    UNKNOWN = "unknown"


class AgentError(Exception):
    """
    Agent 结构化异常 —— 面向用户的错误

    Attributes:
        code:         ErrorCode 枚举值，程序判断错误类型用这个
        user_message: 宠物对主人说的一句话 (短，友好)
        action_hint:  建议主人做什么操作 (中等长度，一句话)
        emotion:      说这句话时的宠物表情 Emotion (字符串，兼容旧版)
        original:     原始异常文本，打 log 用，不展示给用户
    """

    def __init__(
        self,
        code: ErrorCode,
        user_message: str,
        action_hint: str = "",
        emotion: str = "confused",
        original: str = "",
    ):
        self.code = code
        self.user_message = user_message
        self.action_hint = action_hint
        self.emotion = emotion
        self.original = original
        super().__init__(f"[{code.value}] {user_message}")

    def full_text(self, separator: str = "\n") -> str:
        """组装展示给用户的完整文本（消息 + 建议）"""
        if self.action_hint:
            return f"{self.user_message}{separator}{self.action_hint}"
        return self.user_message

    # ====================================================================
    # 分类器
    # ====================================================================
    @classmethod
    def classify(cls, exc: BaseException) -> "AgentError":
        """
        根据原始异常推断最准确的错误分类并返回 AgentError

        工作方式 (按优先级)：
          1. 异常类型名精确匹配 (AuthenticationError / APIStatusError / ...)
          2. 异常 message 正则命中关键字 (如 "Your api key" "invalid")
          3. 兜底 UNKNOWN
        """
        exc_name = type(exc).__name__
        exc_msg = str(exc)

        # 已经是 AgentError，原样返回
        if isinstance(exc, AgentError):
            return exc

        # ------- 1. 先看异常类型（LangChain/OpenAI SDK 都会抛命名明确的异常） -------
        # 小工具：判断 message 里是否有 embedding/dashscope 上下文
        # （memory/store._embed() 抛出时会加 [embedding/dashscope] 前缀，借此分流）
        def _is_embed_msg(m: str) -> bool:
            return _contains(m, "embed|embedding|qwen.*text|dashscope")

        # LLM 鉴权类
        if "AuthenticationError" in exc_name:
            if _contains(exc_msg, "expired|过期|已失效|exhausted"):
                if _is_embed_msg(exc_msg):
                    return cls._build(ErrorCode.EMBED_AUTH_INVALID, original=exc_msg)
                return cls._build(ErrorCode.LLM_AUTH_EXPIRED, original=exc_msg)
            if _is_embed_msg(exc_msg):
                return cls._build(ErrorCode.EMBED_AUTH_INVALID, original=exc_msg)
            return cls._build(ErrorCode.LLM_AUTH_INVALID, original=exc_msg)

        if "PermissionDeniedError" in exc_name or "Forbidden" in exc_name:
            if _is_embed_msg(exc_msg):
                return cls._build(ErrorCode.EMBED_AUTH_INVALID, original=exc_msg)
            return cls._build(ErrorCode.LLM_AUTH_INVALID, original=exc_msg)

        # LLM 配额 / 限流
        if "RateLimitError" in exc_name:
            if _contains(exc_msg, "quota|余额|insufficient|用完|额度"):
                if _is_embed_msg(exc_msg):
                    return cls._build(ErrorCode.EMBED_QUOTA_EXHAUSTED, original=exc_msg)
                return cls._build(ErrorCode.LLM_QUOTA_EXHAUSTED, original=exc_msg)
            if _is_embed_msg(exc_msg):
                # embedding 侧没有单独的 RATE_LIMIT，复用额度/超时相近语义的提示？
                # 这里统一归到 EMBED_SERVER_ERROR (服务端限流本质也是服务端问题)
                return cls._build(ErrorCode.EMBED_SERVER_ERROR, original=exc_msg)
            return cls._build(ErrorCode.LLM_RATE_LIMIT, original=exc_msg)

        # LLM 模型不存在 / URL 错
        if "NotFoundError" in exc_name:
            return cls._build(ErrorCode.LLM_MODEL_NOT_FOUND, original=exc_msg)

        # LLM 上下文超长
        if "ContentTooLongError" in exc_name or "context_length_exceeded" in exc_msg:
            return cls._build(ErrorCode.LLM_CONTEXT_TOO_LONG, original=exc_msg)

        # LLM 服务端 5xx
        if "InternalServerError" in exc_name or "APIConnectionError" in exc_name:
            if _is_embed_msg(exc_msg):
                return cls._build(ErrorCode.EMBED_SERVER_ERROR, original=exc_msg)
            return cls._build(ErrorCode.LLM_SERVER_ERROR, original=exc_msg)

        if "BadRequestError" in exc_name or "InvalidRequestError" in exc_name:
            if _contains(exc_msg, "context_length|max_tokens|token limit"):
                return cls._build(ErrorCode.LLM_CONTEXT_TOO_LONG, original=exc_msg)
            if _is_embed_msg(exc_msg):
                return cls._build(ErrorCode.EMBED_SERVER_ERROR, original=exc_msg)
            return cls._build(ErrorCode.LLM_BAD_REQUEST, original=exc_msg)

        # 超时类（aiohttp ClientTimeout / asyncio.TimeoutError / LangChain Timeout）
        if exc_name in ("TimeoutError", "asyncio.TimeoutError", "ClientTimeoutError") or "Timeout" in exc_name:
            if _contains(exc_msg, "embed|embedding|qwen.*text|dashscope"):
                return cls._build(ErrorCode.EMBED_TIMEOUT, original=exc_msg)
            return cls._build(ErrorCode.LLM_TIMEOUT, original=exc_msg)

        # ChromaDB
        chroma_err = _contains_exc_name(exc, ("ChromaError", "NoIndexException"))
        if "Chroma" in exc_name or chroma_err:
            return cls._build(ErrorCode.MEMORY_CHROMA, original=exc_msg)

        # aiohttp / HTTP 连接错误
        http_err = _contains_exc_name(
            exc,
            (
                "ClientConnectorError", "ClientOSError", "ClientPayloadError",
                "ServerDisconnectedError", "InvalidURL",
            ),
        )
        if http_err:
            if _contains(exc_msg, "nodename nor servname provided|getaddrinfo failed|DNS|Name or service"):
                return cls._build(ErrorCode.NETWORK_DNS_FAIL, original=exc_msg)
            if _contains(exc_msg, "SSL|certificate|certificate verify|CERTIFICATE_VERIFY_FAILED"):
                return cls._build(ErrorCode.NETWORK_SSL_ERROR, original=exc_msg)
            if _contains(exc_msg, "proxy|tunnel|connection refused|actively refused"):
                return cls._build(ErrorCode.NETWORK_PROXY, original=exc_msg)
            if _contains(exc_msg, "Network is unreachable|offline|ENETUNREACH"):
                return cls._build(ErrorCode.NETWORK_OFFLINE, original=exc_msg)
            return cls._build(ErrorCode.TOOL_HTTP_FAILURE, original=exc_msg)

        # MCP
        if "MCP" in exc_name or "MCPClient" in exc_msg:
            return cls._build(ErrorCode.TOOL_MCP_FAILURE, original=exc_msg)

        # ------- 2. 类型没命中，看 message 关键词 -------
        if _contains(exc_msg, "api key.*invalid|Your api key.*invalid|鉴权失败|authentication fails"):
            if _contains(exc_msg, "embed|embedding|dashscope"):
                return cls._build(ErrorCode.EMBED_AUTH_INVALID, original=exc_msg)
            return cls._build(ErrorCode.LLM_AUTH_INVALID, original=exc_msg)

        if _contains(exc_msg, "quota|额度.*用完|余额不足|insufficient.*balance|credit.*exhausted"):
            if _contains(exc_msg, "embed|embedding"):
                return cls._build(ErrorCode.EMBED_QUOTA_EXHAUSTED, original=exc_msg)
            return cls._build(ErrorCode.LLM_QUOTA_EXHAUSTED, original=exc_msg)

        if _contains(exc_msg, "rate limit|too many requests|429|过于频繁|限流"):
            return cls._build(ErrorCode.LLM_RATE_LIMIT, original=exc_msg)

        if _contains(exc_msg, "timeout|timed out|request time out"):
            if _contains(exc_msg, "embed|embedding"):
                return cls._build(ErrorCode.EMBED_TIMEOUT, original=exc_msg)
            return cls._build(ErrorCode.LLM_TIMEOUT, original=exc_msg)

        if _contains(exc_msg, "model.*not found|does not exist|不存在.*模型|模型.*不存在"):
            return cls._build(ErrorCode.LLM_MODEL_NOT_FOUND, original=exc_msg)

        if _contains(exc_msg, "SSL|certificate|证书"):
            return cls._build(ErrorCode.NETWORK_SSL_ERROR, original=exc_msg)

        if _contains(exc_msg, "nodename nor servname provided|getaddrinfo failed|DNS|Name or service"):
            return cls._build(ErrorCode.NETWORK_DNS_FAIL, original=exc_msg)

        if _contains(exc_msg, "refused|代理|proxy|tunnel|无法连接"):
            return cls._build(ErrorCode.NETWORK_PROXY, original=exc_msg)

        if _contains(exc_msg, "No network|Network is unreachable|offline|无网络|ENETUNREACH"):
            return cls._build(ErrorCode.NETWORK_OFFLINE, original=exc_msg)

        # ------- 3. 兜底 -------
        logger.debug(f"[AgentError.classify] 未命中分类: {exc_name}: {exc_msg[:120]}")
        return cls._build(ErrorCode.UNKNOWN, original=exc_msg)

    # ====================================================================
    # 内部辅助
    # ====================================================================
    @classmethod
    def _build(cls, code: ErrorCode, original: str = "") -> "AgentError":
        tpl = _TEMPLATES.get(code, _TEMPLATES[ErrorCode.UNKNOWN])
        return cls(
            code=code,
            user_message=tpl["user_message"],
            action_hint=tpl["action_hint"],
            emotion=tpl["emotion"],
            original=original,
        )


# ============================================================
# 枚举 → (用户消息 / 操作建议 / 表情)
# ============================================================
_TEMPLATES: dict[ErrorCode, dict] = {
    # ---------- LLM ----------
    ErrorCode.LLM_AUTH_INVALID: {
        "user_message": "哎呀，对话模型的 API Key 好像不对哦……",
        "action_hint": "右键我 → 设置 → 对话模型 → 检查 API Key 是否复制正确了。",
        "emotion": "confused",
    },
    ErrorCode.LLM_AUTH_EXPIRED: {
        "user_message": "对话模型的 API Key 过期啦，呜呜……",
        "action_hint": "右键我 → 设置 → 对话模型 → 换一个新的 API Key 吧。",
        "emotion": "sad",
    },
    ErrorCode.LLM_QUOTA_EXHAUSTED: {
        "user_message": "对话模型的额度用光了……我暂时说不出话啦。",
        "action_hint": "右键我 → 设置 → 对话模型 → 换一个模型或给当前账号充值额度。",
        "emotion": "sad",
    },
    ErrorCode.LLM_RATE_LIMIT: {
        "user_message": "请求太频繁啦，模型把我限流了……",
        "action_hint": "稍等 30 秒再跟我说话就好了，或者在设置里换个备用模型。",
        "emotion": "sleep",
    },
    ErrorCode.LLM_TIMEOUT: {
        "user_message": "我脑袋卡啦，网络有点慢或者模型那边排队……",
        "action_hint": "过一会儿再试一次；如果频繁出现，在设置里换一个更快的模型。",
        "emotion": "confused",
    },
    ErrorCode.LLM_MODEL_NOT_FOUND: {
        "user_message": "设置里选的对话模型，服务端说不认识它诶……",
        "action_hint": "右键我 → 设置 → 对话模型 → 确认模型名是否写对，或换官方推荐的模型。",
        "emotion": "confused",
    },
    ErrorCode.LLM_SERVER_ERROR: {
        "user_message": "对话模型服务端出了点小状况……",
        "action_hint": "等几分钟再试，或去设置里换个备用模型。",
        "emotion": "sad",
    },
    ErrorCode.LLM_BAD_REQUEST: {
        "user_message": "发出去的请求格式不对……我有点懵。",
        "action_hint": "试试重新开启对话；如果反复出现，检查设置里 API 地址/模型是否匹配。",
        "emotion": "confused",
    },
    ErrorCode.LLM_CONTEXT_TOO_LONG: {
        "user_message": "我们聊得太久啦，一次装不下这么多内容……",
        "action_hint": "试试清空对话历史再重新问，或者问短一点的问题。",
        "emotion": "confused",
    },

    # ---------- Embedding ----------
    ErrorCode.EMBED_AUTH_INVALID: {
        "user_message": "记忆模型的 API Key 不对哦，我记不住新东西啦……",
        "action_hint": "右键我 → 设置 → 记忆模型 → 检查 Embedding API Key 是否正确。",
        "emotion": "confused",
    },
    ErrorCode.EMBED_QUOTA_EXHAUSTED: {
        "user_message": "记忆模型的额度用完啦，暂时不能记新东西。",
        "action_hint": "右键我 → 设置 → 记忆模型 → 换个 API Key 或给当前账号充值。",
        "emotion": "sad",
    },
    ErrorCode.EMBED_TIMEOUT: {
        "user_message": "记忆模型那边响应有点慢……",
        "action_hint": "过会儿再试一次；频繁出现的话，在设置里换个记忆模型或 API 地址。",
        "emotion": "sleep",
    },
    ErrorCode.EMBED_SERVER_ERROR: {
        "user_message": "记忆模型服务端出了点小状况……",
        "action_hint": "稍等重试，或换个备用 Embedding 模型。",
        "emotion": "sad",
    },

    # ---------- 网络 ----------
    ErrorCode.NETWORK_OFFLINE: {
        "user_message": "好像没网了？我喊不到 AI 小姐姐了……",
        "action_hint": "检查一下电脑 Wi-Fi / 有线网络是否连通，能不能正常上网。",
        "emotion": "sad",
    },
    ErrorCode.NETWORK_DNS_FAIL: {
        "user_message": "DNS 解析失败，我找不到模型服务器在哪里……",
        "action_hint": "检查是否挂了 VPN / 代理，或把 DNS 改成 8.8.8.8 / 223.5.5.5 再试。",
        "emotion": "confused",
    },
    ErrorCode.NETWORK_SSL_ERROR: {
        "user_message": "HTTPS 证书校验失败了，网络环境好像怪怪的……",
        "action_hint": "如果你在公司网络 / 抓包软件下，看看是否需要加 CA 证书；或者换个网络环境。",
        "emotion": "confused",
    },
    ErrorCode.NETWORK_PROXY: {
        "user_message": "代理端口好像连不上哦……",
        "action_hint": "检查系统代理 / VPN 是否正常工作；关了代理再试试也可以。",
        "emotion": "confused",
    },

    # ---------- 工具 ----------
    ErrorCode.TOOL_HTTP_FAILURE: {
        "user_message": "工具请求没成功，好像是网络连接的问题……",
        "action_hint": "稍等几秒再试；如果还是不行，检查当前能不能访问那个工具的网页。",
        "emotion": "confused",
    },
    ErrorCode.TOOL_MCP_FAILURE: {
        "user_message": "外接工具出了点小问题……",
        "action_hint": "确认 Node.js 和 npx 是否安装好，或到日志里看 MCP Server 的启动报错。",
        "emotion": "confused",
    },
    ErrorCode.TOOL_UNKNOWN: {
        "user_message": "那个工具我调不动诶……",
        "action_hint": "过会儿再试，或让主人查看一下日志里的详细报错。",
        "emotion": "sad",
    },

    # ---------- 存储 / 配置 ----------
    ErrorCode.MEMORY_CHROMA: {
        "user_message": "我的记忆盒子坏了，存不了新东西……",
        "action_hint": "试试重启应用；如果仍有问题，到设置里清一下记忆数据库。",
        "emotion": "sad",
    },
    ErrorCode.CONFIG_MISSING_LLM_KEY: {
        "user_message": "对话模型还没配置好呢，现在不能陪主人聊天……",
        "action_hint": "右键我 → 设置 → 对话模型 → 把 API Key 和模型名填上保存。",
        "emotion": "confused",
    },
    ErrorCode.CONFIG_MISSING_EMBED_KEY: {
        "user_message": "记忆模型的 API Key 还没填哦，我记不住新东西……",
        "action_hint": "右键我 → 设置 → 记忆模型 → 把 Embedding API Key 填上保存。",
        "emotion": "confused",
    },

    # ---------- Graph / 未知 ----------
    ErrorCode.GRAPH_NODE_ERROR: {
        "user_message": "脑子里某个零件卡住了……",
        "action_hint": "重新问一遍试试；如果反复出现，就重启一下暖宝吧。",
        "emotion": "sad",
    },
    ErrorCode.UNKNOWN: {
        "user_message": "呜……出了点我也说不清的问题。",
        "action_hint": "重新问一次试试；还是不行的话，让主人看看 logs 里的详细报错吧。",
        "emotion": "sad",
    },
}


# ============================================================
# 工具函数
# ============================================================

_MATCH_CACHE: dict[str, re.Pattern] = {}


def _contains(text: str, pattern: str) -> bool:
    """正则匹配，忽略大小写；pattern 用 | 分隔多个词"""
    if not text:
        return False
    if pattern not in _MATCH_CACHE:
        _MATCH_CACHE[pattern] = re.compile(pattern, re.IGNORECASE)
    return _MATCH_CACHE[pattern].search(text) is not None


def _contains_exc_name(exc: BaseException, names: tuple[str, ...]) -> bool:
    """异常类名(含父类链) 是否匹配任何一个给定名字前缀"""
    for cls in type(exc).__mro__:
        name = getattr(cls, "__name__", "")
        for n in names:
            if n in name:
                return True
    return False
