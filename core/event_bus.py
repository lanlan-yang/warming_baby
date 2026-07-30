"""
全局事件总线 EventBus

用于模块间解耦通信，支持4种事件分类:
- SystemEvent: 系统级事件(启动、关闭、错误等)
- UIEvent: 用户界面事件(点击、拖拽、键盘等)
- AgentEvent: AI Agent事件(思考、响应、工具调用等)
- PetEvent: 宠物行为事件(动画、状态、移动等)

使用示例:
    from core import event_bus, EventCategory, UIEvent, PetEvent

    # 订阅事件
    def on_pet_click(data):
        print(f"宠物被点击: {data}")
    event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, on_pet_click)

    # 发布事件
    event_bus.publish(EventCategory.UI, UIEvent.MOUSE_CLICK, {"x": 100, "y": 200})
"""
from enum import StrEnum
from typing import Any, Callable, Dict, List, Optional
from collections import defaultdict


# ============================================================================
# 事件分类 - 用于区分不同模块的事件
# ============================================================================
class EventCategory(StrEnum):
    """事件分类枚举
    
    Attributes:
        SYSTEM: 系统级事件(应用启动、关闭、配置变更等)
        UI: 用户界面事件(鼠标、键盘、窗口操作等)
        AGENT: AI Agent事件(思考、响应、工具调用等)
        PET: 宠物行为事件(动画播放、状态变化、移动等)
    """
    SYSTEM = 'system'  # 系统事件
    UI = 'ui'          # UI事件
    AGENT = 'agent'    # Agent事件
    PET = 'pet'        # 宠物事件


# ============================================================================
# 系统事件 - 应用生命周期、配置、异常处理
# ============================================================================
class SystemEvent(StrEnum):
    """系统事件枚举
    
    Attributes:
        STARTUP: 应用启动完成时触发
        SHUTDOWN: 应用关闭前触发，用于清理资源
        ERROR: 系统级错误发生时触发
        CONFIG_CHANGED: 配置文件或环境变量变更时触发
    """
    STARTUP = 'startup'  # 应用启动完成时触发
    SHUTDOWN = 'shutdown'  # 应用关闭前触发，用于清理资源
    ERROR = 'error'  # 系统级错误发生时触发
    CONFIG_CHANGED = 'config_changed'  # 配置文件或环境变量变更时触发


# ============================================================================
# UI事件 - 用户交互行为
# ============================================================================
class UIEvent(StrEnum):
    """
    用户界面事件枚举
    """
    MOUSE_CLICK = 'mouse_click'  # 鼠标左键单击(点按无拖拽)
    MOUSE_DOUBLE_CLICK = 'mouse_double_click'  # 鼠标左键双击
    MOUSE_DRAG_START = 'mouse_drag_start'  # 开始拖拽(移动距离超过阈值)
    MOUSE_DRAG_END = 'mouse_drag_end'  # 拖拽结束(释放鼠标)
    MOUSE_DRAG_MOVE = 'mouse_drag_move'  # 拖拽过程中持续触发
    MOUSE_HOVER_ENTER = 'mouse_hover_enter'  # 鼠标进入控件区域
    MOUSE_HOVER_LEAVE = 'mouse_hover_leave'  # 鼠标离开控件区域
    KEY_PRESS = 'key_press'  # 键盘按键按下
    WINDOW_MOVE = 'window_move'  # 窗口位置移动
    WINDOW_RESIZE = 'window_resize'  # 窗口大小改变


# ============================================================================
# Agent事件 - AI大模型交互
# ============================================================================
class AgentEvent(StrEnum):
    """AI Agent事件枚举"""
    THINKING = 'thinking'  # Agent开始思考/调用大模型
    RESPONSE = 'response'  # Agent收到完整响应(非流式)
    RESPONSE_STREAM = 'response_stream'  # Agent流式响应片段
    TOOL_CALL = 'tool_call'  # Agent调用工具/函数
    TOOL_RESULT = 'tool_result'  # 工具/函数执行完成
    ERROR = 'error'  # Agent处理过程中发生错误
    USER_MESSAGE = 'user_message'  # 用户发送消息给Agent


# ============================================================================
# 宠物事件 - 宠物行为和状态
# ============================================================================
class PetEvent(StrEnum):
    """宠物行为事件枚举"""
    ANIMATION_START = 'animation_start'  # 动画开始播放
    ANIMATION_END = 'animation_end'  # 动画播放结束
    ANIMATION_CHANGED = 'animation_changed'  # 动画类型切换(如walk -> fly)
    STATE_CHANGED = 'state_changed'  # 宠物状态变化(如IDLE -> FLYING)
    MOVE = 'move'  # 宠物位置移动(定时器触发)
    DIRECTION_CHANGED = 'direction_changed'  # 宠物朝向变化(左飞/右飞)


