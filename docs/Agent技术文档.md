# Agent 技术文档

## 目录

- [1. 架构概览](#1-架构概览)
- [2. 核心组件](#2-核心组件)
  - [2.1 LangGraph 状态图](#21-langgraph-状态图)
  - [2.2 AgentState 状态管理](#22-agentstate-状态管理)
  - [2.3 EventBus 事件系统](#23-eventbus-事件系统)
- [3. 数据流](#3-数据流)
- [4. 实现细节](#4-实现细节)
  - [4.1 chat_node 节点](#41-chat_node-节点)
  - [4.2 响应解析](#42-响应解析)
  - [4.3 历史管理](#43-历史管理)
- [5. 扩展指南](#5-扩展指南)
  - [5.1 添加新节点](#51-添加新节点)
  - [5.2 实现循环 (Loop)](#52-实现循环-loop)
  - [5.3 接入外部服务](#53-接入外部服务)
- [6. 最佳实践](#6-最佳实践)
- [7. 版本路线图](#7-版本路线图)

---

## 1. 架构概览

### 技术栈

| 组件 | 技术 | 版本 | 说明 |
|------|------|------|------|
| Agent 框架 | LangGraph | 1.2.7 | 状态图编排 |
| LLM | LangChain | 1.3.11 | 模型抽象层 |
| 后端 LLM | DeepSeek | - | 实际调用的模型 |
| 前端 UI | PyQt6 | 6.11.0 | 桌面宠物 |
| 异步桥接 | qasync | 0.28.0 | asyncio 与 Qt 集成 |
| 事件系统 | EventBus | 自研 | 异步通信 |

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        应用架构                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ UI 层 (PyQt6)                                                    │ │
│  │ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │ │
│  │ │ NuanbaoPet  │  │ InputPanel  │  │ SpeechBubble│               │ │
│  │ └─────────────┘  └─────────────┘  └─────────────┘               │ │
│  │         │              │                 │                        │ │
│  │         └──────────────┼─────────────────┘                        │ │
│  │                        ↓ EventBus                                  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                    │                                  │
│                                    ↓                                  │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ Agent 层 (LangGraph)                                             │ │
│  │ ┌─────────────────────────────────────────────────────────────┐ │ │
│  │ │                    ChatAgent                                 │ │ │
│  │ │                                                              │ │ │
│  │ │  State = {                                                   │ │ │
│  │ │    messages: [BaseMessage],  # 对话历史                       │ │ │
│  │ │    user_input: str,          # 当前输入                       │ │ │
│  │ │    response: dict,           # LLM 响应                       │ │ │
│  │ │  }                                                           │ │ │
│  │ │                                                              │ │ │
│  │ │  ┌────────────────────────────────────────────────────┐    │ │ │
│  │ │  │  [chat_node]  →  调用 LLM  →  解析响应  →  END      │    │ │ │
│  │ │  └────────────────────────────────────────────────────┘    │ │ │
│  │ └─────────────────────────────────────────────────────────────┘ │ │
│                                    │                                  │
│                                    ↓                                  │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ Services 层                                                      │ │
│  │ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │ │
│  │ │ LLM Service │  │ Tool Service│  │  ...        │               │ │
│  │ └─────────────┘  └─────────────┘  └─────────────┘               │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                    │                                  │
│                                    ↓                                  │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ Core 层                                                          │ │
│  │ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │ │
│  │ │ EventBus    │  │ Enums       │  │ Schemas     │               │ │
│  │ └─────────────┘  └─────────────┘  └─────────────┘               │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 文件结构

```
warming_baby/
├── main.py                          # 入口：创建循环、启动预热
├── settings.py                      # 全局设置（应用配置）
├── requirements.txt                 # 依赖清单
│
├── agent/                           # Agent 层
│   └── chat/
│       ├── chat_agent.py            # ChatAgent 主类（组装 graph + 事件监听）
│       ├── chat_schema.py           # 数据模型（ChatResponse, Emotion）
│       ├── graph.py                 # LangGraph 图构建（build_graph）
│       ├── state.py                 # AgentState 状态定义
│       ├── auto_speak.py            # 自动说话功能
│       └── nodes/                   # LangGraph 节点
│           ├── chat.py              # chat_node（LLM 对话 + structured output）
│           ├── intent.py            # 意图识别节点
│           ├── retriever.py         # 记忆检索节点
│           └── store.py             # 记忆存储节点
│
├── config/                          # 配置管理
│   ├── manager.py                   # 配置管理器
│   ├── secure.py                    # 加密存储（API Key 等敏感信息）
│   └── storage.py                   # 持久化存储
│
├── core/                            # 核心基础层
│   ├── event_bus.py                 # 事件总线（发布/订阅）
│   ├── animations.py                # 动画注册表（emotion → 动画）
│   ├── topmost.py                   # 跨平台窗口置顶（macOS AppKit + Windows Win32）
│   ├── enums.py                     # 枚举定义（EventCategory, AgentEvent 等）
│   ├── schemas.py                   # 核心 Schema 定义
│   ├── fonts.py                     # 字体配置
│   ├── logger.py                    # 日志系统（基于 loguru）
│   ├── long_memory_base.py          # 长期记忆基础（向量数据库）
│   └── tool_base.py                 # 工具基类
│
├── pet/                             # 桌面宠物 UI
│   ├── pet.py                       # NuanbaoPet 主窗口（无边框 + 置顶）
│   └── images/                      # 动画资源（gif、图标）
│
├── providers/                       # LLM 提供层
│   ├── llm.py                       # LLM 实例管理（get_llm）
│   └── llm_wrapper.py               # LLM 封装（重试、缓存）
│
├── tools/                           # Agent 工具
│   └── play_animation.py            # 播放动画工具
│
└── ui/                              # UI 组件层
    ├── widgets/
    │   ├── bubble.py                # 对话气泡（SpeechBubble）
    │   └── input_panel.py           # 输入面板
    └── dialogs/
        └── settings.py              # 设置对话框
```

---

## 2. 核心组件

### 2.1 LangGraph 状态图

#### 什么是 LangGraph？

LangGraph 是 LangChain 生态中的"工作流编排"框架，用于构建有状态的多步骤 Agent。核心概念：

- **State**: 全局状态对象，所有节点共享
- **Node**: 单个处理步骤
- **Edge**: 节点之间的连接
- **Conditional Edge**: 基于条件的动态路由

#### v0.1 实现

当前是最简单的单节点图：

```python
from langgraph.graph import StateGraph, END

# 定义状态类型
class AgentState(TypedDict):
    messages: list[BaseMessage]
    user_input: str
    response: dict
    error: str | None

# 构建图
graph = StateGraph(AgentState)
graph.add_node("chat", chat_node)
graph.set_entry_point("chat")
graph.add_edge("chat", END)

# 编译
compiled_graph = graph.compile()
```

#### 图结构可视化

```
v0.1 (当前):
┌──────────┐
│  START   │
└────┬─────┘
     ↓
┌──────────┐
│  chat    │  ← chat_node
└────┬─────┘
     ↓
┌──────────┐
│   END    │
└──────────┘
```

### 2.2 AgentState 状态管理

#### 状态定义

```python
from typing import TypedDict, Annotated
from operator import add
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    """
    Agent 状态 - 所有节点共享

    说明:
    - messages: 使用 Annotated[list, add] 实现累积更新
    - 其他字段直接覆盖
    """
    messages: Annotated[list[BaseMessage], add]  # 累积追加
    user_input: str                                # 直接覆盖
    response: dict | None                         # 直接覆盖
    error: str | None                             # 直接覆盖
```

#### 状态流转

```
1. 初始化 (UI 发送消息)
   state = {
     messages: [历史消息...],
     user_input: "你好",
     response: None,
     error: None,
   }

2. chat_node 处理后
   state = {
     messages: [..., HumanMessage("你好"), AIMessage("你好呀")],  # 累积
     user_input: "你好",                                            # 不变
     response: {"text": "你好呀", "emotion": "happy"},              # 新增
     error: None,                                                   # 不变
   }

3. END - 返回完整状态给调用者
```

### 2.3 EventBus 事件系统

#### 为什么需要 EventBus？

LangGraph 是**纯计算**的，不知道 UI 的存在。EventBus 连接 Agent 和 UI：

```
LangGraph Agent  ←→  EventBus  ←→  PyQt6 UI
     (无 UI 依赖)        (解耦)        (纯 UI)
```

#### 事件定义

```python
# core/event_bus.py

class AgentEvent(StrEnum):
    """Agent 相关事件"""
    USER_MESSAGE = "agent.user_message"      # UI → Agent
    THINKING = "agent.thinking"              # Agent 思考中
    RESPONSE = "agent.response"              # Agent → UI
    ERROR = "agent.error"                    # 错误
```

#### 事件流

```python
# 1. UI 发送消息
event_bus.publish(EventCategory.AGENT, AgentEvent.USER_MESSAGE, "你好")

# 2. ChatAgent 监听
class ChatAgent:
    def __init__(self):
        event_bus.subscribe(AgentEvent.USER_MESSAGE, self._on_user_message)

    def _on_user_message(self, message: str, **kwargs):
        # 启动 LangGraph
        loop.create_task(self.chat(message))

# 3. ChatAgent 返回结果
async def chat(self, message: str):
    result = await self.graph.ainvoke(state)
    event_bus.publish(AgentEvent.RESPONSE, result["response"])
```

---

## 3. 数据流

### 完整请求流程

```
用户操作: "点击发送按钮"
    │
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: UI 层                                                    │
├─────────────────────────────────────────────────────────────────┤
│ InputPanel.send_requested.emit("你好")                           │
│     ↓                                                            │
│ NuanbaoPet._on_user_input("你好")                                │
│     ↓                                                            │
│ show_typing()  → 显示思考动画                                     │
│     ↓                                                            │
│ event_bus.publish(AGENT, USER_MESSAGE, "你好")                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: EventBus 分发                                            │
├─────────────────────────────────────────────────────────────────┤
│ EventBus.notify("agent.user_message", "你好")                    │
│     ↓                                                            │
│ ChatAgent._on_user_message("你好")                               │
│     ↓                                                            │
│ event_bus.publish(AGENT, THINKING)  → 通知 UI 显示思考            │
│     ↓                                                            │
│ asyncio.create_task(agent.chat("你好"))                          │
└─────────────────────────────────────────────────────────────────┘
    │
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: LangGraph 处理                                           │
├─────────────────────────────────────────────────────────────────┤
│ ChatAgent.chat("你好")                                           │
│     ↓                                                            │
│ state = {messages: [...], user_input: "你好", ...}                │
│     ↓                                                            │
│ graph.ainvoke(state)                                             │
│     ↓                                                            │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ chat_node:                                                   │ │
│ │   1. 构建 messages = [System, History..., Human("你好")]     │ │
│ │   2. response = await llm.ainvoke(messages)                  │ │
│ │   3. parsed = _parse_llm_response(response.text)             │ │
│ │   4. return {messages: [...], response: parsed.dict()}      │ │
│ └─────────────────────────────────────────────────────────────┘ │
│     ↓                                                            │
│ result = {..., response: {"text": "你好呀", "emotion": "happy"}}│
└─────────────────────────────────────────────────────────────────┘
    │
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: 返回结果                                                  │
├─────────────────────────────────────────────────────────────────┤
│ ChatAgent.chat()                                                 │
│     ↓                                                            │
│ event_bus.publish(AGENT, RESPONSE, {"text": "你好呀", ...})      │
└─────────────────────────────────────────────────────────────────┘
    │
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: UI 更新                                                  │
├─────────────────────────────────────────────────────────────────┤
│ NuanbaoPet._on_agent_response({"text": "你好呀", ...})           │
│     ↓  (可能非 Qt 线程)                                           │
│ QTimer.singleShot(0, lambda: self._handle_agent_response(...))   │
│     ↓  (切到 Qt 主线程)                                           │
│ show_message("你好呀")  → 显示气泡                                │
│ trigger_animation("happy")  → 播放开心动画                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 实现细节

### 4.1 chat_node 节点

#### 完整实现

```python
async def chat_node(state: AgentState) -> dict:
    """
    Chat 节点 - 调用 LLM 生成响应

    职责:
    1. 从 state 中提取 messages 和 user_input
    2. 构建完整的 LLM 请求 (system + history + user)
    3. 调用 LLM
    4. 解析响应为 ChatResponse
    5. 返回更新后的 state

    Args:
        state: AgentState 字典

    Returns:
        dict: 需要更新的 state 字段
    """
    # 1. 提取输入
    user_input = state["user_input"]
    history = state.get("messages", [])

    # 2. 获取 LLM
    from providers import get_llm
    llm = get_llm()

    # 3. 构建消息
    messages = [
        SystemMessage(content=create_system_prompt()),
        *history,
        HumanMessage(content=user_input),
    ]

    # 4. 调用 LLM
    response = await llm.ainvoke(messages)
    response_text = response.content if hasattr(response, "content") else str(response)

    # 5. 解析响应
    chat_response = _parse_llm_response(response_text)

    # 6. 返回更新 (注意: messages 使用 add reducer 会自动累积)
    return {
        "messages": [
            HumanMessage(content=user_input),
            AIMessage(content=response_text),
        ],
        "response": chat_response.model_dump(),
        "error": None,
    }
```

#### 错误处理

```python
async def chat_node(state: AgentState) -> dict:
    try:
        # ... 正常流程
        return {...}

    except Exception as e:
        logger.error(f"chat_node error: {e}")

        # 返回错误状态
        error_response = ChatResponse(
            text=f"呜呜...出错了 ({str(e)[:30]})",
            emotion=Emotion.CONFUSED,
            play_once=True,
        )

        return {
            "messages": [HumanMessage(content=state["user_input"])],
            "response": error_response.model_dump(),
            "error": str(e),
        }
```

### 4.2 响应解析

#### 为什么需要解析？

LLM 返回的是自由文本，但我们需要结构化的 `ChatResponse`：

```python
class ChatResponse(BaseModel):
    text: str           # 显示给用户的文本
    emotion: Emotion    # 对应的情绪 (用于动画)
    play_once: bool     # 动画是否单次播放
```

#### 解析策略

```python
def _parse_llm_response(text: str) -> ChatResponse:
    """
    解析策略 (按优先级):

    1. 尝试提取 JSON 并解析
       - 如果 LLM 返回 JSON 格式
       - 使用 Pydantic 验证

    2. JSON 解析失败 → 返回原文
       - emotion 默认 NEUTRAL
       - text 限制 200 字符
    """
    import re
    import json

    try:
        # 移除 markdown 代码块标记
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text, flags=re.IGNORECASE)

        # 尝试解析 JSON
        data = json.loads(cleaned)

        # 兼容两种格式:
        # Format 1: {"response": {...}}
        # Format 2: {...} (直接是 ChatResponse)
        if "response" in data:
            return ChatResponse.model_validate(data["response"])
        else:
            return ChatResponse.model_validate(data)

    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"JSON parse failed: {e}")

        # Fallback: 原文返回
        return ChatResponse(
            text=text.strip()[:200],
            emotion=Emotion.NEUTRAL,
            play_once=True,
        )
```

### 4.3 历史管理

#### 在 ChatAgent 中管理

```python
class ChatAgent:
    def __init__(self):
        self._history: list[BaseMessage] = []

    async def chat(self, message: str, history: list[dict] | None = None):
        # 1. 构建初始 messages
        messages = self._history.copy()

        # 2. 合并外部传入的 history
        if history:
            for msg in history:
                # 转换为 LangChain 格式
                ...

        # 3. 执行 LangGraph
        result = await self.graph.ainvoke({"messages": messages, ...})

        # 4. 更新本地历史 (保留最近 10 条)
        self._history = result["messages"][-10:]
```

#### 历史数量限制

```
10 条消息 ≈ 5 轮对话 (用户 + AI)

为什么限制?
- 减少 Token 消耗
- 避免超出模型上下文窗口
- 保持对话聚焦

未来可以:
- 实现滑动窗口摘要
- 使用向量数据库检索相关历史
```

---

## 5. 扩展指南

### 5.1 添加新节点

#### 示例: 添加 Tool 节点

```python
# 1. 定义 Tool 节点
async def tool_node(state: AgentState) -> dict:
    """执行工具调用"""
    tool_calls = state.get("tool_calls", [])
    results = []

    for call in tool_calls:
        tool = tool_registry.get_tool(call["name"])
        if tool:
            result = await tool.execute(**call["args"])
            results.append(result)

    return {"tool_results": results}


# 2. 添加到图
def _build_graph(self):
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("chat", chat_node)
    workflow.add_node("tool", tool_node)  # 新增

    # 添加边
    workflow.set_entry_point("chat")
    workflow.add_conditional_edges("chat", should_call_tool)  # 条件路由
    workflow.add_edge("tool", "chat")  # 工具结果再送回 LLM

    return workflow.compile()


# 3. 定义条件路由函数
def should_call_tool(state: AgentState) -> str:
    """决定是否调用工具"""
    if state.get("tool_calls"):
        return "tool"  # 去工具节点
    return END  # 直接结束
```

### 5.2 实现循环 (Loop)

#### ReAct 模式

```
Reason + Act + Observe 循环:

┌──────────┐     ┌──────────┐     ┌──────────┐
│  think   │ ──→ │   act    │ ──→ │ observe  │
└────┬─────┘     └──────────┘     └────┬─────┘
     ↑                                  │
     └──────────────────────────────────┘
                    或
               (直接结束) → END
```

#### 代码实现

```python
async def think_node(state: AgentState) -> dict:
    """LLM 思考下一步"""
    response = await llm.ainvoke(...)

    # 判断: 是否需要工具?
    if response.tool_calls:
        return {"tool_calls": response.tool_calls}
    else:
        return {"final_response": response.text}


async def act_node(state: AgentState) -> dict:
    """执行工具"""
    results = []
    for call in state["tool_calls"]:
        result = await execute_tool(call)
        results.append(result)
    return {"observations": results}


def should_continue(state: AgentState) -> str:
    """决定继续循环还是结束"""
    if state.get("final_response"):
        return END
    return "think"  # 继续循环


# 构建循环图
graph = StateGraph(AgentState)
graph.add_node("think", think_node)
graph.add_node("act", act_node)
graph.add_node("observe", lambda s: s)  # 空节点, 结果会自动累积

graph.set_entry_point("think")
graph.add_edge("think", "act")
graph.add_edge("act", "think")  # 循环回到 think
graph.add_conditional_edges("think", should_continue)  # 或直接结束
```

### 5.3 接入外部服务

#### 示例: 接入 VectorDB

```python
# 新增节点: retrieve_node
async def retrieve_node(state: AgentState) -> dict:
    """从向量数据库检索相关上下文"""
    query = state["user_input"]

    # 1. 调用 Embedding
    embedding = await embed.ainvoke(query)

    # 2. 向量检索
    docs = vector_db.similarity_search(embedding, k=3)

    # 3. 添加到状态
    return {
        "context": [doc.page_content for doc in docs],
    }


# 修改 chat_node 使用 context
async def chat_node(state: AgentState) -> dict:
    context = state.get("context", [])

    messages = [
        SystemMessage(content=create_system_prompt()),
        HumanMessage(content=f"相关上下文:\n{context}\n\n用户问题: {state['user_input']}"),
    ]
    # ...


# 更新图
graph = StateGraph(AgentState)
graph.add_node("retrieve", retrieve_node)  # 新增
graph.add_node("chat", chat_node)

graph.set_entry_point("retrieve")
graph.add_edge("retrieve", "chat")
graph.add_edge("chat", END)
```

---

## 6. 最佳实践

### ✅ 应该做的

1. **节点原子化**: 每个节点做一件事，返回一个更新字典
2. **错误兜底**: 每个节点都要有 try-catch，返回 fallback 状态
3. **状态累积**: messages 使用 `Annotated[list, add]`，避免手动拼接
4. **事件解耦**: Agent 通过 EventBus 与 UI 通信，不要直接引用 UI
5. **类型安全**: 使用 Pydantic 定义所有状态和响应

### ❌ 不应该做的

1. **节点内操作 UI**: Agent 节点应该纯计算，通过事件通知 UI
2. **修改状态直接赋值**: 应该返回更新字典，让 LangGraph 合并
3. **在节点间传递大对象**: 只传必要的字段，大对象存数据库
4. **忽略错误状态**: 每个节点都要处理 error 字段
5. **循环依赖**: core 不应该 import agent

### 📐 节点设计模板

```python
async def my_node(state: AgentState) -> dict:
    """
    节点模板

    Args:
        state: 输入状态

    Returns:
        dict: 输出状态更新
    """
    # 1. 提取输入
    input_data = state.get("input_field")

    # 2. 核心逻辑
    try:
        result = do_something(input_data)

        # 3. 返回成功更新
        return {
            "output_field": result,
            "error": None,
        }

    except Exception as e:
        logger.error(f"my_node failed: {e}")

        # 4. 返回错误更新
        return {
            "output_field": None,
            "error": str(e),
        }
```

---

## 7. 版本路线图

### v0.1 (当前) - MVP

```
✅ 单节点 LangGraph
✅ EventBus 集成
✅ 基础对话功能
✅ emotion → animation 映射
```

### v0.2 - 工具系统

```
📋 添加 Tool 节点
📋 ReAct 循环 (think → act → observe)
📋 内置工具:
   - play_animation (已有)
   - system_command
   - file_read/write
```

### v0.3 - 记忆系统

```
📋 向量数据库 (ChromaDB)
📋 会话摘要
📋 长期记忆检索
```

### v0.4 - 多 Agent

```
📋 Supervisor Agent
📋 Worker Agent
   - 代码分析
   - 任务规划
   - 日程提醒
```

### v1.0 - 完整功能

```
📋 持久化存储 (SQLite/PostgreSQL)
📋 Web 控制台
📋 插件系统
📋 语音交互
```

---

## 附录

### A. 相关文档

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [LangChain 概念](https://python.langchain.com/docs/concepts/)
- [EventBus 使用指南](EventBus使用指南.md)

### B. 调试技巧

```python
# 1. 打印图结构
print(agent.graph.get_graph())

# 2. 可视化图 (需要额外依赖)
from langgraph.graph import StateGraph
import graphviz

graph = agent.graph.get_graph()
graph.draw_png("agent_graph.png")

# 3. 跟踪执行
result = await agent.graph.ainvoke(
    state,
    config={"callbacks": [LangSmithCallback()]},  # 用 LangSmith 跟踪
)
```

### C. 性能优化

| 场景 | 优化 |
|------|------|
| 减少 Token | 限制 history 数量，使用滑动窗口 |
| 并发请求 | 使用 `asyncio.gather` 并行调用多个节点 |
| 缓存 | Embedding 结果缓存到 Redis |
| 流式响应 | 使用 `astream_events` 逐 Token 返回 |

---

**文档版本**: v0.1  
**最后更新**: 2026-08-02
