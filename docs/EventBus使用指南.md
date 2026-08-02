# EventBus 使用指南

## 概述

EventBus 是项目的**全局事件总线**，基于**发布-订阅模式**实现模块间解耦通信。它将 UI、Agent（AI）、Pet（宠物）三个模块串联起来，让各模块无需直接依赖就能协同工作。

### 架构图

```
┌─────────────┐     发布事件      ┌─────────────┐     发布事件      ┌─────────────┐
│   Pet UI    │ ───────────────► │   EventBus  │ ◄─────────────── │  ChatAgent  │
│  (pet.py)   │                  │  (单例)      │                  │ (chat_agent)│
└─────────────┘                  └─────────────┘                  └─────────────┘
       ▲                                │                                ▲
       │                                │                                │
       │     订阅事件                    │     订阅事件                     │
       └────────────────────────────────┴────────────────────────────────┘
```

---

## 核心概念

### 事件分类（EventCategory）

事件按职责划分为 4 大类，避免命名冲突：

| 分类 | 枚举值 | 说明 | 典型场景 |
|------|--------|------|----------|
| `SYSTEM` | `system` | 系统级事件 | 应用启动、关闭 |
| `UI` | `ui` | 用户交互事件 | 鼠标点击、拖拽、hover |
| `AGENT` | `agent` | AI Agent 事件 | 收到用户消息、思考中、返回响应 |
| `PET` | `pet` | 宠物行为事件 | 动画切换、开始/结束播放、方向变化 |

### 完整事件列表

#### SystemEvent（系统事件）
```python
SystemEvent.STARTUP         # 应用启动
SystemEvent.SHUTDOWN        # 应用关闭
SystemEvent.ERROR           # 系统错误
SystemEvent.CONFIG_CHANGED  # 配置变更
```

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
AgentEvent.USER_MESSAGE      # 用户发送消息给 Agent
AgentEvent.THINKING          # Agent 开始思考/调用大模型
AgentEvent.RESPONSE          # Agent 返回完整响应
AgentEvent.RESPONSE_STREAM   # Agent 流式响应片段
AgentEvent.TOOL_CALL         # Agent 调用工具
AgentEvent.TOOL_RESULT       # 工具执行结果
AgentEvent.ERROR             # Agent 处理出错
```

#### PetEvent（宠物行为）
```python
PetEvent.ANIMATION_START     # 动画开始播放
PetEvent.ANIMATION_END       # 动画结束播放
PetEvent.ANIMATION_CHANGED   # 动画类型切换（如 walk → fly）
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

# 带字典参数
event_bus.publish(
    EventCategory.AGENT, 
    AgentEvent.RESPONSE,
    text="你好呀！",
    emotion="happy",
    play_once=True
)

# 动画事件
event_bus.publish(
    EventCategory.PET, 
    PetEvent.ANIMATION_REQUEST,
    animation="touch",
    play_once=True
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
if has_listeners:
    print("有模块在监听 AI 响应")

# 列出所有已订阅的事件
all_events = event_bus.list_events()
print(f"当前订阅的事件: {all_events}")

# 只列出某个分类的事件
pet_events = event_bus.list_events(EventCategory.PET)
print(f"宠物相关事件: {pet_events}")

# 清除所有订阅（谨慎使用）
# event_bus.clear()

# 清除某个分类的订阅
# event_bus.clear(EventCategory.UI)

# 清除某个具体事件的订阅
# event_bus.clear(EventCategory.UI, UIEvent.MOUSE_CLICK)
```

---

## 实战示例

### 场景 1：用户点击宠物 → 进入聊天模式

```
用户点击宠物
    │
    ▼
Pet.mousePressEvent()
    │
    ├── publish(UI.MOUSE_CLICK, x, y)
    │
    ▼
Pet.show_chat_ui()
    │
    ├── show typing 状态 "..."
    ├── 显示输入框
    └── 等待用户输入
```

**Pet UI（事件发布者）**
```python
class NuanbaoPet(QLabel):
    def mousePressEvent(self, event):
        # 发布点击事件
        event_bus.publish(
            EventCategory.UI, 
            UIEvent.MOUSE_CLICK, 
            x=event.position().x(),
            y=event.position().y()
        )
        
        # 如果还没进入聊天模式，打开聊天 UI
        if not self.is_chatting:
            self.show_chat_ui()
```

### 场景 2：用户发送消息 → AI 回复 → 宠物展示

```
用户输入消息，按回车
    │
    ▼
Pet._on_user_input(text)
    │
    ├── publish(AGENT.USER_MESSAGE, message=text)
    │
    ▼
ChatAgent._on_user_message(message)
    │
    ├── publish(AGENT.THINKING)  ──► Pet 播放 CONFUSED 动画
    │
    ▼
ChatAgent.chat() [异步调用 LLM]
    │
    ├── await graph.ainvoke()
    │
    ▼
ChatAgent.publish(AGENT.RESPONSE, response={text, emotion})
    │
    ▼
Pet._on_agent_response(response)
    │
    ├── QTimer.singleShot(0, ...)  ← 转到 Qt 主线程
    │
    ▼
Pet._handle_agent_response(response)
    │
    ├── show_message(text)          ← 显示气泡
    └── trigger_animation(emotion)  ← 播放对应动画
```

**ChatAgent（事件生产者）**
```python
class ChatAgent:
    def __init__(self):
        self.graph = build_graph()
        
        # 订阅用户消息
        event_bus.subscribe(
            EventCategory.AGENT, 
            AgentEvent.USER_MESSAGE, 
            self._on_user_message
        )
    
    def _on_user_message(self, message: str, **kwargs):
        # 通知 UI：开始思考
        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)
        
        # 异步调用 LLM
        loop = asyncio.get_event_loop()
        loop.create_task(self._call_llm(message))
    
    async def _call_llm(self, message: str):
        # 调用 LangGraph
        result = await self.graph.ainvoke({"user_input": message})
        
        # 发布响应事件
        event_bus.publish(
            EventCategory.AGENT, 
            AgentEvent.RESPONSE,
            text=result["text"],
            emotion=result["emotion"],
            play_once=True
        )
