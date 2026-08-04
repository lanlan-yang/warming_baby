# Agent 技术文档

## 目录

- [1. 架构概览](#1-架构概览)
- [2. 核心设计思想](#2-核心设计思想)
- [3. 核心组件](#3-核心组件)
  - [3.1 TurnEngine - LLM+Tool 循环引擎](#31-turnengine---llmtool-循环引擎)
  - [3.2 ChatAgent - 对话代理](#32-chatagent---对话代理)
  - [3.3 MessageBuilder - 消息构建器](#33-messagebuilder---消息构建器)
  - [3.4 ChatSchema - 数据模型](#34-chatschema---数据模型)
- [4. 工具系统](#4-工具系统)
- [5. 记忆系统](#5-记忆系统)
- [6. 自动说话](#6-自动说话)
- [7. 事件系统](#7-事件系统)
- [8. 数据流](#8-数据流)
- [9. 文件结构](#9-文件结构)
- [10. 与旧架构的对比](#10-与旧架构的对比)

---

## 1. 架构概览

### 技术栈

| 组件       | 技术             | 说明                              |
| ---------- | ---------------- | --------------------------------- |
| Agent 范式 | Loop Engineering | 自研，while 循环实现 LLM 自主决策 |
| LLM        | LangChain        | 模型抽象层                        |
| 后端 LLM   | DeepSeek         | 实际调用的模型                    |
| 前端 UI    | PyQt6            | 桌面宠物                          |
| 向量数据库 | ChromaDB         | 记忆存储和检索                    |
| Embedding  | BGE-M3           | 中文语义向量                      |
| 日志       | loguru           | 日志系统                          |

### 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                          UI 层 (PyQt6)                                │
│  ┌─────────────┐    EventBus    ┌─────────────┐    EventBus          │
│  │  Pet        │◄──────────────►│ ChatWindow  │◄───────────────┐    │
│  └──────┬──────┘                 └─────────────┘                │    │
│         │ EventBus                                              │    │
└─────────┼──────────────────────────────────────────────────────┼────┘
          │ USER_MESSAGE                                         │
          ▼                                                       │
┌────────────────────────────────────────────────────────────────┼────┐
│                        Agent 层                                  │    │
│                                                                   │    │
│  ┌──────────────────────────────────────────────────────────────┐ │    │
│  │ ChatAgent                                                     │ │    │
│  │                                                                │ │    │
│  │  chat(message, history)                                       │ │    │
│  │    ├─ MessageBuilder.build_messages()  ← 构建 LLM 输入        │ │    │
│  │    │   ├─ System Prompt (角色+时间+位置+记忆)                 │ │    │
│  │    │   ├─ History (对话历史)                                   │ │    │
│  │    │   └─ User Input (当前输入)                                │ │    │
│  │    │                                                           │ │    │
│  │    ├─ TurnEngine.run(messages)          ← LLM+Tool 循环       │ │    │
│  │    │   ├─ for turn in range(max_turns):                       │ │    │
│  │    │   │   ├─ LLM.ainvoke(messages + tools)                   │ │    │
│  │    │   │   ├─ if tool_calls → 执行工具 → 继续                 │ │    │
│  │    │   │   └─ else → 结束循环                                 │ │    │
│  │    │   └─ _generate_structured_response() ← 结构化输出        │ │    │
│  │    │       └─ ChatResponse (text, emotion, new_memories)     │ │    │
│  │    │                                                           │ │    │
│  │    ├─ MemoryManager.smart_add_memory()  ← 存储新记忆          │ │    │
│  │    └─ EventBus.publish(RESPONSE)       ← 通知 UI              │ │    │
│  └──────────────────────────────────────────────────────────────┘ │    │
│                                                                   │    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │    │
│  │ AutoSpeakManager │  │ LocationService │  │  ToolRegistry    │  │    │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘  │    │
└──────────────────────────────────────────────────────────────────┼────┘
                                                                   │
┌──────────────────────────────────────────────────────────────────┼────┐
│                        Services 层                                │    │
│                                                                   │    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │    │
│  │ MemoryManager   │  │   Tools          │  │  LLM             │  │    │
│  │ ├─ store.py     │  │ ├─ query_memory   │  │  └─ LLMWrapper   │  │    │
│  │ ├─ types.py     │  │ ├─ add_memory     │  │                  │  │    │
│  │ └─ manager.py   │  │ ├─ update_memory  │  │                  │  │    │
│  │                 │  │ ├─ get_weather     │  │                  │  │    │
│  │                 │  │ └─ get_location   │  │                  │  │    │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘  │    │
└──────────────────────────────────────────────────────────────────┼────┘
                                                                   │
┌──────────────────────────────────────────────────────────────────┼────┐
│                        Core 层                                    │    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │    │
│  │ EventBus        │  │   Enums          │  │  Logger          │  │    │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘  │    │
└──────────────────────────────────────────────────────────────────┼────┘
          │                                                        │
          └────────────────────── REPROONSE ──────────────────────┘
```

---

## 2. 核心设计思想

### Loop Engineering 架构

不再依赖 LangGraph 的状态图编排，采用更轻量的 Loop Engineering 模式：

```
旧架构 (LangGraph):
  UI → EventBus → ChatAgent → LangGraph → [nodes] → EventBus → UI
                                  ↑
                          复杂的状态图 + 条件路由

新架构 (Loop Engineering):
  UI → EventBus → ChatAgent → TurnEngine (while 循环) → EventBus → UI
                                  ↑
                          LLM 自主决定是否调工具
```

### LLM 是指挥官

工具系统采用 `tool_choice=auto`，LLM 完全自主决定：

- **是否需要调工具**：不需要就直接回复，需要就调
- **调哪些工具**：可以同时调多个
- **调几次**：最多 `max_turns` 次，然后强制输出结果

### 双通道记忆

```
被动注入 (System Prompt):
  每次对话预检索 1 条最相关的记忆 → LLM 直接看到
  好处：零延迟，适合明显关联场景

主动查询 (工具调用):
  LLM 通过 query_memory 主动查更多
  好处：更精准，适合需要多条信息的场景

自动存储 (new_memories):
  LLM 在回复的 new_memories 字段返回新信息 → 自动存储
  好处：无需额外工具调用
```

### 单次完成 vs 多轮

System Prompt 中明确指示：

```
高效回应（重要）:
- 一次性完成所有操作，不要分多轮
- 可以同时调用多个工具
```

原因：减少 LLM 调用次数（每次 1.5-2 秒），降低延迟。

---

## 3. 核心组件

### 3.1 TurnEngine - LLM+Tool 循环引擎

**核心逻辑**（`engine.py`）：

```python
class TurnEngine:
    def __init__(self, llm, tools, max_turns=5):
        self._llm_with_tools = llm.bind_tools(tools)  # 绑定工具描述
        self._structured_llm = llm.with_structured_output(ChatResponse)

    async def run(self, messages) -> ChatResponse:
        for turn in range(self.max_turns):
            response = await self._llm_with_tools.ainvoke(messages)

            if response.tool_calls:
                # LLM 要调工具 → 执行 → 结果塞回消息 → 继续循环
                tool_results = await self._execute_tool_calls(response.tool_calls)
                messages.extend(tool_results)
            else:
                # LLM 直接输出 → 循环结束
                break

        # 最后一步：结构化输出
        return await self._generate_structured_response(messages)
```

**关键设计**：

- `tool_choice=auto`：LLM 自主决定
- `max_turns=5`：防止无限循环
- 结构化输出用 `_generate_structured_response()`：让 LLM 输出 JSON，包含 `text`, `emotion`, `new_memories`

### 3.2 ChatAgent - 对话代理

**职责**（`chat_agent.py`）：

```python
class ChatAgent:
    async def chat(self, message, history=None) -> ChatResponse:
        # 1. 确保 LLM 已初始化
        llm = self._ensure_llm()

        # 2. 构建消息（System Prompt + 历史 + 用户输入）
        messages = await MessageBuilder().build_messages(
            user_input=message,
            history=self._prepare_history(history),
            location=self._location_text,
        )

        # 3. TurnEngine 执行（LLM 自主决策）
        chat_response = await TurnEngine(llm, tools).run(messages)

        # 4. 更新历史 + 存储新记忆
        self._update_history(message, chat_response.text)
        if chat_response.new_memories:
            await self._save_memories(chat_response.new_memories)

        # 5. 通知 UI
        event_bus.publish(AGENT, RESPONSE, chat_response.model_dump())
```

**事件订阅**：

- `USER_MESSAGE`：用户发送消息
- `AUTO_SPEAK`：宠物自言自语（不走记忆系统）

### 3.3 MessageBuilder - 消息构建器

**System Prompt 结构**（`message_builder.py`）：

```
[角色设定 - 固定不变]
  你是"暖宝"，用户的专属桌宠伙伴...
  性格：活泼可爱...
  高效回应：一次性完成所有操作...

[当前时间 - 每次刷新]
  2026年08月04日 16:05 周一 下午

[用户位置 - 动态获取]
  用户位置：中国 四川 成都
  所在城市：成都

[相关记忆 - 被动注入]
  你对用户的记忆：
  - [preference] (置信度 85%) 用户爱吃香蕉
```

**记忆预检索**：

- 用用户输入作为 query
- 检索 1 条最相关的记忆
- 找到就注入，找不到就跳过

### 3.4 ChatSchema - 数据模型

**ChatResponse**（`chat_schema.py`）：

```python
class ChatResponse(BaseSchema):
    text: str              # 回复内容（给用户看的）
    emotion: Emotion       # 情绪（用于选择动画）
    play_once: bool        # 动画是否单次播放
    new_memories: list[MemoryExtract]  # 自动提取的新记忆
```

**Emotion 枚举**：
| 值 | 含义 | 触发场景示例 |
|----|------|-------------|
| happy | 开心 | 用户打招呼、夸奖 |
| angry | 生气 | 用户批评 |
| sad | 难过 | 用户告别、心情不好 |
| confused | 困惑 | 听不懂用户的话 |
| sleep | 困 | 用户说累、时间很晚 |
| play | 想玩 | 用户说玩游戏 |
| eating | 想吃 | 用户说喂吃的 |
| neutral | 普通 | 日常对话 |

---

## 4. 工具系统

### 工具架构

```python
class BaseTool:
    name: str              # 工具名称
    description: str       # LLM 看到的描述
    args_schema: type      # 参数 Schema

    async def _execute(self, **kwargs) -> str:  # 实际执行
        ...
```

### 当前工具列表

| 工具          | 描述         | 典型场景               |
| ------------- | ------------ | ---------------------- |
| query_memory  | 查询用户记忆 | 用户问"我之前说过什么" |
| add_memory    | 添加新记忆   | 用户说"我叫小明"       |
| update_memory | 修改旧记忆   | 用户说"其实我不喜欢"   |
| get_weather   | 查询天气     | 用户问"今天冷不冷"     |
| get_location  | 获取位置     | 需要位置信息时         |

### 工具注册

```python
# app.py 启动时
from tools import register_all_tools
register_all_tools()

# 内部通过 ToolRegistry 单例管理
ToolRegistry.register(QueryMemoryTool())
ToolRegistry.register(GetWeatherTool())
```

### 注意事项

- **工具描述很重要**：LLM 根据 `description` 判断何时调用
- **不需要 `play_animation` 工具**：动画通过 `emotion` 字段触发，不占用一次 LLM 调用
- **返回值是字符串**：方便 LLM 解析结果

---

## 5. 记忆系统

### 三层架构

```
MemoryManager (单例)
    └─ MemoryStore
        ├─ ChromaDB (向量存储)
        └─ BGE-M3 (Embedding 模型)
```

### 记忆类型

| 类型       | 含义   | 示例          |
| ---------- | ------ | ------------- |
| fact       | 事实   | 用户叫小明    |
| preference | 喜好   | 用户爱吃香蕉  |
| event      | 事件   | 用户今天加班  |
| context    | 上下文 | 正在聊游戏    |
| skill      | 技能   | 用户会 Python |

### 被动注入流程

```
用户输入 → MessageBuilder
             ↓
         memory_manager.get_relevant_memories(query=user_input, max_items=1)
             ↓
         用向量相似度检索
             ↓
         找到 → 注入 System Prompt
         没找到 → 跳过
```

### 自动存储流程

```
TurnEngine → _generate_structured_response()
             ↓
         LLM 输出 JSON: { new_memories: [{content: "...", memory_type: "..."}] }
             ↓
         ChatAgent._save_memories(new_memories)
             ↓
         memory_manager.smart_add_memory(content, type)
             ↓
         smart_add: 自动检测相似旧记忆 → 是则替换，否则新增
```

### 主动查询流程

```
LLM 判断需要更多信息
    ↓
调用 query_memory 工具
    ↓
TurnEngine 执行工具
    ↓
结果塞回 messages
    ↓
LLM 根据结果生成最终回复
```

### smart_add 机制

```python
def smart_add_memory(self, content, memory_type, similarity_threshold=0.5):
    # 1. 查找相似旧记忆
    similar = self.find_similar(content, memory_type, min_score=0.5)

    # 2. 找到 → 替换
    if similar:
        self.delete_by_ids(similar.ids)

    # 3. 添加新记忆
    return self.add_memory(content, memory_type)
```

用途：用户说"我喜欢苹果"后来又说"我不喜欢苹果"，自动替换而不是产生两条矛盾的记忆。

---

## 6. 自动说话

### 架构

```python
AutoSpeakManager              # 触发控制
    ├─ should_speak()         # 判断是否该说话
    ├─ get_speak_params()     # 获取场景 + prompt
    └─ speak_done()          # 标记完成

SceneDetector                 # 场景检测
    └─ detect_scene()         # 根据时间+鼠标活跃度判断

AutoSpeakPrompt               # Prompt 生成
    └─ get_prompt(scene)      # 根据场景生成不同 prompt
```

### 说话时机

| 场景     | 触发条件                |
| -------- | ----------------------- |
| 自言自语 | 空闲 5-15 分钟          |
| 喝水提醒 | 整点 (9:00-21:00)       |
| 起身提醒 | 45 分钟没动鼠标         |
| 早睡提醒 | 23:00-02:00             |
| 早晚问候 | 7:00-9:00 / 21:00-23:00 |

### 执行流程

```
Timer 触发 → AutoSpeakManager.should_speak()
               ↓
           通过检查 → get_speak_params() → prompt
               ↓
           EventBus.publish(AUTO_SPEAK, prompt)
               ↓
           ChatAgent._on_auto_speak(prompt)
               ↓
           单次 LLM 调用（不走记忆系统）
               ↓
           EventBus.publish(RESPONSE, ...)
               ↓
           Pet 显示气泡 + 播放动画
               ↓
           speak_done() → 记录时间
```

### 与普通对话的区别

| 对比项 | 普通对话      | 自动说话 |
| ------ | ------------- | -------- |
| 历史   | 加入对话历史  | 不加入   |
| 记忆   | 预检索 + 存储 | 不涉及   |
| 工具   | 可以调用      | 不调用   |
| 频率   | 用户控制      | 系统控制 |

---

## 7. 事件系统

### EventBus 设计

```python
# 发布
event_bus.publish(EventCategory.AGENT, AgentEvent.RESPONSE, data)

# 订阅
event_bus.subscribe(EventCategory.AGENT, AgentEvent.RESPONSE, handler)
```

### 事件分类

```
EventCategory:
  AGENT    → Agent 相关（对话、自动说话）
  UI       → UI 相关（动画、窗口）
  SYSTEM   → 系统相关（错误、配置）
```

### Agent 事件

| 事件         | 方向         | 载荷 | 含义         |
| ------------ | ------------ | ---- | ------------ |
| USER_MESSAGE | UI → Agent   | str  | 用户发送消息 |
| AUTO_SPEAK   | 内部 → Agent | str  | 宠物自言自语 |
| THINKING     | Agent → UI   | -    | 正在思考     |
| RESPONSE     | Agent → UI   | dict | 对话结果     |

### 事件流示例

```
用户点击发送
  │
  ▼
Pet → EventBus.publish(AGENT, USER_MESSAGE, "好饿啊")
  │
  ▼
ChatAgent._on_user_message("好饿啊")
  │
  ├─ EventBus.publish(AGENT, THINKING)  → UI 显示思考动画
  │
  ├─ ChatAgent.chat("好饿啊")
  │    └─ TurnEngine.run() → ChatResponse
  │
  └─ EventBus.publish(AGENT, RESPONSE, response)
       │
       ▼
Pet._on_chat_response(response)
  ├─ show_message(text)     → 显示气泡
  └─ trigger_animation(emotion)  → 播放动画
```

---

## 8. 数据流

### 完整对话流程

```
用户输入 "好饿啊"
    │
    ▼
┌─ UI 层 ──────────────────────────────────────────────────────────┐
│  InputPanel 获取输入 → show_typing() → EventBus.publish()       │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ ChatAgent ──────────────────────────────────────────────────────┐
│                                                                   │
│  1. _on_user_message("好饿啊")                                   │
│     └─ EventBus.publish(THINKING) → UI 显示思考                  │
│                                                                   │
│  2. chat("好饿啊")                                                │
│     │                                                             │
│     ├─ MessageBuilder.build_messages()                           │
│     │   ├─ _get_role_prompt()      → 角色设定                     │
│     │   ├─ _get_time_context()     → 当前时间                     │
│     │   ├─ 位置文本                    → 四川 成都                 │
│     │   └─ memory_manager.get_relevant_memories()                 │
│     │       → "用户爱吃香蕉" → 注入 System Prompt                 │
│     │                                                             │
│     ├─ TurnEngine.run(messages)                                  │
│     │   │                                                         │
│     │   ├─ [第 1 次 LLM 调用]                                     │
│     │   │   LLM 决定：不需要调工具                                 │
│     │   │   → 直接输出                                            │
│     │   │                                                         │
│     │   └─ _generate_structured_response()                       │
│     │       LLM 输出 JSON:                                        │
│     │       {                                                     │
│     │         text: "饿了呀？吃点香蕉吧~🍌",                      │
│     │         emotion: "happy",                                  │
│     │         new_memories: []                                    │
│     │       }                                                     │
│     │                                                             │
│     ├─ _update_history()  → 更新对话历史                          │
│     │                                                             │
│     └─ EventBus.publish(RESPONSE, response)                       │
│         └─ new_memories 为空 → 跳过存储                           │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ UI 层 ──────────────────────────────────────────────────────────┐
│  Pet._on_chat_response(response)                                │
│  ├─ show_message("饿了呀？吃点香蕉吧~") → 显示气泡               │
│  └─ trigger_animation("happy")        → 播放开心动画             │
└──────────────────────────────────────────────────────────────────┘
```

### 记忆被动注入流程

```
用户输入 "我喜欢猫"
    │
    ▼
MessageBuilder.build_messages()
    │
    ▼
memory_manager.get_relevant_memories(query="我喜欢猫", max_items=1)
    │
    ▼
ChromaDB 向量检索 → 找到 "用户喜欢猫" 已有记忆?
    │
    ├─ 找到（score > 0.3）→ 注入 System Prompt
    │   【你对用户的记忆】
    │   - [preference] (置信度 85%) 用户喜欢猫
    │
    └─ 没找到 → 不注入
    │
    ▼
LLM 看到 System Prompt 中的记忆
    │
    ├─ 如果记忆已存在 → 说 "喵~ 我知道你喜欢猫呀"
    └─ 如果没记忆 → 可能通过 new_memories 保存
```

### 工具调用流程

```
用户输入 "今天成都天气怎么样"
    │
    ▼
TurnEngine.run(messages + [get_weather, ...])
    │
    ▼
[第 1 次 LLM 调用]
  LLM 判断：需要调 get_weather
  → response.tool_calls = [{name: "get_weather", args: {city: "成都"}}]
    │
    ▼
[执行工具]
  weather_tool._execute(city="成都")
  → "成都今天晴，25°C..."
  │
  ▼
  结果塞回 messages → 继续循环
    │
    ▼
[第 2 次 LLM 调用]
  LLM 看到天气结果 → 直接生成最终回复
  → response.tool_calls = None
  → 循环结束
    │
    ▼
_generate_structured_response()
  → { text: "成都今天晴，25度，适合出门~", emotion: "happy" }
```

---

## 9. 文件结构

```
warming_baby/
├── main.py                              # 入口
├── requirements.txt                     # 依赖
│
├── agent/                               # Agent 层
│   ├── __init__.py
│   └── chat/
│       ├── __init__.py
│       ├── chat_agent.py                # ChatAgent 主类
│       ├── chat_schema.py               # 数据模型 (ChatResponse, Emotion, MemoryExtract)
│       ├── engine.py                    # TurnEngine (LLM+Tool 循环)
│       ├── message_builder.py           # 消息构建器
│       └── auto_speak.py                # 自动说话 (Manager + Detector + Prompt)
│
├── tools/                               # 工具层
│   ├── __init__.py
│   ├── tool_base.py                     # BaseTool + ToolRegistry
│   ├── tool_memory.py                   # query_memory / add_memory / update_memory
│   ├── tool_weather.py                  # get_weather
│   └── tool_location.py                 # LocationService
│
├── memory/                              # 记忆层
│   ├── __init__.py
│   ├── manager.py                       # MemoryManager (单例，主入口)
│   ├── store.py                         # MemoryStore (ChromaDB 封装)
│   └── types.py                         # MemoryType, MemoryItem
│
├── providers/                           # LLM 提供层
│   ├── __init__.py
│   ├── llm.py                           # get_llm()
│   └── llm_wrapper.py                   # 调用封装
│
├── core/                                # 核心层
│   ├── __init__.py
│   ├── event_bus.py                     # EventBus
│   ├── enums.py                         # 全局枚举
│   ├── schemas.py                       # 全局 Schema 基类
│   ├── logger.py                        # 日志
│   ├── fonts.py                         # 字体
│   ├── animations.py                    # 动画注册表
│   └── topmost.py                       # 窗口置顶
│
├── pet/                                 # UI 层
│   └── pet.py                           # 桌面宠物主类
│
└── docs/
    └── Agent技术文档.md                  # 本文档
```

---

## 10. 与旧架构的对比

### LangGraph vs Loop Engineering

| 对比项   | LangGraph (旧)               | Loop Engineering (新) |
| -------- | ---------------------------- | --------------------- |
| 编排方式 | 状态图 + 条件路由            | while 循环            |
| 状态传递 | State TypedDict + AddReducer | 函数参数 + 返回值     |
| 节点定义 | 独立文件 (nodes/\*.py)       | 内部方法              |
| 工具调用 | 独立 tool 节点               | LLM 自主调用          |
| 复杂度   | 中等                         | 低                    |
| 调试难度 | 高（状态流转隐式）           | 低（普通函数调用栈）  |

### 架构演进

```
v0.3 (早期):
  ChatAgent → LangGraph → [nodes] → 响应

v0.4 (当前):
  ChatAgent → TurnEngine (Loop Engineering) → ChatResponse

  变化：
  ✅ 移除 LangGraph 依赖
  ✅ 移除 nodes/ 目录
  ✅ 采用 Loop Engineering 实现 LLM+Tool 循环
  ✅ 新增 MessageBuilder 分离消息构建
  ✅ 结构化输出替代自由文本解析
  ✅ 记忆系统重写（被动注入 + 自动存储 + 主动查询）
  ✅ smart_add 自动去重
```

### 为什么迁移

1. **更简单**：while 循环比状态图更直观，调试栈清晰
2. **更灵活**：工具调用完全由 LLM 自主，不需要预定义路由
3. **更高性能**：减少中间状态序列化/反序列化开销
4. **更好维护**：单文件职责明确，减少跨文件跳转

---

**文档版本**: v0.4
**最后更新**: 2026-08-04
