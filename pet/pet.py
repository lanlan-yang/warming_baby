"""
可爱暖宝宝桌面宠物 - 基于事件总线
"""
import os
import sys
import random
import objc

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect
from PyQt6.QtGui import QTransform, QMovie
from PyQt6.QtWidgets import QLabel, QMenu, QApplication
from PyQt6.QtGui import QAction
from core.logger import setup_logger

logger = setup_logger()

from core import (
    AnimationType, AnimationRegistry, PetState,
    event_bus, EventCategory,
    UIEvent, PetEvent, AgentEvent,
    get_default_font, shutdown_event
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
        
        # 窗口设置 - 不用 WindowFlags，全部用 AppKit 控制
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)  # 只保留无边框
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)  # 确保鼠标事件正常
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # 允许焦点以便处理焦点事件
        
        # 路径
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 加载所有动画 (统一来源: AnimationRegistry)
        self.movies = {
            anim_type: QMovie(file_path)
            for anim_type, file_path in AnimationRegistry.generate_movies_dict(base_dir).items()
        }
        
        # 注意：QMovie 没有 setLoopCount 方法，需要在播放时手动检测完成
        # loopCount 默认 -1（无限循环），需要用帧计数检测完成
        
        # 用于减少闪烁的最后一个有效 pixmap
        self._last_valid_pixmap = None
        
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
        self._waiting_llm = False  # 是否等待 LLM 响应（期间保持 confused）
        self._is_exiting = False  # 是否正在退出
        
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
        
        # 订阅动画请求事件 (来自 LLM 工具调用)
        event_bus.subscribe(EventCategory.PET, PetEvent.ANIMATION_REQUEST, self._on_animation_request)
        
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
        bubble_visible = self.bubble and self.bubble.isVisible()
        panel_visible = self.input_panel and self.input_panel.isVisible()
        
        if not bubble_visible and not panel_visible:
            return
        
        pet_pos = self.frameGeometry().topLeft()
        pet_width = self.width()
        
        # 输入框位置: 宠物头顶上方，水平居中
        if panel_visible:
            input_x = pet_pos.x() + (pet_width - self.input_panel.width()) // 2
            input_y = pet_pos.y() - self.input_panel.height() - self.chat_cfg.bubble_offset_y
            
            input_x = max(0, min(input_x, self.screen.width() - self.input_panel.width()))
            input_y = max(0, input_y)
            
            self.input_panel.move(input_x, input_y)
        
        # 气泡在输入框上方
        if bubble_visible:
            base_y = input_y if panel_visible else pet_pos.y() - self.chat_cfg.bubble_offset_y
            bubble_x = pet_pos.x() + (pet_width - self.bubble.width()) // 2
            bubble_y = base_y - self.bubble.height() - self.chat_cfg.input_offset_y
            
            bubble_x = max(0, min(bubble_x, self.screen.width() - self.bubble.width()))
            bubble_y = max(0, bubble_y)
            
            self.bubble.move(bubble_x, bubble_y)
    
    def show_chat_ui(self):
        """显示聊天界面 (只显示输入框)"""
        self._init_chat_ui()
        self.is_chatting = True
        self._waiting_llm = True  # 进入等待 LLM 状态，confused 不可被覆盖
        
        # 播放思考动画
        self.play(AnimationType.CONFUSED)
        
        # 只显示输入框，不显示气泡
        self.input_panel.show_panel()
        
        # 启动定时检查 - 如果应用失去焦点则关闭
        self._focus_check_timer = QTimer(self)
        self._focus_check_timer.timeout.connect(self._check_app_focus)
        self._focus_check_timer.start(500)  # 每 500ms 检查一次
        
        # 更新位置
        self._update_chat_position()
    
    def hide_chat_ui(self):
        """隐藏聊天界面"""
        self.is_chatting = False
        self._waiting_llm = False
        
        # 停止焦点检查定时器
        if hasattr(self, '_focus_check_timer'):
            self._focus_check_timer.stop()
        
        if self.bubble:
            self.bubble.hide_bubble()
        if self.input_panel:
            self.input_panel.hide_panel()
        
        # 退出时不播放其他动画
        if self._is_exiting:
            return
        
        # 根据是否悬停播放不同动画
        if self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
            if self.is_hovering:
                self.play(AnimationType.STAND)  # 鼠标在上方，播放站立
            else:
                self.play(AnimationType.WALK)   # 否则播放走动
    
    def _check_app_focus(self):
        """
        检查应用是否失去焦点
        
        如果应用不是活动状态，则自动关闭对话
        """
        if not self.is_chatting:
            return
        
        # 检查应用是否有活动窗口
        app = QApplication.instance()
        active_window = app.activeWindow()
        focused_widget = app.focusWidget()
        
        # 如果既没有活动窗口，也没有焦点控件，说明应用失去了焦点
        if active_window is None and focused_widget is None:
            self.hide_chat_ui()
    
    def show_message(self, text: str, auto_hide: bool = True, duration: int = None):
        """
        显示消息气泡
        
        Args:
            text: 消息内容
            auto_hide: 是否自动隐藏
            duration: 自动隐藏时间 (毫秒)，None 则使用配置默认值
            
        Note:
            气泡消失后会自动停止对话相关的动画，回到默认状态
        """
        self._init_chat_ui()
        self.is_chatting = True  # 有气泡时保持静止
        
        # 设置气泡消失后的回调 - 恢复默认动画
        self.bubble.set_on_hidden_callback(self._on_bubble_hidden)
        
        self.bubble.show_message(
            text, 
            auto_hide=auto_hide, 
            duration=duration or self.chat_cfg.default_auto_hide_duration
        )
        self._update_chat_position()
    
    def show_typing(self):
        """显示正在输入状态"""
        self._init_chat_ui()
        self.is_chatting = True  # 等待LLM时保持静止
        # 清除之前的回调
        self.bubble.set_on_hidden_callback(None)
        self.bubble.show_typing(auto_hide=False)
        self._update_chat_position()
    
    def _on_bubble_hidden(self):
        """
        气泡隐藏回调
        
        当对话气泡完全消失时，将动画恢复为默认的 WALK 状态
        （仅当当前是对话相关的动画时）
        """
        logger.info("[Pet] Bubble hidden, restoring default animation")
        
        # 只有当没有其他聊天UI显示时才重置
        if not self.input_panel or not self.input_panel.isVisible():
            self.is_chatting = False
            self._waiting_llm = False
        
        # 对话期间使用的动画类型
        chat_animations = {
            AnimationType.HAPPY,
            AnimationType.ANGRY,
            AnimationType.CONFUSED,
            AnimationType.SLEEP,
            AnimationType.PLAYING,
        }
        
        # 如果当前是对话动画，恢复为 WALK
        if self.current_type in chat_animations:
            self.play(AnimationType.WALK)
            logger.info(f"[Pet] Restored to WALK (was {self.current_type})")
    
    def _force_stop_animation(self):
        """强制停止当前动画（回到 WALK）"""
        self.play(AnimationType.WALK)
    
    def _on_user_input(self, text: str):
        """
        用户发送消息
        
        Args:
            text: 用户输入的文本
        """
        logger.info(f"[User] 发送: {text}")
        
        # 隐藏输入框
        if self.input_panel:
            self.input_panel.hide_panel()
        
        # 显示正在输入
        self.show_typing()
        
        # 发布事件给 Agent
        event_bus.publish(EventCategory.AGENT, AgentEvent.USER_MESSAGE, message=text)
    
    def _on_agent_response(self, response: dict):
        """Agent 响应回调（可能来自非 Qt 线程，需安全转发）"""
        # QTimer.singleShot(0, receiver) 会将回调 post 到 receiver 所在线程（Qt 主线程）
        QTimer.singleShot(0, lambda: self._handle_agent_response(response))

    def _handle_agent_response(self, response: dict):
        """实际处理 Agent 响应（在 Qt 主线程执行）"""
        text = response.get('text', '')
        emotion = response.get('emotion', '')
        play_once = response.get('play_once', True)

        # LLM 已返回，清除等待状态，允许切换动画
        self._waiting_llm = False

        # 显示消息气泡
        if text:
            self.show_message(text, auto_hide=True, duration=3000)

        # 播放对应动画
        if emotion:
            self.trigger_animation(emotion, play_once)

    def _on_agent_thinking(self, data: dict = None):
        """Agent 思考回调（可能来自非 Qt 线程）"""
        QTimer.singleShot(0, self._handle_agent_thinking)

    def _handle_agent_thinking(self):
        """实际处理思考状态（在 Qt 主线程执行）"""
        self.play(AnimationType.CONFUSED)

    def _on_animation_request(self, animation: str, play_once: bool = False, **kwargs):
        """
        处理来自 LLM 工具的动画请求

        可能来自非 Qt 线程，需安全转发到主线程

        Args:
            animation: 动画名称或别名
            play_once: 是否单次播放
        """
        QTimer.singleShot(0, lambda: self.trigger_animation(animation, play_once))
    
    # ==================== 动画控制 ====================
    
    def play(self, anim_type, play_once: bool = False):
        """
        播放动画
        
        Args:
            anim_type: 动画类型
            play_once: 是否只播放一次（不循环）
        """
        # 退出时只允许 LEAVE 动画
        if self._is_exiting and anim_type != AnimationType.LEAVE:
            return
            
        movie = self.movies.get(anim_type)
        if not movie:
            return
        
        if self.current_movie == movie and movie.state() == QMovie.MovieState.Running:
            return

        # LLM 等待期间保护 CONFUSED 状态，防止被意外覆盖
        if (self._waiting_llm and self.current_type == AnimationType.CONFUSED 
            and anim_type != AnimationType.CONFUSED):
            print(f"[Pet] play blocked: waiting for LLM, keep confused (skip {anim_type})")
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
        
        # 断开之前的 frameChanged 连接
        try:
            movie.frameChanged.disconnect()
        except:
            pass
        
        if play_once:
            # 单次播放 - 检测最后一帧
            movie.frameChanged.connect(lambda frame: self._on_frame_once(frame, movie, anim_type))
        else:
            # 循环播放
            movie.frameChanged.connect(self._on_frame)
        
        movie.start()
        
        # 发布动画开始事件
        event_bus.publish(EventCategory.PET, PetEvent.ANIMATION_START, anim_type.value)
    
    def _on_frame_once(self, frame, movie, anim_type):
        """单次播放的帧处理 - 到达最后一帧时停止"""
        self._on_frame(frame)
        
        # 检测是否到达最后一帧
        if frame == movie.frameCount() - 1:
            movie.stop()
            print(f"[Pet] Animation finished: {anim_type}")
            # 动画完成后的回调可以在这里添加
    
    def trigger_animation(self, anim_name: str, play_once: bool = False):
        """
        外部触发动画

        Args:
            anim_name: 动画名称或别名 (walk, stand, fly, touch, happy, idle, ...)
            play_once: 是否只播放一次 (False 则循环播放)

        Note:
            动画名称解析统一由 AnimationRegistry 处理
            如果配置了 play_once=True，会自动覆盖参数
        """
        # 从注册表解析动画
        anim_type = AnimationRegistry.resolve(anim_name)
        if not anim_type:
            logger.warning(f"[Pet] Unknown animation: {anim_name}")
            return

        # 如果配置了默认单次播放 (如 touch/happy)，覆盖参数
        if AnimationRegistry.should_play_once(anim_type):
            play_once = True

        # 如果已经在播放该动画，跳过
        if (self.current_type == anim_type 
            and self.current_movie 
            and self.current_movie.state() == QMovie.MovieState.Running):
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

        # LLM 等待期间保护 CONFUSED 状态
        if (self._waiting_llm and self.current_type == AnimationType.CONFUSED 
            and anim_type != AnimationType.CONFUSED):
            print(f"[Pet] play_once blocked: waiting for LLM, keep confused (skip {anim_type})")
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
        # 回到之前状态，但 confused 是临时状态，不应恢复
        if prev_type and prev_type != self.current_type:
            if prev_type == AnimationType.CONFUSED:
                if self.is_hovering:
                    self.play(AnimationType.STAND)
                else:
                    self.play(AnimationType.WALK)
            else:
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
        
        # 使用 AnimationRegistry 的统一配置
        duration = AnimationRegistry.get_duration(AnimationType.TOUCH)
        self.touch_timer.start(duration)
    
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
        if self.current_type == AnimationType.LEAVE:
            print(f">>> LEAVE frame {frame}/{self.current_movie.frameCount()}")
        
        pixmap = self.current_movie.currentPixmap()
        
        # 如果当前帧无效，使用上一个有效帧减少闪烁
        if pixmap.isNull():
            if self._last_valid_pixmap is not None:
                self.setPixmap(self._last_valid_pixmap)
            return
        
        # 保存有效 pixmap
        self._last_valid_pixmap = pixmap.copy()
        
        # 应用翻转
        if self.facing_right:
            pixmap = pixmap.transformed(QTransform().scale(-1, 1))
        
        # 缩放
        scaled = pixmap.scaledToHeight(self.display_height, Qt.TransformationMode.SmoothTransformation)
        
        # 设置 pixmap
        self.setPixmap(scaled)
        
        # 只在尺寸变化时调整窗口大小（减少 resize 导致的闪烁）
        new_size = scaled.size()
        if self.size() != new_size:
            self.resize(new_size)
        
        # 更新聊天组件位置
        self._update_chat_position()
    
    def move_step(self):
        """移动"""
        # 退出时不移动
        if self._is_exiting:
            return
            
        # 主动检测鼠标是否在宠物范围内（解决失焦时enterEvent不触发的问题）
        self._check_mouse_hover()
        
        if self.is_dragging or self.is_hovering:
            return
        if self.current_type in (AnimationType.TOUCH, AnimationType.FLY, AnimationType.LEAVE):
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
    
    def _check_mouse_hover(self):
        """
        主动检测鼠标是否在宠物范围内
        
        解决应用失焦时 enterEvent/leaveEvent 不触发的问题
        """
        # 退出时不检测鼠标
        if self._is_exiting:
            return
            
        from PyQt6.QtGui import QCursor
        
        # 获取鼠标全局位置
        mouse_pos = QCursor.pos()
        
        # 获取宠物的全局矩形
        pet_rect = self.geometry()
        pet_top_left = self.mapToGlobal(QPoint(0, 0))
        pet_global_rect = QRect(pet_top_left, pet_rect.size())
        
        # 检查鼠标是否在宠物范围内
        mouse_in_pet = pet_global_rect.contains(mouse_pos)
        
        # 根据状态变化更新
        if mouse_in_pet and not self.is_hovering:
            # 鼠标进入
            self.is_hovering = True
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            event_bus.publish(EventCategory.UI, UIEvent.MOUSE_HOVER_ENTER)
            if not self.is_chatting and self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
                self.play(AnimationType.STAND)
        elif not mouse_in_pet and self.is_hovering:
            # 鼠标离开
            self.is_hovering = False
            self.unsetCursor()
            event_bus.publish(EventCategory.UI, UIEvent.MOUSE_HOVER_LEAVE)
            if not self.is_chatting and self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
                self.play(AnimationType.WALK)
    
    def enterEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
            
        self.is_hovering = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 发布 UI 事件
        event_bus.publish(EventCategory.UI, UIEvent.MOUSE_HOVER_ENTER)
        if self.is_chatting:
            return
        if self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
            self.play(AnimationType.STAND)
    
    def leaveEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
            
        self.is_hovering = False
        self.unsetCursor()
        # 发布 UI 事件
        event_bus.publish(EventCategory.UI, UIEvent.MOUSE_HOVER_LEAVE)
        if self.is_chatting:
            return
        if self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
            self.play(AnimationType.WALK)
    
    def mousePressEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
            
        if event.button() == Qt.MouseButton.LeftButton:
            self.click_start_pos = event.globalPosition().toPoint()
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.is_clicking = True
            self.is_dragging = False
            self.last_mouse_x = event.globalPosition().x()
    
    def mouseMoveEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
            
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
        # 退出时不响应
        if self._is_exiting:
            return
            
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
                
                # 显示聊天 UI（内部播放 confused 动画）
                self.show_chat_ui()
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        exit_act = QAction('退出', self)
        exit_act.triggered.connect(self._exit_with_animation)
        menu.addAction(exit_act)
        menu.exec(event.globalPos())
    
    def _exit_with_animation(self):
        """先播放 LEAVE 动画，完成后退出"""
        print(">>> _exit_with_animation called")
        self._is_exiting = True  # 设置退出标志，阻止其他动画
        
        try:
            # 停止所有定时器
            self.move_timer.stop()
            self.touch_timer.stop()
            if hasattr(self, '_topmost_timer'):
                self._topmost_timer.stop()
            if hasattr(self, '_focus_check_timer'):
                self._focus_check_timer.stop()
            
            # 先保存当前 pixmap，确保过渡平滑
            if self.current_movie:
                current_pixmap = self.current_movie.currentPixmap()
                if not current_pixmap.isNull():
                    self._last_valid_pixmap = current_pixmap.copy()
            
            # 直接隐藏对话 UI，不触发动画
            self.is_chatting = False
            self._waiting_llm = False
            if self.bubble:
                self.bubble.hide_bubble()
            if self.input_panel:
                self.input_panel.hide_panel()
            
            # 检查 LEAVE 动画
            leave_movie = self.movies.get(AnimationType.LEAVE)
            
            if leave_movie and leave_movie.isValid() and leave_movie.frameCount() > 0:
                print(f">>> Playing LEAVE, frames: {leave_movie.frameCount()}")
                
                # 停止当前动画（但保持最后的 pixmap 显示）
                if self.current_movie:
                    self.current_movie.stop()
                    try:
                        self.current_movie.finished.disconnect()
                    except:
                        pass
                    try:
                        self.current_movie.frameChanged.disconnect()
                    except:
                        pass
                
                self.current_movie = leave_movie
                self.current_type = AnimationType.LEAVE
                
                # 断开旧连接
                try:
                    leave_movie.frameChanged.disconnect()
                except:
                    pass
                try:
                    leave_movie.finished.disconnect()
                except:
                    pass
                
                # 连接帧显示
                leave_movie.frameChanged.connect(self._on_frame)
                
                # 记录第一次循环的帧计数，防止 QMovie 循环导致的问题
                first_loop_done = [False]
                total_frames = leave_movie.frameCount()
                
                def check_leave_finished(frame):
                    # 只在第一次循环结束时触发
                    if not first_loop_done[0] and frame >= total_frames - 1:
                        first_loop_done[0] = True
                        print(f">>> LEAVE animation completed (frame {frame}/{total_frames - 1})")
                        leave_movie.stop()
                        # 延迟一点时间让最后一帧显示，避免瞬间消失
                        QTimer.singleShot(200, self._do_exit)
                
                leave_movie.frameChanged.connect(check_leave_finished)
                
                # 直接开始，不用延迟
                leave_movie.start()
                print(f">>> After start, state: {leave_movie.state()}")
                print(f">>> Total frames to play: {total_frames}")
                
                # 确保窗口在退出期间保持可见
                self.show()
                self.raise_()
            else:
                print(">>> No valid LEAVE animation, exiting now")
                self._do_exit()
        except Exception as e:
            print(f">>> ERROR in _exit_with_animation: {e}")
            import traceback
            traceback.print_exc()
            self._do_exit()
    
    def _do_exit(self):
        """执行退出"""
        print(">>> _do_exit called")
        
        # 确保窗口在退出前保持稳定状态
        try:
            # 停止所有剩余的定时器
            self.move_timer.stop()
            self.touch_timer.stop()
            if hasattr(self, '_topmost_timer'):
                self._topmost_timer.stop()
            if hasattr(self, '_focus_check_timer'):
                self._focus_check_timer.stop()
            
            # 停止动画
            if self.current_movie:
                self.current_movie.stop()
        except Exception as e:
            print(f">>> Cleanup error: {e}")
        
        # 先设置 shutdown_event，让 main() 能够优雅退出
        try:
            if not shutdown_event.is_set():
                shutdown_event.set()
                print(">>> shutdown_event set")
        except Exception as e:
            print(f">>> shutdown_event error: {e}")
        
        # 退出应用
        print(">>> Calling QApplication.quit()")
        QApplication.quit()
    
    def showEvent(self, event):
        """显示事件"""
        super().showEvent(event)
        if sys.platform == 'darwin':
            # 延迟调用，确保 Qt 窗口已创建
            QTimer.singleShot(10, self._apply_topmost_native)
            QTimer.singleShot(100, self._apply_topmost_native)
            QTimer.singleShot(500, self._apply_topmost_native)
    
    def _apply_topmost_native(self):
        """使用原生 AppKit 设置窗口置顶 - 已验证可行"""
        try:
            from AppKit import (
                NSStatusWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary,
            )
            
            win_id = int(self.winId())
