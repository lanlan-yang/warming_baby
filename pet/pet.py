"""
可爱暖宝宝桌面宠物 - 基于事件总线
"""
import os
import sys
import random

from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QTransform, QMovie
from PyQt6.QtWidgets import QLabel, QMenu, QApplication
from PyQt6.QtGui import QAction

from core import (
    AnimationType, PetState,
    event_bus, EventCategory,
    UIEvent, PetEvent, AgentEvent,
    get_default_font
)
from config import settings

from .bubble import SpeechBubble
from .input_panel import InputPanel


class NuanbaoPet(QLabel):
    """
    宠物UI组件
    
    事件发布:
    - UIEvent.MOUSE_CLICK: 鼠标点击
    - UIEvent.MOUSE_DRAG_START: 开始拖拽
    - UIEvent.MOUSE_DRAG_END: 结束拖拽
    - UIEvent.MOUSE_HOVER_ENTER: 鼠标进入
    - UIEvent.MOUSE_HOVER_LEAVE: 鼠标离开
    - PetEvent.ANIMATION_START: 动画开始
    - PetEvent.ANIMATION_END: 动画结束
    - PetEvent.ANIMATION_CHANGED: 动画切换
    - PetEvent.DIRECTION_CHANGED: 朝向变化
    
    UI组件:
    - SpeechBubble: 对话气泡 (头顶)
    - InputPanel: 输入框 (气泡下方)
    """
    
    def __init__(self):
        super().__init__()
        
        # 加载配置
        self.pet_cfg = settings.pet
        self.chat_cfg = settings.chat
        
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
        self.drag_threshold = self.pet_cfg.drag_threshold
        self.is_hovering = False
        self.last_mouse_x = 0
        self.facing_right = True
        self.display_height = self.pet_cfg.display_height
        
        # 移动设置
        self.direction = random.choice([-1, 1])
        self.y_direction = random.choice([-1, 1])
        self.move_speed = self.pet_cfg.move_speed
        self.move_y_speed = self.pet_cfg.move_y_speed
        self.screen = QApplication.primaryScreen().availableGeometry()
        
        # 聊天 UI 组件
        self.bubble = None
        self.input_panel = None
        self.is_chatting = False  # 是否在聊天中
        
        # 定时器
        self.move_timer = QTimer(self)
        self.move_timer.timeout.connect(self.move_step)
        self.move_timer.start(30)
        
        # touch 定时器 (用于管理 touch 动画时长)
        self.touch_timer = QTimer(self)
        self.touch_timer.setSingleShot(True)
        self.touch_timer.timeout.connect(self._finish_touch)
        
        # 订阅外部事件 (AI -> UI)
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.RESPONSE, self._on_agent_response)
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.THINKING, self._on_agent_thinking)
        
        # 发布启动事件
        event_bus.publish(EventCategory.SYSTEM, 'pet_started')
        
        # 开始走路
        self.play(AnimationType.WALK)
    
    def _init_chat_ui(self):
        """初始化聊天 UI (延迟创建)"""
        if self.bubble is None:
            self.bubble = SpeechBubble()
        if self.input_panel is None:
            self.input_panel = InputPanel()
            self.input_panel.send_requested.connect(self._on_user_input)
    
    def _update_chat_position(self):
        """更新聊天组件位置，使其跟随宠物"""
        if self.bubble is None or not self.bubble.isVisible():
            return
        
        pet_pos = self.frameGeometry().topLeft()
        pet_width = self.width()
        
        # 气泡位置: 宠物上方，水平居中
        bubble_width = self.bubble.width()
        bubble_x = pet_pos.x() + (pet_width - bubble_width) // 2
        bubble_y = pet_pos.y() - self.bubble.height() - self.chat_cfg.bubble_offset_y
        
        # 边界检查
        bubble_x = max(0, min(bubble_x, self.screen.width() - bubble_width))
        bubble_y = max(0, bubble_y)
        
        self.bubble.move(bubble_x, bubble_y)
        
        # 输入框位置: 气泡下方
        if self.input_panel and self.input_panel.isVisible():
            input_x = pet_pos.x() + (pet_width - self.input_panel.width()) // 2
            input_y = bubble_y + self.bubble.height() + self.chat_cfg.input_offset_y
            
            # 边界检查
            input_x = max(0, min(input_x, self.screen.width() - self.input_panel.width()))
            input_y = min(input_y, self.screen.height() - self.input_panel.height())
            
            self.input_panel.move(input_x, input_y)
    
    def show_chat_ui(self):
        """显示聊天界面 (气泡 + 输入框)"""
        self._init_chat_ui()
        self.is_chatting = True
        
        # 显示气泡引导语
        self.bubble.show_message("和我说话吧~", auto_hide=False)
        
        # 显示输入框
        self.input_panel.show_panel()
        
        # 更新位置
        self._update_chat_position()
    
    def hide_chat_ui(self):
        """隐藏聊天界面"""
        self.is_chatting = False
        if self.bubble:
            self.bubble.hide_bubble()
        if self.input_panel:
            self.input_panel.hide_panel()
    
    def show_message(self, text: str, auto_hide: bool = True, duration: int = None):
        """
        显示消息气泡
        
        Args:
            text: 消息内容
            auto_hide: 是否自动隐藏
            duration: 自动隐藏时间 (毫秒)，None 则使用配置默认值
        """
        self._init_chat_ui()
        self.bubble.show_message(
            text, 
            auto_hide=auto_hide, 
            duration=duration or self.chat_cfg.default_auto_hide_duration
        )
        self._update_chat_position()
    
    def show_typing(self):
        """显示正在输入状态"""
        self._init_chat_ui()
        self.bubble.show_typing(auto_hide=False)
        self._update_chat_position()
    
    def _on_user_input(self, text: str):
        """
        用户发送消息
        
        Args:
            text: 用户输入的文本
        """
        print(f"[User] 发送: {text}")
        
        # 隐藏输入框
        if self.input_panel:
            self.input_panel.hide_panel()
        
        # 显示正在输入
        self.show_typing()
        
        # 发布事件给 Agent
        event_bus.publish(EventCategory.AGENT, AgentEvent.USER_MESSAGE, message=text)
    
    def _on_agent_response(self, response: dict):
        """
        处理 Agent 响应
        
        Args:
            response: Agent 响应数据
                - text: 响应文本
                - emotion: 情感类型 (用于动画)
                - play_once: 是否只播放一次
        """
        text = response.get('text', '')
        emotion = response.get('emotion', '')
        play_once = response.get('play_once', True)
        
        # 显示消息气泡
        if text:
            self.show_message(text, auto_hide=True, duration=3000)
        
        # 播放对应动画
        if emotion:
            self.trigger_animation(emotion, play_once)
    
    def _on_agent_thinking(self, data: dict = None):
        """Agent 正在思考"""
        self.show_typing()
    
    # ==================== 动画控制 ====================
    
    def play(self, anim_type):
        """播放动画"""
        movie = self.movies.get(anim_type)
        if not movie:
            return
        
        if self.current_movie == movie and movie.state() == QMovie.MovieState.Running:
            return
        
        # 取消 touch 定时器 (关键！)
        self.touch_timer.stop()
        
        # 发布动画切换事件
        prev_type = self.current_type
        if prev_type and prev_type != anim_type:
            event_bus.publish(EventCategory.PET, PetEvent.ANIMATION_CHANGED, 
                            from_=prev_type.value, to=anim_type.value)
        
        # 停止当前并清理所有信号连接
        if self.current_movie:
            self.current_movie.stop()
            try:
                self.current_movie.frameChanged.disconnect()
                self.current_movie.finished.disconnect()
            except:
                pass
        
        self.current_movie = movie
        self.current_type = anim_type
        movie.frameChanged.connect(self._on_frame)
        movie.start()
        
        # 发布动画开始事件
        event_bus.publish(EventCategory.PET, PetEvent.ANIMATION_START, anim_type.value)
    
    def trigger_animation(self, anim_name: str, play_once: bool = False):
        """
        外部触发动画
        
        Args:
            anim_name: 动画名称 (walk, stand, fly, touch, happy, ...)
            play_once: 是否只播放一次
        """
        anim_map = {
            'walk': AnimationType.WALK,
            'stand': AnimationType.STAND,
            'idle': AnimationType.STAND,
            'fly': AnimationType.FLY,
            'touch': AnimationType.TOUCH,
            'happy': AnimationType.TOUCH,
        }
        
        anim_type = anim_map.get(anim_name)
        if not anim_type:
            print(f'[Pet] Unknown animation: {anim_name}')
            return
        
        # 如果已经在播放该动画，跳过
        if self.current_type == anim_type and self.current_movie and self.current_movie.state() == QMovie.MovieState.Running:
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
        
        # 发布动画开始事件
        event_bus.publish(EventCategory.PET, PetEvent.ANIMATION_START, anim_type.value)
    
    def _on_once_finished(self, prev_type):
        """单次播放完成"""
        event_bus.publish(EventCategory.PET, PetEvent.ANIMATION_END, 
                        self.current_type.value if self.current_type else '')
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
        movie.start()
        
        # 发布动画开始事件
        event_bus.publish(EventCategory.PET, PetEvent.ANIMATION_START, AnimationType.TOUCH.value)
        
        # 后结束 (使用统一的 touch_timer)
        self.touch_timer.start(self.pet_cfg.touch_duration)
    
    def _finish_touch(self):
        """touch 动画结束"""
        if self.current_type == AnimationType.TOUCH and self.current_movie:
            self.current_movie.stop()
            try:
                self.current_movie.frameChanged.disconnect()
                self.current_movie.finished.disconnect()
            except:
                pass
            self.current_movie = None
            self.current_type = None
            
            event_bus.publish(EventCategory.PET, PetEvent.ANIMATION_END, AnimationType.TOUCH.value)
            
            # 判断：鼠标在身上 -> stand，不在 -> walk
            if self.is_hovering:
                self.play(AnimationType.STAND)
            else:
                self.play(AnimationType.WALK)
    
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
        
        # 更新聊天组件位置
        self._update_chat_position()
    
    def move_step(self):
        """移动"""
        if self.is_dragging or self.is_hovering:
            return
        if self.current_type in (AnimationType.TOUCH, AnimationType.FLY):
            return
        # 聊天时也暂停移动
        if self.is_chatting:
            return
        
        # 随机改方向
        if random.random() < self.pet_cfg.walking_dir_change_prob:
            self.direction *= -1
        if random.random() < self.pet_cfg.walking_y_dir_change_prob:
            self.y_direction *= -1
        
        new_facing = self.direction > 0
        if new_facing != self.facing_right:
            self.facing_right = new_facing
            # 发布朝向变化事件
            event_bus.publish(EventCategory.PET, PetEvent.DIRECTION_CHANGED, 
                            facing_right=self.facing_right)
        
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
        # 更新聊天组件位置
        self._update_chat_position()
    
    # ==================== 鼠标事件 ====================
    
    def enterEvent(self, event):
        self.is_hovering = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 发布 UI 事件
        event_bus.publish(EventCategory.UI, UIEvent.MOUSE_HOVER_ENTER)
        if self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
            self.play(AnimationType.STAND)
    
    def leaveEvent(self, event):
        self.is_hovering = False
        self.unsetCursor()
        # 发布 UI 事件
        event_bus.publish(EventCategory.UI, UIEvent.MOUSE_HOVER_LEAVE)
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
                self.hide_chat_ui()  # 拖拽时隐藏聊天 UI
                self.play(AnimationType.FLY)
                # 发布 UI 事件
                event_bus.publish(EventCategory.UI, UIEvent.MOUSE_DRAG_START)
        
        if self.is_dragging:
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            # 发布拖拽移动事件
            event_bus.publish(EventCategory.UI, UIEvent.MOUSE_DRAG_MOVE, 
                            x=event.globalPosition().x(), 
                            y=event.globalPosition().y())
            
            current_x = event.globalPosition().x()
            if current_x != self.last_mouse_x:
                self.facing_right = current_x > self.last_mouse_x
                self.last_mouse_x = current_x
                # 发布朝向变化事件
                event_bus.publish(EventCategory.PET, PetEvent.DIRECTION_CHANGED, 
                                facing_right=self.facing_right)
            
            # 更新聊天组件位置
            self._update_chat_position()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_dragging:
                self.is_dragging = False
                self.drag_offset = None
                # 发布 UI 事件
                event_bus.publish(EventCategory.UI, UIEvent.MOUSE_DRAG_END)
                if self.is_hovering:
                    self.play(AnimationType.STAND)
                else:
                    self.play(AnimationType.WALK)
            elif self.is_clicking:
                self.is_clicking = False
                # 发布 UI 事件
                event_bus.publish(EventCategory.UI, UIEvent.MOUSE_CLICK, 
                                x=event.globalPosition().x(),
                                y=event.globalPosition().y())
                self.play_touch()
                
                # 显示聊天 UI
                self.show_chat_ui()
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        exit_act = QAction('退出', self)
        exit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_act)
        menu.exec(event.globalPos())


def run():
    app = QApplication(sys.argv)
    
    # 设置全局字体（避免字体警告）
    app.setFont(get_default_font(10))
    
    # 发布启动事件
    event_bus.publish(EventCategory.SYSTEM, 'app_started')
    
    pet = NuanbaoPet()
    pet.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    run()
