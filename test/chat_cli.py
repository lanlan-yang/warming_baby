#!/usr/bin/env python3
"""
test/chat_cli.py - 终端聊天测试工具

最小可运行的聊天测试，支持多轮对话、记忆和工具调用。

Usage:
    cd warming_baby
    python test/chat_cli.py

Commands:
    /exit, /quit  - 退出
    /clear        - 清空对话历史
    /reset        - 重置会话 (新的 thread_id)
    /tools        - 显示可用工具
    /memory       - 显示当前记忆
    /search <kw>  - 搜索记忆
    /norm <text>  - 测试归一化 (显示 normalized + field)
    /purge        - 清空记忆数据库
    /stats        - 显示记忆统计
    /help         - 显示帮助
"""

import os

# 禁用 LangGraph msgpack 严格模式警告
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

import asyncio
import sys

sys.path.insert(0, '.')

from tools.tool_base import tool_registry
from tools.tool_location import get_current_location
from tools.tool_weather import WeatherTool
from tools.tool_memory import QueryMemoryTool
from memory import MemoryManager, MemoryType, get_normalizer, get_core_cache
from agent.chat.chat_agent import ChatAgent


class ChatCLI:
    """终端聊天客户端"""

    def __init__(self):
        print("初始化系统...")

        # 初始化记忆系统
        print("  初始化记忆系统...")
        self.memory_manager = MemoryManager.get_instance()
        self.memory_manager.initialize()
        print(f"  记忆系统就绪: {self.memory_manager.is_ready}")

        # 注册工具
        print("  注册工具...")
        self._register_tools()
        print(f"  工具就绪: {len(tool_registry.get_tools())} 个")

        # 初始化 ChatAgent
        print("  初始化 ChatAgent...")
        self.agent = ChatAgent()
        print("  ChatAgent 就绪")
        print()

        # 显示工具列表
        self.show_tools()
        print()

    def _register_tools(self):
        """注册所有工具"""
        tool_registry.clear()
        tool_registry.register(get_current_location)
        tool_registry.register(WeatherTool)
        tool_registry.register(QueryMemoryTool)
        # 记忆存储由 memory_node 确定性节点处理，LLM 无需 add/update 工具

    async def chat(self, user_input: str) -> str:
        """发送消息并获取回复"""
        try:
            response = await self.agent.chat(user_input)
            return response.text
        except Exception as e:
            return f"抱歉，出错了: {e}"

    def show_tools(self):
        """显示可用工具"""
        print("\n📦 可用工具:")
        for tool in tool_registry.get_tools():
            name = tool.name if hasattr(tool, 'name') else str(tool)
            desc = getattr(tool, 'description', '无描述')
            print(f"  - {name}: {desc[:60]}...")

    def show_memory(self):
        """显示当前记忆（含字段、重要性、访问次数）"""
        memories = self.memory_manager.get_all_memories()
        if not memories:
            print("\n📝 当前无记忆")
            return

        print(f"\n📝 当前记忆 ({len(memories)} 条):")
        for i, mem in enumerate(memories, 1):
            content = mem.get('content', '')
            meta = mem.get('metadata', {})
            mtype = meta.get('type', '?')
            field = meta.get('field', '-')
            importance = meta.get('importance', 0.5)
            access = meta.get('access_count', 0)
            print(f"  {i:2d}. [{mtype:10s}] [{field:8s}] (重要性 {importance:.0%}, 访问 {access}次) {content}")

    def search_memory(self, query: str):
        """搜索记忆"""
        if not query:
            print("用法: /search <关键词>")
            return

        results = self.memory_manager.search(query, n_results=5)
        if not results:
            print(f"\n🔍 搜索 '{query}' 无结果")
            return

        print(f"\n🔍 搜索 '{query}' 找到 {len(results)} 条:")
        for i, r in enumerate(results, 1):
            content = r.get('content', '')
            sim = r.get('similarity', 0)
            decay = r.get('time_decay', 1.0)
            imp = r.get('importance', 0.5)
            score = r.get('score', 0)
            access = r.get('access_count', 0)
            print(f"  {i}. {content}")
            print(f"     相似度 {sim:.0%} | 新鲜度 {decay:.0%} | 重要性 {imp:.0%} | 综合 {score:.0%} | 访问 {access}次")

    def test_normalize(self, text: str, mtype: str = 'fact'):
        """测试归一化: 显示 normalized content 和 extracted field"""
        if not text:
            print("用法: /norm <text> [fact|preference]")
            return

        type_map = {
            'fact': MemoryType.FACT,
            'preference': MemoryType.PREFERENCE,
            'skill': MemoryType.SKILL,
            'event': MemoryType.EVENT,
            'context': MemoryType.CONTEXT,
        }
        memory_type = type_map.get(mtype.lower(), MemoryType.FACT)

        normalizer = get_normalizer()
        norm = normalizer.normalize(text, memory_type)
        field = normalizer.extract_field(text, memory_type)

        print(f"\n🔍 归一化测试:")
        print(f"  原文:   {text}")
        print(f"  类型:   {memory_type.value}")
        print(f"  归一化: {norm}")
        print(f"  字段:   {field}")

        # 如果是 FACT 或 PREFERENCE，额外显示字段信息
        if memory_type == MemoryType.PREFERENCE:
            direction, core = normalizer.extract_preference(text)
            print(f"  方向:   {direction}")
            print(f"  核心:   {core}")

    def show_stats(self):
        """显示统计信息"""
        stats = self.memory_manager.get_memory_stats()
        print(f"\n📊 记忆统计: 共 {stats['total']} 条")
        if 'by_type' in stats:
            for type_name, count in stats['by_type'].items():
                print(f"  - {type_name}: {count}")

    def purge_memory(self):
        """清空记忆数据库"""
        count = len(self.memory_manager.get_all_memories())
        if count == 0:
            print("\n📭 数据库已为空")
            return
        try:
            self.memory_manager.clear_all()
            print(f"\n🗑️ 已清空 {count} 条记忆")
        except Exception as e:
            print(f"\n❌ 清空失败: {e}")


