# LangGraph 工具调用上下文机制

## 问题描述

**问题**：LangGraph 在调用工具时，是基于整个上下文（包括历史 AI 回复）还是仅基于当前消息来判断是否调用？如果是一个增加记忆的工具，这样会不会导致重复添加记忆，或者把 AI 编造的内容当成用户记忆存储？

---

## 一、LangGraph 官方机制

### 1.1 上下文传递方式

LangGraph 的核心是 **State**，每个节点从 State 读取数据，处理后返回更新。

```python
# State 定义
class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    # ...其他字段
```

**关键**：`messages` 使用 `add_messages` reducer，会累积所有消息。

### 1.2 LLM 看到的是什么？

当 LLM 被调用时，它看到的是完整的 `messages` 列表：

```python
messages = [
    SystemMessage(...),           # 系统提示
    HumanMessage("你好"),         # 用户消息 1
    AIMessage("你好呀！"),        # AI 回复 1
    HumanMessage("我叫小明"),     # 用户消息 2
    AIMessage("小明你好！"),      # AI 回复 2
    HumanMessage("你记得我叫什么吗？")  # 当前用户消息
]
```

**结论：LLM 基于完整的对话上下文（包括历史 AI 回复）来决定是否调用工具和构造参数。**

### 1.3 工具调用流程

```
START → agent_node → [有 tool_calls?] → tools_node → agent_node (循环)
                   → [无 tool_calls?] → format_node → END
```

在 `agent_node` 中：
```python
response = await llm.ainvoke(state["messages"])  # 传入完整上下文
```

LLM 返回：
```python
AIMessage(
    content="你叫小明呀！",
    tool_calls=[{
        "name": "add_memory",
        "args": {"content": "用户叫小明", "memory_type": "fact"}
    }]
)
```

---

## 二、潜在问题场景

### 2.1 问题一：重复添加记忆

**场景**：
```
用户: "我叫小明"
AI 回复: [add_memory("用户叫小明")] + "小明你好！"

# 下一轮对话
用户: "你记得我叫什么吗？"
# LLM 可能再次调用 add_memory("用户叫小明")
# 导致重复存储
```

### 2.2 问题二：AI 编造记忆

**场景**：
```
用户: "我爱吃苹果"
AI 回复: [add_memory("用户爱吃苹果")] + "好的，记住了！"

# 下一轮对话，假设 AI 自行回复了一些内容
用户: "我爱吃鱼"（假设用户没说过这句话）
AI 回复: [add_memory("用户爱吃鱼")]  # AI 基于自己之前的回复编造
```

**原因**：LLM 看到了完整上下文，包括 AI 自己之前的回复，可能会误判哪些内容是用户明确说的。

---

## 三、当前项目的解决方案

### 3.1 三重防线架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph State 层                            │
│  processed_memories: set  ← 记录已处理的记忆归一化 key          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: CustomToolNode 拦截                                   │
│  - 检查 processed_memories，已处理则跳过                        │
│  - 纯字符串处理，不查库                                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: FormatNode 来源过滤                                    │
│  - 只从 HumanMessage 提取新记忆                                  │
│  - 不从 AI 回复内容提取                                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: MemoryStore.smart_add 向量去重                        │
│  - 真正存储时进行向量相似度搜索                                  │
│  - 兜底防线，防止任何遗漏                                        │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 具体实现

#### Layer 1: State 层去重（纯内存）

**state.py**
```python
def _merge_set(existing: set, new: set) -> set:
    return existing | new

class ChatState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    processed_memories: Annotated[set, _merge_set]  # 新增字段
```

**nodes.py - CustomToolNode**
```python
async def __call__(self, inputs: dict) -> dict:
    processed_memories = inputs.get("processed_memories", set())
    
    for tool_call in message.tool_calls:
        if tool_name == "add_memory":
            # 计算归一化 key（纯字符串处理，不查库）
            key = self._compute_key(content, memory_type)
            
            # 检查是否已处理
            if key in processed_memories:
                continue  # 跳过重复添加
            
            # 执行工具
            tool_result = await tool.ainvoke(tool_args)
            
            # 更新 processed_memories
            new_processed.add(key)
```