```

**Pet UI（事件消费者）**
```python
class NuanbaoPet(QLabel):
    def __init__(self):
        # 订阅 Agent 事件
        event_bus.subscribe(
            EventCategory.AGENT, 
            AgentEvent.THINKING, 
            self._on_agent_thinking
        )
        event_bus.subscribe(
            EventCategory.AGENT, 
            AgentEvent.RESPONSE, 
            self._on_agent_response
        )
    
    def _on_agent_thinking(self):
        # 在 Qt 主线程执行 UI 更新
        QTimer.singleShot(0, self._play_confused)
    
    def _play_confused(self):
        self.play(AnimationType.CONFUSED)
    
    def _on_agent_response(self, response: dict, **kwargs):
        # 可能来自 asyncio 线程，需要转到 Qt 主线程
        QTimer.singleShot(0, lambda: self._handle_response(response))
    
    def _handle_response(self, response: dict):
        text = response.get("text", "")
        emotion = response.get("emotion", "happy")
        play_once = response.get("play_once", True)
        
        # 显示消息气泡
        self.show_message(text)
        
        # 播放对应动画
        self.trigger_animation(emotion, play_once)
```

### 场景 3：AI 工具请求播放动画

```
LLM 调用 PlayAnimation 工具
    │
    ▼
PlayAnimation.execute(animation="touch")
    │
    ├── event_bus.publish(PET.ANIMATION_REQUEST, ...)
    │
    ▼
Pet._on_animation_request(animation, play_once)
    │
    ├── QTimer.singleShot(0, ...)  ← 转到 Qt 主线程
    │
    ▼
Pet.trigger_animation(animation, play_once)
```

**PlayAnimation 工具**
```python
class PlayAnimation(AgentTool):
    def execute(self, animation: str, play_once: bool = True) -> str:
        # 通过 EventBus 请求播放动画
        event_bus.publish(
            EventCategory.PET,
            PetEvent.ANIMATION_REQUEST,
            animation=animation,
            play_once=play_once
        )
        return f"开始播放 {animation} 动画"
```

**Pet UI 处理动画请求**
```python
class NuanbaoPet(QLabel):
    def __init__(self):
        # 订阅动画请求
        event_bus.subscribe(
            EventCategory.PET,
            PetEvent.ANIMATION_REQUEST,
            self._on_animation_request
        )
    
    def _on_animation_request(self, animation: str, play_once: bool = False, **kwargs):
        # 转到 Qt 主线程执行
        QTimer.singleShot(0, lambda: self.trigger_animation(animation, play_once))
```

### 场景 4：宠物动画事件

```
Pet.play(AnimationType.WALK)
    │
    ├── publish(PET.ANIMATION_START, "walk")
    │
    ▼
[动画播放中...]
    │
    ├── publish(PET.ANIMATION_CHANGED, from_="walk", to_="happy")
    │
    ▼
[动画结束]
    │
    └── publish(PET.ANIMATION_END, "happy")
