# 🐣 暖宝 Nuanbao

**你的专属机甲小仓鼠桌宠**

---

暖宝是一只住在你电脑里的小机甲仓鼠，软乎乎的金属外壳下藏着个治愈系的小灵魂，是专属于程序员的桌面搭档。

它不是什么无所不能的超级 AI，只是个会摸鱼、会犯困、会陪你熬夜改 bug 的小室友：

## 🎨 外观特征

> 哔哩哔哩地址：https://www.bilibili.com/video/BV11yuq6gE5X/

- **圆滚滚的白色机甲外壳**，粉粉嫩嫩的超级可爱
- **粉色显示屏眼睛**会变化各种表情（开心、疑惑、困了...）
- **头顶两根小天线**，思考的时候会转呀转
- **胸口的电量条**，摸鱼时暗暗的，帮你干活时亮满格

![暖宝外观](assets/icons/icon_451.png)

## 🐾 日常行为

- 平时安安静待在屏幕角落，自己会晃悠、会打盹、会偷偷看你写代码
- 你拖它、扔它、戳它，它都会有小情绪 😤
- 你写代码到凌晨它会陪你，自动说暖心话提醒休息
- 长时间不理它会自己缩在角落睡觉，鼻子冒小电泡 💤

## 🧠 AI 功能

### 智能对话

- 可以和暖宝自然聊天，它会根据你的情绪回应
- 支持多种情绪表达：开心、困惑、撒娇、傲娇

### 智能记忆

- ✨ **LLM 语义记忆架构**：云端 Embedding + LLM 语义提取，告别本地模型依赖
  - **云端 Embedding**：通过 API 调用云端向量模型，无需下载本地模型文件
  - **LLM 提取记忆**：`memory_extract` 节点读取完整对话历史，LLM 理解语义后提取结构化记忆（类型 + 字段 + 内容）
  - **多主体区分**：自动识别用户/家人/朋友等不同主体的信息，分别存储
  - **时间变化理解**：能理解"以前住在成都，现在搬去上海了"，只保留最新状态
  - **智能去重**：LLM 提取的 field + 归一化双重去重，不会重复记录相同信息
  - **并行执行**：记忆提取与情绪判断并行处理，回复更快
- 你可以说：
  - "我叫小明" → LLM 提取 field=name，立即存储
  - "我以前住在成都，现在搬去上海了" → LLM 理解时间变化，只存上海
  - "我妈妈住在北京" → 自动区分主体，field=mother_location
  - "我不喜欢桃子，我喜欢梨" → 替换旧偏好，存新偏好

### 实用工具

- 🌤️ **天气查询**：问天气、温度、穿衣建议
- 📍 **自动定位**：自动获取你的位置
- 📝 **记忆管理**：记住重要的事情
- 🔥 **热榜看板**：查询各大平台实时热榜，独立弹窗展示
  - 支持主流平台：B站、微博、知乎、抖音、小红书、快手、百度、今日头条、新浪、贴吧、澎湃新闻、腾讯新闻、IT之家、CSDN、掘金、V2EX、HelloGitHub 等
  - 多平台热榜在同一窗口通过 Tab 页合并展示
  - 点击热榜条目直接打开原链接
  - 无边框圆角弹窗，支持拖拽移动、ESC 关闭
- 🔌 **MCP 外部工具**：通过 Model Context Protocol 动态接入第三方工具
  - 启动时自动发现 MCP Server 暴露的工具，无缝融入工具链
  - 支持 stdio 模式（npx 子进程）和远程 Server
  - 已接入：Bing 搜索（web_search、image_search）

<img src="assets/hot_board.png" width="400" alt="热榜看板" />

### 🐹 宠物状态系统

暖宝有四项核心状态，会随时间自然衰减，影响它的情绪和说话内容：

| 状态   | 范围  | 满状态衰减速率 | 触发阈值         |
| ------ | ----- | -------------- | ---------------- |
| 饱食度 | 0-100 | 5 分钟 -1      | < 30 触发饥饿    |
| 心情   | 0-100 | 10 分钟 -1     | < 30 触发难过    |
| 体力   | 0-100 | 8 分钟 -1      | < 20 触发困倦    |
| 亲密度 | 0-100 | 不衰减         | 累积值，影响语气 |

