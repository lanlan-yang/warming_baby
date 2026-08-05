#!/usr/bin/env python3
"""
test/chat_cli.py - 终端聊天测试工具

最小可运行的聊天测试，支持多轮对话、记忆和工具调用。

Usage:
    cd warming_baby
    python test/chat_cli.py

Commands:
    /exit, /quit  - 退出
    /clear        - 清空历史
    /reset        - 重置会话 (新的 thread_id)
    /tools        - 显示可用工具
    /history      - 显示历史消息数量
    /help         - 显示帮助
"""

import os

# 禁用 LangGraph msgpack 严格模式警告
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

import asyncio
import sys
import uuid

sys.path.insert(0, '.')

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from providers import get_llm
from core.enums import ModelTask
from tools.tool_location import get_current_location
from tools.tool_weather import WeatherTool
from tools.tool_memory import QueryMemoryTool, AddMemoryTool, UpdateMemoryTool
from memory import MemoryManager
from agent.chat.graph import ChatGraph


SYSTEM_PROMPT_TEMPLATE = """你是"暖宝"，一个可爱的桌面宠物助手。
你的语气要友好、活泼，像朋友一样和用户聊天。

【当前时间】
{time_context}

你有以下工具可以使用：
1. get_weather - 查询天气。不传city会自动通过IP定位（更精确到区），传city可以查询指定城市
2. query_memory - 查询记忆，当你需要知道用户的信息时使用
3. add_memory - 添加记忆，当用户告诉你新的信息时使用
4. update_memory - 修改记忆，当用户更正之前说的信息时使用

提示：
- 用户问"今天天气"、"我这边天气" -> 调用 get_weather() 不传参数
- 用户问"成都天气"、"北京天气" -> 调用 get_weather(city="成都")
- 用户问"你知道我叫什么吗" -> 调用 query_memory
- 用户说"我叫小明" -> 调用 add_memory
- 用表情符号让对话更有趣"""


def get_time_context() -> str:
    """获取时间上下文"""
    from datetime import datetime
    
    now = datetime.now()
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_names[now.weekday()]

    hour = now.hour
    if 5 <= hour < 9:
        period = "早晨"
    elif 9 <= hour < 12:
        period = "上午"
    elif 12 <= hour < 14:
        period = "中午"
    elif 14 <= hour < 18:
        period = "下午"
    elif 18 <= hour < 21:
        period = "傍晚"
    elif 21 <= hour < 24:
        period = "晚上"
    else:
        period = "深夜"

    time_str = now.strftime("%Y年%m月%d日 %H:%M")
    return f"{time_str} {weekday} {period}"