```

---

## 跨线程安全

### 问题背景

EventBus 本身是**同步调用**（`publish` 直接调用回调），但在 qasync 架构下，事件可能来自**不同线程**：

| 来源线程 | 示例 |
|----------|------|
| Qt 主线程 | `mousePressEvent` 中发布事件 |
| asyncio 线程 | `ChatAgent._call_llm` 发布响应事件 |

### 关键规则

**⚠️ 任何涉及 QWidget/QLabel/UI 操作的回调，必须确保在 Qt 主线程执行！**

### 解决方案

使用 `QTimer.singleShot(0, callback)` 将回调 post 到 Qt 主线程：

```python
from PyQt6.QtCore import QTimer

class PetUI(QLabel):
    def __init__(self):
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.RESPONSE, self._on_response)
    
    def _on_response(self, response: dict):
        # ⚠️ 这个回调可能来自 asyncio 线程！
        # 不能直接操作 UI！
        
        # ✅ 使用 QTimer.singleShot 转到 Qt 主线程
        QTimer.singleShot(0, lambda: self._handle_response(response))
    
    def _handle_response(self, response: dict):
        # ✅ 这里一定在 Qt 主线程，可以安全操作 UI
        self.show_message(response["text"])
        self.trigger_animation(response["emotion"])
```

### 原理说明

`QTimer.singleShot(0, slot)` 会：
1. 将 slot 回调**post** 到事件队列
2. 投递到 receiver（`self`）所在的线程
3. QObject 默认在创建它的线程（Qt 主线程）

### 当前项目中的用法

查看 [pet.py](file:///Users/yangchengwei/Documents/workspace/github_workspace/my_baby/warming_baby/pet/pet.py)：

```python
# pet.py 第 317-340 行
class NuanbaoPet(QLabel):
    def _on_agent_response(self, response: dict):
        # Agent 响应可能来自 asyncio 线程
        QTimer.singleShot(0, lambda: self._handle_agent_response(response))
    
    def _on_agent_thinking(self, data: dict = None):
        # 同样转到 Qt 主线程
        QTimer.singleShot(0, self._handle_agent_thinking)
    
    def _on_animation_request(self, animation: str, play_once: bool = False, **kwargs):
        # 处理动画请求
        QTimer.singleShot(0, lambda: self.trigger_animation(animation, play_once))
```

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
    HAPPY_JUMP = "happy_jump"  # 新增：开心跳跃
```

然后直接使用：

```python
event_bus.publish(EventCategory.PET, PetEvent.BLINK)
```

**无需修改 EventBus 本身！**

---

## API 速查

### EventBus 类（单例，全局使用 `event_bus`）

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `subscribe(category, event, callback)` | `EventCategory, str, Callable` | `None` | 订阅事件 |
| `unsubscribe(category, event, callback)` | `EventCategory, str, Callable` | `None` | 取消订阅 |
| `publish(category, event, *args, **kwargs)` | `EventCategory, str, ...` | `None` | 发布事件 |
| `has_subscribers(category, event)` | `EventCategory, str` | `bool` | 是否有订阅者 |
| `list_events(category=None)` | `EventCategory \| None` | `List[str]` | 列出已订阅事件 |
| `clear(category=None, event=None)` | `EventCategory \| None, str \| None` | `None` | 清除订阅 |

### 导入语句

```python
from core import event_bus
from core import EventCategory, SystemEvent, UIEvent, AgentEvent, PetEvent
```

---

## 注意事项

1. **EventBus 是单例**：全局只有一个实例，所有模块共享
2. **同步调用**：`publish` 会**立即**调用所有回调，会阻塞发布者直到回调执行完
3. **线程安全**：非线程安全，涉及 UI 操作的回调务必用 `QTimer.singleShot` 转到 Qt 主线程
4. **异常隔离**：某个回调抛异常不会影响其他回调（EventBus 内部 try/except 保护）
5. **松耦合**：模块间通过 EventBus 解耦，不要直接 import 其他模块的具体实现
6. **内存管理**：订阅者持有回调引用，如果回调是实例方法，实例不能先被 GC（可以用弱引用或在类中保存强引用）
7. **参数传递**：建议使用关键字参数（`x=1, y=2`），让回调函数签名更清晰

---

## 与其他通信方式对比

| 方式 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **EventBus（推荐）** | 模块内/同一进程 | 解耦、类型安全、轻量、低延迟 | 单进程 |
| 直接调用 | 紧密耦合模块 | 简单直接、类型安全 | 耦合度高、难维护 |
| REST API | 跨进程/跨服务 | 标准协议、可跨平台 | 需要网络开销、序列化 |
| WebSocket | 实时双向通信 | 低延迟、全双工 | 复杂度高、需要服务端 |

**本项目选择 EventBus**：所有模块都在同一进程内，追求低延迟和松耦合，无需网络开销。
