"""
tools/tool_weather - 天气工具（异步）

使用 UAPI /misc/weather 查询天气。
使用 aiohttp 异步请求，复用共享的 ClientSession。

定位方式：
- 不传 city：自动通过IP定位（更精确，甚至到区）
- 传 city：查询指定城市的天气

API 参数：
- city: 城市名（可选，为空则IP定位）
- forecast: 是否获取7天预报（可选，默认 false）
- indices: 是否获取18项生活指数（可选，默认 false）

缓存策略：
- 使用 @cache 装饰器
- 缓存时间：30分钟
- 缓存键：city | forecast | indices

LLM 使用建议：
- 查询"今天天气"、"我这边天气" -> 不传 city，自动定位
- 查询"成都天气"、"北京天气" -> 传 city
- 查询"明天天气"、"下周天气" -> forecast=True
- 查询"穿什么"、"紫外线" -> indices=True
- 查询详细天气 -> forecast=True, indices=True

Usage:
    from tools.tool_weather import WeatherTool
    
    # 方式1: 注册到 ToolRegistry
    from tools.tool_base import tool_registry
    tool_registry.register(WeatherTool)
    
    # 方式2: 直接实例化
    weather_tool = WeatherTool()
    await weather_tool.ainvoke({})  # 自动IP定位
    await weather_tool.ainvoke({"city": "成都"})  # 指定城市
    await weather_tool.ainvoke({"forecast": True})  # 7天预报
    await weather_tool.ainvoke({"indices": True})  # 生活指数
"""
import json
import os
import urllib.parse

from aiohttp import ClientError
from pydantic import Field

from tools.tool_base import AgentTool, BaseToolArgs
from tools.cache import cache, get_cache, clear_cache, get_cache_stats
from tools.http_client import http_get
from core.logger import setup_logger

logger = setup_logger()

UAPI_BASE_URL = "https://uapis.cn/api/v1"


# ============================================================================
# 1. Args Schema 定义（LLM 看到的参数说明）
# ============================================================================

class WeatherArgs(BaseToolArgs):
    """查询天气的参数"""
    city: str = Field(
        default="",
        description="城市名，如'成都'、'北京'、'上海'。如果不传，会自动通过IP定位到当前城市（更精确，甚至到区）"
    )
    forecast: bool = Field(
        default=False,
        description="是否获取7天预报。查询未来天气、明天穿什么时设为 true"
    )
    indices: bool = Field(
        default=False,
        description="是否获取18项生活指数（穿衣、紫外线、洗车、雨伞等）。查询生活建议时设为 true"
    )


# ============================================================================
# 2. Tool 实现
# ============================================================================

