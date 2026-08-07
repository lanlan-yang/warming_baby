# EventBus 使用指南

## 概述

EventBus 是项目的**全局事件总线**，基于**发布-订阅模式**实现模块间解耦通信。它将 UI、Agent（AI）、Pet（宠物）、App（应用生命周期）四个模块串联起来，让各模块无需直接依赖就能协同工作。

### 架构图

```
┌─────────────┐     发布事件      ┌─────────────┐     发布事件      ┌─────────────┐
│   Pet UI    │ ───────────────► │   EventBus  │ ◄─────────────── │  ChatAgent  │
│  (pet.py)   │                  │  (单例)      │                  │(chat_agent) │
└─────────────┘                  └─────────────┘                  └─────────────┘
       ▲                                │                                ▲
       │                                │                                │
       │     订阅事件                    │     订阅事件                     │
       └────────────────────────────────┴────────────────────────────────┘
                                        ▲
                                        │ 发布 System 事件
                                ┌───────────────┐
                                │    app.py     │
                                │ (应用生命周期)  │
                                └───────────────┘
```

**事件流向**：

- `app.py` 发布 `AGENT_READY`、`LLM_CONFIG_ERROR` 等 System 事件
- `pet.py` 发布 `USER_MESSAGE`、`AUTO_SPEAK` 事件 → `ChatAgent` 订阅
- `ChatAgent` 发布 `THINKING`、`RESPONSE` 事件 → `pet.py` 订阅
- `ChatAgent` 发布 `LLM_CONFIG_ERROR` → `pet.py` 订阅（显示错误提示）

---

## 核心概念

### 事件分类（EventCategory）

事件按职责划分为 4 大类，避免命名冲突：

| 分类     | 枚举值   | 说明          | 典型场景                                 |
| -------- | -------- | ------------- | ---------------------------------------- |
| `SYSTEM` | `system` | 系统级事件    | 应用启动、关闭、Agent 就绪、LLM 配置错误 |
| `UI`     | `ui`     | 用户交互事件  | 鼠标点击、拖拽、hover                    |
| `AGENT`  | `agent`  | AI Agent 事件 | 收到用户消息、思考中、返回响应、主动说话 |
| `PET`    | `pet`    | 宠物行为事件  | 动画切换、开始/结束播放、方向变化        |

### 完整事件列表

> 源码位置：[core/event_bus.py](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/core/event_bus.py)

#### SystemEvent（系统事件）

```python
SystemEvent.STARTUP          # 应用启动
SystemEvent.SHUTDOWN         # 应用关闭
SystemEvent.ERROR            # 系统错误
SystemEvent.CONFIG_CHANGED   # 配置变更
SystemEvent.LLM_CONFIG_ERROR # LLM 配置错误（API Key 缺失等）
SystemEvent.AGENT_READY      # Agent 预热完成，可以显示宠物
```

发布者：`app.py`（`AGENT_READY`）、`chat_agent.py`（`LLM_CONFIG_ERROR`）

#### UIEvent（用户交互）

```python
UIEvent.MOUSE_CLICK          # 鼠标左键单击
UIEvent.MOUSE_DOUBLE_CLICK   # 鼠标双击
UIEvent.MOUSE_DRAG_START     # 开始拖拽（移动距离超过阈值）
UIEvent.MOUSE_DRAG_MOVE      # 拖拽过程中持续触发
UIEvent.MOUSE_DRAG_END       # 拖拽结束（释放鼠标）
UIEvent.MOUSE_HOVER_ENTER    # 鼠标进入宠物区域
UIEvent.MOUSE_HOVER_LEAVE    # 鼠标离开宠物区域
UIEvent.KEY_PRESS            # 键盘按键
UIEvent.WINDOW_MOVE          # 窗口位置移动
UIEvent.WINDOW_RESIZE        # 窗口大小改变
```

#### AgentEvent（AI 交互）

```python
AgentEvent.USER_MESSAGE      # 用户发送消息给 Agent（pet → agent）
AgentEvent.THINKING          # Agent 开始思考/调用大模型
AgentEvent.RESPONSE          # Agent 返回完整响应
AgentEvent.RESPONSE_STREAM   # Agent 流式响应片段（预留）
AgentEvent.TOOL_CALL         # Agent 调用工具
AgentEvent.TOOL_RESULT       # 工具执行结果
AgentEvent.AUTO_SPEAK        # 宠物主动说话（无需用户输入）
AgentEvent.ERROR             # Agent 处理出错
```

