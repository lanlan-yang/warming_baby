# EventBus 使用指南

## 概述

EventBus 是项目的**全局事件总线**，基于**发布-订阅模式**实现模块间解耦通信。它将 UI、Agent（AI）、Pet（宠物）三个模块串联起来，让各模块无需直接依赖就能协同工作。

---

## 核心概念

### 事件分类（EventCategory）

事件按职责划分为 4 大类，避免命名冲突：

| 分类 | 枚举值 | 说明 | 典型事件 |
|------|--------|------|----------|
| `SYSTEM` | `system` | 系统级事件 | 应用启动、关闭、配置变更 |
| `UI` | `ui` | 用户交互事件 | 鼠标点击、拖拽、hover |
| `AGENT` | `agent` | AI Agent 事件 | 收到用户消息、思考中、返回响应 |
| `PET` | `pet` | 宠物行为事件 | 动画切换、开始/结束播放 |

### 事件名称

每个分类下有具体的事件枚举：

**UIEvent（用户交互）**
```python
UIEvent.MOUSE_CLICK          # 鼠标点击
UIEvent.MOUSE_DOUBLE_CLICK   # 鼠标双击
UIEvent.MOUSE_DRAG_START     # 开始拖拽
UIEvent.MOUSE_DRAG_END       # 拖拽结束
UIEvent.MOUSE_HOVER_ENTER    # 鼠标进入
UIEvent.MOUSE_HOVER_LEAVE    # 鼠标离开
```

**AgentEvent（AI 交互）**
```python
AgentEvent.USER_MESSAGE    # 用户发送消息给 AI
AgentEvent.THINKING        # AI 正在思考
AgentEvent.RESPONSE        # AI 返回响应
AgentEvent.RESPONSE_STREAM # AI 流式响应（逐字输出）
AgentEvent.TOOL_CALL       # AI 调用工具
AgentEvent.TOOL_RESULT     # 工具执行结果
AgentEvent.ERROR           # AI 出错
```

**PetEvent（宠物状态）**
```python
PetEvent.ANIMATION_START      # 动画开始
PetEvent.ANIMATION_END        # 动画结束
PetEvent.ANIMATION_CHANGED    # 动画切换
PetEvent.STATE_CHANGED        # 状态变化
PetEvent.DIRECTION_CHANGED    # 朝向变化
```

**SystemEvent（系统事件）**
```python
SystemEvent.STARTUP         # 应用启动
SystemEvent.SHUTDOWN        # 应用关闭
SystemEvent.ERROR           # 系统错误
SystemEvent.CONFIG_CHANGED  # 配置变更
```

---

## 基本用法

### 订阅事件

订阅后，每次该事件被发布，回调函数就会被调用。

```python
from core import event_bus, EventCategory, UIEvent, AgentEvent, PetEvent

# 订阅宠物点击事件
def on_pet_click(x, y):
    print(f"宠物被点击了，位置: ({x}, {y})")
event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, on_pet_click)

# 订阅 AI 返回响应
def on_ai_response(response: dict):
    text = response.get("text", "")
    emotion = response.get("emotion", "")
    print(f"AI说: {text} (情绪: {emotion})")
event_bus.subscribe(EventCategory.AGENT, AgentEvent.RESPONSE, on_ai_response)
```

### 发布事件

```python
# 发布 UI 事件（带位置参数）
event_bus.publish(EventCategory.UI, UIEvent.MOUSE_CLICK, x=100, y=200)

# 发布 Agent 响应事件（带 dict 参数）
event_bus.publish(
    EventCategory.AGENT, AgentEvent.RESPONSE,
    response={"text": "你好", "emotion": "happy"},
)

# 发布动画切换事件
event_bus.publish(
    EventCategory.PET, PetEvent.ANIMATION_CHANGED,
    from_="walk", to_="fly",
)
```

### 取消订阅

通常不需要手动取消（事件总线会自动管理）。如果确实需要：

```python
event_bus.unsubscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, on_pet_click)
```

### 查询事件

```python
# 检查某事件是否有订阅者
if event_bus.has_subscribers(EventCategory.AGENT, AgentEvent.RESPONSE):
    print("有模块在监听 AI 响应")

# 列出所有已订阅的事件
all_events = event_bus.list_events()
print(f"当前订阅的事件: {all_events}")

# 只列出某个分类的事件
ui_events = event_bus.list_events(EventCategory.UI)
```

