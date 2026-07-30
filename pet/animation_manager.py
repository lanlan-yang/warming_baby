"""
动画管理器 - 封装所有 GIF 动画的加载、播放、切换
"""
from typing import Callable, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QMovie

from core import AnimationType


class AnimationManager(QObject):
    """
    动画管理器
    
    负责管理所有 GIF 动画的加载、播放、切换
    
    信号:
        frame_changed: 当前动画帧变化 (animation_type, frame_number)
        animation_finished: 动画播放完成 (animation_type)
        animation_changed: 当前动画类型变化 (new_animation_type)
    """
    
    # Qt 信号
    frame_changed = pyqtSignal(str, int)  # animation_type, frame_number
    animation_finished = pyqtSignal(str)  # animation_type
    animation_changed = pyqtSignal(str)  # new_animation_type
    
    def __init__(self, animations: Dict[AnimationType, str], 
                 one_shot_durations: Optional[Dict[AnimationType, int]] = None):
        """
        初始化动画管理器
        
        Args:
            animations: 动画类型到文件路径的映射字典
            one_shot_durations: 需要只播放一次的动画时长映射 (毫秒)
                              例如: {AnimationType.TOUCH: 4340}
        """
        super().__init__()
        
        self._movies: Dict[AnimationType, QMovie] = {}
        self._current_type: Optional[AnimationType] = None
        self._callbacks: Dict[str, list] = {
            "on_frame": [],
            "on_finished": [],
            "on_changed": []
        }
        
        # 只播放一次的动画时长
        self._one_shot_durations = one_shot_durations or {}
        self._one_shot_timer = QTimer(self)
        self._one_shot_timer.setSingleShot(True)
        self._one_shot_timer.timeout.connect(self._on_one_shot_timeout)
        self._current_one_shot_type: Optional[AnimationType] = None
        
        # 加载所有动画
        for anim_type, file_path in animations.items():
            movie = QMovie(file_path)
            self._movies[anim_type] = movie
    
    def play(self, animation_type: AnimationType, play_once: bool = False):
        """
        播放指定动画
        
        Args:
            animation_type: 动画类型
            play_once: 是否只播放一次（使用定时器）
        """
        if animation_type not in self._movies:
            raise ValueError(f"Unknown animation type: {animation_type}")
        
        # 停止当前动画
        if self._current_type:
            self._stop_current()
        
        movie = self._movies[animation_type]
        self._current_type = animation_type
        
        # 连接信号
        movie.frameChanged.connect(self._on_frame_changed)
        
        # 启动动画
        movie.start()
        
        # 如果只播放一次，设置定时器
        if play_once and animation_type in self._one_shot_durations:
            duration = self._one_shot_durations[animation_type]
            self._current_one_shot_type = animation_type
            self._one_shot_timer.start(duration)
        
        # 发送动画变化信号
        self.animation_changed.emit(animation_type.value)
        self._notify_callbacks("on_changed", animation_type)
    
    def _stop_current(self):
        """停止当前动画"""
        # 停止定时器
        self._one_shot_timer.stop()
        self._current_one_shot_type = None
        
        if self._current_type and self._current_type in self._movies:
            movie = self._movies[self._current_type]
            movie.stop()
            try:
                movie.frameChanged.disconnect(self._on_frame_changed)
            except TypeError:
                pass
            self._current_type = None
    
    def _on_one_shot_timeout(self):
        """只播放一次的动画超时"""
        if self._current_one_shot_type:
            anim_type = self._current_one_shot_type
            self._stop_current()
            self.animation_finished.emit(anim_type.value)
            self._notify_callbacks("on_finished", anim_type)
    
    def stop(self):
        """停止当前动画"""
        self._stop_current()
    
    def current_pixmap(self):
        """获取当前帧的 pixmap"""
        if self._current_type and self._current_type in self._movies:
            return self._movies[self._current_type].currentPixmap()
        return None
    
    def current_movie(self) -> Optional[QMovie]:
        """获取当前动画的 QMovie 对象"""
        if self._current_type and self._current_type in self._movies:
            return self._movies[self._current_type]
        return None
    
    def current_type(self) -> Optional[AnimationType]:
        """获取当前动画类型"""
        return self._current_type
    
    # 回调注册
    def on_frame(self, callback: Callable[[AnimationType, int], None]):
        """
        注册帧变化回调
        
        Args:
            callback: 回调函数 (animation_type, frame_number) -> None
        """
        self._callbacks["on_frame"].append(callback)
    
    def on_finished(self, callback: Callable[[AnimationType], None]):
        """
        注册动画完成回调
        
        Args:
            callback: 回调函数 (animation_type) -> None
        """
        self._callbacks["on_finished"].append(callback)
    
    def on_changed(self, callback: Callable[[AnimationType], None]):
        """
        注册动画变化回调
        
        Args:
            callback: 回调函数 (new_animation_type) -> None
        """
        self._callbacks["on_changed"].append(callback)
    
    def remove_callback(self, callback: Callable):
        """移除所有匹配的回调函数"""
        for key in self._callbacks:
            if callback in self._callbacks[key]:
                self._callbacks[key].remove(callback)
    
    # 内部处理
    def _on_frame_changed(self, frame_number: int):
        """帧变化处理"""
        if self._current_type is None:
            return
        
        animation_type = self._current_type
        self.frame_changed.emit(animation_type.value, frame_number)
        self._notify_callbacks("on_frame", animation_type, frame_number)
    
    def _notify_callbacks(self, event: str, *args):
        """通知所有回调函数"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args)
            except Exception as e:
                print(f"Callback error in {event}: {e}")
