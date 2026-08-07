"""
tools/tool_location - 位置工具（异步）

使用 uapis.cn /api/v1/network/myip 获取用户 IP 位置。
使用 aiohttp 异步请求，复用共享的 ClientSession。

缓存策略：
- 使用 @cache 装饰器
- 缓存时间：1小时（位置变化不频繁）
- 缓存名称：location

不需要 API Key，直接调用即可。

Usage:
    from tools.tool_location import get_current_location
    # 直接给 llm.bind_tools([get_current_location]) 用
"""
import json

from aiohttp import ClientError

from langchain_core.tools import tool

from core.logger import setup_logger
from tools.http_client import http_get
from tools.cache import cache

logger = setup_logger()

LOCATION_API_URL = "https://uapis.cn/api/v1/network/myip"


@tool(description="获取用户当前的网络位置（IP定位）。当你需要知道用户在哪里时调用。")
@cache(ttl=3600, cache_name="location")  # 1小时缓存
async def get_current_location() -> str:
    """获取用户当前的网络位置"""
    logger.info("[get_current_location] 调用")

    try:
        data = json.loads(await http_get(LOCATION_API_URL))

        region_parts = data.get("region", "").split()
        country = region_parts[0] if len(region_parts) >= 1 else "中国"
        province = region_parts[1] if len(region_parts) >= 2 else ""
        city = region_parts[2] if len(region_parts) >= 3 else (region_parts[1] if len(region_parts) >= 2 else "")

        if not city:
            return "抱歉，无法获取您的位置信息"

        lines = [f"【当前位置】", f"国家: {country}"]
        if province:
            lines.append(f"省份: {province}")
        lines.append(f"城市: {city}")
        if data.get("latitude") and data.get("longitude"):
            lines.append(f"坐标: {data['latitude']}, {data['longitude']}")
        
        result = "\n".join(lines)
        logger.info(f"[get_current_location] 完成: {province} {city}")
        return result

    except ClientError as e:
        logger.error(f"[get_current_location] 网络错误: {e}")
        return f"抱歉，网络请求失败: {e}"
    except Exception as e:
        logger.error(f"[get_current_location] 错误: {e}")
        return f"抱歉，获取位置失败: {e}"


class LocationInfo:
    """位置信息数据类"""
    def __init__(self, country: str = "", province: str = "", city: str = ""):
        self.country = country
        self.province = province
        self.city = city

    def to_prompt_text(self) -> str:
        """转换为 prompt 文本"""
        if self.city:
            return f"我所在的位置是{self.country}{self.province}{self.city}"
        elif self.province:
            return f"我所在的位置是{self.country}{self.province}"
        return f"我所在的位置是{self.country}"


class LocationService:
    """位置服务类 - 带缓存的位置获取"""
    
    def __init__(self):
        self._location_info = None

    @staticmethod
    @cache(ttl=3600, cache_name="location_service")  # 1小时缓存
    async def _fetch_location_data() -> dict:
        """
        获取原始位置数据（带缓存）
        
        Returns:
            原始位置数据字典
        """
        data = json.loads(await http_get(LOCATION_API_URL))
        return data

    async def get_current(self) -> LocationInfo:
        """获取当前位置（带缓存）"""
        try:
            data = await self._fetch_location_data()
            
            region_parts = data.get("region", "").split()
            country = region_parts[0] if len(region_parts) >= 1 else "中国"
            province = region_parts[1] if len(region_parts) >= 2 else ""
            city = region_parts[2] if len(region_parts) >= 3 else (
                region_parts[1] if len(region_parts) >= 2 else ""
            )

            self._location_info = LocationInfo(
                country=country,
                province=province,
                city=city
            )
            return self._location_info

        except Exception as e:
            logger.error(f"[LocationService] 获取位置失败: {e}")
            return LocationInfo()


def clear_location_cache():
    """清除位置缓存"""
    from tools.cache import clear_cache
    clear_cache("location")
    clear_cache("location_service")


def get_location_cache_info() -> dict:
    """获取位置缓存信息"""
    from tools.cache import get_cache_stats
    stats = get_cache_stats()
    return {
        "location": stats.get("location", {"size": 0, "ttl": 3600}),
        "location_service": stats.get("location_service", {"size": 0, "ttl": 3600}),
    }