#             print(f"[Topmost] winId: {win_id}")
            
            if not win_id:
#                 print("[Topmost] winId 无效")
                return
            
            ns_view = objc.objc_object(c_void_p=win_id)
            ns_window = ns_view.window()
#             print(f"[Topmost] ns_window: {ns_window}")
            
            if ns_window is None:
#                 print("[Topmost] ns_window 为 None")
                return
            
            # 检查当前 level
            current_level = ns_window.level()
#             print(f"[Topmost] 当前 level: {current_level}")
            
            # 关键：设置最高层级
            ns_window.setLevel_(NSStatusWindowLevel)
            new_level = ns_window.level()
#             print(f"[Topmost] 设置后 level: {new_level}")
            
            # 跨 Space 显示
            ns_window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces | 
                NSWindowCollectionBehaviorStationary
            )
            
            # 关键：强制置顶显示（不激活应用）
            ns_window.orderFrontRegardless()
#             print("[Topmost] orderFrontRegardless 已调用")
            
            # 保存引用，用于后续刷新
            self._ns_window_ref = ns_window
            self._ns_level = NSStatusWindowLevel
            
#             print("[Topmost] ✓ 原生置顶设置成功")
            
            # 定时刷新 level（用 QTimer，更安全）
            if not hasattr(self, '_topmost_timer'):
                self._topmost_timer = QTimer(self)
                self._topmost_timer.timeout.connect(self._refresh_topmost)
                self._topmost_timer.start(200)  # 每 200ms 刷新
