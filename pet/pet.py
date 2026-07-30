"""
可爱暖宝宝桌面宠物 - 简化版
"""
import os
import sys
import random

from PyQt6.QtCore import Qt, QTimer, QPoint, QObject, pyqtSignal
from PyQt6.QtGui import QTransform, QMovie
from PyQt6.QtWidgets import QLabel, QMenu, QApplication
from PyQt6.QtGui import QAction

from core import AnimationType, PetState


class PetSignals(QObject):
    """宠物事件信号"""
    on_click = pyqtSignal()
    on_drag_start = pyqtSignal()
    on_drag_end = pyqtSignal()
    on_hover_enter = pyqtSignal()
    on_hover_leave = pyqtSignal()
    on_animation_end = pyqtSignal(str)  # 动画名
    
    # 外部触发事件（AI -> UI）
    play_animation = pyqtSignal(str, bool)  # 动画名, 是否只播放一次


class NuanbaoPet(QLabel):
    def __init__(self):
        super().__init__()
        
        # 信号
        self.signals = PetSignals()
        
        # 连接外部触发
        self.signals.play_animation.connect(self._on_play_from_external)
        
        # 窗口设置
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                          Qt.WindowType.WindowStaysOnTopHint | 
                          Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 路径
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 加载所有动画
        self.movies = {
            AnimationType.WALK: QMovie(os.path.join(base_dir, 'images/action/walk_left.gif')),
            AnimationType.STAND: QMovie(os.path.join(base_dir, 'images/action/stand_by.gif')),
            AnimationType.FLY: QMovie(os.path.join(base_dir, 'images/action/fly.gif')),
            AnimationType.TOUCH: QMovie(os.path.join(base_dir, 'images/action/touch.gif')),
        }
        
        # 状态
        self.current_movie = None
        self.current_type = None
        self.is_dragging = False
        self.is_clicking = False
        self.click_start_pos = QPoint()
        self.drag_offset = QPoint()
        self.drag_threshold = 5
        self.is_hovering = False
        self.last_mouse_x = 0
        self.facing_right = True
        self.display_height = 120
        
        # 移动设置
        self.direction = random.choice([-1, 1])
        self.y_direction = random.choice([-1, 1])
        self.move_speed = 2
        self.move_y_speed = 1
        self.screen = QApplication.primaryScreen().availableGeometry()
        
        # 定时器
        self.move_timer = QTimer(self)
        self.move_timer.timeout.connect(self.move_step)
        self.move_timer.start(30)
        
        # 开始走路
        self.play(AnimationType.WALK)
    
    def play(self, anim_type):
        """播放动画"""
        movie = self.movies.get(anim_type)
        if not movie:
            return
        
        if self.current_movie == movie and movie.isRunning():
            return
        
        # 停止当前
        if self.current_movie:
            self.current_movie.stop()
            try:
                self.current_movie.frameChanged.disconnect(self._on_frame)
                self.current_movie.finished.disconnect(self._on_finished)
            except:
                pass
        
        self.current_movie = movie
        self.current_type = anim_type
        movie.frameChanged.connect(self._on_frame)
        movie.finished.connect(self._on_finished)
        movie.start()
    
    def trigger_animation(self, anim_name: str, play_once: bool = False):
        """
        外部触发动画（AI -> UI 接口）
        
        Args:
            anim_name: 动画名称 ('walk', 'stand', 'fly', 'touch', 'happy', ...)
            play_once: 是否只播放一次
        """
        self.signals.play_animation.emit(anim_name, play_once)
    
    def _on_play_from_external(self, anim_name: str, play_once: bool):
        """处理外部触发"""
        anim_map = {
            'walk': AnimationType.WALK,
            'stand': AnimationType.STAND,
            'idle': AnimationType.STAND,
            'fly': AnimationType.FLY,
            'touch': AnimationType.TOUCH,
            'happy': AnimationType.TOUCH,  # happy 映射到 touch 动画
        }
        
        anim_type = anim_map.get(anim_name)
        if not anim_type:
            print(f'[Pet] Unknown animation: {anim_name}')
            return
        
        if play_once:
            self.play_once(anim_type)
        else:
            self.play(anim_type)
    
    def play_once(self, anim_type):
        """播放一次动画然后回到之前的状态"""
        prev_type = self.current_type
        
        movie = self.movies.get(anim_type)
        if not movie:
            return
        
        if self.current_movie:
            self.current_movie.stop()
            try:
                self.current_movie.frameChanged.disconnect(self._on_frame)
                self.current_movie.finished.disconnect()
            except:
                pass
        
        self.current_movie = movie
        self.current_type = anim_type
        movie.frameChanged.connect(self._on_frame)
        movie.finished.connect(lambda: self._on_once_finished(prev_type))
        movie.start()
    
    def _on_once_finished(self, prev_type):
        """单次播放完成"""
        self.signals.on_animation_end.emit(self.current_type.value if self.current_type else '')
        # 回到之前状态
        if prev_type and prev_type != self.current_type:
            self.play(prev_type)
    
    def play_touch(self):
        """播放 touch 并在结束后判断状态"""
        movie = self.movies[AnimationType.TOUCH]
        
        # 先停止
        if self.current_movie:
            self.current_movie.stop()
            try:
                self.current_movie.frameChanged.disconnect(self._on_frame)
                self.current_movie.finished.disconnect()
            except:
                pass
        
        self.current_movie = movie
        self.current_type = AnimationType.TOUCH
        movie.frameChanged.connect(self._on_frame)
        movie.finished.connect(self._on_touch_finished)
        movie.start()
        
        # 4340ms 后结束
        QTimer.singleShot(4340, self._finish_touch)
    
    def _finish_touch(self):
        """touch 动画结束"""
        if self.current_type == AnimationType.TOUCH:
            self.current_movie.stop()
            try:
                self.current_movie.frameChanged.disconnect(self._on_frame)
                self.current_movie.finished.disconnect(self._on_touch_finished)
            except:
                pass
            self.current_movie = None
            self.current_type = None
        
        # 判断：鼠标在身上 -> stand，不在 -> walk
        if self.is_hovering:
            self.play(AnimationType.STAND)
        else:
            self.play(AnimationType.WALK)
    
    def _on_touch_finished(self):
        pass
    
    def _on_finished(self):
        pass
    
    def _on_frame(self, frame):
        """更新显示"""
        pixmap = self.current_movie.currentPixmap()
        if not pixmap.isNull():
            if self.facing_right:
                pixmap = pixmap.transformed(QTransform().scale(-1, 1))
            scaled = pixmap.scaledToHeight(self.display_height, Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(scaled)
            new_size = scaled.size()
            if self.size() != new_size:
                self.resize(new_size)
    
    def move_step(self):
        """移动"""
        if self.is_dragging or self.is_hovering:
            return
        if self.current_type in (AnimationType.TOUCH, AnimationType.FLY):
            return
        
        # 随机改方向
        if random.random() < 0.005:
            self.direction *= -1
        if random.random() < 0.003:
            self.y_direction *= -1
        
        new_facing = self.direction > 0
        if new_facing != self.facing_right:
            self.facing_right = new_facing
        
        x = self.x() + self.direction * self.move_speed
        y = self.y() + self.y_direction * self.move_y_speed
        
        if x <= 0:
            self.direction = 1
            self.facing_right = True
        elif x + self.width() >= self.screen.width():
            self.direction = -1
            self.facing_right = False
        
        if y <= 0:
            self.y_direction = 1
        elif y + self.height() >= self.screen.height():
            self.y_direction = -1
        
        self.move(x, y)
    
    # 鼠标事件
    def enterEvent(self, event):
        self.is_hovering = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.signals.on_hover_enter.emit()
        if self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
            self.play(AnimationType.STAND)
    
    def leaveEvent(self, event):
        self.is_hovering = False
        self.unsetCursor()
        self.signals.on_hover_leave.emit()
        if self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
            self.play(AnimationType.WALK)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.click_start_pos = event.globalPosition().toPoint()
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.is_clicking = True
            self.is_dragging = False
            self.last_mouse_x = event.globalPosition().x()
    
    def mouseMoveEvent(self, event):
        if self.is_clicking and not self.is_dragging:
            pos = event.globalPosition().toPoint()
            dist = (pos - self.click_start_pos).manhattanLength()
            if dist > self.drag_threshold:
                self.is_dragging = True
                self.is_clicking = False
                self.play(AnimationType.FLY)
                self.signals.on_drag_start.emit()
        
        if self.is_dragging:
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            
            current_x = event.globalPosition().x()
            if current_x != self.last_mouse_x:
                self.facing_right = current_x > self.last_mouse_x
                self.last_mouse_x = current_x
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_dragging:
                self.is_dragging = False
                self.drag_offset = None
                self.signals.on_drag_end.emit()
                if self.is_hovering:
                    self.play(AnimationType.STAND)
                else:
                    self.play(AnimationType.WALK)
            elif self.is_clicking:
                self.is_clicking = False
                self.signals.on_click.emit()
                self.play_touch()
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        exit_act = QAction('退出', self)
        exit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_act)
        menu.exec(event.globalPos())


def run():
    app = QApplication(sys.argv)
    pet = NuanbaoPet()
    pet.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    run()
