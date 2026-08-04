"""
tools.get_location - 获取当前位置信息的服务

通过 IP 地址获取地理位置信息（城市、国家、经纬度等）。
采用多服务降级 + 缓存策略，在 ChatAgent 启动时调用一次，
结果注入 system prompt 供 LLM 使用。

Usage:
    from tools.get_location import LocationService

    service = LocationService()
    location = await service.get_current()
    # location = {"country": "中国", "region": "四川", "city": "成都", ...}
"""
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional, Callable


# ============================================================================
# 数据结构
# ============================================================================
@dataclass
class Location:
    """地理位置数据"""
    country: str = ""
    region: str = ""
    city: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    timezone: str = ""
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
        if self.lat is not None and self.lon is not None:
            parts.append(f"({self.lat:.4f}, {self.lon:.4f})")
        location_str = " ".join(parts) if parts else "未知"
        return f"用户地理位置：{location_str}，时区：{self.timezone or '未知'}，运营商：{self.isp or '未知'}"


# ============================================================================
# 多服务配置（按优先级排序）
# ============================================================================
class _GeoProvider:
    """单个 IP 定位服务的配置"""

    def __init__(self, name: str, url_template: str, parser: Callable, user_agent: str = "curl/7.68.0", timeout: int = 5):
        self.name = name
        self.url_template = url_template
        self.parser = parser
        self.user_agent = user_agent
        self.timeout = timeout


_GEO_PROVIDERS: list[_GeoProvider] = [
    _GeoProvider(
        name="ipapi",
        url_template="https://ipapi.co/{ip}/json/",
        parser=lambda d: {
            "country": d.get("country_name", ""),
            "country_code": d.get("country_code", ""),
            "region": d.get("region", ""),
            "city": d.get("city", ""),
            "lat": d.get("latitude"),
            "lon": d.get("longitude"),
            "timezone": d.get("timezone", ""),
            "isp": d.get("org", "") or d.get("asn", ""),
        },
        user_agent="curl/7.68.0",
    ),
    _GeoProvider(
        name="ip.sb",
        url_template="https://api.ip.sb/geoip/{ip}",
        parser=lambda d: {
            "country": d.get("country", ""),
            "country_code": d.get("country_code", ""),
            "region": d.get("region", ""),
            "city": d.get("city", ""),
            "lat": d.get("latitude"),
            "lon": d.get("longitude"),
            "timezone": d.get("timezone", ""),
            "isp": d.get("isp", ""),
        },
    ),
    _GeoProvider(
        name="ip-api",
        url_template="http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,message,country,regionName,city,lat,lon,timezone,isp",
        parser=lambda d: {
            "country": d.get("country", ""),
            "country_code": "",
            "region": d.get("regionName", ""),
            "city": d.get("city", ""),
            "lat": d.get("lat"),
            "lon": d.get("lon"),
            "timezone": d.get("timezone", ""),
            "isp": d.get("isp", ""),
        },
    ),
    _GeoProvider(
        name="ipinfo",
        url_template="https://ipinfo.io/{ip}/json",
        parser=lambda d: {
            "country": "",
            "country_code": d.get("country", ""),
            "region": d.get("region", ""),
            "city": d.get("city", ""),
            "lat": float(d.get("loc", ",").split(",")[0]) if d.get("loc") else None,
            "lon": float(d.get("loc", ",").split(",")[1]) if d.get("loc") else None,
            "timezone": d.get("timezone", ""),
            "isp": d.get("org", ""),
        },
    ),
]

# 缓存: {ip: (timestamp, result_dict)}
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL: int = 300  # 5分钟

# 公网IP缓存
_PUBLIC_IP_CACHE: tuple[float, str] = (0, "")