# ============================================================================
# 事件总线核心类
# ============================================================================
class EventBus:
    """
    全局事件总线（单例模式）
    
    实现发布-订阅模式，模块间通过事件解耦通信。
    支持按EventCategory分类管理事件，避免命名冲突。
    
    线程安全: 非线程安全，建议在主线程中使用
    
    Example:
        >>> bus = EventBus()
        >>> bus.subscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, lambda: print("点击"))
        >>> bus.publish(EventCategory.UI, UIEvent.MOUSE_CLICK)
        点击
    """
    
    _instance = None  # 单例实例
    
    def __new__(cls) -> 'EventBus':
        """单例模式: 确保全局只有一个EventBus实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # 初始化订阅器字典: {category: {event: [callback, ...]}}
            cls._instance._subscribers = defaultdict(lambda: defaultdict(list))
        return cls._instance
    
    def subscribe(
        self,
        category: EventCategory,
        event: str,
        callback: Callable[..., Any]
    ) -> None:
        """
        订阅事件
        
        Args:
            category: 事件分类(EventCategory枚举)
            event: 事件名称(字符串或枚举值)
            callback: 回调函数，当事件发布时被调用
                      支持任意参数: callback(*args, **kwargs)
        
        Example:
            >>> def on_click(x, y):
            ...     print(f"点击位置: ({x}, {y})")
            >>> event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, on_click)
        """
        self._subscribers[category][event].append(callback)
    
    def unsubscribe(
        self,
        category: EventCategory,
        event: str,
        callback: Callable[..., Any]
    ) -> None:
        """
        取消订阅事件
        
        Args:
            category: 事件分类
            event: 事件名称
            callback: 要取消的回调函数(必须和subscribe时相同的函数引用)
        
        Note:
            如果callback不在订阅列表中，不会报错(静默失败)
        
        Example:
            >>> event_bus.unsubscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, on_click)
        """
        if callback in self._subscribers[category][event]:
            self._subscribers[category][event].remove(callback)
    
    def publish(
        self,
        category: EventCategory,
        event: str,
        *args: Any,
        **kwargs: Any
    ) -> None:
        """
        发布事件，通知所有订阅者
        
        Args:
            category: 事件分类
            event: 事件名称
            *args: 位置参数，将传递给所有回调函数
            **kwargs: 关键字参数，将传递给所有回调函数
        
        Note:
            如果某个回调抛出异常，会被捕获并打印，不影响其他回调执行
        
        Example:
            >>> event_bus.publish(EventCategory.UI, UIEvent.MOUSE_CLICK, x=100, y=200)
        """
        subscribers = self._subscribers[category].get(event, [])
        for callback in subscribers:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"[EventBus] Error in {category.value}.{event}: {e}")
    
    def clear(
        self,
        category: Optional[EventCategory] = None,
        event: Optional[str] = None
    ) -> None:
        """
        清除订阅
        
        Args:
            category: 事件分类
                      - None: 清除所有分类的所有订阅
                      - 指定分类: 只清除该分类的订阅
            event: 事件名称
                   - None: 清除该分类下所有事件的订阅
                   - 指定事件: 只清除该事件的订阅
        
        Example:
            >>> event_bus.clear()  # 清除所有
            >>> event_bus.clear(EventCategory.UI)  # 只清除UI事件
            >>> event_bus.clear(EventCategory.UI, UIEvent.MOUSE_CLICK)  # 只清除点击事件
        """
        if category is None:
            # 清除所有
            self._subscribers.clear()
        elif event is None:
            # 清除指定分类的所有事件
            self._subscribers[category].clear()
        else:
            # 清除指定分类的指定事件
            self._subscribers[category][event].clear()
    
    def has_subscribers(self, category: EventCategory, event: str) -> bool:
        """
        检查某个事件是否有订阅者
        
        Args:
            category: 事件分类
            event: 事件名称
        
        Returns:
            bool: True表示有订阅者，False表示没有
        
        Example:
            >>> if event_bus.has_subscribers(EventCategory.UI, UIEvent.MOUSE_CLICK):
            ...     print("有订阅者")
        """
        return len(self._subscribers[category].get(event, [])) > 0
    
    def list_events(self, category: Optional[EventCategory] = None) -> List[str]:
        """
        列出已订阅的事件名称
        
        Args:
            category: 事件分类
                      - None: 列出所有分类的事件
                      - 指定分类: 只列出该分类的事件
        
        Returns:
            List[str]: 事件名称列表
        
        Example:
            >>> print(event_bus.list_events(EventCategory.UI))
            ['mouse_click', 'mouse_drag_start']
        """
        events = []
        if category:
            # 只列出指定分类的事件
            events.extend(self._subscribers[category].keys())
        else:
            # 列出所有分类的事件
            for cat_events in self._subscribers.values():
                events.extend(cat_events.keys())
        return events


# ============================================================================
# 全局单例实例 - 项目中统一使用这个实例
# ============================================================================
event_bus = EventBus()