**曲线衰减策略**：实际衰减率随当前值变化，公式 `factor = 0.3 + 0.7 × (value/100)²`

- 高值（80-100）：全速衰减，代谢旺盛（吃饱了消化快）
- 中值（30-80）：减速衰减，平稳过渡
- 低值（0-30）：慢速衰减，省电保命（饿了维持更久等用户救援）

这样用户操作后效果保持更久，低值时不会迅速归零。

**互动方式**：右键暖宝可见动作栏，提供四个动作：

- 🍚 **投喂**：饱食度 +20，心情 +5（吃太饱 ≥95 时心情 -1）
- 🎾 **玩耍**：心情 +15，体力 -10
- ✋ **抚摸**：心情 +10，亲密度 +3（边际递减 + 每日上限 15）
- 💤 **睡觉**：体力 +50

**冷却机制**：状态值 ≥ 80 时启用冷却（避免频繁操作），低于 80 时不限制，方便快速恢复。

**状态感知**：LLM 会根据当前状态生成对应回复——饿了被喂会说还想吃，吃饱了被喂会说吃不下。动作触发时携带操作前的状态快照，确保 LLM 回复基于"动作发生时"的状态而非动作后的值。

### 自动陪伴

- 定时自动说话，提醒你休息
- 长时间不理它会主动找你聊天
- 根据当前时间说合适的话（早上问候、晚上提醒休息等）
- 状态过低时自动触发对应情绪动画和说话内容

## 🛡️ 隐私与安全

- 不会弹广告，不会打扰你开会
- 记忆数据保存在本地，不会上传到云端
- 可以随时在设置中清除记忆

---

## ⚙️ 配置说明

### 方式一：通过设置窗口（推荐）

1. **右键点击暖宝** → 选择「设置...」
2. 在设置窗口中配置各项参数：
   - **AI 模型**：对话 API Key、模型选择、温度、Token 限制
   - **记忆模型**：云端 Embedding 模型名称、API 地址、API Key（支持测试连接）
   - **外观**：透明度、窗口置顶、Dock 显示
   - **行为**：自动说话间隔、睡眠时间
3. 点击「保存」，配置立即生效

### 方式二：通过 .env 文件（仅首次配置）

如果您希望在启动应用前快速配置，可以修改项目根目录的 `.env` 文件：

```bash
# 必填：您的 AI API Key
LLM_API_KEY=sk-your-api-key-here

# 可选：对话模型（默认 deepseek-v4-flash）
LLM_MODEL_CHAT=deepseek-v4-flash

# 可选：复杂任务模型（默认 deepseek-v4-pro）
LLM_MODEL_GENERATE=deepseek-v4-pro

# 记忆模型（Embedding）配置
embedding_model=qwen3.7-text-embedding
embedding_model_url=https://dashscope.aliyuncs.com/compatible-mode/v1
embedding_model_api_key=sk-your-embedding-api-key
```

> **注意**：`.env` 文件仅用于首次启动时读取。一旦通过设置窗口保存配置，后续将以设置窗口为准。
>
> **说明**：天气和位置服务使用免费 API（uapis.cn），无需配置额外的 API Key。

### 配置说明

| 配置项                    | 必填 | 说明                                               |
| ------------------------- | ---- | -------------------------------------------------- |
| `LLM_API_KEY`             | ✅   | AI 服务的 API Key                                  |
| `LLM_MODEL_CHAT`          | ❌   | 对话模型（默认 deepseek-v4-flash）                 |
| `LLM_MODEL_GENERATE`      | ❌   | 复杂任务模型（默认 deepseek-v4-pro）               |
| `embedding_model`         | ❌   | 记忆 Embedding 模型（默认 qwen3.7-text-embedding） |
| `embedding_model_url`     | ❌   | Embedding API 地址                                 |
| `embedding_model_api_key` | ❌   | Embedding API Key（可与 LLM 共用）                 |

### 配置文件位置

