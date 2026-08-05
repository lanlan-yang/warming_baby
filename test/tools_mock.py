"""
tools_mock.py - Mock 测试所有工具

使用 unittest.mock mock 外部依赖，验证工具的核心逻辑。
不依赖真实的 API Key 和网络请求。

Usage:
    python test/tools_mock.py
"""
import asyncio
import json
import os
import sys

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import aiohttp
from aiohttp import ClientResponseError


# ============================================================================
# Mock 辅助类
# ============================================================================
class MockResponse:
    """Mock aiohttp ClientResponse"""
    def __init__(self, status):
        self.status = status
        self._text = f'{{"status": {status}}}'
    
    async def text(self):
        return self._text
    
    def raise_for_status(self):
        if self.status >= 400:
            raise ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=self.status,
                message=f"HTTP {self.status}",
            )


class MockResponseContext:
    """Mock async context manager for response"""
    def __init__(self, status):
        self.response = MockResponse(status)
    
    async def __aenter__(self):
        return self.response
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


def create_response_ctx(status):
    """创建 Mock 的 response context"""
    return MockResponseContext(status)


async def test_location_tool():
    """测试位置工具"""
    print("\n" + "="*60)
    print("测试 1: get_current_location")
    print("="*60)

    from tools import tool_location
    from tools.cache import clear_cache
    
    # 清除缓存，确保测试不受影响
    clear_cache("location")

    # Mock 成功响应
    mock_data = {
        "region": "中国 四川 成都",
        "ip": "114.249.50.2",
        "latitude": 30.5728,
        "longitude": 104.0668,
        "isp": "中国电信"
    }

    with patch.object(tool_location, 'http_get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps(mock_data)
        
        result = await tool_location.get_current_location.ainvoke({})
        
        print(f"\n✅ 调用成功")
        print(f"📋 返回内容:")
        print(result)
        
        assert "成都" in result, "应该包含城市名"
        assert "四川" in result, "应该包含省份"
        print(f"\n✅ 验证通过: 包含正确的城市和省份信息")

    # 清除缓存，测试失败场景
    clear_cache("location")
    
    # Mock 失败响应
    print(f"\n--- 测试失败场景 ---")
    with patch.object(tool_location, 'http_get', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Network Error")
        
        result = await tool_location.get_current_location.ainvoke({})
        
        print(f"✅ 错误处理正常")
        print(f"📋 返回内容: {result}")
        assert "失败" in result or "Error" in str(result), f"应该返回错误信息，实际返回: {result}"


async def test_weather_tool():
    """测试天气工具"""
    print("\n" + "="*60)
    print("测试 2: WeatherTool")
    print("="*60)

    from tools.tool_weather import WeatherTool
    from tools.cache import clear_cache
    
    # 清除缓存，确保测试不受影响
    clear_cache("weather")

    # Mock 成功响应 - 完整数据
    mock_data_full = {
        "province": "四川",
        "city": "成都",
        "weather": "多云",
        "temperature": "18",
        "feels_like": "16",
        "wind_direction": "东北",
        "wind_power": "3级",
        "aqi": 52,
        "aqi_category": "良",
        "life_indices": {
            "clothing": {"advice": "建议穿薄外套或牛仔裤。"},
            "uv": {"desc": "中等"},
            "car_wash": {"desc": "适合洗车"},
            "umbrella": {"desc": "不需要带伞"},
        },
        "forecast": [
            {"week": "周五", "date": "2025-08-08", "weather_day": "多云", "weather_night": "晴", "temp_min": "15", "temp_max": "22", "wind_dir_day": "东南", "wind_scale_day": "2级"},
            {"week": "周六", "date": "2025-08-09", "weather_day": "阴", "weather_night": "小雨", "temp_min": "14", "temp_max": "20", "wind_dir_day": "东", "wind_scale_day": "3级"},
        ]
    }

    # Mock 成功响应 - 基础数据（无 forecast/indices）
    mock_data_basic = {
        "province": "四川",
        "city": "成都",
        "weather": "多云",
        "temperature": "18",
        "feels_like": "16",
        "wind_direction": "东北",
        "wind_power": "3级",
        "aqi": 52,
        "aqi_category": "良",
    }

    # 创建工具实例
    tool = WeatherTool()

    # 测试 1: 基础查询（无扩展）
    print(f"\n--- 测试 1: 基础查询 ---")
    with patch('tools.tool_weather.http_get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps(mock_data_basic)
        
        result = await tool.ainvoke({"city": "成都"})
        
        print(f"✅ 基础查询成功")
        print(f"📋 返回内容:")
        print(result)
        
        assert "成都" in result, "应该包含城市名"
        assert "温度" in result, "应该包含温度"
        assert "穿衣建议" not in result, "基础查询不应包含穿衣建议"
        assert "7天预报" not in result, "基础查询不应包含预报"

    # 测试 2: 带 forecast
    print(f"\n--- 测试 2: 带 forecast ---")
    with patch('tools.tool_weather.http_get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps(mock_data_full)
        
        result = await tool.ainvoke({"city": "成都", "forecast": True})
        
        print(f"✅ forecast 查询成功")
        print(f"📋 返回内容:")
        print(result)
        
        assert "7天预报" in result, "应该包含预报"
        assert "穿衣建议" not in result, "不应包含穿衣建议"

    # 测试 3: 带 indices
    print(f"\n--- 测试 3: 带 indices ---")
    with patch('tools.tool_weather.http_get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps(mock_data_full)
        
        result = await tool.ainvoke({"city": "成都", "indices": True})
        
        print(f"✅ indices 查询成功")
        print(f"📋 返回内容:")
        print(result)
        
        assert "穿衣建议" in result, "应该包含穿衣建议"
        assert "紫外线" in result, "应该包含紫外线"
        assert "7天预报" not in result, "不应包含预报"

    # 测试 4: 完整查询（forecast + indices）
    print(f"\n--- 测试 4: 完整查询 ---")
    with patch('tools.tool_weather.http_get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps(mock_data_full)
        
        result = await tool.ainvoke({"city": "成都", "forecast": True, "indices": True})
        
        print(f"✅ 完整查询成功")
        print(f"📋 返回内容:")
        print(result)
        
        assert "7天预报" in result, "应该包含预报"
        assert "穿衣建议" in result, "应该包含穿衣建议"
        assert "紫外线" in result, "应该包含紫外线"

    # 清除缓存，测试失败场景
    clear_cache("weather")

    # Mock 失败场景：找不到城市
    print(f"\n--- 测试失败场景: 找不到城市 ---")
    with patch('tools.tool_weather.http_get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps({"province": "", "city": ""})
        
        result = await tool.ainvoke({"city": "不存在的城市"})
        
        print(f"✅ 错误处理正常")
        print(f"📋 返回内容: {result}")
        # 修改断言以匹配实际返回的消息
        assert "无法获取" in result or "抱歉" in result, f"应该返回找不到城市的提示，实际返回: {result}"

    # 清除缓存，测试网络错误
    clear_cache("weather")

    # Mock 失败场景：网络错误
    print(f"\n--- 测试失败场景: 网络错误 ---")
    with patch('tools.tool_weather.http_get', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Connection Timeout")
        
        result = await tool.ainvoke({"city": "成都"})
        
        print(f"✅ 错误处理正常")
        print(f"📋 返回内容: {result}")
        assert "失败" in result or "抱歉" in result, f"应该返回错误信息，实际返回: {result}"


async def test_tools_in_list():
    """测试工具可以正确添加到列表"""
    print("\n" + "="*60)
    print("测试 3: 工具列表和绑定")
    print("="*60)

    from tools.tool_location import get_current_location
    from tools.tool_weather import WeatherTool

    # 创建天气工具实例
    weather_tool = WeatherTool()

    tools = [get_current_location, weather_tool]
    
    print(f"\n✅ 工具列表创建成功")
    print(f"📋 工具列表:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:50]}...")
    
    assert get_current_location.name == "get_current_location", "工具名称应该正确"
    assert weather_tool.name == "weather", "工具名称应该正确"
    assert len(tools) == 2, "应该有2个工具"
    print(f"\n✅ 验证通过: 工具属性正确")


async def test_tools_schema():
    """测试工具的参数 schema"""
    print("\n" + "="*60)
    print("测试 4: 工具参数 Schema")
    print("="*60)

    from tools.tool_location import get_current_location
    from tools.tool_weather import WeatherTool, WeatherArgs

    # 创建天气工具实例
    weather_tool = WeatherTool()

    print(f"\n📋 get_current_location schema:")
    print(f"  name: {get_current_location.name}")
    print(f"  description: {get_current_location.description[:60]}...")
    print(f"  args_schema: {get_current_location.args}")
    
    print(f"\n📋 WeatherTool schema:")
    print(f"  name: {weather_tool.name}")
    print(f"  description: {weather_tool.description[:60]}...")
    print(f"  args_schema: {weather_tool.args_schema}")
    
    # 验证 WeatherArgs 的 Field 描述
    print(f"\n📋 WeatherArgs 字段详情:")
    for field_name, field_info in WeatherArgs.model_fields.items():
        print(f"  - {field_name}: {field_info.description}")
    
    assert "city" in WeatherArgs.model_fields, "WeatherArgs 应该有 city 字段"
    assert WeatherArgs.model_fields["city"].description, "city 字段应该有描述"
    print(f"\n✅ 验证通过: 参数 schema 正确")


async def test_http_retry():
    """测试 HTTP 重试判断逻辑"""
    print("\n" + "="*60)
    print("测试 5: HTTP 重试判断逻辑")
    print("="*60)

    from tools.http_client import _is_retryable_error

    # 测试可重试的错误
    print(f"\n--- 可重试的错误 ---")
    
    # 500 错误
    error_500 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=500,
        message="Server Error",
    )
    assert _is_retryable_error(error_500), "500 应该可重试"
    print(f"✅ 500 可重试")
    
    # 502 错误
    error_502 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=502,
        message="Bad Gateway",
    )
    assert _is_retryable_error(error_502), "502 应该可重试"
    print(f"✅ 502 可重试")
    
    # 503 错误
    error_503 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=503,
        message="Service Unavailable",
    )
    assert _is_retryable_error(error_503), "503 应该可重试"
    print(f"✅ 503 可重试")
    
    # 504 错误
    error_504 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=504,
        message="Gateway Timeout",
    )
    assert _is_retryable_error(error_504), "504 应该可重试"
    print(f"✅ 504 可重试")
    
    # 429 错误
    error_429 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=429,
        message="Too Many Requests",
    )
    assert _is_retryable_error(error_429), "429 应该可重试"
    print(f"✅ 429 可重试")
    
    # 超时错误
    timeout_error = asyncio.TimeoutError("Request timeout")
    assert _is_retryable_error(timeout_error), "超时应该可重试"
    print(f"✅ 超时错误可重试")
    
    # 连接错误
    connection_error = aiohttp.ClientConnectorError(
        connection_key=MagicMock(),
        os_error=OSError("Connection refused"),
    )
    assert _is_retryable_error(connection_error), "连接错误应该可重试"
    print(f"✅ 连接错误可重试")

    # 测试不可重试的错误
    print(f"\n--- 不可重试的错误 ---")
    
    # 400 错误
    error_400 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=400,
        message="Bad Request",
    )
    assert not _is_retryable_error(error_400), "400 不应可重试"
    print(f"✅ 400 不可重试")
    
    # 401 错误
    error_401 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=401,
        message="Unauthorized",
    )
    assert not _is_retryable_error(error_401), "401 不应可重试"
    print(f"✅ 401 不可重试")
    
    # 403 错误
    error_403 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=403,
        message="Forbidden",
    )
    assert not _is_retryable_error(error_403), "403 不应可重试"
    print(f"✅ 403 不可重试")
    
    # 404 错误
    error_404 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=404,
        message="Not Found",
    )
    assert not _is_retryable_error(error_404), "404 不应可重试"
    print(f"✅ 404 不可重试")
    
    # 405 错误
    error_405 = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=405,
        message="Method Not Allowed",
    )
    assert not _is_retryable_error(error_405), "405 不应可重试"
    print(f"✅ 405 不可重试")

    print(f"\n✅ 所有重试判断逻辑测试通过")


