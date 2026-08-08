# EventBus 与异步任务投递

## 核心结论

`event_bus` 是主线程同步派发，回调函数必须是同步的（`def`，不能 `async def`）。
在同步回调里要执行异步逻辑，需要借助主事件循环 `create_task()` 把协程投递回主 loop 异步执行。

## 完整链路

```
主线程 event_bus.publish(USER_MESSAGE)
        ↓ 同步调用
ChatAgent._on_user_message(msg)             ← 同步回调
        ↓
_run_in_background(self.chat(msg))
        ↓
main_loop.create_task(coro)                 ← 把协程塞进主 loop
        ↓ 协程异步跑完
task.add_done_callback(_handle_task_result) ← 完成后回到主线程处理异常
```

## 三个关键点

1. **event_bus 是主线程同步派发**
   - `publish()` / `subscribe()` 都是同步方法
   - 回调函数必须是 `def`，不能是 `async def`

2. **同步回调里不能 `await`**
   - 必须用 `main_loop.create_task()` 把协程投递回主事件循环异步执行
   - 这就是 `_run_in_background()` 的作用

3. **`done_callback` 是异常兜底**
   - 不加 callback，Task 抛的异常会被 asyncio 静默吞掉
   - 加上后能在任务完成后捕获并记录异常

## 为什么必须传 `event_loop=main_loop`

```python
# app.py
self.chat_agent = ChatAgent(event_loop=main_loop)
```

不是为了让任务"异步执行"，而是为了让**同步回调能找到那个运行中的事件循环**。

原因：在 `def` 函数里调用 `asyncio.get_running_loop()` 会抛 `RuntimeError`（因为不在协程上下文里），所以必须显式传入 loop 引用。

```python
def _run_in_background(self, coro) -> None:
    if self._main_loop is None:
        self._main_loop = asyncio.get_running_loop()  # 兜底（协程上下文可用）
    task = self._main_loop.create_task(coro)
    task.add_done_callback(self._handle_task_result)
```

## 一句话总结

> event_bus 把任务交给异步方法，其实是 **ChatAgent 在同步的事件回调里，借助传入的 `main_loop`，用 `create_task` 把协程塞进主事件循环异步执行**。`event_loop=main_loop` 桥接了「同步事件总线」和「异步协程执行」两个世界。

## 补充：Qt 信号槽（Pet 侧的接收）

event_bus 回调里不直接操作 UI，而是 `pyqtSignal.emit()` → Qt 槽函数，原因有三：

1. **防子线程回调**：`asyncio.to_thread()` 里如果触发 publish，回调就在线程池线程，直接操作 UI 会崩
2. **防重入**：`emit` 把 UI 操作推迟到下一次事件循环迭代，当前协程栈先干净退出，避免 `processEvents()` 引发的嵌套回调
3. **解耦**：`_on_xxx_response` 只管收数据，`_handle_xxx_response` 只管画 UI，逻辑分层

## 补充：qasync 下的真实线程模型

```
单进程
├─ 主线程：Qt EventLoop + asyncio EventLoop 共享（qasync 合并）
│   ├─ Qt 定时器/鼠标事件/UI渲染
│   └─ asyncio 协程（LLM、event_bus 回调）
└─ 默认 ThreadPoolExecutor：asyncio.to_thread() 扔的阻塞任务
   └─ Embedding 加载、chromadb 向量检索等
```

event_bus 回调大多在主线程，但信号机制仍然必要（原因见上一节）。

## 相关代码

- [app.py](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/app.py) - ChatAgent 创建处
- [chat_agent.py](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/agent/chat/chat_agent.py) - `_run_in_background` / `_handle_task_result`
- [event_bus.py](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/core/event_bus.py) - 同步发布/订阅
- [pet.py](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py#L197-L201) - Qt 信号连接处
