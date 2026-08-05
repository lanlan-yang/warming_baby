"""
tools/http_client - 共享的异步 HTTP 客户端

特性：
- 复用同一个 ClientSession（单例）
- 自动重试 3 次（指数退避）
- 只对可重试错误重试（5xx、429、超时、连接错误）
- 业务错误（400/401/404）不重试

Usage:
    from tools.http_client import http_get, http_post

    async def fetch():
        return await http_get("https://api.example.com/data")
"""
import asyncio

import aiohttp
from aiohttp import ClientError, ClientResponseError

from core.logger import setup_logger

logger = setup_logger()

# ============================================================================
# 配置
# ============================================================================
MAX_RETRIES = 3
INITIAL_DELAY = 1.0  # 初始延迟 1 秒
MAX_DELAY = 10.0  # 最大延迟 10 秒
TIMEOUT = 10

# 可重试的 HTTP 状态码
RETRYABLE_STATUS = {500, 502, 503, 504, 429}

# 不可重试的 HTTP 状态码（业务错误）
NON_RETRYABLE_STATUS = {400, 401, 403, 404, 405, 422}


# ============================================================================
# Client 管理
# ============================================================================
_client: aiohttp.ClientSession | None = None


def get_http_client() -> aiohttp.ClientSession:
    """获取共享的 ClientSession（单例）"""
    global _client
    if _client is None or _client.closed:
        _client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT))
        logger.info("[HttpClient] 创建新的 ClientSession")
    return _client


async def close_http_client() -> None:
    """关闭共享的 ClientSession"""
    global _client
    if _client and not _client.closed:
        await _client.close()
        logger.info("[HttpClient] ClientSession 已关闭")
    _client = None


# ============================================================================
# 重试判断
# ============================================================================
def _is_retryable_error(error: Exception) -> bool:
    """
    判断错误是否可重试

    可重试：
    - 5xx 服务端错误
    - 429 限流
    - 超时错误
    - 连接错误

    不可重试：
    - 400/401/403/404 等业务错误
    """
    if isinstance(error, ClientResponseError):
        # HTTP 响应错误
        status = error.status
        if status in RETRYABLE_STATUS:
            return True
        if status in NON_RETRYABLE_STATUS:
            return False
        # 其他状态码（如 408）默认不重试
        return False
    
    if isinstance(error, (aiohttp.ServerTimeoutError, asyncio.TimeoutError)):
        # 超时错误
        return True
    
    if isinstance(error, ClientError):
        # 连接错误（连接被拒绝、DNS 失败等）
        return True
    
    return False


async def _execute_with_retry(method: str, url: str, **kwargs) -> str:
    """
    带重试的 HTTP 请求

    Args:
        method: HTTP 方法 (GET/POST)
        url: 请求地址
        **kwargs: 传递给 aiohttp 的额外参数

    Returns:
        响应文本

    Raises:
        最后一次重试的异常（如果所有重试都失败）
    """
    client = get_http_client()
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with client.request(method, url, **kwargs) as resp:
                # 让 aiohttp 自动抛出 ClientResponseError (对非 2xx 状态码)
                resp.raise_for_status()
                return await resp.text()

        except Exception as e:
            last_error = e
            
            if not _is_retryable_error(e):
                # 不可重试的错误，直接抛出
                logger.warning(f"[HttpClient] 不可重试错误: {e}")
                raise

            if attempt < MAX_RETRIES:
                # 计算指数退避延迟
                delay = min(INITIAL_DELAY * (2 ** attempt), MAX_DELAY)
                logger.warning(
                    f"[HttpClient] 请求失败 (第 {attempt + 1}/{MAX_RETRIES} 次): {e}, "
                    f"{delay:.1f}s 后重试..."
                )
                await asyncio.sleep(delay)
            else:
                # 所有重试都失败
                logger.error(
                    f"[HttpClient] 请求最终失败 (已重试 {MAX_RETRIES} 次): {e}"
                )

    # 所有重试都失败，抛出最后一个错误
    raise last_error


# ============================================================================
# 简化的 API
# ============================================================================
async def http_get(url: str, headers: dict | None = None) -> str:
    """
    异步 GET 请求（带重试）

    Args:
        url: 请求地址
        headers: 请求头

    Returns:
        响应文本

    Raises:
        ClientError: 所有重试都失败
    """
    return await _execute_with_retry("GET", url, headers=headers)


async def http_post(url: str, json: dict | None = None, headers: dict | None = None) -> str:
    """
    异步 POST 请求（带重试）

    Args:
        url: 请求地址
        json: JSON body
        headers: 请求头

    Returns:
        响应文本

    Raises:
        ClientError: 所有重试都失败
    """
    return await _execute_with_retry("POST", url, json=json, headers=headers)