#### PetEvent（宠物行为）

```python
PetEvent.ANIMATION_START     # 动画开始播放
PetEvent.ANIMATION_END       # 动画结束播放
PetEvent.ANIMATION_CHANGED   # 动画类型切换（如 walk → happy）
PetEvent.ANIMATION_REQUEST   # 请求播放动画（AI Agent 触发）
PetEvent.STATE_CHANGED       # 宠物状态变化
PetEvent.MOVE                # 宠物位置移动
PetEvent.DIRECTION_CHANGED   # 宠物朝向变化（左/右）
```

---

## 快速开始

### 导入

```python
from core import event_bus, EventCategory, UIEvent, AgentEvent, PetEvent, SystemEvent
```

### 订阅事件

```python
# 简单的回调函数
def on_pet_click(x, y):
    print(f"宠物被点击了，位置: ({x}, {y})")

event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, on_pet_click)

# 使用实例方法（推荐）
class MyClass:
    def __init__(self):
        event_bus.subscribe(
            EventCategory.AGENT,
            AgentEvent.RESPONSE,
            self._on_agent_response
        )

    def _on_agent_response(self, response: dict):
        text = response.get("text", "")
        emotion = response.get("emotion", "")
        print(f"AI 回复: {text} (情绪: {emotion})")
```

### 发布事件

```python
# 无参数事件
event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)

# 带关键字参数
event_bus.publish(
    EventCategory.UI,
    UIEvent.MOUSE_CLICK,
    x=100,
    y=200
)

# 带字典参数（注意：dict 作为位置参数传入，回调需用 **kwargs 或 data 接收）
event_bus.publish(
    EventCategory.AGENT,
    AgentEvent.RESPONSE,
    chat_response.model_dump(),  # 位置参数
)

# System 事件
event_bus.publish(
    EventCategory.SYSTEM,
    SystemEvent.LLM_CONFIG_ERROR,
    {"error": "API Key 未配置", "source": "chat"}
)
```

### 取消订阅

通常**不需要**手动取消（对象销毁时会自然移除）。如果确实需要：

```python
event_bus.unsubscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, on_pet_click)
```

### 查询事件

```python
# 检查某事件是否有订阅者
has_listeners = event_bus.has_subscribers(EventCategory.AGENT, AgentEvent.RESPONSE)

# 列出所有已订阅的事件
all_events = event_bus.list_events()

# 只列出某个分类的事件
pet_events = event_bus.list_events(EventCategory.PET)
```

---

## 实战示例

> 以下示例全部对应当前代码，可对照源码阅读

### 场景 1：用户点击宠物 → 进入聊天模式

**实际流程**：`mousePressEvent` 直接调用 `show_chat_ui()`，不发 EventBus 事件。

```
用户点击宠物
    │
    ▼
Pet.mousePressEvent()
    │
    ├── 记录点击位置
    │
    ▼ (释放鼠标后)
Pet._on_click_triggered()
    │
    ├── show_chat_ui()  ← 直接调方法，不走 EventBus
    │
    └── 显示输入框 + 播放 CONFUSED 动画
```

**源码**：[pet/pet.py](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py) 的 `mousePressEvent` / `show_chat_ui`

> **说明**：UI 内部的简单交互（如点击显示输入框）不需要走 EventBus，直接方法调用更简单。EventBus 用于**跨模块**通信。

### 场景 2：用户发送消息 → AI 回复 → 宠物展示

这是 EventBus 最核心的场景，涉及 UI → Agent → UI 的完整闭环。