# ============================================================================
# LocationService - 纯服务类
# ============================================================================
class LocationService:
    """
    位置服务 - 多源降级 + 缓存

    在 ChatAgent 启动时调用 get_current() 获取一次位置，
    后续通过 get_location_text() 注入 system prompt。
    """

    def __init__(self, cache_ttl: int = 1800):
        """
        Args:
            cache_ttl: 位置刷新间隔（秒），默认 30 分钟
        """
        self._cache_ttl = cache_ttl
        self._cached_location: Optional[Location] = None
        self._last_update: float = 0

    async def get_current(self) -> Optional[Location]:
        """
        获取当前位置（会缓存，超过 ttl 会刷新）

        Returns:
            Location: 位置信息，失败返回 None

        Example:
            service = LocationService()
            location = await service.get_current()
            if location:
                print(location.to_prompt_text())
        """
        now = time.time()
        if self._cached_location and (now - self._last_update) < self._cache_ttl:
            return self._cached_location

        location = await self._fetch_location()
        if location:
            self._cached_location = location
            self._last_update = now
        return location

    def get_prompt_text(self) -> str:
        """获取位置的 prompt 文本（同步，使用缓存值）"""
        if self._cached_location:
            return self._cached_location.to_prompt_text()
        return "用户位置：未知"

    # ---- 核心查询 ----
    async def _fetch_location(self) -> Optional[Location]:
        """获取位置"""
        ip = self._get_public_ip()
        if not ip:
            return None

        cached = self._get_cache(ip)
        if cached:
            return self._build_location(ip, cached, "cache")

        result, provider_name = self._query_with_fallback(ip)
        if not result:
            return None

        self._set_cache(ip, result)
        return self._build_location(ip, result, provider_name)

    def _query_with_fallback(self, ip: str) -> tuple[dict, str]:
        """按优先级依次尝试各服务"""
        for provider in _GEO_PROVIDERS:
            try:
                result = self._query_one(provider, ip)
                if result and result.get("city"):
                    return result, provider.name
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    continue
            except Exception:
                continue
        return {}, ""

    def _query_one(self, provider: _GeoProvider, ip: str) -> Optional[dict]:
        """查询单个服务"""
        url = provider.url_template.format(ip=ip)
        req = urllib.request.Request(url, headers={"User-Agent": provider.user_agent})
        response = urllib.request.urlopen(req, timeout=provider.timeout)
        data = json.loads(response.read())

        if provider.name == "ip-api" and data.get("status") != "success":
            return None
        return provider.parser(data)

    def _build_location(self, ip: str, raw: dict, source: str) -> Location:
        """从原始数据构建 Location"""
        country = raw.get("country", "") or raw.get("country_code", "")
        region = raw.get("region", "")
        city = raw.get("city", "")
        lat = raw.get("lat")
        lon = raw.get("lon")
        timezone = raw.get("timezone", "")
        isp = raw.get("isp", "")

        country = self._translate_country(country, raw.get("country_code", ""))
        region = self._translate_region(region, raw.get("country_code", ""))

        return Location(
            country=country,
            region=region,
            city=city,
            lat=float(lat) if lat else None,
            lon=float(lon) if lon else None,
            timezone=timezone,
            isp=isp,
            ip=ip,
            source=source,
        )

    # ---- 缓存管理 ----
    def _get_cache(self, ip: str) -> Optional[dict]:
        entry = _CACHE.get(ip)
        if not entry:
            return None
        timestamp, result = entry
        if time.time() - timestamp > _CACHE_TTL:
            _CACHE.pop(ip, None)
            return None
        return result

    def _set_cache(self, ip: str, result: dict) -> None:
        _CACHE[ip] = (time.time(), result)

    # ---- 公网 IP ----
    def _get_public_ip(self) -> str:
        """获取公网 IP（同步）"""
        global _PUBLIC_IP_CACHE
        now = time.time()
        cached_time, cached_ip = _PUBLIC_IP_CACHE
        if cached_ip and now - cached_time < 600:
            return cached_ip

        plain_text_services = [
            "https://ipv4.icanhazip.com",
            "https://ifconfig.me/ip",
        ]
        json_services = [
            ("https://api.ipify.org?format=json&ipv=4", lambda d: d.get("ip", "")),
            ("http://httpbin.org/ip", lambda d: d.get("origin", "")),
        ]

        for url in plain_text_services:
            ip = self._fetch_plain_text(url)
            if ip and self._is_valid_ipv4(ip) and self._is_public_ip(ip):
                _PUBLIC_IP_CACHE = (now, ip)
                return ip

        for url, parser in json_services:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
                response = urllib.request.urlopen(req, timeout=5)
                data = json.loads(response.read())
                ip = parser(data)
                if ip and self._is_valid_ipv4(ip) and self._is_public_ip(ip):
                    _PUBLIC_IP_CACHE = (now, ip)
                    return ip
            except Exception:
                continue

        return ""

    def _fetch_plain_text(self, url: str) -> str:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            response = urllib.request.urlopen(req, timeout=5)
            return response.read().decode().strip()
        except Exception:
            return ""

    # ---- 校验 ----
    @staticmethod
    def _is_public_ip(ip: str) -> bool:
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        a, b = int(parts[0]), int(parts[1])
        if a == 10:
            return False
        if a == 172 and 16 <= b <= 31:
            return False
        if a == 192 and b == 168:
            return False
        if a == 127:
            return False
        if a == 169 and b == 254:
            return False
        return True

    @staticmethod
    def _is_valid_ipv4(ip: str) -> bool:
        if not ip:
            return False
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

    # ---- 名称翻译 ----
    @staticmethod
    def _translate_country(country: str, country_code: str) -> str:
        country_map = {
            "China": "中国",
            "United States": "美国",
            "Japan": "日本",
            "Korea, Republic of": "韩国",
            "Korea, Democratic People's Republic of": "朝鲜",
            "United Kingdom": "英国",
            "Germany": "德国",
            "France": "法国",
            "Russia": "俄罗斯",
            "Singapore": "新加坡",
            "Australia": "澳大利亚",
            "Canada": "加拿大",
            "India": "印度",
            "Brazil": "巴西",
        }
        translated = country_map.get(country, country)
        if country_code == "CN" and translated != "中国":
            translated = "中国"
        return translated

    @staticmethod
    def _translate_region(region: str, country_code: str) -> str:
        if country_code != "CN":
            return region
        province_map = {
            "Beijing": "北京", "Shanghai": "上海", "Tianjin": "天津", "Chongqing": "重庆",
            "Guangdong": "广东", "Sichuan": "四川", "Yunnan": "云南", "Guizhou": "贵州",
            "Guangxi": "广西", "Hainan": "海南", "Fujian": "福建", "Jiangxi": "江西",
            "Zhejiang": "浙江", "Jiangsu": "江苏", "Anhui": "安徽", "Hubei": "湖北",
            "Hunan": "湖南", "Shandong": "山东", "Henan": "河南", "Hebei": "河北",
            "Shanxi": "山西", "Shaanxi": "陕西", "Inner Mongolia": "内蒙古",
            "Liaoning": "辽宁", "Jilin": "吉林", "Heilongjiang": "黑龙江",
            "Xinjiang": "新疆", "Tibet": "西藏", "Ningxia": "宁夏", "Qinghai": "青海",
        }
        return province_map.get(region, region)