def show_help():
    """显示帮助"""
    print("\n可用命令:")
    print("  /exit, /quit  - 退出程序")
    print("  /clear        - 清空对话历史 (记忆保留)")
    print("  /reset        - 重置会话")
    print("  /tools        - 显示可用工具")
    print("  /memory       - 显示所有记忆 (含重要性、访问次数)")
    print("  /search <kw>  - 搜索记忆 (显示综合分数)")
    print("  /norm <text>  - 测试归一化 (显示 normalized + field)")
    print("  /purge        - 清空记忆数据库 (不可恢复)")
    print("  /stats        - 显示记忆统计")
    print("  /help         - 显示此帮助")


async def main():
    """主循环"""
    print("=" * 50)
    print("🐹 暖宝终端聊天测试工具")
    print("=" * 50)
    print("输入消息开始聊天，或输入 /help 查看命令")
    print()

    try:
        cli = ChatCLI()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return

    while True:
        try:
            # 获取用户输入
            user_input = input("你: ").strip()

            if not user_input:
                continue

            # 处理命令
            if user_input.startswith('/'):
                parts = user_input[1:].split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ''

                if cmd in ('exit', 'quit'):
                    print("\n👋 再见！")
                    break
                elif cmd == 'clear':
                    cli.agent.clear_history()
                    print("✅ 对话历史已清空 (记忆保留)")
                    continue
                elif cmd == 'reset':
                    print("✅ 会话已重置")
                    continue
                elif cmd == 'tools':
                    cli.show_tools()
                    continue
                elif cmd == 'memory':
                    cli.show_memory()
                    continue
                elif cmd == 'search':
                    cli.search_memory(arg)
                    continue
                elif cmd == 'norm':
                    # /norm <text> [fact|preference]
                    norm_parts = arg.rsplit(maxsplit=1)
                    text = norm_parts[0] if norm_parts else ''
                    mtype = norm_parts[1] if len(norm_parts) > 1 else 'fact'
                    cli.test_normalize(text, mtype)
                    continue
                elif cmd == 'purge':
                    cli.purge_memory()
                    continue
                elif cmd == 'stats':
                    cli.show_stats()
                    continue
                elif cmd == 'help':
                    show_help()
                    continue
                else:
                    print(f"❌ 未知命令: /{cmd}，输入 /help 查看帮助")
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
                import traceback
                traceback.print_exc()

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