```
用户输入消息，按回车
    │
    ▼
Pet._on_user_input(text)
    │
    ├── hide_panel() + show_typing()
    │
    └── QTimer.singleShot(0, publish(AGENT.USER_MESSAGE, message=text))
                              │
                              ▼
ChatAgent._on_user_message(message)
    │
    ├── publish(AGENT.THINKING)  ──► Pet 播放 CONFUSED 动画
    │
    └── _run_in_background(self.chat(message))
                              │
                              ▼
ChatAgent.chat()
    │
    ├── 检查 API Key（未配置则发 LLM_CONFIG_ERROR，return）
    ├── _ensure_chat_graph() + _ensure_location_fetch()
    ├── _build_messages() (系统提示 + 核心记忆 + 历史 + 用户消息)
    │
    └── await self._chat_graph.run_chat(messages)
                              │
                              ▼
    publish(AGENT.RESPONSE, chat_response.model_dump())
                              │
                              ▼
Pet._on_agent_response(response)
    │
    ├── 检查 _is_exiting / isVisible()
    │
    └── _agent_response_received.emit(response)  ← pyqtSignal 跨线程
                              │
                              ▼ (Qt 主线程)
Pet._handle_agent_response(response)
    │
    ├── show_message(text)          ← 显示气泡
    └── trigger_animation(emotion)  ← 播放对应动画
```