#### Layer 2: 来源过滤（FormatNode）

```python
def format_node(state: ChatState):
    # 只提取用户消息中的新记忆
    user_content = last_human_message.content  # HumanMessage
    ai_content = last_ai_message.content        # AIMessage（仅用于情绪判断）
    
    # 记忆提取基于用户消息
    # 防止 AI 编造内容被当成用户信息存储
    metadata = llm.extract(user_content)  # ← 只传用户消息
```

#### Layer 3: 向量去重（兜底）

```python
# store.py smart_add
def smart_add(self, items, similarity_threshold=0.8):
    # 向量搜索相似记忆
    similar = self.search(query, min_score=similarity_threshold)
    
    if similar:
        # 替换旧记忆
        self.delete(similar[0]["id"])
```

---

## 四、归一化 key 计算

### 4.1 为什么不查库？

`_compute_key` 是纯字符串处理函数，用于快速拦截：

```python
def _compute_key(content: str, memory_type: str) -> str:
    # 1. 类型修正（规则匹配）
    corrected = normalizer.correct_type(content, mtype)
    
    # 2. 内容归一化（字符串处理）
    return normalizer.normalize(content, corrected)
    # "我叫小明" → "用户叫小明"
    # "我喜欢苹果" → "用户喜欢苹果"
```

### 4.2 性能考虑

| 层级 | 操作 | 是否查库 | 性能 |
|------|------|----------|------|
| Layer 1 | 字符串归一化 | ❌ | O(1) |
| Layer 2 | 消息过滤 | ❌ | O(1) |
| Layer 3 | 向量搜索 | ✅ | O(n) |

**设计原则**：先用快速方法拦截，尽量不触发数据库查询。

---

## 五、最佳实践

### 5.1 Prompt 约束

在工具描述中明确规则：

```python
class AddMemoryTool(AgentTool):
    description = (
        "添加用户的稳定个人信息到长期记忆中。\n"
        "【必须记忆 DO】\n"
        "- 用户的姓名、住址、喜好、技能\n"
        "【绝对不要记忆 DON'T】\n"
        "- AI 回复中提到的内容\n"  # 明确禁止
        "- 推测内容\n"
        "- 临时信息"
    )
```

### 5.2 消息来源检查

在工具执行层验证：

```python
async def _execute(self, content: str, ...):
    # 检查内容是否可能来自 AI
    # 简单启发式：检查是否包含 AI 常用表述
    ai_patterns = ["好的，我记住了", "我记得你说过", "让我想想"]
    for pattern in ai_patterns:
        if pattern in content:
            return "拒绝：内容可能来自 AI 回复"
```

### 5.3 单元测试场景

```python
def test_ai_message_filtering():
    """测试 AI 消息过滤"""
    # 场景 1: 正常添加
    result = add_memory("我叫小明")
    assert result == "已添加"
    
    # 场景 2: AI 编造内容被拒
    result = add_memory("用户爱吃鱼")  # 假设用户没说过
    assert "拒绝" in result
    
    # 场景 3: 重复添加被拦截
    result = add_memory("我叫小明")  # 第二次
    assert "已存在" in result
```

---

## 六、总结

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 重复添加记忆 | LLM 看到完整上下文，可能重复调用 | State 层 `processed_memories` 去重 |
| AI 编造记忆 | LLM 把 AI 回复内容当成用户信息 | FormatNode 只从 HumanMessage 提取 |
| 跨类型重复 | 同内容不同类型（FACT vs PREFERENCE） | normalizer.correct_type 强制统一类型 |

**核心思路**：在 LLM 层面（State）进行快速拦截，在存储层面（Store）进行最终兜底，确保记忆质量。

---

## 相关代码

- [state.py](../agent/chat/state.py) - ChatState 定义
- [nodes.py](../agent/chat/nodes.py) - CustomToolNode 和 FormatNode
- [normalizer.py](../memory/normalizer.py) - 记忆归一化
- [tool_memory.py](../tools/tool_memory.py) - 记忆工具实现
- [store.py](../memory/store.py) - 向量存储和去重