| 平台        | 路径                                                 |
| ----------- | ---------------------------------------------------- |
| **macOS**   | `~/Library/Application Support/WarmBaby/config.json` |
| **Windows** | `%APPDATA%\WarmBaby\config.json`                     |
| **Linux**   | `~/.config/WarmBaby/config.json`                     |

---

## 🚀 快速开始

### 第一步：安装依赖和启动

```bash
# 1. 创建 conda 环境 (推荐)
conda create -n warming_baby python=3.13
conda activate warming_baby

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动应用
python main.py

# 4. 右键暖宝 → 设置 → 配置 AI 模型 + 记忆模型 API Key → 保存
# 5. 开始和暖宝对话！
```

> **说明**：记忆系统使用云端 Embedding API，无需下载本地模型文件。首次启动时，若未检测到 API Key，会自动弹窗引导配置。

---

## 🤖 技术架构

### 图结构（LangGraph ReAct + 并行记忆提取）

```
        START → agent_node → [有 tool_calls?] → tools_node → agent_node (循环)
                           → [无 tool_calls?] → ┬→ memory_extract_node ┬→ memory_node → END
                                                → format_node ─────────┘
```

- `memory_extract_node` 和 `format_node` **并行执行**（fan-out）
- `memory_node` 等待两者都完成后再执行（barrier）
- **记忆提取**：LLM 基于完整对话历史理解语义，输出结构化记忆（类型 + field + 内容）
- **情绪判断**：LLM 从 AI 回复 + 宠物状态中提取 emotion

### 核心技术栈

| 组件      | 技术                              | 说明                         |
| --------- | --------------------------------- | ---------------------------- |
| UI 框架   | PyQt6                             | 跨平台 GUI                   |
| AI 对话   | LangGraph                         | 图结构编排，LLM 语义记忆提取 |
| LLM       | LangChain                         | 支持多种模型                 |
| 记忆存储  | ChromaDB                          | 向量数据库                   |
| 记忆提取  | LLM (云端)                        | 完整对话理解 + 结构化提取    |
| Embedding | 云端 API (qwen3.7-text-embedding) | 云端向量模型，无需本地部署   |
| 情绪判断  | LLM (云端)                        | 并行执行，与记忆提取同步     |
| 事件系统  | EventBus                          | 发布-订阅模式                |
| 外部工具  | MCP (Model Context Protocol)      | 标准协议接入第三方工具       |
| Qt 集成   | qasync                            | Qt 事件循环 + asyncio        |

**MCP 关键设计**：

- **动态发现**：启动时通过 `tools/list` 自动获取 Server 暴露的所有工具，无需预配置
- **通用包装**：`McpToolWrapper` 将任意 MCP 工具转成 `AgentTool`，一个类适配所有 MCP 工具
- **无缝集成**：MCP 工具与原生工具（天气/热榜/记忆）在 `tool_registry` 中统一管理，LLM 无差别调用
- **生命周期管理**：`MCPClientManager` 单例管理所有 Server 的启动、握手、工具注册和优雅关闭

---

## 📝 更新日志

### v0.7.1

- 修复已知bug
- 增加全局错误处理机制

### v0.7.0

**🧠 记忆架构重构：LLM 语义记忆 + 云端 Embedding**

- ✨ 全新 `memory_extract` 节点：LLM 基于完整对话历史提取结构化记忆，理解时间变化、多主体等复杂语义
- ⚡ 并行执行优化：`memory_extract`（记忆提取）与 `format`（情绪判断）通过 fan-out/barrier 并行执行，回复速度显著提升
- ☁️ 云端 Embedding：移除本地 BGE 模型依赖，通过云端 API（qwen3.7-text-embedding 等）生成向量，打包体积减少 500MB+
- 🎯 LLM 提取 field：记忆的去重键（field）由 LLM 直接语义化命名（如 `name`、`mother_location`、`桃子`），normalizer 规则作为兜底
- 🛡️ 类型/字段修正：`memory_node` 对 LLM 提取的结果执行 `correct_type` 和 `extract_field` 兜底，防止误判
- 🧹 清理冗余代码：移除 `store.py` 中重复的 `normalizer.extract_field` 调用
- 🔧 配置 UI 新增「记忆模型」Tab：支持 Embedding 模型名、API 地址、API Key 配置及「测试连接」
- 🚀 首次安装引导：无 LLM/Embedding API Key 时自动弹窗提示配置
- 🔐 Embedding API Key 存储在 `.secrets.json`，与主配置隔离