#                 print(f"[Topmost] 定时器已启动，间隔 200ms")
                
        except Exception as e:
#             print(f"[Topmost] 设置失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _refresh_topmost(self):
        """定期刷新窗口层级"""
        if hasattr(self, '_ns_window_ref') and self._ns_window_ref:
            try:
                self._ns_window_ref.setLevel_(self._ns_level)
                self._ns_window_ref.orderFrontRegardless()
#                 print(f"[Topmost] 刷新完成 - 当前 level: {self._ns_window_ref.level()}")
            except Exception:
                pass
        else:
            pass
    
    def focusOutEvent(self, event):
        """焦点处理 - 暂时禁用"""
        super().focusOutEvent(event)
        # TODO: 后续添加合适的焦点处理逻辑
    
    def closeEvent(self, event):
        """关闭事件"""
        # 如果还没有触发退出流程，触发完整的退出动画
        if not self._is_exiting:
            print(">>> closeEvent: triggering animated exit")
            self._exit_with_animation()
            event.ignore()  # 阻止默认关闭，让我们的流程处理
            return
        
        super().closeEvent(event)


def init_pet():
    """初始化宠物 GUI（返回 app 和 pet，供外部事件循环使用）"""
    app = QApplication(sys.argv)
    app.setFont(get_default_font(10))
    event_bus.publish(EventCategory.SYSTEM, 'app_started')
    pet = NuanbaoPet()
    pet.show()
    return app, pet


def run():
    """独立启动宠物（用于测试）"""
    app, pet = init_pet()
    sys.exit(app.exec())


if __name__ == '__main__':
    run()
