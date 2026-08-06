"""
可爱暖宝宝桌面宠物 - 基于事件总线
"""
import os
import sys
import random
import time

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QTransform, QMovie

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from version import __version__, __app_name__, __author__, __copyright__
from PyQt6.QtWidgets import QLabel, QMenu, QApplication
from PyQt6.QtGui import QAction
from core.logger import setup_logger

logger = setup_logger()

from core import (
    AnimationType, AnimationRegistry,
    event_bus, EventCategory,
    UIEvent, PetEvent, AgentEvent,
    get_default_font, shutdown_event
)
from settings import settings
from config import config_manager  # 导入配置管理器

from ui.widgets import SpeechBubble
from ui.widgets import InputPanel
from agent.chat.auto_speak import AutoSpeakManager, AutoSpeakPrompt
from agent.chat.chat_schema import Emotion
from core.topmost import set_window_topmost

# ============================================================================
# Emotion -> AnimationType 映射表
# ============================================================================
EMOTION_TO_ANIMATION = {
    Emotion.HAPPY: AnimationType.HAPPY,
    Emotion.ANGRY: AnimationType.ANGRY,
    Emotion.SAD: AnimationType.SAD,
    Emotion.CONFUSED: AnimationType.CONFUSED,
    Emotion.SLEEP: AnimationType.SLEEP,
    Emotion.PLAY: AnimationType.PLAYING,
    Emotion.EATING: AnimationType.EATING,
    Emotion.NEUTRAL: AnimationType.NEUTRAL,  # 正常说话时的动画
}