### v0.6.8

**🔌 MCP 外部工具集成**

- 新增 MCP (Model Context Protocol) 集成，支持通过标准协议接入第三方工具
- 实现 `MCPClientManager` 单例，管理 MCP Server 的启动、握手、工具发现和优雅关闭
- 实现 `McpToolWrapper` 桥接器，将 MCP 工具动态包装成 `AgentTool` 注册到 `tool_registry`
- 实现 JSON Schema → Pydantic 自动转换，运行时动态生成 args_schema
- 支持 stdio 模式（npx 子进程）连接 MCP Server，配置即插即用
- 已接入 Bing 搜索工具（web_search、image_search）
- MCP 工具与原生工具（天气/热榜/记忆）统一管理，LLM 无差别调用
- 新增 `tools/mcp/` 模块（mcp_config / mcp_bridge / mcp_client）

**🔥 热榜看板优化**

- 优化 Tab 栏样式：去除图标、居中字体、调整宽度和间距
- 优化弹窗圆角和 Tab 与内容区的视觉衔接
- 清理热榜平台类型，移除无效 API

**🧠 架构优化**

- `tool_registry` 支持动态刷新，MCP 工具注册后自动生效
- `ChatGraph` 新增 `refresh_tools()` 方法，热更新工具列表
- 新增 `core/topmost.py` 跨平台窗口置顶（macOS AppKit / Windows Win32）

### v0.6.5

**🔥 热榜看板功能**

- 新增热榜查询工具，支持 23 个平台（B站、微博、知乎、抖音、小红书、快手、百度、今日头条、新浪、贴吧、澎湃新闻、腾讯新闻、IT之家、CSDN、掘金、V2EX、HelloGitHub、英雄联盟、原神、网易云音乐、QQ音乐、微信读书、历史上的今天）
- 多平台热榜在同一窗口通过 Tab 页合并展示，点击条目直接打开原链接
- 无边框圆角弹窗，自绘暖黄色背景，风格与状态面板一致
- 支持拖拽移动、ESC 关闭、跨平台窗口置顶（macOS AppKit / Windows Win32）
- 5 分钟 API 缓存，避免重复请求
- 用户关闭弹窗后自动清空 Tab 内容，下次查询是全新窗口

### v0.6.x

**宠物状态系统 + 交互体验优化**

- 🐹 新增宠物状态系统（饱食度/心情/体力/亲密度），曲线衰减 + 离线衰减（高值掉得快，低值省电保命）
- 🎯 四个动作（投喂/玩耍/抚摸/睡觉）走 LLM 链路，回复带状态感知
- 🧊 状态值 < 80 时不启用冷却，方便快速恢复宠物状态
- 🍚 喂太饱（≥95）时心情 -1 惩罚
- 💬 气泡边缘修复（描边不再被裁剪）+ 尾巴朝向跟随布局方向（宠物在顶部时尾巴朝上）
- ⏳ typing 气泡改为三点波浪动画，替代原来的 "..." 文字
- 🗣️ 自动说话支持四个负面状态（饥饿/无聊/困倦/悲伤）触发对应动画
- 🧠 ChatAgent 架构重构：拆分 prompts/nodes/schema，graph.py 单独编排
- 📊 LLM 拿到操作前的状态快照，避免基于动作后数值回复错误内容
- 新增 Focus 模式

### v0.5.8

**记忆系统架构重构：确定性节点替代 LLM 自主存储**

- 移除 `AddMemoryTool`/`UpdateMemoryTool`，LLM 不再自主添加/修改记忆
- 新增 `memory_node` 确定性节点，每次对话结束自动执行记忆提取和存储
- 新增 `CoreMemoryCache` 核心记忆缓存，启动时加载 FACT + 高重要性 PREFERENCE/SKILL 到内存
- FormatNode 只从 HumanMessage 提取记忆，杜绝 AI 回复内容被存储
- 移除 `processed_memories` State 字段和 `FactField` 枚举（死代码清理）
- 图结构：`agent ⇄ tools → format → memory → END`