async def test_retry_flow():
    """测试真正的重试流程"""
    print("\n" + "="*60)
    print("测试 6: 重试流程 (真正触发重试)")
    print("="*60)

    from tools import http_client

    print(f"\n--- 测试 1: 第一次失败(500)，第二次成功(200) ---")
    
    call_count = 0
    
    def mock_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        
        if call_count == 1:
            return create_response_ctx(500)
        else:
            return create_response_ctx(200)
    
    mock_client = MagicMock()
    mock_client.request = mock_request
    
    with patch.object(http_client, 'get_http_client', return_value=mock_client):
        result = await http_client.http_get("https://api.example.com/retry-success")
        
        print(f"  调用次数: {call_count} (应该是 2 次)")
        print(f"  返回结果: {result}")
        
        assert call_count == 2, f"应该调用 2 次，实际调用了 {call_count} 次"
        assert '"status": 200' in result, "应该返回成功的响应"
        print(f"  ✅ 第一次 500 失败后重试，第二次 200 成功")

    print(f"\n--- 测试 2: 3 次都失败(500) ---")
    
    call_count2 = 0
    
    def mock_request_all_fail(method, url, **kwargs):
        nonlocal call_count2
        call_count2 += 1
        return create_response_ctx(500)
    
    mock_client2 = MagicMock()
    mock_client2.request = mock_request_all_fail
    
    with patch.object(http_client, 'get_http_client', return_value=mock_client2):
        try:
            await http_client.http_get("https://api.example.com/all-fail")
            print(f"  ❌ 应该抛出异常")
            assert False, "应该抛出异常"
        except ClientResponseError as e:
            print(f"  调用次数: {call_count2} (应该是 4 次)")
            print(f"  最终错误: HTTP {e.status}")
            
            assert call_count2 == 4, f"应该调用 4 次，实际调用了 {call_count2} 次"
            assert e.status == 500, f"应该是 500 错误"
            print(f"  ✅ 重试耗尽: 3 次重试后还是失败，抛出异常")

    print(f"\n--- 测试 3: 第一次 500，第二次 500，第三次 200 ---")
    
    call_count3 = 0
    
    def mock_request_two_fail_then_success(method, url, **kwargs):
        nonlocal call_count3
        call_count3 += 1
        
        if call_count3 <= 2:
            return create_response_ctx(500)
        else:
            return create_response_ctx(200)
    
    mock_client3 = MagicMock()
    mock_client3.request = mock_request_two_fail_then_success
    
    with patch.object(http_client, 'get_http_client', return_value=mock_client3):
        result = await http_client.http_get("https://api.example.com/two-fail")
        
        print(f"  调用次数: {call_count3} (应该是 3 次)")
        print(f"  返回结果: {result}")
        
        assert call_count3 == 3, f"应该调用 3 次，实际调用了 {call_count3} 次"
        assert '"status": 200' in result, "应该返回成功的响应"
        print(f"  ✅ 两次 500 失败后重试，第三次 200 成功")

    print(f"\n--- 测试 4: 404 不重试 ---")
    
    call_count4 = 0
    
    def mock_request_404(method, url, **kwargs):
        nonlocal call_count4
        call_count4 += 1
        return create_response_ctx(404)
    
    mock_client4 = MagicMock()
    mock_client4.request = mock_request_404
    
    with patch.object(http_client, 'get_http_client', return_value=mock_client4):
        try:
            await http_client.http_get("https://api.example.com/not-found")
            print(f"  ❌ 应该抛出异常")
            assert False, "应该抛出异常"
        except ClientResponseError as e:
            print(f"  调用次数: {call_count4} (应该是 1 次，不重试)")
            print(f"  最终错误: HTTP {e.status}")
            
            assert call_count4 == 1, f"应该只调用 1 次，实际调用了 {call_count4} 次"
            assert e.status == 404, f"应该是 404 错误"
            print(f"  ✅ 404 业务错误不重试")

    print(f"\n✅ 所有重试流程测试通过")