**Pet UI（事件发布者）** — [pet/pet.py#L526-528](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py#L526-528)

```python
def _on_user_input(self, text: str):
    logger.info(f"[User] 发送: {text}")
    if self.input_panel:
        self.input_panel.hide_panel()
    self.show_typing()

    # 用 QTimer.singleShot 让 Qt 先刷新 UI（显示"..."）再发布事件
    QTimer.singleShot(0, lambda: event_bus.publish(
        EventCategory.AGENT, AgentEvent.USER_MESSAGE, message=text
    ))
```

**ChatAgent（事件消费者 + 生产者）** — [agent/chat/chat_agent.py#L178-182](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/agent/chat/chat_agent.py#L178-182)

```python
def _on_user_message(self, message: str, **kwargs) -> None:
    """处理 USER_MESSAGE 事件"""
    logger.info(f"[ChatAgent] USER_MESSAGE: '{message}'")
    event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)
    self._run_in_background(self.chat(message, kwargs.get("history")))

async def chat(self, message, history=None) -> ChatResponse:
    # ... 构建 messages ...
    chat_response = await self._chat_graph.run_chat(messages)

    event_bus.publish(
        EventCategory.AGENT,
        AgentEvent.RESPONSE,
        chat_response.model_dump(),  # 位置参数，回调用 response: dict 接收
    )
    return chat_response
```

**Pet UI（事件消费者）** — [pet/pet.py#L577-614](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py#L577-614)

```python
def _on_agent_response(self, response: dict):
    """Agent 响应回调（可能来自非 Qt 线程，需安全转发）"""
    if self._is_exiting or not self.isVisible():
        return
    # 使用 pyqtSignal 跨线程转发到 Qt 主线程
    self._agent_response_received.emit(response)

def _handle_agent_response(self, response: dict):
    """实际处理 Agent 响应（在 Qt 主线程执行）"""
    if not self.can_process_response():
        return

    text = response.get('text', '')
    emotion = response.get('emotion', '')
    play_once = response.get('play_once', True)

    if text and self.can_show_bubble():
        self.show_message(text, auto_hide=True)

    if emotion and self.can_trigger_animation():
        self.trigger_animation(emotion, play_once)
```

### 场景 3：宠物主动说话

宠物定时触发主动说话，ChatAgent 单次 LLM 调用生成短句。

```
auto_speak_check_timer 触发
    │
    ▼
Pet._check_auto_speak()
    │
    ├── 检查 can_auto_speak()（非睡眠/拖拽/聊天/预热中）
    │
    └── publish(AGENT.AUTO_SPEAK, prompt=prompt)
                              │
                              ▼
ChatAgent._on_auto_speak(prompt)
    │
    └── _run_in_background(self.auto_speak(prompt))
                              │
                              ▼
ChatAgent.auto_speak()
    │
    ├── 检查 API Key（未配置则 return，不发请求）
    ├── get_llm(thinking_enabled=False)  ← 禁用思考，快速响应
    │
    └── await structured_llm.ainvoke(messages)
                              │
                              ▼
    publish(AGENT.RESPONSE, response_data)  ← 带 is_auto_speak=True
                              │
                              ▼
Pet._on_agent_response(response)  ← 同场景 2
```

**源码**：

- 发布：[pet/pet.py#L1685-1689](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py#L1685-1689)
- 订阅：[agent/chat/chat_agent.py#L184-187](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/agent/chat/chat_agent.py#L184-187)
- 执行：[agent/chat/chat_agent.py#L260-313](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/agent/chat/chat_agent.py#L260-313)

### 场景 4：LLM 配置错误 → 提示用户

API Key 未配置或 LLM 调用失败时，通过 System 事件通知 UI。

```
ChatAgent.chat() 检测到无 API Key
    │
    ▼
publish(SYSTEM.LLM_CONFIG_ERROR, {"error": "...", "source": "chat"})
    │
    ▼
Pet._on_llm_config_error(data)
    │
    └── _llm_config_error_received.emit(data)  ← pyqtSignal 跨线程
                │
                ▼ (Qt 主线程)
Pet._handle_llm_config_error(data)
    │
    └── show_message("我还没配置好呢～请右键我 → 「设置」配置 API Key")
```

**源码**：

- 发布：[agent/chat/chat_agent.py#L212-216](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/agent/chat/chat_agent.py#L212-216)
- 订阅：[pet/pet.py#L208](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py#L208)
- 处理：[pet/pet.py#L530-534](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py#L530-534)

### 场景 5：应用预热完成

`app.py` 在后台预热完成后发布 `AGENT_READY` 事件。

```
app._warmup_in_background() 完成
    │
    ▼
publish(SYSTEM.AGENT_READY, {"chat_agent": True, "success": True})
    │
    ▼
（当前无订阅者，仅作为日志/调试用途，未来可扩展）
```

**源码**：[app.py#L284-288](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/app.py#L284-288)

---

## 跨线程安全

### 问题背景

EventBus 本身是**同步调用**（`publish` 直接调用回调），但在 qasync 架构下，事件可能来自**不同线程**：

| 来源线程     | 示例                            |
| ------------ | ------------------------------- |
| Qt 主线程    | `mousePressEvent` 中发布事件    |
| asyncio 线程 | `ChatAgent.chat()` 发布响应事件 |

### 关键规则

**⚠️ 任何涉及 QWidget/QLabel/UI 操作的回调，必须确保在 Qt 主线程执行！**

### 解决方案：pyqtSignal（项目实际使用的方式）

使用 `pyqtSignal` 跨线程转发，信号 emit 时 Qt 会自动将调用投递到接收者所在的线程（Qt 主线程）。

```python
from PyQt6.QtCore import pyqtSignal

class NuanbaoPet(QLabel):
    # 定义信号（类级别）
    _agent_response_received = pyqtSignal(dict)
    _agent_thinking_received = pyqtSignal()
    _animation_request_received = pyqtSignal(dict)
    _llm_config_error_received = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        # 连接信号到处理函数（处理函数在 Qt 主线程执行）
        self._agent_response_received.connect(self._handle_agent_response)
        self._agent_thinking_received.connect(self._handle_agent_thinking)
        self._animation_request_received.connect(self._handle_animation_request)
        self._llm_config_error_received.connect(self._handle_llm_config_error)

        # 订阅 EventBus 事件
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.RESPONSE, self._on_agent_response)
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.THINKING, self._on_agent_thinking)

    def _on_agent_response(self, response: dict):
        """EventBus 回调（可能来自 asyncio 线程）"""
        if self._is_exiting or not self.isVisible():
            return
        # 通过信号转发到 Qt 主线程
        self._agent_response_received.emit(response)

    def _handle_agent_response(self, response: dict):
        """实际处理（在 Qt 主线程执行，可安全操作 UI）"""
        self.show_message(response['text'])
        self.trigger_animation(response['emotion'])
```

### 为什么用 pyqtSignal 而不是 QTimer.singleShot？

| 方式                      | 优点                                | 缺点                              |
| ------------------------- | ----------------------------------- | --------------------------------- |
| **pyqtSignal（推荐）**    | Qt 原生机制，自动线程切换，类型安全 | 需要预先定义信号                  |
| QTimer.singleShot(0, ...) | 简单，无需预定义                    | 无类型检查，lambda 捕获变量需小心 |

项目早期用 `QTimer.singleShot`，后来统一改为 `pyqtSignal`，更规范。当前 [pet.py](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py) 中所有跨线程转发都用信号。

### 例外：发布事件时也可用 QTimer

在 UI 线程内发布事件时，如果希望先让 Qt 刷新 UI 再发布，可以用 `QTimer.singleShot(0, ...)`：

```python
# pet.py#L526 - 先显示"..."再发布 USER_MESSAGE
QTimer.singleShot(0, lambda: event_bus.publish(
    EventCategory.AGENT, AgentEvent.USER_MESSAGE, message=text
))
```

这里 `QTimer.singleShot` 不是用于跨线程，而是用于**延迟一帧**，让 UI 先刷新。

---

## 添加自定义事件

如果需要新的事件类型，只需在对应的 Enum 中添加：

```python
# 在 core/event_bus.py 中

class AgentEvent(StrEnum):
    # ... 现有事件
    STREAM_CHUNK = "stream_chunk"  # 新增：LLM 流式输出的每个 chunk
    TOOL_INVOKED = "tool_invoked"  # 新增：LLM 调用了某个具体工具

class PetEvent(StrEnum):
    # ... 现有事件
    BLINK = "blink"  # 新增：眨眼睛动画
```

然后直接使用：

```python
event_bus.publish(EventCategory.PET, PetEvent.BLINK)
```

**无需修改 EventBus 本身！**

---

## API 速查

### EventBus 类（单例，全局使用 `event_bus`）

| 方法                                        | 参数                                 | 返回值      | 说明           |
| ------------------------------------------- | ------------------------------------ | ----------- | -------------- |
| `subscribe(category, event, callback)`      | `EventCategory, str, Callable`       | `None`      | 订阅事件       |
| `unsubscribe(category, event, callback)`    | `EventCategory, str, Callable`       | `None`      | 取消订阅       |
| `publish(category, event, *args, **kwargs)` | `EventCategory, str, ...`            | `None`      | 发布事件       |
| `has_subscribers(category, event)`          | `EventCategory, str`                 | `bool`      | 是否有订阅者   |
| `list_events(category=None)`                | `EventCategory \| None`              | `List[str]` | 列出已订阅事件 |
| `clear(category=None, event=None)`          | `EventCategory \| None, str \| None` | `None`      | 清除订阅       |

### 导入语句

```python
from core import event_bus
from core import EventCategory, SystemEvent, UIEvent, AgentEvent, PetEvent
```

---

## 注意事项

1. **EventBus 是单例**：全局只有一个实例，所有模块共享
2. **同步调用**：`publish` 会**立即**调用所有回调，会阻塞发布者直到回调执行完
3. **线程安全**：非线程安全，涉及 UI 操作的回调务必用 `pyqtSignal` 转到 Qt 主线程
4. **异常隔离**：某个回调抛异常不会影响其他回调（EventBus 内部 try/except 保护）
5. **松耦合**：模块间通过 EventBus 解耦，不要直接 import 其他模块的具体实现
6. **参数传递**：建议使用关键字参数（`x=1, y=2`），让回调函数签名更清晰；但项目中也用位置参数传 dict（如 `RESPONSE` 事件传 `chat_response.model_dump()`）
7. **状态守卫**：回调开头检查 `_is_exiting` / `isVisible()` 等状态，避免退出时还在处理事件

---

## 与其他通信方式对比

| 方式                          | 适用场景                 | 优点                  | 缺点                 |
| ----------------------------- | ------------------------ | --------------------- | -------------------- |
| **EventBus（跨模块）**        | UI ↔ Agent ↔ App         | 解耦、类型安全、轻量  | 单进程、需手动跨线程 |
| **pyqtSignal（跨线程）**      | asyncio → Qt 主线程      | Qt 原生、自动线程切换 | 需预定义信号         |
| **直接调用**                  | 模块内（如 pet.py 内部） | 简单直接              | 耦合度高             |
| **QTimer.singleShot(0, ...)** | 延迟一帧执行             | 无需预定义            | 不适合跨线程 UI 操作 |

**本项目选择**：

- 跨模块通信用 **EventBus**（解耦）
- 跨线程转发用 **pyqtSignal**（Qt 原生线程切换）
- 模块内简单交互用**直接调用**（如 `show_chat_ui()`）