class ChatCLI:
    """终端聊天客户端"""

    def __init__(self, show_thinking: bool = False):
        self.show_thinking = show_thinking
        
        print("初始化系统...")
        
        # 初始化 MemoryManager
        print("  初始化记忆系统...")
        self.memory_manager = MemoryManager.get_instance()
        self.memory_manager.initialize()
        print(f"  记忆系统就绪: {self.memory_manager.is_ready}")
        
        # 初始化 LLM
        print("  初始化 LLM...")
        self.llm = get_llm(ModelTask.CHAT)
        print("  LLM 就绪")

        # 初始化工具
        print("  注册工具...")
        self.tools = [
            get_current_location,
            WeatherTool(),
            QueryMemoryTool(),
            AddMemoryTool(),
            UpdateMemoryTool(),
        ]
        print(f"  工具就绪: {len(self.tools)} 个")

        # 初始化 ChatGraph
        self.graph = ChatGraph(
            llm=self.llm,
            tools=self.tools,
            max_iterations=5,
        )
        print("  ChatGraph 就绪")
        print()

        # 对话历史（持久化）- 系统提示会在每次对话时更新
        self.history = []
        self._refresh_system_prompt()

        # 会话配置
        self.config = self._new_config()

    def _refresh_system_prompt(self):
        """刷新系统提示（更新时间）"""
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            time_context=get_time_context()
        )
        # 如果历史为空，直接添加
        if not self.history:
            self.history = [SystemMessage(content=system_prompt)]
        # 如果历史第一条是 SystemMessage，更新它
        elif isinstance(self.history[0], SystemMessage):
            self.history[0] = SystemMessage(content=system_prompt)
        # 否则插入到第一条
        else:
            self.history.insert(0, SystemMessage(content=system_prompt))

    def _new_config(self) -> dict:
        """创建新的会话配置"""
        return {
            "configurable": {
                "thread_id": f"cli-{uuid.uuid4().hex[:8]}",
            }
        }

    async def chat(self, user_input: str) -> str:
        """发送消息并获取回复"""
        import asyncio
        
        # 刷新系统提示（更新时间）
        self._refresh_system_prompt()
        
        # 添加用户消息
        self.history.append(HumanMessage(content=user_input))

        # 直接调用 graph.ainvoke
        initial_state = {
            "messages": self.history,
            "max_iterations": self.graph.max_iterations,
            "iteration": 0,
        }
        
        try:
            result = await self.graph.graph.ainvoke(
                initial_state,
                config=self.config
            )
        except asyncio.CancelledError:
            # 任务被取消（用户 Ctrl+C），清理历史
            self.history.pop()  # 移除刚才添加的用户消息
            raise  # 重新抛出，让调用者处理
        
        # 获取最终响应
        final_response = result.get("final_response")
        response_text = final_response.text if final_response else "抱歉，我处理你的消息时遇到了问题..."

        # 添加 AI 回复到历史
        if response_text:
            self.history.append(AIMessage(content=response_text))

        return response_text

    def clear_history(self):
        """清空历史但保持同一会话"""
        self.history = []
        self._refresh_system_prompt()

    def reset_session(self):
        """重置会话 (新的 thread_id)"""
        self.history = []
        self._refresh_system_prompt()
        self.graph = ChatGraph(
            llm=self.llm,
            tools=self.tools,
            max_iterations=5,
        )
        self.config = self._new_config()

    def show_tools(self):
        """显示可用工具"""
        print("\n可用工具:")
        for tool in self.tools:
            if hasattr(tool, 'name'):
                name = tool.name
                desc = getattr(tool, 'description', '无描述')
            elif hasattr(tool, '__name__'):
                name = tool.__name__
                desc = getattr(tool, 'description', '无描述')
            else:
                name = str(tool)
                desc = '无描述'
            print(f"  - {name}: {desc}")

    def show_history_count(self):
        """显示历史消息数量"""
        # 减去 SystemMessage
        chat_count = len(self.history) - 1
        print(f"\n历史消息数: {chat_count}")


def show_help():
    """显示帮助"""
    print("\n可用命令:")
    print("  /exit, /quit  - 退出程序")
    print("  /clear        - 清空对话历史")
    print("  /reset        - 重置会话 (新的记忆)")
    print("  /tools        - 显示可用工具")
    print("  /history      - 显示历史消息数量")
    print("  /help         - 显示此帮助")


async def main():
    """主循环"""
    import asyncio
    
    print("=" * 50)
    print("🐹 暖宝终端聊天测试工具")
    print("=" * 50)
    print("输入消息开始聊天，或输入 /help 查看命令")
    print()

    try:
        cli = ChatCLI()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        print("请检查配置是否正确")
        return

    while True:
        try:
            # 获取用户输入
            user_input = input("你: ").strip()

            if not user_input:
                continue

            # 处理命令
            if user_input.startswith('/'):
                cmd = user_input[1:].lower()
                if cmd in ('exit', 'quit'):
                    print("\n👋 再见！")
                    break
                elif cmd == 'clear':
                    cli.clear_history()
                    print("✅ 历史已清空")
                    continue
                elif cmd == 'reset':
                    cli.reset_session()
                    print("✅ 会话已重置 (新的记忆)")
                    continue
                elif cmd == 'tools':
                    cli.show_tools()
                    continue
                elif cmd == 'history':
                    cli.show_history_count()
                    continue
                elif cmd == 'help':
                    show_help()
                    continue
                else:
                    print(f"❌ 未知命令: {cmd}，输入 /help 查看帮助")
                    continue

            # 发送消息并获取回复
            print("\n🤔 思考中...")
            try:
                response = await cli.chat(user_input)
                print(f"\n🐹 暖宝: {response}")
            except asyncio.CancelledError:
                print("\n\n⏹️ 请求已取消")
                continue
            except Exception as e:
                print(f"\n❌ 出错了: {e}")
            
            print()

        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except EOFError:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 再见！")
    except Exception as e:
        print(f"\n❌ 程序错误: {e}")
        import traceback
        traceback.print_exc()