async def main():
    """运行所有测试"""
    print("\n" + "🚀"*30)
    print("开始 Mock 测试所有工具")
    print("🚀"*30)
    
    results = []
    
    try:
        await test_location_tool()
        results.append(("位置工具", "✅ PASSED"))
    except Exception as e:
        results.append(("位置工具", f"❌ FAILED: {e}"))
    
    try:
        await test_weather_tool()
        results.append(("天气工具", "✅ PASSED"))
    except Exception as e:
        results.append(("天气工具", f"❌ FAILED: {e}"))
    
    try:
        await test_tools_in_list()
        results.append(("工具列表", "✅ PASSED"))
    except Exception as e:
        results.append(("工具列表", f"❌ FAILED: {e}"))
    
    try:
        await test_tools_schema()
        results.append(("参数 Schema", "✅ PASSED"))
    except Exception as e:
        results.append(("参数 Schema", f"❌ FAILED: {e}"))
    
    try:
        await test_http_retry()
        results.append(("重试判断", "✅ PASSED"))
    except Exception as e:
        results.append(("重试判断", f"❌ FAILED: {e}"))
    
    try:
        await test_retry_flow()
        results.append(("重试流程", "✅ PASSED"))
    except Exception as e:
        results.append(("重试流程", f"❌ FAILED: {e}"))
    
    # 关闭 http client
    try:
        from tools.http_client import close_http_client
        await close_http_client()
    except:
        pass
    
    # 打印结果
    print("\n" + "="*60)
    print("📊 测试结果汇总")
    print("="*60)
    for name, result in results:
        print(f"  {name}: {result}")
    
    passed = sum(1 for _, r in results if "PASSED" in r)
    total = len(results)
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n⚠️  部分测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