def emotion_to_animation(emotion) -> AnimationType:
    """将 Emotion 枚举转换为 AnimationType"""
    try:
        return EMOTION_TO_ANIMATION[emotion]
    except (KeyError, TypeError):
        logger.warning(f"[Pet] Unknown emotion '{emotion}', using STAND")
        return AnimationType.STAND


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
    
    信号:
    - _agent_response_received(dict): 用于跨线程传递 Agent 响应
    - _llm_config_error_received(dict): 用于跨线程传递 LLM 配置错误
    - _animation_request_received(dict): 用于跨线程传递动画请求
    """
    
    # 用于跨线程传递事件的信号
    _agent_response_received = pyqtSignal(dict)
    _llm_config_error_received = pyqtSignal(dict)
    _animation_request_received = pyqtSignal(dict)
    _agent_thinking_received = pyqtSignal()
    
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
        
        # 路径 (项目根目录)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
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
        self._is_warming_up = False  # 是否正在预热（启动时显示 SEARCHING 动画）
        
        # 睡眠相关状态
        self._is_sleeping = False  # 是否在睡眠中
        self._last_interaction_time = time.time()  # 最后互动时间戳
        self._prev_animation_before_sleep = None  # 睡眠前的动画（用于唤醒后恢复）
        self._pending_response_cancelled = False  # 待处理的响应是否已取消
        
        # 主动说话管理器 - 从配置读取间隔
        speak_interval_min = config_manager.get("behavior.auto_speak_interval_min", 5)
        speak_interval_sec = speak_interval_min * 60
        self.auto_speak_manager = AutoSpeakManager(
            min_interval=speak_interval_sec,
            max_interval=speak_interval_sec + 60,  # 最多多 60 秒随机
            enabled=config_manager.get("behavior.auto_speak_enabled", True),
        )
        
        # 定时器
        self.move_timer = QTimer(self)
        self.move_timer.timeout.connect(self.move_step)
        self.move_timer.start(30)
        
        # touch 定时器 (用于管理 touch 动画时长)
        self.touch_timer = QTimer(self)
        self.touch_timer.setSingleShot(True)
        self.touch_timer.timeout.connect(self._finish_touch)
        
        # 空闲检查定时器 - 定期检查是否应该进入睡眠
        self.idle_check_timer = QTimer(self)
        self.idle_check_timer.timeout.connect(self._check_idle)
        self.idle_check_timer.start(self.pet_cfg.idle_check_interval_ms)
        
        # 睡眠时间结束定时器 - 睡眠到时后唤醒
        self.sleep_end_timer = QTimer(self)
        self.sleep_end_timer.setSingleShot(True)
        self.sleep_end_timer.timeout.connect(self._wake_up)
        
        # 主动说话检查定时器 - 每 60 秒检查一次
        self.auto_speak_check_timer = QTimer(self)
        self.auto_speak_check_timer.timeout.connect(self._check_auto_speak)
        self.auto_speak_check_timer.start(60000)  # 60 秒
        logger.info(f"[Pet] Auto speak check timer started (interval=60s)")
        
        # 应用用户配置 & 注册监听器
        self._apply_user_config()
        config_manager.add_listener(self._on_config_changed)
        
        # 连接信号（跨线程通信）
        self._agent_response_received.connect(self._handle_agent_response)
        self._llm_config_error_received.connect(self._handle_llm_config_error)
        self._animation_request_received.connect(self._handle_animation_request)
        self._agent_thinking_received.connect(self._handle_agent_thinking)
        
        # 订阅外部事件 (AI -> UI)
        # 主要通过 RESPONSE 的 emotion 字段触发动画
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.RESPONSE, self._on_agent_response)
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.THINKING, self._on_agent_thinking)
        
        # 备用动画通道（预留用于其他模块触发动画）
        event_bus.subscribe(EventCategory.PET, PetEvent.ANIMATION_REQUEST, self._on_animation_request)
        
        # 订阅 LLM 配置错误事件
        from core import SystemEvent
        event_bus.subscribe(EventCategory.SYSTEM, SystemEvent.LLM_CONFIG_ERROR, self._on_llm_config_error)
        
        # 预创建聊天 UI 组件（避免第一次使用时的延迟）
        self._init_chat_ui()
        
        # 注意：不在此处播放 WALK 动画
        # 动画将由 start_warming_up() 控制，先显示 SEARCHING 等待
    
    # ========================================================================
    # 状态守卫函数 - 防止状态冲突
    # ========================================================================
    
    def can_show_bubble(self) -> bool:
        """检查是否可以显示气泡"""
        return not self._is_sleeping and not self._is_exiting and self.isVisible()
    
    def can_process_response(self) -> bool:
        """检查是否可以处理 LLM 响应"""
        return not self._is_sleeping and not self._is_exiting and not self._pending_response_cancelled
    
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

    # ========================================================================
    # 预热状态管理
    # ========================================================================
    
    def start_warming_up(self):
        """开始预热状态
        
        显示 SEARCHING 动画和"正在加载"提示
        在预热完成前，阻止某些操作（如移动、自动说话等）
        """
        self._is_warming_up = True
        
        # 播放 SEARCHING 动画
        self.play(AnimationType.SEARCHING)
        
        # 停止移动（预热时不动）
        self.move_timer.stop()
        
        # 显示可爱的加载提示
        self.show_message("正在加载中... 🔍", auto_hide=False)
        
        logger.info("[Pet] Started warming up")
    
    def finish_warming_up(self, success: bool = True):
        """预热完成
        
        Args:
            success: 预热是否成功
        """
        self._is_warming_up = False
        
        # 隐藏加载提示
        if self.bubble:
            self.bubble.hide_bubble()
        
        # 恢复移动
        self.move_timer.start(30)
        
        if success:
            # 预热成功 - 先设置 WALK 作为"目标状态"
            # 这样 HAPPY 动画结束后会自动恢复到 WALK
            self.play(AnimationType.WALK)
            
            # 显示欢迎语（和开心动画同时）
            self.show_message("嗨！我是暖宝 🐹\n有什么可以帮你的吗？", auto_hide=True, duration=3000)
            
            # 播放开心动画（单次播放，结束后自动回到 WALK）
            self.play_once(AnimationType.HAPPY)
        else:
            # 预热失败 - 显示提示
            self.show_message("加载有点慢...\n不过我还能陪你聊天哦 😊", auto_hide=True, duration=3000)
            self.play(AnimationType.STAND)
        
        logger.info(f"[Pet] Warm up finished (success={success}, type={self.current_type}, chatting={self.is_chatting})")
    
    @property
    def is_warming_up(self) -> bool:
        """是否正在预热"""
        return getattr(self, '_is_warming_up', False)
    
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
        
        # 检查是否正在播放单次动画（如 EATING, HAPPY 等）
        if self.current_type and AnimationRegistry.should_play_once(self.current_type):
            logger.info(f"[Pet] skip changing animation in hide_chat_ui, current: {self.current_type}")
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
        
        只有在输入框可见时才检查焦点，因为：
        - 输入框需要用户交互，失去焦点意味着用户可能不想输入了
        - 自动说话时只有气泡，不需要焦点，不应该被隐藏
        """
        if not self.is_chatting:
            return
        
        # 如果输入框不可见，说明只是在显示气泡（如自动说话），不需要检查焦点
        if not self.input_panel or not self.input_panel.isVisible():
            return
        
        # 检查应用是否有活动窗口
        app = QApplication.instance()
        active_window = app.activeWindow()
        focused_widget = app.focusWidget()
        
        # 如果既没有活动窗口，也没有焦点控件，说明应用失去了焦点
        if active_window is None and focused_widget is None:
            logger.info("[Pet] App lost focus, hiding chat UI")
            self.hide_chat_ui()
    
    def show_message(self, text: str, auto_hide: bool = True, duration: int = None, is_auto_speak: bool = False):
        """
        显示消息气泡
        
        Args:
            text: 要显示的文本
            auto_hide: 是否自动隐藏
            duration: 固定显示时间（毫秒），如果为 None 则根据文本长度动态计算
            is_auto_speak: 是否为自动说话（给予更长的显示时间）
        """
        if not self.can_show_bubble():
            return
            
        self._init_chat_ui()
        self.is_chatting = True  # 有气泡时保持静止
        
        # 设置气泡消失后的回调 - 恢复默认动画
        self.bubble.set_on_hidden_callback(self._on_bubble_hidden)
        
        # 只有显式传入 duration 时才使用固定时间，否则让 bubble 动态计算
        self.bubble.show_message(
            text, 
            auto_hide=auto_hide, 
            duration=duration,
            is_auto_speak=is_auto_speak
        )
        self._update_chat_position()
        
        # 强制处理 UI 事件，确保气泡立即显示
        QApplication.processEvents()
    
    def show_typing(self):
        """显示正在输入状态"""
        if not self.can_show_bubble():
            return
            
        self._init_chat_ui()
        self.is_chatting = True  # 等待LLM时保持静止
        # 清除之前的回调
        self.bubble.set_on_hidden_callback(None)
        self.bubble.show_typing(auto_hide=False)
        self._update_chat_position()
        # 强制处理 UI 事件，确保等待框立即显示
        QApplication.processEvents()
    
    def _on_bubble_hidden(self):
        """
        气泡隐藏回调
        
        当对话气泡完全消失时，处理动画恢复。
        但如果当前正在播放单次动画（如 EATING, HAPPY 等），
        则等待它自己完成，不要强制切换。
        """
        # 退出时不处理
        if self._is_exiting:
            return
        
        logger.info(f"[Pet] Bubble hidden: current_type={self.current_type}, was_chatting={self.is_chatting}")
        
        # 只有当没有其他聊天UI显示时才重置
        if not self.input_panel or not self.input_panel.isVisible():
            self.is_chatting = False
            self._waiting_llm = False
        
        # 检查当前是否在播放单次动画（如 EATING, HAPPY 等）
        if self.current_type and AnimationRegistry.should_play_once(self.current_type):
            logger.info(f"[Pet] Bubble hidden but waiting for single-play animation: {self.current_type}")
            return
        
        # 对话期间使用的动画类型
        chat_animations = {
            AnimationType.CONFUSED,
            AnimationType.SLEEP,
            AnimationType.PLAYING,
            AnimationType.NEUTRAL,  # 正常说话时的动画
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
        
        # 使用 QTimer.singleShot 让 Qt 先处理 UI 更新
        # 然后再发布事件给 Agent，确保 "...等待框" 先显示出来
        QTimer.singleShot(0, lambda: event_bus.publish(
            EventCategory.AGENT, AgentEvent.USER_MESSAGE, message=text
        ))
    
    def _on_llm_config_error(self, data: dict):
        """LLM配置错误回调 - 显示可爱的提示消息"""
        if self._is_exiting:
            return
        self._llm_config_error_received.emit(data)
    
    def _handle_llm_config_error(self, data: dict):
        """处理LLM配置错误（在Qt主线程执行）"""
        import random
        
        if not self.can_show_bubble():
            return
        
        # 可爱的提示消息列表
        cute_messages = [
            "呜呜...我好像没电了 T_T\n能帮我检查一下设置吗？",
            "呜哇！我需要加油啦 ⚡\n右键点我→设置→输入API Key",
            "主人~我的脑子转不动了 🥺\n需要帮我配置一下吗？",
            "哎呀！我好像失忆了 😵\n帮我重新设置一下吧~",
            "嘟~电量不足警告 🔋\n去设置里给我充充电吧！",
        ]
        
        message = random.choice(cute_messages)
        
        # 使用统一的 show_message 方法（包含守卫检查）
        self.show_message(message, auto_hide=False)
        
        # 设置提示消失时间
        error_source = data.get('source', 'unknown')
        if error_source == 'warmup':
            # 预热错误 - 显示较长时间让用户注意
            QTimer.singleShot(5000, self._hide_error_message)
        else:
            # 对话错误 - 显示短一些
            QTimer.singleShot(4000, self._hide_error_message)
        
        # 播放困惑的动画
        self.play(AnimationType.CONFUSED)
        
        logger.warning(f"[Pet] LLM config error shown to user: {data.get('error', 'unknown')}")
    
    def _hide_error_message(self):
        """隐藏错误消息并重置状态"""
        if self.bubble and self.bubble.isVisible():
            self.bubble.hide_bubble()
            self.is_chatting = False

    def _on_agent_response(self, response: dict):
        """Agent 响应回调（可能来自非 Qt 线程，需安全转发）"""
        # 检查是否正在退出或隐藏
        if self._is_exiting or not self.isVisible():
            return
        # 使用信号 emit，比 QTimer.singleShot 更快
        self._agent_response_received.emit(response)

    def _handle_agent_response(self, response: dict):
        """实际处理 Agent 响应（在 Qt 主线程执行）"""
        if not self.can_process_response():
            return
        
        text = response.get('text', '')
        emotion = response.get('emotion', '')
        play_once = response.get('play_once', True)
        is_auto_speak = response.get('is_auto_speak', False)

        # 使用守卫函数检查是否可以显示气泡
        if text and self.can_show_bubble():
            # 注意：先设置 is_chatting = True，再清除 _waiting_llm
            # 防止 _check_idle 在两者之间触发，导致气泡被隐藏
            self.show_message(text, auto_hide=True, is_auto_speak=is_auto_speak)
            
            # 气泡显示后，清除等待状态
            self._waiting_llm = False
            
            # 设置隐藏回调
            self.bubble.set_on_hidden_callback(self._on_chat_response_finished)
            
            logger.info(f"[Pet] Bubble shown, is_auto_speak={is_auto_speak}, text_len={len(text)}")
        else:
            # 没有气泡，直接清除等待状态
            self._waiting_llm = False

        # 使用守卫函数检查是否可以触发动画
        if emotion and self.can_trigger_animation():
            self.trigger_animation(emotion, play_once)

    def _on_chat_response_finished(self):
        """
        聊完天后的回调 - 完整处理清理逻辑
        
        1. 先执行原来的 _on_bubble_hidden 清理工作
        2. 检查是否有单次动画正在播放，如果有，等待它完成
        3. 否则根据鼠标位置切换动画
        """
        # 退出时不处理
        if self._is_exiting:
            return
            
        logger.info("[Pet] Chat response finished, checking state")
        
        # Step 1: 清理状态
        if not self.input_panel or not self.input_panel.isVisible():
            self.is_chatting = False
            self._waiting_llm = False
        
        # Step 2: 检查当前是否在播放单次动画（如 EATING, HAPPY 等）
        if self.current_type and AnimationRegistry.should_play_once(self.current_type):
            # 正在播放单次动画，等待它完成（_on_once_finished 会处理后续）
            logger.info(f"[Pet] Waiting for single-play animation: {self.current_type}")
            return
        
        # Step 3: 没有单次动画，根据鼠标位置切换
        self._check_mouse_hover()
        if self.is_hovering:
            self.play(AnimationType.STAND)
        else:
            self.play(AnimationType.WALK)
    
    def _post_chat_check(self):
        """延迟检查 - 保留用于需要的场景"""
        self._check_mouse_hover()
        if self.is_hovering:
            self.play(AnimationType.STAND)
        else:
            self.play(AnimationType.WALK)

    def _on_agent_thinking(self, data: dict = None):
        """Agent 思考回调（可能来自非 Qt 线程）"""
        # 检查是否正在退出或隐藏
        if self._is_exiting or not self.isVisible():
            return
        # 使用信号 emit
        self._agent_thinking_received.emit()

    def _handle_agent_thinking(self):
        """实际处理思考状态（在 Qt 主线程执行）"""
        # 再次检查是否正在退出或隐藏
        if self._is_exiting or not self.isVisible():
            return
        self.play(AnimationType.CONFUSED)

    def _on_animation_request(self, animation: str, play_once: bool = False, **kwargs):
        """
        处理来自 LLM 工具的动画请求

        可能来自非 Qt 线程，需安全转发到主线程

        Args:
            animation: 动画名称或别名
            play_once: 是否单次播放
        """
        # 检查是否正在退出
        if self._is_exiting:
            return
        # 使用信号 emit
        self._animation_request_received.emit({
            'animation': animation,
            'play_once': play_once
        })
    
    def _handle_animation_request(self, data: dict):
        """处理动画请求（在 Qt 主线程执行）"""
        if self._is_exiting:
            return
        animation = data.get('animation')
        play_once = data.get('play_once', False)
        if animation:
            self.trigger_animation(animation, play_once)
    
    # ==================== 动画控制 ====================
    
    def play(self, anim_type, play_once: bool = False):
        """
        播放动画
        
        Args:
            anim_type: 动画类型
            play_once: 是否只播放一次（不循环）
        """
        # 1. 退出时只允许 LEAVE 动画
        if self._is_exiting and anim_type != AnimationType.LEAVE:
            return
        
        # 2. 睡眠时只允许 SLEEP 动画（唤醒由用户交互触发）
        if self._is_sleeping and anim_type != AnimationType.SLEEP:
            return
        
        # 3. 拖拽时只允许 FLY/DRAG 相关动画
        if self.is_dragging and anim_type not in (AnimationType.FLY, AnimationType.DRAG):
            return
            
        movie = self.movies.get(anim_type)
        if not movie:
            return
        
        if self.current_movie == movie and movie.state() == QMovie.MovieState.Running:
            return

        # LLM 等待期间保护 CONFUSED 状态，防止被意外覆盖
        if (self._waiting_llm and self.current_type == AnimationType.CONFUSED 
            and anim_type != AnimationType.CONFUSED):
            return
        
        # 取消 touch 定时器 (关键！)
        self.touch_timer.stop()
        
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
    
    def _on_frame_once(self, frame, movie, anim_type):
        """单次播放的帧处理 - 到达最后一帧时停止"""
        self._on_frame(frame)
        
        # 检测是否到达最后一帧
        if frame == movie.frameCount() - 1:
            movie.stop()
    
    def trigger_animation(self, anim_name, play_once: bool = False):
        """
        外部触发动画

        Args:
            anim_name: 动画名称或 Emotion 枚举 (walk, stand, happy, Emotion.HAPPY, ...)
            play_once: 是否只播放一次 (False 则循环播放)

        Note:
            动画名称解析统一由 AnimationRegistry 处理
            如果配置了 play_once=True，会自动覆盖参数
        """
        # 如果是 Emotion 枚举，先转换为对应的动画名
        if isinstance(anim_name, Emotion):
            anim_name = emotion_to_animation(anim_name).value
        
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
        if self._is_exiting and anim_type != AnimationType.LEAVE:
            return
        
        if self._is_sleeping:
            return
        
        if self.is_dragging:
            return
            
        prev_type = self.current_type
        
        movie = self.movies.get(anim_type)
        if not movie:
            return

        # LLM 等待期间保护 CONFUSED 状态
        if (self._waiting_llm and self.current_type == AnimationType.CONFUSED 
            and anim_type != AnimationType.CONFUSED):
            return

        if self.current_movie:
            self.current_movie.stop()
            try:
                self.current_movie.frameChanged.disconnect()
                self.current_movie.finished.disconnect()
            except:
                pass
        
        self.current_movie = movie
        self.current_type = anim_type
        
        # 断开旧连接
        try:
            movie.frameChanged.disconnect()
        except:
            pass
        try:
            movie.finished.disconnect()
        except:
            pass
        
        # 连接帧显示
        movie.frameChanged.connect(self._on_frame)
        
        # 检测动画完成的状态变量
        first_loop_done = [False]
        total_frames = movie.frameCount()
        first_seen_frame = [-1]
        
        def check_animation_finished(frame):
            nonlocal total_frames
            
            # 如果帧数未知，尝试从帧变化推断
            if total_frames <= 0:
                # 记录第一次看到的帧
                if first_seen_frame[0] < 0:
                    first_seen_frame[0] = frame
                    return
                
                # 如果帧数回到第一帧，说明已经循环了一次
                if frame == first_seen_frame[0]:
                    first_loop_done[0] = True
                    movie.stop()
                    QTimer.singleShot(200, lambda: self._on_once_finished(prev_type))
                return
            
            # 帧数已知的情况
            if not first_loop_done[0] and frame >= total_frames - 1:
                first_loop_done[0] = True
                movie.stop()
                QTimer.singleShot(200, lambda: self._on_once_finished(prev_type))

        movie.frameChanged.connect(check_animation_finished)
        
        # 开始播放
        movie.start()
    
    def _stop_current_animation(self, prev_type):
        """停止当前动画并恢复之前的状态"""
        if self.current_movie:
            self.current_movie.stop()
        self._on_once_finished(prev_type)
    
    def _on_once_finished(self, prev_type):
        """单次播放完成"""
        # 退出时不处理
        if self._is_exiting:
            return
            
        logger.info(f"[Pet] Single-play finished: prev={prev_type}, current={self.current_type}")
        
        # 回到之前状态，但 confused 是临时状态，不应恢复
        if prev_type and prev_type != self.current_type:
            if prev_type == AnimationType.CONFUSED:
                if self.is_hovering:
                    self.play(AnimationType.STAND)
                else:
                    self.play(AnimationType.WALK)
            else:
                self.play(prev_type)
            logger.info(f"[Pet] Restored animation to {prev_type}")
    
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
        
        # 睡眠时不移动
        if self._is_sleeping:
            return
        
        # 预热时不移动（正在显示 SEARCHING 动画）
        if self._is_warming_up:
            return
            
        # 主动检测鼠标是否在宠物范围内（解决失焦时enterEvent不触发的问题）
        self._check_mouse_hover()
        
        if self.is_dragging or self.is_hovering:
            return
        if self.current_type in (AnimationType.TOUCH, AnimationType.FLY, AnimationType.LEAVE, AnimationType.SLEEP):
            return
        # 聊天时也暂停移动
        if self.is_chatting:
            return
        # 单次播放动画期间也暂停移动（如 EATING, HAPPY, ANGRY 等）
        if self.current_type and AnimationRegistry.should_play_once(self.current_type):
            return
        
        # 随机改方向
        if random.random() < self.pet_cfg.walking_dir_change_prob:
            self.direction *= -1
        if random.random() < self.pet_cfg.walking_y_dir_change_prob:
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
            if not self.is_chatting and self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
                self.play(AnimationType.STAND)
        elif not mouse_in_pet and self.is_hovering:
            # 鼠标离开
            self.is_hovering = False
            self.unsetCursor()
            if not self.is_chatting and self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
                self.play(AnimationType.WALK)
    
    def enterEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
        
        # 预热时不响应
        if self._is_warming_up:
            return
            
        self.is_hovering = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if self.is_chatting:
            return
        if self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
            self.play(AnimationType.STAND)
    
    def leaveEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
        
        # 预热时不响应
        if self._is_warming_up:
            return
            
        self.is_hovering = False
        self.unsetCursor()
        if self.is_chatting:
            return
        if self.current_type not in (AnimationType.TOUCH, AnimationType.FLY):
            self.play(AnimationType.WALK)
    
    def mousePressEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
        
        # 预热时不响应
        if self._is_warming_up:
            return
        
        # 重置互动时间并唤醒
        self._reset_interaction()
            
        if event.button() == Qt.MouseButton.LeftButton:
            self.click_start_pos = event.globalPosition().toPoint()
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.is_clicking = True
            self.is_dragging = False
            self.last_mouse_x = event.globalPosition().x()

        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event)
    
    def show_context_menu(self, event):
        """显示右键菜单"""
        # 预热时不允许操作
        if self._is_warming_up:
            return
            
        from PyQt6.QtWidgets import QMenu
        
        menu = QMenu(self)
        
        menu.addAction("🙈 隐藏暖宝", self._hide_with_hint)
        menu.addSeparator()
        menu.addAction("⚙️ 设置...", self.open_settings)
        menu.addSeparator()
        menu.addAction("❤️ 关于暖宝", self.show_about)
        menu.addSeparator()
        menu.addAction("🚪 退出", self._exit_with_animation)
        menu.addSeparator()
        menu.addAction("⭐ 给我个 Star 吧！", self.show_github_star)
        
        menu.exec(event.globalPosition().toPoint())

    def open_settings(self):
        """打开设置窗口"""
        try:
            from ui import SettingsDialog
            from PyQt6.QtWidgets import QApplication
            # 使用活动窗口作为父窗口，避免被 pet 的小尺寸限制
            parent = QApplication.activeWindow()
            if parent is None or parent == self:
                parent = None
            dialog = SettingsDialog(parent)
            dialog.exec()
        except Exception as e:
            logger.error(f"[Pet] Failed to open settings: {e}")

    def toggle_auto_speak(self, enabled: bool):
        """切换自动说话"""
        try:
            from config import config_manager
            config_manager.set("behavior.auto_speak_enabled", enabled)
            logger.info(f"[Pet] Auto speak {'enabled' if enabled else 'disabled'}")
        except Exception as e:
            logger.error(f"[Pet] Failed to toggle auto speak: {e}")

    def show_about(self):
        """显示关于窗口"""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            f"关于{__app_name__}",
            f"<h3>🐹 {__app_name__} - 机甲仓鼠</h3>"
            f"<p>版本: v{__version__}</p>"
            f"<p>一个可爱的桌面宠物助手</p>"
            f"<p>© {__copyright__}</p>"
        )

    def _hide_with_hint(self):
        """显示提示气泡后隐藏，告诉用户可以在托盘恢复"""
        self.show_message("我先躲起来啦～点击托盘图标就能叫我出来哦！", auto_hide=False)
        QTimer.singleShot(2000, self.hide)

    def show_github_star(self):
        """打开 GitHub 项目页面请求 Star"""
        import webbrowser
        github_url = "https://github.com/lanlan-yang/warming_baby"
        webbrowser.open(github_url)
        logger.info("[Pet] Opened GitHub page for star request")

    def mouseMoveEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
        
        # 预热时不响应
        if self._is_warming_up:
            return
            
        if self.is_clicking and not self.is_dragging:
            pos = event.globalPosition().toPoint()
            dist = (pos - self.click_start_pos).manhattanLength()
            if dist > self.drag_threshold:
                self.is_dragging = True
                self.is_clicking = False
                self._reset_interaction()  # 重置互动时间
                self.hide_chat_ui()  # 拖拽时隐藏聊天 UI
                self.play(AnimationType.FLY)
        
        if self.is_dragging:
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            
            current_x = event.globalPosition().x()
            if current_x != self.last_mouse_x:
                self.facing_right = current_x > self.last_mouse_x
                self.last_mouse_x = current_x
            
            # 更新聊天组件位置
            self._update_chat_position()

    def mouseReleaseEvent(self, event):
        # 退出时不响应
        if self._is_exiting:
            return
        
        # 预热时不响应
        if self._is_warming_up:
            return
            
        # 重置互动时间
        self._reset_interaction()
            
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_dragging:
                self.is_dragging = False
                self.drag_offset = None
                if self.is_hovering:
                    self.play(AnimationType.STAND)
                else:
                    self.play(AnimationType.WALK)
            elif self.is_clicking:
                self.is_clicking = False
                
                # 显示聊天 UI（内部播放 confused 动画）
                self.show_chat_ui()
    
    def _exit_with_animation(self):
        """先播放 LEAVE 动画，完成后退出"""
        self._is_exiting = True  # 设置退出标志，阻止其他动画
        
        try:
            # 停止所有定时器
            self.move_timer.stop()
            self.touch_timer.stop()
            if hasattr(self, '_topmost_timer'):
                self._topmost_timer.stop()
            if hasattr(self, '_focus_check_timer'):
                self._focus_check_timer.stop()
            # 停止自动说话检查定时器
            if hasattr(self, 'auto_speak_check_timer'):
                self.auto_speak_check_timer.stop()
            
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
                    # 动态获取总帧数（如果还没获取到的话）
                    nonlocal total_frames
                    if total_frames <= 0:
                        total_frames = leave_movie.frameCount()
                    
                    # 只在第一次循环结束时触发
                    if total_frames > 0 and not first_loop_done[0] and frame >= total_frames - 1:
                        first_loop_done[0] = True
                        leave_movie.stop()
                        # 延迟一点时间让最后一帧显示，避免瞬间消失
                        QTimer.singleShot(200, self._do_exit)
                
                leave_movie.frameChanged.connect(check_leave_finished)
                
                # 备用机制：如果 5 秒后还没退出，强制退出
                def force_exit():
                    if not first_loop_done[0]:
                        logger.warning("[Pet] LEAVE animation timeout, force exit")
                        first_loop_done[0] = True
                        self._do_exit()
                
                QTimer.singleShot(5000, force_exit)
                
                # 直接开始，不用延迟
                leave_movie.start()
                
                # 确保窗口在退出期间保持可见
                self.show()
                self.raise_()
            else:
                self._do_exit()
        except Exception as e:
            logger.error(f"[Pet] Exit animation error: {e}")
            self._do_exit()
    
    def _do_exit(self):
        """执行退出"""
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
        except Exception:
            pass
        
        # 先设置 shutdown_event，让 main() 能够优雅退出
        try:
            if not shutdown_event.is_set():
                shutdown_event.set()
        except Exception:
            pass
        
        # 退出应用
        QApplication.quit()
    
    def showEvent(self, event):
        """显示事件"""
        super().showEvent(event)
        # 根据配置决定是否置顶
        always_on_top = config_manager.get("appearance.always_on_top", True)
        if always_on_top:
            # 延迟调用，确保 Qt 窗口已创建
            QTimer.singleShot(10, self._apply_topmost_native)
            QTimer.singleShot(100, self._apply_topmost_native)
            QTimer.singleShot(500, self._apply_topmost_native)
        
        # 恢复自动说话计时器
        if hasattr(self, 'auto_speak_check_timer'):
            if not self.auto_speak_check_timer.isActive():
                self.auto_speak_check_timer.start(60000)
        
        # 恢复动画状态
        if self._is_warming_up:
            # 预热中，恢复 SEARCHING 动画
            self.play(AnimationType.SEARCHING)
        elif self.move_timer.isActive() and not self.is_chatting:
            # 正常状态，恢复 WALK 动画
            self.play(AnimationType.WALK)

    def hideEvent(self, event):
        """隐藏事件 - 停止所有不必要的活动"""
        super().hideEvent(event)
        # 停止自动说话计时器
        if hasattr(self, 'auto_speak_check_timer'):
            self.auto_speak_check_timer.stop()
        # 隐藏对话 UI
        self.hide_chat_ui()
        # 停止所有动画并重置状态
        if self.current_movie:
            self.current_movie.stop()
        self.current_type = None  # 重置动画类型，防止恢复时状态异常
    
    def _apply_topmost_native(self):
        """Cross-platform window topmost"""
        # Windows: First set Qt flag, then override with Win32 API
        if sys.platform == 'win32':
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.show()
            QApplication.processEvents()
        
        if set_window_topmost(self):
            # Periodic refresh to prevent system reset
            if not hasattr(self, '_topmost_timer'):
                self._topmost_timer = QTimer(self)
                self._topmost_timer.timeout.connect(lambda: set_window_topmost(self))
                self._topmost_timer.start(200)

    def _remove_topmost(self):
        """移除窗口置顶"""
        # 停止定时刷新
        if hasattr(self, '_topmost_timer'):
            self._topmost_timer.stop()
        
        # macOS 上使用 AppKit 取消置顶
        if sys.platform == 'darwin':
            try:
                from AppKit import NSNormalWindowLevel
                win_id = int(self.winId())
                if win_id:
                    import objc
                    ns_view = objc.objc_object(c_void_p=win_id)
                    ns_window = ns_view.window()
                    if ns_window:
                        ns_window.setLevel_(NSNormalWindowLevel)
                        ns_window.orderOut_(None)
                        ns_window.orderFront_(None)
            except Exception as e:
                logger.warning(f"[Pet] 取消置顶失败: {e}")

    def focusOutEvent(self, event):
        """焦点处理 - 暂时禁用"""
        super().focusOutEvent(event)
        # TODO: 后续添加合适的焦点处理逻辑
    
    def closeEvent(self, event):
        """关闭事件"""
        if not self._is_exiting:
            self._exit_with_animation()
            event.ignore()
            return
        
        super().closeEvent(event)



    # ==================== 睡眠相关方法 ====================
    
    def _reset_interaction(self):
        """
        重置互动时间
        
        在用户进行任何互动（点击、拖拽、发送消息等）时调用。
        如果宠物在睡眠中，会自动唤醒。
        """
        self._last_interaction_time = time.time()
        
        # 如果在睡眠中，立即唤醒
        if self._is_sleeping:
            self._wake_up()
    
    def _check_idle(self):
        """
        定期检查是否应该进入睡眠
        
        由 idle_check_timer 定时调用。
        如果超过 idle_to_sleep_seconds 没有互动，且不在特殊状态，就进入睡眠。
        """
        # 正在退出时不检查
        if self._is_exiting:
            return
        
        # 已经在睡眠中不检查
        if self._is_sleeping:
            return
        
        # 以下状态不进入睡眠
        if self.is_dragging or self.is_chatting or self._waiting_llm:
            return
        
        if self.current_type in (AnimationType.TOUCH, AnimationType.FLY, 
                               AnimationType.LEAVE, AnimationType.SLEEP):
            return
        
        # 计算空闲时间
        idle_time = time.time() - self._last_interaction_time
        
        # 从用户配置读取睡眠时间
        idle_to_sleep = config_manager.get("behavior.idle_to_sleep_min", 5) * 60
        if idle_time >= idle_to_sleep:
            logger.info(f"[Pet] 空闲 {idle_time:.0f}秒，进入睡眠")
            self._enter_sleep()
    
    def _enter_sleep(self):
        """进入睡眠状态"""
        if not self.can_enter_sleep():
            return
        
        self._is_sleeping = True
        
        # 取消所有待处理的响应
        self._pending_response_cancelled = True
        self._waiting_llm = False
        
        # 如果有显示的气泡，隐藏它
        if self.bubble and self.bubble.isVisible():
            self.bubble.hide_bubble(trigger_callback=False)
            self.is_chatting = False
        
        # 记录睡眠前的动画
        self._prev_animation_before_sleep = self.current_type
        
        # 播放睡眠动画
        self.play(AnimationType.SLEEP)
        
        # 启动睡眠时间定时器 - 从用户配置读取
        sleep_duration_min = config_manager.get("behavior.sleep_duration_min", 1)
        self.sleep_end_timer.start(sleep_duration_min * 60 * 1000)
        
        logger.info(f"[Pet] 睡眠中，{sleep_duration_min}分钟后醒来")
    
    def _wake_up(self):
        """从睡眠中醒来"""
        self._is_sleeping = False
        self._pending_response_cancelled = False
        
        # 停止睡眠时间定时器
        self.sleep_end_timer.stop()
        
        # 重置互动时间
        self._last_interaction_time = time.time()
        
        # 关键！先检查当前鼠标状态（睡眠期间状态可能已过时）
        self._check_mouse_hover()
        
        # 播放醒来后的动画（根据最新的鼠标位置）
        if self.is_hovering:
            self.play(AnimationType.STAND)
        else:
            self.play(AnimationType.WALK)
        
        logger.info(f"[Pet] 醒来了 (is_hovering={self.is_hovering})")
    
    # ==================== 睡眠相关结束 ====================
    
    # ==================== 用户配置相关 ====================
    
    def _apply_user_config(self):
        """应用用户配置到各个模块"""
        try:
            # ========== 外观设置 ==========
            # 窗口透明度
            opacity = config_manager.get("appearance.opacity", 1.0)
            self.setWindowOpacity(opacity)
            
            # 窗口置顶 - 仅在窗口已显示时应用
            always_on_top = config_manager.get("appearance.always_on_top", True)
            if self.isVisible():
                if always_on_top:
                    self._apply_topmost_native()
                else:
                    self._remove_topmost
            
            # ========== 行为设置 ==========
            # 更新自动说话间隔
            speak_interval_min = config_manager.get("behavior.auto_speak_interval_min", 5)
            speak_interval_sec = speak_interval_min * 60
            self.auto_speak_manager.set_interval(
                min_interval=speak_interval_sec,
                max_interval=speak_interval_sec + 60
            )
            
            # 更新自动说话开关
            auto_speak_enabled = config_manager.get("behavior.auto_speak_enabled", True)
            if auto_speak_enabled:
                self.auto_speak_manager.enable()
            else:
                self.auto_speak_manager.disable()
            
            logger.info(f"[Pet] 用户配置已应用 - 透明度: {opacity}, 置顶: {always_on_top}, 自动说话间隔: {speak_interval_min}分钟")
            
        except Exception as e:
            logger.warning(f"[Pet] 应用用户配置失败: {e}")
    
    def _on_config_changed(self, key: str, value) -> None:
        """配置变更回调 - 通过 ConfigManager 监听器触发"""
        apply_keys = [
            "behavior.auto_speak_enabled",
            "behavior.auto_speak_interval_min",
            "behavior.idle_to_sleep_min",
            "behavior.sleep_duration_min",
            "appearance.opacity",
            "appearance.always_on_top",
        ]
        if key in apply_keys or key == "*":
            self._apply_user_config()

    # ==================== 自动说话相关 ====================
    
    def _check_auto_speak(self):
        """检查是否应该主动说话"""
        # 使用守卫函数检查是否可以触发自动说话
        if not self.can_auto_speak():
            return
        
        now = time.time()
        should_speak = self.auto_speak_manager.should_speak(
            is_chatting=self.is_chatting,
            is_sleeping=self._is_sleeping,
            is_dragging=self.is_dragging,
        )
        
        if not should_speak:
            return
        
        if not self.can_auto_speak():
            return
        
        # 获取说话参数
        params = self.auto_speak_manager.get_speak_params()
        prompt = params['prompt']
        scene = params['scene']
        
        logger.info(f"[Pet] Auto speak triggered: {scene.value}")
        
        # 标记为等待 LLM 响应
        self._waiting_llm = True
        
        # 发布事件 - 让 ChatAgent 处理
        event_bus.publish(
            EventCategory.AGENT,
            AgentEvent.AUTO_SPEAK,
            prompt=prompt,
        )
        
        # 标记已说话
        self.auto_speak_manager.speak_done()
    
    # ==================== 自动说话相关结束 ====================


def init_pet():
    """初始化宠物 GUI（返回 app 和 pet，供外部事件循环使用）"""
    app = QApplication(sys.argv)
    app.setFont(get_default_font(10))
    pet = NuanbaoPet()
    pet.show()
    return app, pet


def run():
    """独立启动宠物（用于测试）"""
    app, pet = init_pet()
    sys.exit(app.exec())


if __name__ == '__main__':
    run()