---

## 跨线程安全

EventBus 本身是**同步调用**（`publish` 直接调用回调），但在 qasync 架构下，事件可能来自**不同线程**：

| 来源线程 | 示例 |
|----------|------|
| FastAPI asyncio 线程 | `POST /chat` 接口调用 `event_bus.publish` |
| 普通 thread（LLM 调用） | `LLMAgent._call_llm` 在线程中发布事件 |
| Qt 主线程 | `mousePressEvent` 中发布事件 |

**⚠️ 关键规则：凡是操作 QWidget/QLabel 的回调，必须确保在 Qt 主线程执行。**

### 线程安全示例

```python
from PyQt6.QtCore import QTimer

class PetController:
    def __init__(self):
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.RESPONSE, self._on_response)

    def _on_response(self, response: dict):
        # 可能来自 asyncio 线程或普通 thread
        # 需要将实际 UI 操作 post 到 Qt 主线程
        QTimer.singleShot(0, lambda: self._handle_response(response))

    def _handle_response(self, response: dict):
        # 这里一定在 Qt 主线程
        self.pet.show_message(response["text"])
        self.pet.trigger_animation(response.get("emotion", "happy"))
```

**原理**：`QTimer.singleShot(0, slot)` 会将 slot 回调 post 到 receiver 对象所在线程（即创建它的线程），而 QObject 默认在创建它的线程（Qt 主线程）。

---

## 项目实战场景

### 场景 1：LLM 驱动宠物动画

```
┌──────────┐   publish(USER_MESSAGE)   ┌─────────┐
│ FastAPI  │ ────────────────────────► │         │
│  /chat   │                           │         │
└──────────┘                           │         │
                                       │ EventBus │
┌──────────┐   subscribe(USER_MESSAGE)  │         │
│ LLMAgent │ ◄──────────────────────── │         │
│          │                           │         │
│ ├─ 调用 LLM                          │         │
│ └─ publish(RESPONSE) ──────────────► │         │
└──────────┘                           │         │
                                       │         │
┌──────────┐   subscribe(RESPONSE)      │         │
│ Pet UI   │ ◄──────────────────────── │         │
│          │   (QTimer.singleShot)      └─────────┘
│ ├─ show_message(text)
│ └─ trigger_animation(emotion)
└──────────┘
```

**LLMAgent（事件生产者）**
```python
class LLMAgent:
    def __init__(self):
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.USER_MESSAGE, self.on_user_message)

    def on_user_message(self, message: str):
        # 发布思考中事件（宠物会播 confused 动画）
        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)

        # 异步调用 LLM，完成后发布响应
        threading.Thread(target=self.call_llm, args=(message,), daemon=True).start()

    def call_llm(self, message: str):
        response = self.client.chat.completions.create(...)
        event_bus.publish(
            EventCategory.AGENT, AgentEvent.RESPONSE,
            response={"text": response.text, "emotion": "happy"},
        )
```

**Pet UI（事件消费者）**
```python
class NuanbaoPet(QLabel):
    def __init__(self):
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.RESPONSE, self._on_response)
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.THINKING, self._on_thinking)

    def _on_thinking(self):
        QTimer.singleShot(0, self.play_confused)

    def _on_response(self, response: dict):
        QTimer.singleShot(0, lambda: self.handle_response(response))

    def play_confused(self):
        self.play(AnimationType.CONFUSED)

    def handle_response(self, response: dict):
        self.show_message(response["text"])
        self.trigger_animation(response.get("emotion", "happy"))
```

**FastAPI（事件生产者）**
```python
from fastapi import APIRouter
from core import event_bus, EventCategory, AgentEvent

router = APIRouter()

@router.post("/chat")
async def chat(req: ChatRequest):
    # HTTP 接口直接发布事件，不关心谁来处理
    event_bus.publish(EventCategory.AGENT, AgentEvent.USER_MESSAGE, message=req.message)
    return {"status": "ok"}
```

### 场景 2：宠物点击打开聊天框

```python
class NuanbaoPet(QLabel):
    def mousePressEvent(self, event):
        # 点击时发布事件
        event_bus.publish(EventCategory.UI, UIEvent.MOUSE_CLICK, x=event.x(), y=event.y())

    def show_chat_ui(self):
        # 内部监听自身事件（或由外部监听）
        ...
```

### 场景 3：添加新事件类型

