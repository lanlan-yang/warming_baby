"""
providers/chat_demo.py — LLM Provider 测试脚本

在终端交互式对话，验证 providers 模块是否正常工作。

Usage:
    cd warming_baby
    python providers/chat_demo.py

Commands:
    /task <chat|complex|code>  — 切换任务类型（模型）
    /stream                   — 切换流式输出
    /quit                     — 退出
"""
import asyncio
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中（从任意位置运行均可）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.logger import setup_logger

from core.enums import ModelTask
from providers import get_llm

logger = setup_logger()
async def chat_once(llm, message: str, streaming: bool = False):
    """单次对话"""
    if streaming:
        print("\n🤖 [流式] ", end="", flush=True)
        full = []
        start = time.perf_counter()
        async for chunk in llm.astream(message):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            if text:
                print(text, end="", flush=True)
                full.append(text)
        elapsed = time.perf_counter() - start
        print(f"\n   ({elapsed:.1f}s)\n")
    else:
        print("🤖 ", end="", flush=True)
        start = time.perf_counter()
        response = await llm.ainvoke(message)
        elapsed = time.perf_counter() - start
        print(f"{response.content}")
        print(f"   ({elapsed:.1f}s)\n")


async def interactive_chat():
    """交互式对话"""
    print("=" * 50)
    print("  LLM Chat Demo — 输入消息开始对话")
    print("  /task chat|complex|code  切换模型")
    print("  /stream                 切换流式输出")
    print("  /quit                   退出")
    print("=" * 50)

    task = ModelTask.CHAT
    streaming = False

    def _show_status():
        mode = "流式" if streaming else "单次"
        print(f"\n  当前: [{task.value}] {mode}模式")
        print("-" * 50)

    _show_status()

    while True:
        try:
            user_input = input("\n🧑 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not user_input:
            continue

        # 命令处理
        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd == "/quit":
                print("bye")
                break
            elif cmd == "/stream":
                streaming = not streaming
                label = "ON" if streaming else "OFF"
                print(f"  流式输出: {label}")
                continue
            elif cmd.startswith("/task"):
                parts = cmd.split()
                if len(parts) == 2:
                    try:
                        task = ModelTask(parts[1])
                        LLMProvider = sys.modules["providers.llm"].LLMProvider
                        LLMProvider.reset()
                        _show_status()
                    except ValueError:
                        valid = [t.value for t in ModelTask if t != ModelTask.VISION and t != ModelTask.EMBEDDING]
                        print(f"  无效任务类型，可用: {valid}")
                    continue
                else:
                    print("  用法: /task chat|complex|code")
                    continue
            else:
                print(f"  未知命令: {cmd}")
                continue

        # 调用 LLM
        try:
            llm = get_llm(task)
            await chat_once(llm, user_input, streaming)
        except ValueError as e:
            print(f"\n❌ 配置错误: {e}")
            print("  请在 .env 设置: LLM_API_KEY=sk-xxx")
            break
        except Exception as e:
            logger.error(f"调用失败: {type(e).__name__}: {e}")
            print(f"\n❌ 调用失败: {e}")


if __name__ == "__main__":
    asyncio.run(interactive_chat())