class WeatherTool(AgentTool):
    """
    查询天气信息
    
    可以获取：
    - 基础天气：温度、天气状况、风力、空气质量
    - 7天预报：未来天气、温度、风力
    - 生活指数：穿衣、紫外线、洗车、雨伞等
    
    定位方式（重要）：
    - 不传 city：自动通过IP定位到当前城市（更精确，甚至到区）
    - 传 city：查询指定城市的天气
    
    LLM 使用建议：
    - 用户问"今天天气"、"我这边天气" -> 不传 city，自动定位
    - 用户问"成都天气"、"北京天气" -> 传 city
    - 用户问"明天穿什么" -> forecast=True, indices=True
    """

    name: str = "weather"
    description: str = (
        "查询天气信息。不传city时自动通过IP定位（更精确到区），"
        "传city时查询指定城市。当用户问天气、温度、穿什么时调用。"
    )
    args_schema: type[BaseToolArgs] = WeatherArgs

    @staticmethod
    @cache(
        ttl=1800,  # 30分钟缓存
        cache_name="weather",
        key_func=lambda city, forecast, indices: f"{city}|{forecast}|{indices}"
    )
    async def _fetch_weather_data(
        city: str,
        forecast: bool,
        indices: bool,
    ) -> dict:
        """
        获取天气数据（带缓存装饰器）
        
        这是一个静态方法，使用 @cache 装饰器实现自动缓存。
        
        Args:
            city: 城市名（为空则IP定位）
            forecast: 是否获取7天预报
            indices: 是否获取生活指数
            
        Returns:
            原始天气数据字典
        """
        uapi_key = WeatherTool._get_uapi_key_static()
        if not uapi_key:
            raise ValueError("天气服务未配置")

        # 构建请求参数
        params = []
        if city:
            params.append(f"city={urllib.parse.quote(city)}")
        if forecast:
            params.append("forecast=true")
        if indices:
            params.append("indices=true")
        
        url = f"{UAPI_BASE_URL}/misc/weather"
        if params:
            url += f"?{'&'.join(params)}"
        headers = {"Authorization": f"Bearer {uapi_key}"}
        
        data = json.loads(await http_get(url, headers=headers))
        
        if not data.get("city"):
            raise ValueError("无法获取天气信息")
        
        return data

    async def _execute(
        self,
        city: str = "",
        forecast: bool = False,
        indices: bool = False,
    ) -> str:
        """
        执行天气查询
        
        Args:
            city: 城市名，如果为空则自动通过IP定位
            forecast: 是否获取7天预报
            indices: 是否获取生活指数
            
        Returns:
            格式化的天气信息
        """
        location_desc = city if city else "IP定位"
        logger.info(f"[WeatherTool] 查询: {location_desc}, forecast={forecast}, indices={indices}")
        
        try:
            # 使用带缓存的静态方法获取数据
            data = await self._fetch_weather_data(city, forecast, indices)
            
            # 格式化结果
            result = self._format_weather(data, forecast, indices)
            logger.info(f"[WeatherTool] 完成: {data.get('city', '未知')}")
            
            return result

        except ValueError as e:
            logger.warning(f"[WeatherTool] {e}")
            return f"抱歉，{str(e)}"
        except ClientError as e:
            logger.error(f"[WeatherTool] 网络错误: {location_desc}, {e}")
            return f"抱歉，网络请求失败: {e}"
        except Exception as e:
            logger.error(f"[WeatherTool] 错误: {location_desc}, {e}")
            return f"抱歉，获取天气失败: {e}"

    def _get_uapi_key_static() -> str:
        """获取 UAPI Key（静态方法）"""
        key = os.environ.get("UAPI_PRO_API_KEY", "")
        if not key:
            env_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                '.env'
            )
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    for line in f:
                        if line.startswith('UAPI_PRO_API_KEY='):
                            key = line.split('=', 1)[1].strip().strip('"').strip("'")
                            break
        return key

    def _format_weather(self, data: dict, forecast: bool, indices: bool) -> str:
        """格式化天气数据"""
        # 基础天气信息
        lines = [
            f"【天气】{data.get('province', '')} {data.get('city')}",
            f"天气: {data.get('weather', '未知')}",
            f"温度: {data.get('temperature', '?')}°C",
        ]
        
        # 可选：体感温度
        if data.get("feels_like"):
            lines.append(f"体感: {data['feels_like']}°C")
        
        # 可选：风力
        if data.get("wind_direction"):
            wind = data["wind_direction"]
            if data.get("wind_power"):
                wind += f" {data['wind_power']}"
            lines.append(f"风力: {wind}")
        
        # 可选：空气质量
        if data.get("aqi"):
            aqi_line = f"空气质量: AQI {data['aqi']}"
            if data.get("aqi_category"):
                aqi_line += f" ({data['aqi_category']})"
            lines.append(aqi_line)

        # 生活指数（仅当 indices=True 时请求）
        if indices and data.get("life_indices"):
            idx = data["life_indices"]
            
            # 常用指数
            if idx.get("clothing"):
                lines.append(f"穿衣建议: {idx['clothing'].get('advice', '')}")
            if idx.get("uv"):
                lines.append(f"紫外线: {idx['uv'].get('desc', '')}")
            if idx.get("car_wash"):
                lines.append(f"洗车: {idx['car_wash'].get('desc', '')}")
            if idx.get("umbrella"):
                lines.append(f"雨伞: {idx['umbrella'].get('desc', '')}")
            if idx.get("sport"):
                lines.append(f"运动: {idx['sport'].get('desc', '')}")
            if idx.get("air_purifier"):
                lines.append(f"净化器: {idx['air_purifier'].get('desc', '')}")
            
            # 其他指数
            extra_idx = {
                "cold": "感冒", "comfort": "舒适", "sunscreen": "防晒",
                "makeup": "化妆", "fishing": "钓鱼", "allergy": "过敏",
                "air_conditioner": "空调", "night_life": "夜生活",
            }
            for key, name in extra_idx.items():
                if idx.get(key) and idx[key].get("desc"):
                    lines.append(f"{name}: {idx[key]['desc']}")

        # 天气预报（仅当 forecast=True 时请求）
        if forecast and data.get("forecast"):
            lines.append("")
            lines.append("【7天预报】")
            for day in data["forecast"]:
                day_info = f"{day.get('week', '')} {day.get('date', '')}"
                if day.get("weather_day"):
                    day_info += f" 白天:{day['weather_day']}"
                if day.get("weather_night"):
                    day_info += f" 夜间:{day['weather_night']}"
                if day.get("temp_max") and day.get("temp_min"):
                    day_info += f" {day['temp_min']}~{day['temp_max']}°C"
                if day.get("wind_dir_day") and day.get("wind_scale_day"):
                    day_info += f" {day['wind_dir_day']}{day['wind_scale_day']}"
                lines.append(day_info)

        return "\n".join(lines)


def clear_weather_cache():
    """
    清除所有天气缓存
    
    使用场景：
    - 用户更新位置信息后
    - 天气数据可能已过时
    - 调试时需要强制刷新
    """
    clear_cache("weather")


def get_weather_cache_info() -> dict:
    """
    获取天气缓存信息
    
    Returns:
        dict: 包含缓存大小和配置的信息
    """
    cache_stats = get_cache_stats()
    return cache_stats.get("weather", {
        "size": 0,
        "ttl": 1800,
        "max_size": 100,
    })
