"""
tools/tool_location - 获取地理位置的工具

使用 UAPI 获取用户当前位置。

UAPI 文档: https://uapis.cn/docs/api-reference/get-network-myip

Usage:
    from tools.tool_location import register_location_tools
    register_location_tools()  # 在 app.py 预热阶段调用
"""
import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

from pydantic import Field

from tools.tool_base import AgentTool, BaseToolArgs, tool_registry
from core.logger import logger


# ============================================================================
# 1. 数据结构
# ============================================================================
@dataclass
class Location:
    """地理位置数据"""
    country: str = ""
    region: str = ""  # 省份
    city: str = ""
    district: str = ""  # 区县
    adcode: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    timezone: str = "Asia/Shanghai"
    isp: str = ""
    ip: str = ""
    source: str = ""

    def to_prompt_text(self) -> str:
        """转换为 LLM 易读的文本"""
        parts = []
        if self.country:
            parts.append(self.country)
        if self.region:
            parts.append(self.region)
        if self.city:
            parts.append(self.city)
        if self.district:
            parts.append(self.district)
        if self.lat is not None and self.lon is not None:
            parts.append(f"({self.lat:.4f}, {self.lon:.4f})")
        location_str = " ".join(parts) if parts else "未知"
        return f"用户地理位置：{location_str}，时区：{self.timezone}"


# ============================================================================
# 2. 参数定义
# ============================================================================

class GetCurrentLocationArgs(BaseToolArgs):
    """获取当前位置参数（无参数）"""
    pass


class GetLocationByCityArgs(BaseToolArgs):
    """根据城市名获取位置参数"""
    city: str = Field(description="城市名称，如'成都'、'北京'、'上海'")


# ============================================================================
# 3. UAPI 配置
# ============================================================================

UAPI_BASE_URL = "https://uapis.cn/api/v1"


def get_uapi_key() -> str:
    """获取 UAPI Key"""
    key = os.environ.get("UAPI_PRO_API_KEY", "")
    if not key:
        # 尝试从 .env 文件加载
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if line.startswith('UAPI_PRO_API_KEY='):
                        key = line.split('=', 1)[1].strip().strip('"').strip("'")
                        break
    return key


