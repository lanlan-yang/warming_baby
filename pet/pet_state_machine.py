"""
状态机 - 管理宠物状态和状态转换
"""
from typing import Callable, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core import AnimationType, PetState


class PetStateMachine(QObject):
    """
    宠物状态机
    
    管理宠物的各种状态和状态转换规则
    
    信号:
        state_changed: 状态变化信号 (old_state, new_state)
        event_emitted: 事件发出信号 (event_name, data)
    """
    
    # Qt 信号
    state_changed = pyqtSignal(str, str)  # old_state, new_state
    event_emitted = pyqtSignal(str, dict)  # event_name, data
    
    # 事件类型
    EVENT_CLICK = "click"
    EVENT_DRAG_START = "drag_start"
    EVENT_DRAG_MOVE = "drag_move"
    EVENT_DRAG_END = "drag_end"
    EVENT_HOVER_ENTER = "hover_enter"
    EVENT_HOVER_LEAVE = "hover_leave"
    EVENT_ANIMATION_FINISHED = "animation_finished"
    EVENT_STATE_TIMEOUT = "state_timeout"
    
    def __init__(self):
        super().__init__()
        
        self._state: PetState = PetState.WALKING
        self._previous_state: Optional[PetState] = None
        self._callbacks: Dict[str, list] = {
            "on_state_change": [],
            "on_event": [],
            "on_click": [],
            "on_drag_start": [],
            "on_drag_move": [],
            "on_drag_end": [],
            "on_hover_enter": [],
            "on_hover_leave": [],
            "on_touch_finished": [],
            "on_fly_finished": [],
            "on_idle_finished": [],
        }
        
        # 记录拖拽起始位置（用于区分点击和拖拽）
        self._click_start_pos = None
        self._drag_threshold = 5
        self._is_dragging = False
        self._is_clicking = False
    
    @property
    def state(self) -> PetState:
        """获取当前状态"""
        return self._state
    
    def set_state(self, new_state: PetState):
        """
        设置新状态
        
        Args:
            new_state: 新状态
        """
        if self._state == new_state:
            return
        
        old_state = self._state
        self._previous_state = old_state
        self._state = new_state
        
        # 发送状态变化信号
        self.state_changed.emit(old_state.value, new_state.value)
        self._notify_callbacks("on_state_change", old_state, new_state)
    
    # 事件处理方法 - 由 View 层调用
    
    def handle_hover_enter(self):
        """鼠标悬停进入事件"""
        if self._state in [PetState.WALKING, PetState.IDLE]:
            self.set_state(PetState.HOVERING)
        
        self._emit_event(self.EVENT_HOVER_ENTER)
        self._notify_callbacks("on_hover_enter")
    
    def handle_hover_leave(self):
        """鼠标悬停离开事件"""
        if self._state == PetState.HOVERING:
            # 恢复到之前的状态
            self.set_state(self._previous_state or PetState.WALKING)
        
        self._emit_event(self.EVENT_HOVER_LEAVE)
        self._notify_callbacks("on_hover_leave")
    
    def handle_mouse_press(self, pos_x: float, pos_y: float):
        """
        鼠标按下事件
        
        Args:
            pos_x: 鼠标X坐标
            pos_y: 鼠标Y坐标
        """
        self._is_clicking = True
        self._is_dragging = False
        self._click_start_pos = (pos_x, pos_y)
    
    def handle_mouse_move(self, pos_x: float, pos_y: float):
        """
        鼠标移动事件
        
        Args:
            pos_x: 鼠标X坐标
            pos_y: 鼠标Y坐标
        """
        if self._is_clicking and not self._is_dragging and self._click_start_pos:
            # 检测是否超过拖拽阈值
            dist_x = abs(pos_x - self._click_start_pos[0])
            dist_y = abs(pos_y - self._click_start_pos[1])
            distance = dist_x + dist_y
            
            if distance > self._drag_threshold:
                # 开始拖拽
                self._is_dragging = True
                self._is_clicking = False
                self._handle_drag_start()
        
        if self._is_dragging:
            self._handle_drag_move(pos_x, pos_y)
    
    def handle_mouse_release(self):
        """鼠标释放事件"""
        if self._is_dragging:
            # 拖拽结束
            self._handle_drag_end()
        elif self._is_clicking:
            # 点击完成
            self._handle_click()
        
        self._is_clicking = False
        self._is_dragging = False
        self._click_start_pos = None
    
    def handle_animation_finished(self, animation_type: AnimationType):
        """
        动画播放完成事件
        
        Args:
            animation_type: 完成的动画类型
        """
        if animation_type == AnimationType.TOUCH:
            self._notify_callbacks("on_touch_finished")
            # 触摸动画结束，恢复状态
            if self._state == PetState.TOUCHED:
                if self._previous_state == PetState.HOVERING:
                    self.set_state(PetState.HOVERING)
                else:
                    self.set_state(self._previous_state or PetState.WALKING)
        
        self._emit_event(self.EVENT_ANIMATION_FINISHED, {"animation": animation_type.value})
    
    def handle_state_timeout(self):
        """状态超时事件 - 由定时器触发"""
        self._emit_event(self.EVENT_STATE_TIMEOUT)
        
        if self._state == PetState.IDLE:
            self.set_state(PetState.WALKING)
        elif self._state == PetState.WALKING:
            self.set_state(PetState.IDLE)
    
    # 内部处理方法
    
    def _handle_click(self):
        """处理点击事件"""
        self.set_state(PetState.TOUCHED)
        self._emit_event(self.EVENT_CLICK)
        self._notify_callbacks("on_click")
    
    def _handle_drag_start(self):
        """处理拖拽开始"""
        self.set_state(PetState.FLYING)
        self._emit_event(self.EVENT_DRAG_START)
        self._notify_callbacks("on_drag_start")
    
    def _handle_drag_move(self, pos_x: float, pos_y: float):
        """处理拖拽移动"""
        self._emit_event(self.EVENT_DRAG_MOVE, {"x": pos_x, "y": pos_y})
        self._notify_callbacks("on_drag_move", pos_x, pos_y)
    
    def _handle_drag_end(self):
        """处理拖拽结束"""
        self._notify_callbacks("on_drag_end")
        
        if self._state == PetState.FLYING:
            if self._previous_state == PetState.HOVERING:
                self.set_state(PetState.HOVERING)
            else:
                self.set_state(self._previous_state or PetState.WALKING)
        
        self._emit_event(self.EVENT_DRAG_END)
    
    def _emit_event(self, event_name: str, data: Optional[dict] = None):
        """发出事件信号"""
        self.event_emitted.emit(event_name, data or {})
        self._notify_callbacks("on_event", event_name, data or {})
    
    # 回调注册 API
    
    def on_state_change(self, callback: Callable[[PetState, PetState], None]):
        """
        注册状态变化回调
        
        Args:
            callback: 回调函数 (old_state, new_state) -> None
        """
        self._callbacks["on_state_change"].append(callback)
    
    def on_event(self, callback: Callable[[str, dict], None]):
        """
        注册所有事件回调
        
        Args:
            callback: 回调函数 (event_name, data) -> None
        """
        self._callbacks["on_event"].append(callback)
    
    def on_click(self, callback: Callable[[], None]):
        """注册点击事件回调"""
        self._callbacks["on_click"].append(callback)
    
    def on_drag_start(self, callback: Callable[[], None]):
        """注册拖拽开始回调"""
        self._callbacks["on_drag_start"].append(callback)
    
    def on_drag_move(self, callback: Callable[[float, float], None]):
        """注册拖拽移动回调"""
        self._callbacks["on_drag_move"].append(callback)
    
    def on_drag_end(self, callback: Callable[[], None]):
        """注册拖拽结束回调"""
        self._callbacks["on_drag_end"].append(callback)
    
    def on_hover_enter(self, callback: Callable[[], None]):
        """注册悬停进入回调"""
        self._callbacks["on_hover_enter"].append(callback)
    
    def on_hover_leave(self, callback: Callable[[], None]):
        """注册悬停离开回调"""
        self._callbacks["on_hover_leave"].append(callback)
    
    def on_touch_finished(self, callback: Callable[[], None]):
        """注册触摸动画结束回调"""
        self._callbacks["on_touch_finished"].append(callback)
    
    def remove_callback(self, callback: Callable):
        """移除所有匹配的回调函数"""
        for key in self._callbacks:
            if callback in self._callbacks[key]:
                self._callbacks[key].remove(callback)
    
    def _notify_callbacks(self, event: str, *args):
        """通知所有回调函数"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args)
            except Exception as e:
                print(f"StateMachine callback error in {event}: {e}")
