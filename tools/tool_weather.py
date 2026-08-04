"""
tools/tool_weather - UAPI 天气查询工具

使用 UAPI 天气接口查询国内城市天气。
支持实时天气、多天预报、生活指数等。

UAPI 文档: https://uapis.cn/docs/api-reference/get-misc-weather

Usage:
    from tools.tool_weather import register_weather_tools
    register_weather_tools()  # 在 app.py 预热阶段调用
"""

import json
import os
import time
import urllib.request
import urllib.parse
from typing import Optional

from pydantic import Field

from tools.tool_base import AgentTool, BaseToolArgs, tool_registry
from core.logger import logger


# ============================================================================
# 1. 参数定义
# ============================================================================

class GetWeatherArgs(BaseToolArgs):
    """天气查询参数"""
    city: str = Field(description="城市名称，如'成都'、'北京'、'上海'")


# ============================================================================
# 2. UAPI 配置
# ============================================================================

UAPI_BASE_URL = "https://uapis.cn/api/v1"


def get_uapi_key() -> str:
    """获取 UAPI Key"""
    key = os.environ.get("UAPI_PRO_API_KEY", "")
    if not key:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if line.startswith('UAPI_PRO_API_KEY='):
                        key = line.split('=', 1)[1].strip().strip('"').strip("'")
                        break
    return key


# 缓存配置
CACHE_TTL = 600  # 10 分钟
_weather_cache: dict[str, tuple[float, dict]] = {}


# ============================================================================
# 3. UAPI 天气客户端
# ============================================================================

