# 动画与 UI 规则文档

> 本文档定义了宠物应用中所有动画、UI组件的行为规则、优先级和冲突处理机制。

---

## 目录

1. [概述](#1-概述)
2. [状态定义](#2-状态定义)
3. [动画系统](#3-动画系统)
4. [UI组件系统](#4-ui组件系统)
5. [状态转换规则](#5-状态转换规则)
6. [优先级规则](#6-优先级规则)
7. [冲突处理规则](#7-冲突处理规则)
8. [实现要点](#8-实现要点)
9. [日志与调试](#9-日志与调试)

---

## 1. 概述

### 1.1 设计目标

- **单一状态源**: 任何时刻只有一个活跃的动画状态
- **优先级明确**: 高优先级状态可以打断低优先级状态
- **可预测性**: 状态转换规则清晰可预测
- **鲁棒性**: 处理异步事件和竞态条件

### 1.2 核心概念

| 概念 | 描述 |
|-----|------|
| **状态标志** | 布尔标志，指示宠物当前的状态（如 `_is_sleeping`） |
| **动画状态** | 当前播放的动画类型（如 `WALK`, `HAPPY`） |
| **UI状态** | UI组件的显示/隐藏状态（如气泡、输入框） |
| **守卫函数** | 在执行操作前检查是否允许的函数 |

---

## 2. 状态定义

### 2.1 核心状态标志

| 状态标志 | 类型 | 描述 | 设置时机 |
|---------|------|------|---------|
| `_is_exiting` | bool | 正在退出应用 | 用户关闭应用时 |
| `_is_sleeping` | bool | 正在睡眠 | 空闲超时或进入睡眠时 |
| `_is_warming_up` | bool | 正在预热 | 应用启动时 |
| `is_dragging` | bool | 被用户拖拽 | 用户按下并拖动时 |
| `is_chatting` | bool | 显示对话气泡 | 气泡显示时 |
| `_waiting_llm` | bool | 等待 LLM 响应 | 发送请求后 |
| `_pending_response_cancelled` | bool | 待处理响应已取消 | 进入睡眠时 |

### 2.2 状态生命周期图

```
正常状态
  ├── 拖拽中 (is_dragging=True)
  ├── 对话中 (is_chatting=True)
  │   └── 等待 LLM (_waiting_llm=True)
  ├── 睡眠中 (_is_sleeping=True)
  ├── 预热中 (_is_warming_up=True)
  └── 退出中 (_is_exiting=True)
```

---

## 3. 动画系统

### 3.1 动画分类

#### 3.1.1 按播放模式分类

| 分类 | 动画 | 播放模式 | 描述 |
|-----|------|---------|------|
| **基础循环动画** | WALK, STAND, FLY, CONFUSED | 循环 | 表示宠物的基本状态 |
| **情绪单次动画** | HAPPY, SAD, ANGRY, TOUCH | 单次 | 表示短暂的情绪反应 |
| **状态循环动画** | SLEEP, PLAYING, SEARCHING, NEUTRAL | 循环 | 表示持续的状态 |
| **动作单次动画** | LEAVE, DRAG, EATING | 单次 | 表示短暂的动作 |

#### 3.1.2 动画属性

```python
# 每个动画的完整配置
AnimationConfig(
    animation_type=AnimationType.HAPPY,
    file_name='happy.gif',           # GIF 文件名
    aliases=['happy', 'joy', ...],   # LLM 可识别的别名
    description='开心/兴奋',         # 描述
    play_once=True,                  # 是否单次播放
    duration_ms=None,                # 单次播放时长 (None 使用默认 4340ms)
)
```

### 3.2 动画触发方式

#### 3.2.1 主动播放

| 方法 | 描述 | 恢复行为 |
|-----|------|---------|
| `play(anim_type)` | 循环播放 | 保持该状态直到被其他动画打断 |
| `play_once(anim_type)` | 单次播放 | 播放完恢复到之前的动画 |
| `trigger_animation(name)` | 根据名称触发 | 自动判断单次/循环 |

#### 3.2.2 被动触发

| 触发源 | 方式 | 示例 |
|-------|------|------|
| LLM 响应 | `emotion` 字段 | `"emotion": "happy"` |
| 用户交互 | 直接调用 | 点击时触发 `TOUCH` |
| 系统事件 | 定时器/状态变化 | 空闲超时触发 `SLEEP` |

### 3.3 动画保护规则

#### 3.3.1 LLM 等待保护

```python
# 在等待 LLM 响应时，保护 CONFUSED 状态
if self._waiting_llm and self.current_type == AnimationType.CONFUSED:
    # 不允许切换到其他动画（除了 CONFUSED 自身）
    if anim_type != AnimationType.CONFUSED:
        return  # 阻止切换
```

#### 3.3.2 退出保护

```python
# 退出时只允许 LEAVE 动画
if self._is_exiting and anim_type != AnimationType.LEAVE:
    return  # 阻止其他动画
```

#### 3.3.3 拖拽保护

```python
# 拖拽时保持 DRAG 动画
if self.is_dragging and anim_type != AnimationType.DRAG:
    return  # 阻止其他动画
```

---

## 4. UI组件系统

### 4.1 UI组件列表

| 组件 | 文件 | 描述 | 显示条件 |
|-----|------|------|---------|
| **气泡** | `ui/widgets/bubble.py` | 显示对话内容 | `can_show_bubble() == True` |
| **输入框** | `ui/widgets/input_panel.py` | 用户输入框 | 用户聚焦时 |
| **设置对话框** | `ui/dialogs/settings.py` | 设置面板 | 用户打开设置时 |

### 4.2 气泡组件

#### 4.2.1 核心方法

| 方法 | 描述 | 参数 |
|-----|------|------|
| `show_message(text, auto_hide, duration)` | 显示消息 | `text`: 消息内容, `auto_hide`: 自动隐藏, `duration`: 隐藏延迟 |
| `show_typing()` | 显示"..."占位符 | 无 |
| `hide_bubble(trigger_callback)` | 立即隐藏 | `trigger_callback`: 是否触发隐藏回调 |
| `start_fade_out()` | 开始淡出动画 | 无 |

#### 4.2.2 气泡生命周期

```
1. show_message() 被调用
   ├── 设置 opacity = 0 (确保与动画起始值一致)
   ├── 停止所有定时器和动画
   ├── 计算气泡尺寸
   ├── show() 显示窗口 (此时透明)
   ├── processEvents() 强制刷新
   ├── 开始淡入动画 (0 -> 1)
   └── 启动自动隐藏定时器

2. 自动隐藏定时器触发
   └── start_fade_out() 开始淡出 (当前值 -> 0)

3. 淡出动画完成
   ├── opacity <= 0.01
   ├── hide() 隐藏窗口
   └── 触发 on_hidden_callback (清除状态)
```

#### 4.2.3 气泡显示规则

| 规则 | 条件 | 行为 |
|-----|------|------|
| **睡眠中** | `_is_sleeping == True` | 不显示气泡 |
| **退出中** | `_is_exiting == True` | 不显示气泡 |
| **不可见** | `isVisible() == False` | 不显示气泡 |
| **有新消息** | `show_message()` 调用 | 覆盖旧消息，重新计时 |

#### 4.2.4 气泡配置

```python
# settings.py 中的 BubbleConfig
class BubbleConfig(BaseConfig):
    max_width: int = 300           # 最大宽度
    min_width: int = 150           # 最小宽度
    padding: int = 12              # 内边距
    corner_radius: int = 12        # 圆角半径
    tail_height: int = 15          # 尾巴高度
    tail_width: int = 20           # 尾巴宽度
    fade_in_duration: int = 200    # 淡入时长 (ms)
    fade_out_duration: int = 300   # 淡出时长 (ms)
    default_hide_delay: int = 3000 # 默认隐藏延迟 (ms)
```

### 4.3 输入框组件

#### 4.3.1 核心方法

| 方法 | 描述 |
|-----|------|
| `show_panel()` | 显示输入框 |
| `hide_panel()` | 隐藏输入框 |
| `clear_input()` | 清空输入内容 |
| `set_placeholder(text)` | 设置占位文本 |

#### 4.3.2 输入框规则

| 规则 | 描述 |
|-----|------|
| **焦点管理** | 显示后自动获得焦点 |
| **自动隐藏** | 失去焦点时自动隐藏 |
| **事件穿透** | 拦截鼠标事件防止穿透 |
| **跨平台** | Windows 上调整 `WA_ShowWithoutActivating` 属性 |

---

## 5. 状态转换规则

### 5.1 守卫函数

所有状态转换都应通过守卫函数检查：

```python
class NuanbaoPet:
    # === 状态守卫函数 ===
    
    def can_show_bubble(self) -> bool:
        """检查是否可以显示气泡"""
        return (not self._is_sleeping and 
                not self._is_exiting and 
                self.isVisible())
    
    def can_process_response(self) -> bool:
        """检查是否可以处理 LLM 响应"""
        return (not self._is_sleeping and 
                not self._is_exiting and 
                not self._pending_response_cancelled)
    
    def can_auto_speak(self) -> bool:
        """检查是否可以触发自动说话"""
        return (not self._is_sleeping and 
                not self._is_exiting and 
                not self.is_dragging and 
                not self.is_chatting and
                not self._is_warming_up)
    
    def can_trigger_animation(self) -> bool:
        """检查是否可以触发动画"""
        return not self._is_sleeping and not self._is_exiting
    
    def can_enter_sleep(self) -> bool:
        """检查是否可以进入睡眠"""
        return (not self.is_dragging and 
                not self.is_chatting and 
                not self._waiting_llm and
                not self._is_warming_up)
```

### 5.2 关键转换流程

#### 5.2.1 进入睡眠

```python
def _enter_sleep(self):
    # 1. 检查是否可以进入睡眠
    if not self.can_enter_sleep():
        return
    
    # 2. 设置状态标志
    self._is_sleeping = True
    self._pending_response_cancelled = True  # 取消待处理响应
    self._waiting_llm = False
    
    # 3. 清理 UI
    if self.bubble and self.bubble.isVisible():
        self.bubble.hide_bubble(trigger_callback=False)
        self.is_chatting = False
    
    # 4. 切换动画
    self._prev_animation_before_sleep = self.current_type
    self.play(AnimationType.SLEEP)
    
    # 5. 设置唤醒定时器
    self.sleep_end_timer.start(sleep_duration_ms)
```

#### 5.2.2 从睡眠唤醒

```python
def _wake_up(self):
    # 1. 清除状态标志
    self._is_sleeping = False
    self._pending_response_cancelled = False
    
    # 2. 停止定时器
    self.sleep_end_timer.stop()
    
    # 3. 根据鼠标状态决定动画
    self._check_mouse_hover()
    if self.is_hovering:
        self.play(AnimationType.STAND)
    else:
        self.play(AnimationType.WALK)
    
    # 4. 记录唤醒时间
    self._last_interaction_time = time.time()
```

#### 5.2.3 处理 LLM 响应

```python
def _handle_agent_response(self, response: dict):
    # 1. 检查是否可以处理响应
    if not self.can_process_response():
        logger.debug("Blocked response due to state")
        return
    
    # 2. 提取响应内容
    text = response.get('text', '')
    emotion = response.get('emotion', '')
    
    # 3. 显示气泡（如果允许）
    if text and self.can_show_bubble():
        self.show_message(text, ...)
    
    # 4. 触发动画（如果允许）
    if emotion and self.can_trigger_animation():
        self.trigger_animation(emotion, ...)
```

---

## 6. 优先级规则

### 6.1 状态优先级

从高到低：

| 优先级 | 状态 | 影响范围 | 说明 |
|-------|------|---------|------|
| 1 | 退出中 | 全局 | 阻止所有非 LEAVE 动画 |
| 2 | 睡眠中 | 全局 | 阻止气泡、响应处理、自动说话 |
| 3 | 拖拽中 | 局部 | 阻止 DRAG 以外的动画 |
| 4 | 对话中 | 局部 | 阻止自动说话 |
| 5 | 等待 LLM | 局部 | 保护 CONFUSED 状态 |
| 6 | 预热中 | 局部 | 阻止自动说话、动画切换 |

### 6.2 动画优先级

#### 6.2.1 可被打断的状态

| 当前动画 | 可被以下动画打断 | 不可被以下动画打断 |
|---------|----------------|------------------|
| WALK | STAND, SLEEP, TOUCH, 所有情绪动画 | |
| STAND | WALK, SLEEP, TOUCH, 所有情绪动画 | |
| SLEEP | (不可被打断) | 除了用户交互唤醒 |
| CONFUSED | 只有其他动画 (等待 LLM 期间保护) | |
| NEUTRAL | WALK, STAND, SLEEP | 情绪单次动画 |

#### 6.2.2 单次动画的特殊处理

```python
# play_once 的工作方式
def play_once(self, anim_type):
    prev_type = self.current_type  # 保存当前状态
    
    # 播放单次动画
    movie.frameChanged.connect(lambda frame: self._on_single_frame(...))
    movie.finished.connect(lambda: self._restore_prev_state(prev_type))
```

| 单次动画 | 完成后恢复 | 特殊情况 |
|---------|----------|---------|
| HAPPY | 之前的循环动画 | 被拖拽打断时恢复到 DRAG |
| SAD | 之前的循环动画 | |
| TOUCH | 之前的循环动画 | 可以连续触发 |
| EATING | 之前的循环动画 | |
| LEAVE | (不恢复，准备退出) | |

### 6.3 UI 优先级

| UI 元素 | 优先级 | 说明 |
|---------|-------|------|
| 设置对话框 | 1 | 模态，阻止其他 UI |
| 输入框 | 2 | 需要焦点，自动隐藏气泡 |
| 气泡 | 3 | 可被输入框覆盖 |

---

## 7. 冲突处理规则

### 7.1 冲突场景列表

| 场景 | 冲突方 | 处理方式 |
|-----|-------|---------|
| 自动说话触发 + 空闲超时进入睡眠 | `_check_auto_speak` vs `_check_idle` | 睡眠优先，自动说话被阻止 |
| LLM 响应到达 + 正在睡眠 | `_handle_agent_response` vs `_is_sleeping` | 丢弃响应 |
| 用户拖拽 + 自动说话触发 | `is_dragging` vs `_check_auto_speak` | 拖拽优先，阻止自动说话 |
| 用户输入 + 等待 LLM 响应 | 新请求 vs 旧响应 | 旧响应被取消 |
| 退出 + 任何动画 | `_is_exiting` vs 所有动画 | 只允许 LEAVE |

### 7.2 竞态条件处理

#### 7.2.1 双检查模式

```python
def _check_auto_speak(self):
    # 第一次检查
    if not self.can_auto_speak():
        return
    
    # 执行可能耗时的操作
    should_speak = self.auto_speak_manager.should_speak(...)
    
    if not should_speak:
        return
    
    # 第二次检查（防止状态在操作期间变化）
    if not self.can_auto_speak():
        logger.debug("Blocked after should_speak check")
        return
    
    # 执行操作
    self._waiting_llm = True
    event_bus.publish(...)
```

#### 7.2.2 取消机制

```python
# 设置取消标志
def _enter_sleep(self):
    self._pending_response_cancelled = True

# 检查取消标志
def _handle_agent_response(self, response):
    if self._pending_response_cancelled:
        return
```

#### 7.2.3 信号转发

```python
# 从非 UI 线程安全转发到 UI 线程
def _on_agent_response(self, response):
    if self._is_exiting:
        return
    # 使用 Qt 信号机制确保线程安全
    self._agent_response_received.emit(response)

def _handle_agent_response(self, response):
    # 这里在 UI 线程执行
    ...
```

### 7.3 冲突解决矩阵

| 当前状态 | 触发事件 | 目标状态 | 处理结果 | 说明 |
|---------|---------|---------|---------|------|
| **正常 (WALK)** | 自动说话 | 对话 | ✅ 允许 | 正常流程 |
| **正常 (WALK)** | 空闲超时 | 睡眠 | ✅ 允许 | 正常流程 |
| **对话中** | 空闲超时 | 睡眠 | ❌ 阻止 | `can_enter_sleep()` 返回 False |
| **对话中** | 自动说话 | 对话 | ❌ 阻止 | `can_auto_speak()` 返回 False |
| **对话中** | 用户拖拽 | 拖拽 | ✅ 允许 | 取消对话，开始拖拽 |
| **睡眠中** | LLM 响应 | 对话 | ❌ 阻止 | `can_process_response()` 返回 False |
| **睡眠中** | 自动说话 | 对话 | ❌ 阻止 | `can_auto_speak()` 返回 False |
| **睡眠中** | 用户拖拽 | 拖拽 | ✅ 允许 | 唤醒并开始拖拽 |
| **拖拽中** | 自动说话 | 对话 | ❌ 阻止 | `can_auto_speak()` 返回 False |
| **拖拽中** | 空闲超时 | 睡眠 | ❌ 阻止 | `can_enter_sleep()` 返回 False |
| **退出中** | 任何动画 | 任何 | ❌ 阻止 | 除 LEAVE 外 |

---

## 8. 实现要点

### 8.1 关键检查点

以下位置必须包含守卫函数检查：

| 函数 | 检查点 | 守卫函数 |
|-----|-------|---------|
| `show_message()` | 显示气泡前 | `can_show_bubble()` |
| `show_typing()` | 显示输入前 | `can_show_bubble()` |
| `_handle_agent_response()` | 处理响应前 | `can_process_response()` |
| `_check_auto_speak()` | 触发说话前 | `can_auto_speak()` |
| `_enter_sleep()` | 进入睡眠前 | `can_enter_sleep()` |
| `play()` | 播放动画前 | 内联检查 |
| `play_once()` | 播放单次前 | 内联检查 |
| `trigger_animation()` | 触发动画前 | 内联检查 |

### 8.2 错误处理模式

```python
# 模式 1: 提前返回
def some_function(self):
    if not self.can_do_something():
        logger.debug("Blocked: reason")
        return
    
    # 正常逻辑
    ...

# 模式 2: 状态变化时清理
def state_transition(self, from_state, to_state):
    # 清理 from_state 的副作用
    self._cleanup(from_state)
    
    # 设置 to_state
    self._state = to_state
    self._setup(to_state)
    
    # 记录转换
    logger.info(f"State: {from_state} -> {to_state}")

# 模式 3: 异步回调检查
async def async_operation(self):
    # 发送请求
    response = await api.call()
    
    # 检查状态是否仍然有效
    if not self.is_valid_state():
        return
    
    # 处理响应
    self._handle(response)
```

### 8.3 线程安全

| 场景 | 处理方式 |
|-----|---------|
| 非 UI 线程调用 UI 方法 | 使用 `emit()` 转发信号 |
| 定时器回调 | 默认为 UI 线程，安全 |
| 异步任务完成 | 通过信号或 `QTimer.singleShot()` |
| 事件总线 | 实现需考虑线程安全 |

---

## 9. 日志与调试

### 9.1 关键日志点

```python
# 状态转换时 (INFO)
logger.info(f"State changed: {old_state} -> {new_state}, reason: {event}")

# 被守卫阻止的操作 (DEBUG)
logger.debug(f"Blocked {operation}: {reason}")

# 被取消的操作 (WARNING)
logger.warning(f"Cancelled {operation}: {reason}")

# 动画切换 (INFO)
logger.info(f"Animation: {old_anim} -> {new_anim}, play_once={play_once}")
```

### 9.2 调试辅助

#### 9.2.1 状态快照

```python
def dump_state(self) -> dict:
    """导出当前完整状态用于调试"""
    return {
        # 状态标志
        'flags': {
            'is_sleeping': self._is_sleeping,
            'is_exiting': self._is_exiting,
            'is_warming_up': self._is_warming_up,
            'is_dragging': self.is_dragging,
            'is_chatting': self.is_chatting,
            'waiting_llm': self._waiting_llm,
            'response_cancelled': self._pending_response_cancelled,
        },
        # 动画状态
        'animation': {
            'current': self.current_type,
            'prev': self._prev_animation_before_sleep,
            'is_running': self.current_movie is not None,
        },
        # UI 状态
        'ui': {
            'bubble_visible': self.bubble and self.bubble.isVisible(),
            'input_visible': self.input_panel and self.input_panel.isVisible(),
        },
        # 计时器
        'timers': {
            'idle': self.idle_check_timer.isActive(),
            'sleep_end': self.sleep_end_timer.isActive(),
            'auto_speak': self.auto_speak_check_timer.isActive(),
        },
    }
```

#### 9.2.2 守卫状态检查

```python
def check_all_guards(self) -> dict:
    """检查所有守卫函数的返回值"""
    return {
        'can_show_bubble': self.can_show_bubble(),
        'can_process_response': self.can_process_response(),
        'can_auto_speak': self.can_auto_speak(),
        'can_trigger_animation': self.can_trigger_animation(),
        'can_enter_sleep': self.can_enter_sleep(),
    }
```

### 9.3 常见问题排查

#### 问题 1: 气泡闪一下就没了

**原因**: `show()` 时 opacity 不为 0，用户看到不透明窗口，然后淡入动画从 0 开始。

**排查**:
```python
# 检查 opacity 设置顺序
def show_message(self, ...):
    self._opacity = 0  # ✅ 必须先设置为 0
    self.show()         # ✅ 然后 show
    self._start_fade_in()  # ✅ 最后开始动画 (0 -> 1)
```

#### 问题 2: 睡眠中气泡出现

**原因**: `_handle_agent_response` 没有检查 `_is_sleeping`。

**排查**:
```python
# 检查守卫函数调用
def _handle_agent_response(self, ...):
    if not self.can_process_response():  # ✅ 必须有这个检查
        return
```

#### 问题 3: 自动说话在错误时机触发

**原因**: `_check_auto_speak` 没有完整检查所有状态。

**排查**:
```python
# 使用完整的守卫函数
def _check_auto_speak(self):
    if not self.can_auto_speak():  # ✅ 检查所有禁止条件
        return
```

---

## 附录

### A. 完整动画列表

| 枚举值 | GIF 文件 | 单次播放 | 分类 |
|-------|---------|---------|------|
| `WALK` | walk_left.gif | ❌ | 基础循环 |
| `STAND` | stand_by.gif | ❌ | 基础循环 |
| `FLY` | fly.gif | ❌ | 基础循环 |
| `CONFUSED` | confused.gif | ❌ | 基础循环 |
| `TOUCH` | touch.gif | ✅ | 情绪单次 |
| `HAPPY` | happy.gif | ✅ | 情绪单次 |
| `SAD` | sad.gif | ✅ | 情绪单次 |
| `ANGRY` | anger.gif | ✅ | 情绪单次 |
| `SLEEP` | sleep.gif | ❌ | 状态循环 |
| `PLAYING` | playing.gif | ❌ | 状态循环 |
| `SEARCHING` | searching.gif | ❌ | 状态循环 |
| `EATING` | eatting.gif | ✅ | 动作单次 |
| `NEUTRAL` | neutral.gif | ❌ | 状态循环 |
| `LEAVE` | leave.gif | ✅ | 动作单次 |
| `DRAG` | drag.gif | ✅ | 动作单次 |

### B. Emotion 到动画的映射

| Emotion | 对应动画 |
|---------|---------|
| HAPPY | `HAPPY` |
| SAD | `SAD` |
| ANGRY | `ANGRY` |
| SURPRISED | `HAPPY` (临时) |
| CONFUSED | `CONFUSED` |
| NEUTRAL | `NEUTRAL` |

### C. 配置项速查

```yaml
# 气泡配置 (settings.py BubbleConfig)
bubble:
  max_width: 300           # 最大宽度 (px)
  min_width: 150           # 最小宽度 (px)
  padding: 12              # 内边距 (px)
  corner_radius: 12        # 圆角 (px)
  tail_height: 15          # 尾巴高度 (px)
  tail_width: 20           # 尾巴宽度 (px)
  fade_in_duration: 200    # 淡入时长 (ms)
  fade_out_duration: 300   # 淡出时长 (ms)

# 行为配置
behavior:
  idle_to_sleep_min: 5     # 空闲多久进入睡眠 (分钟)
  sleep_duration_min: 1    # 睡眠时间 (分钟)
  auto_speak_interval_min: 5  # 自动说话间隔 (分钟)
  auto_speak_enabled: true # 启用自动说话

# 宠物配置
pet:
  move_speed: 2            # 移动速度
  idle_check_interval_ms: 10000  # 空闲检查间隔 (ms)
```

### D. 版本历史

| 版本 | 日期 | 变更 |
|-----|------|------|
| v1.0 | 2026-08-04 | 初始版本 |

---

**文档维护者**: 开发团队  
**最后更新**: 2026-08-04