### v0.5.2

**架构重构：从 LangGraph 迁移到 ReAct 架构**

- 又改回 LangGraph 啦！！！，发现还是 LangGraph 封装的更好，代码更加优雅
- LLM 现在可以自主决定是否调用工具、调用哪些工具
- 大幅简化代码结构，减少抽象层次

**智能记忆系统优化**

- 记忆改为 LLM 主动调用 `add_memory`/`query_memory`/`update_memory` 工具
- FACT 类型记忆智能去重，不再误删不同事实
- 记忆提示词优化，LLM 更准确地使用记忆（注：v0.5.8 已改为确定性节点，不再依赖 LLM 自主调用）

**UI/UX 优化**

- 气泡显示时间根据字数动态计算（约 10 字/秒）
- 单次情绪动画（HAPPY/SAD）后自动切换到 NEUTRAL 配合气泡显示
- 自动说话禁用思考模式，响应更快
- 天气和位置服务改为免费 API，无需配置

### v0.5.1

**🏗️ 架构重构**

- 🔧 从 LangGraph 4节点架构迁移到 ReAct 模式
- ⚡ 更简洁的代码结构，更少的抽象层次
- 🤖 LLM 可以自主决定是否调用工具、调用哪些工具
- 📍 新增位置自动获取功能
- 🌤️ 新增天气查询功能

**🐛 Bug 修复**

- 修复位置获取因变量名错误无法执行的问题
- 修复异步任务冲突导致的 RuntimeError
- 修复 LLM 无法使用位置信息查询天气的问题

**📚 文档整理**

- 更新技术文档，移除过时的 LangGraph 相关内容

### v0.4.1

**🧠 智能记忆系统**

- ✨ 新增基于 ChromaDB 的向量记忆存储
- 🔄 自动从对话中提取并存储用户信息（姓名、偏好、习惯等）
- 🎯 语义检索，让 AI "记住"你说过的话
- 🛡️ 智能去重：关键词匹配 + 语义相似度判断
- 📦 记忆分类：支持 fact/preference/event/context/skill 五种类型

**⚙️ 配置系统优化**

- 🎨 全新设置界面，支持实时配置
- 🔐 API Key 安全存储（加密保护）
- 📋 记忆管理界面，可查看和删除已存储的记忆

### v0.3

**🤖 多模型支持**

- 🔄 支持多种 AI 服务：DeepSeek、OpenAI、通义千问等
- 🎯 可为不同任务配置不同模型
- 🔌 统一的 LLM 接口，方便扩展

**🎨 UI 改进**

- 💬 优化对话框样式，更现代美观
- 🖼️ 气泡动画效果优化
- 📱 响应式布局改进

### v0.2

**🎮 交互增强**

- 🖱️ 新增右键菜单快速操作
- 🎯 优化触摸响应
- 😊 更多表情动画
- 🔊 新增自动说话功能

**⚡ 性能优化**

- 🚀 启动速度提升 50%
- 💾 内存占用降低 30%
- 🎯 动画流畅度提升

### v0.1

**🎉 初始版本**

- ✨ 基础桌宠功能
- 💬 简单 AI 对话
- 🎨 基础动画效果
- 📍 窗口位置保持

---

## 💡 使用技巧

- 🎯 **对话技巧**：描述越具体，AI 回应越准确
- 📍 **天气查询**：支持免费 API，无需配置即可使用。直接问"今天天气"会自动定位你的位置
- 🧠 **记忆管理**：可以在设置中查看和删除暖宝记住的内容
- 💤 **睡眠模式**：长时间不活动会自动进入睡眠

---

## ⚠️ 注意事项

- macOS 和 Windows 双端均支持
- 打包 Windows/macOS 均已支持（云端 Embedding 无本地模型依赖）
- 需要联网才能使用 AI 功能
- 首次启动需要初始化连接，可能需要几秒
- 记忆数据保存在本地，不会上传到云端

---

> 当前版本 v0.7.1