# ============================================================================
# 4. LocationService - 核心服务类
# ============================================================================
class LocationService:
    """位置服务 - 使用 UAPI"""

    def __init__(self, cache_ttl: int = 1800):
        """
        初始化位置服务

        Args:
            cache_ttl: 缓存时间（秒），默认 30 分钟
        """
        self.cache_ttl = cache_ttl
        self._cached_location: Optional[Location] = None
        self._last_update: float = 0
        self._uapi_key = get_uapi_key()

        if not self._uapi_key:
            logger.warning("[Location] 未配置 UAPI_PRO_API_KEY，位置服务将不可用")
        else:
            logger.info("[Location] UAPI 已配置")

    async def get_current(self) -> Optional[Location]:
        """
        获取当前位置

        优先使用缓存，缓存过期后重新获取。

        Returns:
            Location: 位置信息，失败返回 None
        """
        if not self._uapi_key:
            logger.warning("[Location] 无 API Key，无法获取位置")
            return None

        now = time.time()
        if self._cached_location and (now - self._last_update) < self.cache_ttl:
            logger.debug(f"[Location] 使用缓存位置: {self._cached_location.city}")
            return self._cached_location

        location = await self._get_by_ip()

        if location:
            self._cached_location = location
            self._last_update = now
            logger.info(f"[Location] 位置获取成功: {location.region} {location.city}")

        return location

    async def get_by_city(self, city_name: str) -> Optional[Location]:
        """
        根据城市名获取位置（公开方法）

        Args:
            city_name: 城市名，如 "成都"、"北京"

        Returns:
            Location: 位置信息，失败返回 None
        """
        return await self._get_by_city(city_name)

    async def _get_by_ip(self) -> Optional[Location]:
        """
        通过 IP 获取当前位置

        UAPI myip 接口直接返回：
        - region: "中国 四川 成都"
        - lat/lng
        - isp

        Returns:
            Location: 位置信息
        """
        try:
            url = f"{UAPI_BASE_URL}/network/myip"
            headers = {"Authorization": f"Bearer {self._uapi_key}"}
            response = await self._http_get(url, headers=headers)
            data = json.loads(response)

            # 解析 region: "中国 四川 成都"
            region_str = data.get("region", "")
            region_parts = region_str.split() if region_str else []

            country = "中国"
            province = ""
            city = ""

            if len(region_parts) >= 3:
                country = region_parts[0]
                province = region_parts[1]
                city = region_parts[2]
            elif len(region_parts) >= 2:
                country = region_parts[0]
                city = region_parts[1]
            elif len(region_parts) >= 1:
                city = region_parts[0]

            # 解析 IP 范围
            ip = data.get("ip", "")

            # 获取经纬度
            lat = data.get("latitude")
            lon = data.get("longitude")

            # 获取运营商
            isp = data.get("isp", "")

            if not city:
                logger.warning("[Location] IP 定位返回空的城市信息")
                return None

            location = Location(
                country=country,
                region=province,
                city=city,
                lat=lat,
                lon=lon,
                isp=isp,
                ip=ip,
                source="uapi_myip",
            )

            logger.info(f"[Location] IP 定位成功: {province} {city}")
            return location

        except Exception as e:
            logger.error(f"[Location] IP 定位异常: {e}")
            return None

    async def _get_by_city(self, city_name: str) -> Optional[Location]:
        """
        根据城市名获取位置

        使用 UAPI 天气接口获取城市信息，因为它直接返回 adcode、经纬度等。

        Args:
            city_name: 城市名

        Returns:
            Location: 位置信息
        """
        try:
            import urllib.parse
            url = f"{UAPI_BASE_URL}/misc/weather?city={urllib.parse.quote(city_name)}"
            headers = {"Authorization": f"Bearer {self._uapi_key}"}
            response = await self._http_get(url, headers=headers)
            data = json.loads(response)

            province = data.get("province", "")
            city = data.get("city", "") or city_name
            district = data.get("district", "")
            adcode = data.get("adcode", "")

            # 从天气接口获取经纬度（如果有的话）
            lat = None
            lon = None

            location = Location(
                country="中国",
                region=province,
                city=city,
                district=district,
                adcode=adcode,
                lat=lat,
                lon=lon,
                source="uapi_weather",
            )

            logger.info(f"[Location] 城市定位成功: {city}")
            return location

        except Exception as e:
            logger.error(f"[Location] 城市定位异常: {e}")
            return None

    async def _http_get(self, url: str, headers: Optional[dict] = None, timeout: int = 5) -> str:
        """异步 HTTP GET 请求"""
        import asyncio

        default_headers = {"User-Agent": "WarmingBaby/1.0"}
        if headers:
            default_headers.update(headers)

        def _sync_get(u: str, h: dict) -> str:
            req = urllib.request.Request(u, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")

        return await asyncio.to_thread(_sync_get, url, default_headers)


# ============================================================================
# 5. 工具实现
# ============================================================================

class GetCurrentLocationTool(AgentTool):
    """
    获取当前网络位置

    使用 UAPI 直接从 IP 获取位置信息，准确且稳定。
    无需参数，自动根据网络 IP 定位。
    """

    name: str = "get_current_location"
    description: str = (
        "获取用户当前的网络位置（城市、省份、经纬度）。\n"
        "【重要】当需要知道用户在哪里时调用此工具，例如：\n"
        "- 查询天气时需要知道城市\n"
        "- 用户问'你知道我在哪里吗'\n"
        "- 任何需要位置信息的场景\n"
        "无需参数，自动根据网络 IP 定位。"
    )
    args_schema: type[BaseToolArgs] = GetCurrentLocationArgs

    def __init__(self, location_service: Optional[LocationService] = None):
        super().__init__()
        self._location_service = location_service or LocationService()

    async def _execute(self) -> str:
        """获取当前位置"""
        if not self._location_service._uapi_key:
            return "抱歉，位置服务未配置"

        location = await self._location_service.get_current()

        if location and location.city:
            parts = [
                f"【当前位置】",
                f"国家: {location.country}",
                f"省份: {location.region}",
                f"城市: {location.city}",
            ]
            if location.district:
                parts.append(f"区县: {location.district}")
            if location.lat is not None and location.lon is not None:
                parts.append(f"坐标: {location.lat}, {location.lon}")
            if location.isp:
                parts.append(f"运营商: {location.isp}")
            return "\n".join(parts)
        else:
            return "抱歉，无法获取您的位置信息，请检查网络连接"


class GetLocationByCityTool(AgentTool):
    """
    根据城市名获取位置详情

    获取指定城市的位置信息。
    """

    name: str = "get_location_by_city"
    description: str = (
        "根据城市名称获取该城市的位置详情。\n"
        "参数 city 是城市名称，如'成都'、'北京'、'上海'。\n"
        "用于确认城市位置。"
    )
    args_schema: type[BaseToolArgs] = GetLocationByCityArgs

    def __init__(self, location_service: Optional[LocationService] = None):
        super().__init__()
        self._location_service = location_service or LocationService()

    async def _execute(self, city: str) -> str:
        """根据城市名获取位置"""
        if not self._location_service._uapi_key:
            return "抱歉，位置服务未配置"

        location = await self._location_service.get_by_city(city)

        if location and location.city:
            parts = [
                f"【位置信息】{city}",
                f"省份: {location.region}",
                f"城市: {location.city}",
            ]
            if location.district:
                parts.append(f"区县: {location.district}")
            if location.adcode:
                parts.append(f"adcode: {location.adcode}")
            return "\n".join(parts)
        else:
            return f"抱歉，无法找到'{city}'这个城市，请检查城市名称是否正确"


# ============================================================================
# 6. 单例 LocationService
# ============================================================================

_location_service_instance: Optional[LocationService] = None


def get_location_service() -> LocationService:
    """获取全局 LocationService 单例"""
    global _location_service_instance
    if _location_service_instance is None:
        _location_service_instance = LocationService()
    return _location_service_instance


# ============================================================================
# 7. 注册入口
# ============================================================================

def register_location_tools() -> list[AgentTool]:
    """
    注册位置工具到 ToolRegistry

    Returns:
        注册的工具列表

    使用位置: app.py 的预热阶段
    """
    service = get_location_service()

    current_location_tool = GetCurrentLocationTool(location_service=service)
    city_location_tool = GetLocationByCityTool(location_service=service)

    tool_registry.register(current_location_tool)
    tool_registry.register(city_location_tool)

    logger.info(f"[LocationTools] 已注册: {current_location_tool.name}, {city_location_tool.name}")
    return [current_location_tool, city_location_tool]