def _http_get(url: str, headers: Optional[dict] = None, timeout: int = 5) -> str:
    """同步 HTTP GET 请求"""
    default_headers = {"User-Agent": "WarmingBaby/1.0"}
    if headers:
        default_headers.update(headers)
    
    req = urllib.request.Request(url, headers=default_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8")


async def _async_http_get(url: str, headers: Optional[dict] = None, timeout: int = 5) -> str:
    """异步 HTTP GET 请求"""
    import asyncio
    return await asyncio.to_thread(_http_get, url, headers, timeout)


async def fetch_weather(city: str, uapi_key: str) -> Optional[dict]:
    """
    获取实时天气数据

    使用 UAPI 天气接口，支持丰富的参数：
    - extended: 返回更多字段（体感温度、AQI等）
    - forecast: 返回多天预报
    - indices: 返回生活指数

    Args:
        city: 城市名称
        uapi_key: UAPI Key

    Returns:
        dict: 天气数据
        失败返回 None
    """
    try:
        encoded_city = urllib.parse.quote(city)
        url = f"{UAPI_BASE_URL}/misc/weather?city={encoded_city}&extended=true&indices=true"
        headers = {"Authorization": f"Bearer {uapi_key}"}
        
        response = await _async_http_get(url, headers=headers)
        data = json.loads(response)
        
        # 检查是否有错误
        if "code" in data and data["code"] != 200 and data["code"] != "200":
            logger.warning(f"[Weather] 天气查询失败: {data.get('message', data.get('code'))}")
            return None
        
        # 检查是否有城市名（作为成功标志）
        if not data.get("city"):
            logger.warning(f"[Weather] 未找到城市: {city}")
            return None
        
        return data
        
    except Exception as e:
        logger.error(f"[Weather] 天气查询异常: {city}, 错误: {e}")
        return None


# ============================================================================
# 4. 格式化输出
# ============================================================================

def format_weather(weather: dict) -> str:
    """
    将 UAPI 天气数据格式化为 LLM 易读的文本

    UAPI 天气数据字段:
    - province: 省份
    - city: 城市
    - district: 区县
    - weather: 天气描述
    - temperature: 温度
    - feels_like: 体感温度 (extended=true)
    - wind_direction: 风向
    - wind_power: 风力
    - humidity: 湿度
    - aqi: AQI (extended=true)
    - aqi_category: AQI 等级 (extended=true)
    - life_indices: 生活指数 (indices=true)
    - forecast: 多天预报 (forecast=true)
    
    Args:
        weather: UAPI 天气数据

    Returns:
        格式化的天气文本
    """
    province = weather.get("province", "")
    city = weather.get("city", "")
    district = weather.get("district", "")
    weather_desc = weather.get("weather", "未知")
    temperature = weather.get("temperature", "?")
    feels_like = weather.get("feels_like")
    wind_direction = weather.get("wind_direction", "")
    wind_power = weather.get("wind_power", "")
    humidity = weather.get("humidity", "?")
    aqi = weather.get("aqi")
    aqi_category = weather.get("aqi_category", "")
    report_time = weather.get("report_time", "")
    
    # 构建地点字符串
    location_parts = [city]
    if province and province != city:
        location_parts.insert(0, province)
    if district:
        location_parts.append(district)
    location_str = " ".join(location_parts)
    
    # 构建风向字符串
    wind_str = ""
    if wind_direction:
        wind_str = wind_direction
        if wind_power:
            wind_str += f" {wind_power}"
    
    # 构建基础天气信息
    lines = [
        f"【天气】{location_str}",
        f"发布时间: {report_time}",
        f"天气: {weather_desc}",
        f"温度: {temperature}°C",
    ]
    
    # 添加体感温度
    if feels_like is not None:
        lines.append(f"体感温度: {feels_like}°C")
    
    # 添加其他信息
    if humidity != "?":
        lines.append(f"湿度: {humidity}%")
    if wind_str:
        lines.append(f"风力: {wind_str}")
    
    # 添加空气质量
    if aqi is not None:
        aqi_str = f"空气质量: AQI {aqi}"
        if aqi_category:
            aqi_str += f" ({aqi_category})"
        lines.append(aqi_str)
    
    # 添加生活指数中的穿衣指数（对 AI 回答很重要）
    life_indices = weather.get("life_indices", {})
    if life_indices:
        clothing = life_indices.get("clothing", {})
        if clothing:
            advice = clothing.get("advice", "")
            if advice:
                lines.append(f"穿衣建议: {advice}")
    
    # 添加未来天气预报
    forecast = weather.get("forecast", [])
    if forecast and len(forecast) > 0:
        lines.append("")
        lines.append("【未来天气】")
        for day in forecast[:3]:  # 只显示前3天
            date = day.get("date", "")
            weekday = day.get("week", "")
            weather_day = day.get("weather_day", "")
            temp_max = day.get("temp_max", "")
            temp_min = day.get("temp_min", "")
            forecast_line = f"{weekday}({date}): {weather_day}"
            if temp_max and temp_min:
                forecast_line += f" {temp_min}~{temp_max}°C"
            lines.append(forecast_line)
    
    return "\n".join(lines)


# ============================================================================
# 5. 天气工具实现
# ============================================================================

class GetWeatherTool(AgentTool):
    """
    查询国内城市的实时天气

    使用 UAPI 天气接口，支持丰富的天气数据。
    """
    
    name: str = "get_weather"
    description: str = (
        "查询城市的实时天气数据（温度、体感温度、天气状况、湿度、风力、空气质量）。\n"
        "【重要】当用户询问任何与天气相关的问题时，都应该调用此工具，包括：\n"
        "- 直接问天气：今天天气怎么样、下雨了吗、刮风吗\n"
        "- 问温度：今天冷不冷、多少度、热不热、气温如何\n"
        "- 间接问：穿什么衣服、需要带伞吗、适合出门吗\n"
        "- 季节相关：夏天还热吗、冬天冷不冷\n"
        "- 未来天气：明天会下雨吗、这周天气如何\n"
        "参数 city 是城市名称，从用户位置或对话中提取。\n"
        "支持国内城市，如'成都'、'北京'、'上海'、'广州'。"
    )
    args_schema: type[BaseToolArgs] = GetWeatherArgs
    
    def __init__(self, **data):
        super().__init__(**data)
        self._uapi_key = get_uapi_key()
        if not self._uapi_key:
            logger.warning("[Weather] 未配置 UAPI_PRO_API_KEY，天气工具不可用")
        else:
            logger.info("[Weather] UAPI 天气工具已初始化")
    
    async def _execute(self, city: str) -> str:
        """
        执行天气查询

        Args:
            city: 城市名称

        Returns:
            格式化的天气文本
        """
        if not self._uapi_key:
            return "抱歉，天气服务未配置"
        
        # 检查缓存
        now = time.time()
        cache_key = city.lower()
        if cache_key in _weather_cache:
            cached_time, cached_data = _weather_cache[cache_key]
            if now - cached_time < CACHE_TTL:
                logger.info(f"[Weather] 使用缓存: {city}")
                return format_weather(cached_data)
        
        # 获取天气
        weather_data = await fetch_weather(city, self._uapi_key)
        if not weather_data:
            return f"抱歉，获取'{city}'的天气信息失败，请确认城市名称是否正确"
        
        # 存入缓存
        _weather_cache[cache_key] = (now, weather_data)
        
        result = format_weather(weather_data)
        logger.info(f"[Weather] 查询成功: {city}")
        return result


# ============================================================================
# 6. 注册入口
# ============================================================================

def register_weather_tools() -> list[AgentTool]:
    """
    注册天气工具到 ToolRegistry

    Returns:
        注册的工具列表

    使用位置: app.py 的预热阶段
    """
    tool = GetWeatherTool()
    tool_registry.register(tool)
    logger.info(f"[WeatherTools] 已注册: {tool.name}")
    return [tool]