如果需要新的事件，只需在对应的 Enum 中添加：

```python
class AgentEvent(StrEnum):
    ...
    # 新增：LLM 流式输出的每个 chunk
    STREAM_CHUNK = "stream_chunk"
    # 新增：LLM 调用了某个具体工具
    TOOL_INVOKED = "tool_invoked"
```

然后直接使用，无需修改 EventBus 本身。

---

## 完整流程示例

### 用户点击宠物 → AI 回复 → 宠物 happy

```
时间线:
═══════════════════════════════════════════════════════════════════════════

[用户] 点击宠物
   │
   ▼
[Pet] mousePressEvent
   │ publish(UI.MOUSE_CLICK)
   │ publish(UI.DRAG_START) [如果拖拽]
   │ play(FLY) [如果拖拽]
   │
   ▼
[Pet] show_chat_ui()
   │ play(CONFUSED)
   │ show_input_panel()
   │
   ▼
[用户] 输入文字, 按 Enter
   │
   ▼
[Pet] _on_user_input(text)
   │ publish(AGENT.USER_MESSAGE, message=text)
   │
   ▼
[LLMAgent] on_user_message(message)
   │ publish(AGENT.THINKING) ────────► [Pet] play(CONFUSED) ✓
   │
   ▼
[LLMAgent] call_llm() [后台线程]
   │ 调用 LLM API (1-2秒)
   │
   ▼
[LLMAgent] publish(AGENT.RESPONSE, response={text, emotion:"happy"})
   │
   ▼
[Pet] _on_response(response) [可能来自非 Qt 线程]
   │ QTimer.singleShot(0, ...)
   │
   ▼
[Pet] _handle_response(response) [Qt 主线程]
   │ show_message(text) ─────────────► 显示气泡
   │ trigger_animation("happy") ─────► play_once(TOUCH)
   │
   ▼
[Pet] TOUCH 动画结束
   │ _on_once_finished(prev_type)
   │ prev_type == CONFUSED? → play(WALK or STAND)
   │
   ▼
[Pet] 恢复走路/站立, 🎉 完成

═══════════════════════════════════════════════════════════════════════════
```

---

## API 速查

### 类：`EventBus`（单例，全局使用 `event_bus`）

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `subscribe(category, event, callback)` | `EventCategory, str, Callable` | `None` | 订阅事件 |
| `unsubscribe(category, event, callback)` | `EventCategory, str, Callable` | `None` | 取消订阅 |
| `publish(category, event, *args, **kwargs)` | `EventCategory, str, ...` | `None` | 发布事件 |
| `has_subscribers(category, event)` | `EventCategory, str` | `bool` | 是否有订阅者 |
| `list_events(category=None)` | `EventCategory \| None` | `List[str]` | 列出已订阅事件 |
| `clear(category=None, event=None)` | `EventCategory \| None, str \| None` | `None` | 清除订阅 |

### 导入

```python
from core import event_bus, EventCategory, UIEvent, PetEvent, AgentEvent, SystemEvent
```

---

## 注意事项

1. **EventBus 是单例**：全局只有一个实例，所有模块共享
2. **同步调用**：`publish` 会**立即**调用所有回调，阻塞发布者直到回调全部执行完
3. **线程安全**：非线程安全，回调涉及 UI 操作时务必用 `QTimer.singleShot` 转到 Qt 主线程
4. **异常隔离**：某个回调抛异常不会影响其他回调（EventBus 内部 try/except 保护）
5. **新事件添加**：直接在 Enum 中新增即可，无需改 EventBus 核心
6. **避免循环依赖**：模块间通过 EventBus 解耦，不要直接 import 其他模块的具体实现
7. **内存管理**：订阅者持有回调引用，如果回调是实例方法，实例不能先被 GC

---

## 与其他通信方式对比

| 方式 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **EventBus（推荐）** | 模块内/同一进程 | 解耦、类型安全、轻量 | 单进程 |
| REST API | 跨进程/跨服务 | 标准协议、可跨平台 | 需要网络开销、异步 |
| WebSocket | 实时双向通信 | 低延迟、全双工 | 复杂度高、需要服务端 |
| Direct Call | 紧密耦合模块 | 简单直接 | 耦合度高、难维护 |

**本项目选择 EventBus**：模块都在同一进程内，追求低延迟和松耦合，REST API 仅作为外部入口（FastAPI `/chat`），内部全部走 EventBus。
