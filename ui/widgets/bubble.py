"""
对话气泡组件 - 可靠的文本渲染版本

关键改进:
1. 使用 QPainter.boundingRect() 计算文本尺寸，而非手动累加
2. 使用 QPainter.drawText() + TextWordWrap 自动换行
3. 尺寸计算和绘制使用相同的逻辑，保证一致性
4. 简化代码，减少出错可能性
"""
from core.logger import setup_logger

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QPointF, QTimer, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QLinearGradient, QFont, QFontMetrics
from PyQt6.QtWidgets import QWidget
from core import get_default_font, IS_MAC
from core.topmost import set_window_topmost
from settings import settings

logger = setup_logger()


class SpeechBubble(QWidget):
    """
    可靠的对话气泡组件
    
    设计原则:
    1. 先测量后绘制 - 用 boundingRect 确定尺寸
    2. 绘制和测量使用相同的参数 - 保证一致性
    3. 支持自动换行 - 让 Qt 帮我们处理复杂的文字布局
    """
    
    # 颜色配置
    COLORS = {
        'bg_start': QColor(255, 255, 255, 245),
        'bg_end': QColor(255, 248, 220, 245),
        'border': QColor(255, 200, 100, 200),
        'text': QColor(80, 60, 40),
        'shadow': QColor(0, 0, 0, 60),
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 加载配置
        self.cfg = settings.bubble
        
        # 设置窗口属性 - 无边框
        # Windows: 不用 Qt.Tool（会在失去焦点时自动隐藏），改用 Win32 WS_EX_TOOLWINDOW 隐藏任务栏
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        
        # 内容
        self._text = ""

        # 尾巴朝向：False=朝下（气泡在宠物上方，默认）
        #           True=朝上（气泡在宠物下方时指向宠物）
        self._tail_up = False

        # typing 动画（等待 LLM 响应时显示三点波浪）
        self._is_typing = False
        self._typing_phase = 0.0  # 0..1 循环
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(80)  # 80ms 一帧
        self._typing_timer.timeout.connect(self._on_typing_tick)

        # 透明度动画
        self._opacity = 0
        self._fade_in_duration = self.cfg.fade_in_duration
        self._fade_out_duration = self.cfg.fade_out_duration
        self._opacity_anim = QPropertyAnimation(self, b"opacity")
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._opacity_anim.finished.connect(self._on_animation_finished)
        
        # 自动隐藏定时器
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.start_fade_out)
        
        # 消失回调
        self._on_hidden_callback = None
        
        # 设置字体
        self._font = self._create_cute_font()
        self.setFont(self._font)
        
        # macOS 置顶相关
        self._ns_window_ref = None
        self._topmost_timer = None
    
    def _create_cute_font(self) -> QFont:
        """创建可爱字体"""
        font = get_default_font(14)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        return font
    
    def showEvent(self, event):
        """显示时设置置顶"""
        super().showEvent(event)
        QTimer.singleShot(10, self._setup_topmost)
        QTimer.singleShot(100, self._setup_topmost)

    def _setup_topmost(self):
        """置顶设置"""
        if set_window_topmost(self):
            if self._topmost_timer is None:
                self._topmost_timer = QTimer(self)
                self._topmost_timer.timeout.connect(lambda: set_window_topmost(self))
                self._topmost_timer.start(200)

    def set_on_hidden_callback(self, callback):
        """设置隐藏回调"""
        self._on_hidden_callback = callback

    def set_tail_up(self, up: bool):
        """设置尾巴朝向

        Args:
            up: True=尾巴朝上（气泡在宠物下方时使用）
                False=尾巴朝下（气泡在宠物上方时使用，默认）
        """
        if self._tail_up != up:
            self._tail_up = up
            self.update()
    
    def show_message(self, text: str, auto_hide: bool = True, duration: int = None, is_auto_speak: bool = False):
        """
        显示消息

        Args:
            text: 要显示的文本
            auto_hide: 是否自动隐藏
            duration: 固定显示时间（毫秒），如果为 None 则根据文本长度动态计算
            is_auto_speak: 是否为自动说话（给予更长的显示时间）
        """
        import logging
        logger = logging.getLogger(__name__)

        # 退出 typing 模式（切到普通文本）
        self._stop_typing()
        
        saved_callback = self._on_hidden_callback
        logger.info(f"[Bubble] show_message called, saved_callback={saved_callback is not None}")
        
        # 关键修复：先断开动画信号，防止 stop() 触发 _on_animation_finished
        # 在 Windows 上，QPropertyAnimation.stop() 可能会发送 finished 信号
        self._opacity_anim.finished.disconnect(self._on_animation_finished)
        
        # 先设置透明度为 0（让窗口透明显示，然后淡入）
        self._opacity = 0.0
        
        # 停止所有动画和定时器
        self._auto_hide_timer.stop()
        self._opacity_anim.stop()
        
        # 重新连接信号
        self._opacity_anim.finished.connect(self._on_animation_finished)
        
        self._on_hidden_callback = saved_callback
        self._text = text
        
        # 计算尺寸
        self._calculate_size()
        
        # 显示（此时窗口是透明的）
        self.show()
        logger.debug(f"[Bubble] window shown, size={self.width()}x{self.height()}")
        
        # 强制处理 UI 事件，确保窗口已显示
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        
        # macOS 置顶
        if IS_MAC:
            QTimer.singleShot(10, self._setup_topmost)
        
        # 淡入动画（从 0 渐变到 1）
        self._start_fade_in()
        logger.debug(f"[Bubble] fade_in started")
        
        # 自动隐藏
        if auto_hide:
            if duration is not None:
                delay = duration
            else:
                delay = self.cfg.calculate_hide_delay(len(text), is_auto_speak)
            logger.info(f"[Bubble] Auto hide in {delay}ms ({delay/1000:.1f}s)")
            self._auto_hide_timer.start(delay)
            logger.debug(f"[Bubble] auto_hide timer started, delay={delay}ms")

    def show_typing(self, auto_hide: bool = False):
        """显示打字状态（三点波浪动画）"""
        import logging
        logger = logging.getLogger(__name__)

        # 关键修复：断开动画信号，防止 stop() 触发 _on_animation_finished
        self._opacity_anim.finished.disconnect(self._on_animation_finished)

        self._opacity = 0.0
        self._auto_hide_timer.stop()
        self._opacity_anim.stop()

        self._opacity_anim.finished.connect(self._on_animation_finished)

        self._text = ""
        saved_callback = self._on_hidden_callback
        self._on_hidden_callback = saved_callback

        # 进入 typing 模式
        self._is_typing = True
        self._typing_phase = 0.0
        self._typing_timer.start()

        # typing 气泡尺寸：小而紧凑
        # 宽度 = 三点 + 间距 + padding；高度 = 圆点 + 上下padding + tail
        dot_size = 7
        dot_gap = 10
        pad = 14
        typing_w = dot_size * 3 + dot_gap * 2 + pad * 2
        typing_h = dot_size + pad * 2 + self.cfg.tail_height + 2
        self.resize(int(typing_w), int(typing_h))

        self.show()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        if IS_MAC:
            QTimer.singleShot(10, self._setup_topmost)

        self._start_fade_in()

        if auto_hide:
            self._auto_hide_timer.start(3000)

    def _stop_typing(self):
        """退出 typing 模式"""
        if self._is_typing:
            self._typing_timer.stop()
            self._is_typing = False
            self._typing_phase = 0.0

    def _on_typing_tick(self):
        """typing 动画帧更新"""
        # 一个完整循环 1.2 秒（15 帧 × 80ms）
        self._typing_phase = (self._typing_phase + 80.0 / 1200.0) % 1.0
        self.update()
    
    def hide_bubble(self, trigger_callback: bool = True):
        """立即隐藏"""
        logger.debug(f"[Bubble] hide_bubble called, trigger_callback={trigger_callback}, "
                     f"has_callback={self._on_hidden_callback is not None}")

        # 停止所有定时器
        self._auto_hide_timer.stop()
        self._opacity_anim.stop()
        self._stop_typing()
        self._stop_topmost_timer()
        
        self._opacity = 0
        
        if trigger_callback and self._on_hidden_callback:
            logger.debug("[Bubble] calling _on_hidden_callback from hide_bubble")
            callback = self._on_hidden_callback
            self._on_hidden_callback = None
            callback()
            logger.debug("[Bubble] _on_hidden_callback completed")
        elif not self._on_hidden_callback:
            logger.debug("[Bubble] no _on_hidden_callback set")
        
        self.hide()
        logger.debug(f"[Bubble] bubble hidden, isVisible={self.isVisible()}")
    
    def _stop_topmost_timer(self):
        """停止置顶刷新定时器"""
        if self._topmost_timer is not None:
            self._topmost_timer.stop()
            self._topmost_timer = None
            logger.debug("[Bubble] _topmost_timer stopped")
    
    def set_auto_hide_delay(self, delay: int):
        self._auto_hide_delay = delay
    
    def set_opacity(self, value: float):
        self._opacity = value
        self.update()
    
    def get_opacity(self) -> float:
        return self._opacity
    
    opacity = pyqtProperty(float, get_opacity, set_opacity)
    
    def _calculate_size(self):
        """
        计算气泡尺寸 - 使用 QFontMetrics 来保证准确性
        
        关键: QFontMetrics.boundingRect 会考虑字体的实际渲染参数，
        包括字距、行距等，比手动累加更准确。
        """
        padding = self.cfg.padding + 4
        max_text_width = self.cfg.max_width - 2 * padding
        
        # 使用 QFontMetrics 计算文本尺寸
        fm = QFontMetrics(self._font)
        
        # boundingRect 返回文本需要的最小矩形
        # 第一个参数是可用的宽度，第二个是高度（给足够大）
        text_rect = fm.boundingRect(
            0, 0,  # x, y
            max_text_width, 10000,  # 宽度限制，足够大的高度
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self._text
        )
        
        # 文本实际尺寸
        text_width = text_rect.width()
        text_height = text_rect.height()
        
        # 气泡尺寸 (加上 padding)
        # +2 给 2px 描边留余量，避免边缘被窗口边界裁剪
        bubble_width = text_width + 2 * padding + 2
        bubble_height = text_height + 2 * padding + self.cfg.tail_height + 2
        
        # 限制在最小/最大范围内
        bubble_width = max(bubble_width, self.cfg.min_width)
        bubble_width = min(bubble_width, self.cfg.max_width)
        bubble_height = max(bubble_height, self.cfg.min_height + self.cfg.tail_height)
        
        # 应用尺寸
        self.resize(int(bubble_width), int(bubble_height))
    
    def _start_fade_in(self):
        """淡入动画"""
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.setDuration(self._fade_in_duration)
        self._opacity_anim.stop()
        self._opacity_anim.start()
    
    def start_fade_out(self):
        """淡出动画"""
        logger.debug(f"[Bubble] start_fade_out called, current _opacity={self._opacity}")
        logger.debug(f"[Bubble] _opacity_anim state: running={self._opacity_anim.state()}, "
                     f"duration={self._opacity_anim.duration()}")
        
        self._opacity_anim.setStartValue(self._opacity)
        self._opacity_anim.setEndValue(0.0)
        self._opacity_anim.setDuration(self._fade_out_duration)
        self._opacity_anim.stop()
        self._opacity_anim.start()
        
        logger.debug(f"[Bubble] fade_out started: start={self._opacity}, "
                     f"end=0.0, duration={self._fade_out_duration}ms")

    def _on_animation_finished(self):
        """动画结束处理"""
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"[Bubble] Animation finished, opacity={self._opacity:.3f}, has_callback={self._on_hidden_callback is not None}")
        
        if self._opacity <= 0.01:
            logger.debug("[Bubble] Fade out complete, hiding")
            self.hide()
            logger.debug(f"[Bubble] bubble hidden, isVisible={self.isVisible()}")
            
            if self._on_hidden_callback:
                logger.debug("[Bubble] calling _on_hidden_callback")
                callback = self._on_hidden_callback
                self._on_hidden_callback = None
                logger.debug("[Bubble] Calling hidden callback")
                callback()
        else:
            logger.debug("[Bubble] Fade in complete, staying visible")
    
    def paintEvent(self, event):
        """绘制气泡"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._opacity)

        # typing 模式：画三点波浪动画
        if self._is_typing:
            self._paint_typing(painter)
            painter.end()
            return

        w = self.width()
        h = self.height()
        tail_h = self.cfg.tail_height
        tail_w = self.cfg.tail_width
        radius = self.cfg.corner_radius
        tail_center_x = int(w * 0.55)

        # 1. 阴影
        shadow_path = self._create_bubble_path(
            w, h, tail_h, tail_w, radius, tail_center_x,
            offset_x=3, offset_y=3, tail_up=self._tail_up
        )
        painter.setBrush(QBrush(self.COLORS['shadow']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(shadow_path)

        # 2. 背景
        bg_path = self._create_bubble_path(
            w, h, tail_h, tail_w, radius, tail_center_x,
            tail_up=self._tail_up
        )
        if self._tail_up:
            # 尾巴在顶部，主体在 tail_h 下方
            gradient = QLinearGradient(0, tail_h, 0, h)
        else:
            # 尾巴在底部，主体在 0..h-tail_h
            gradient = QLinearGradient(0, 0, 0, h - tail_h)
        gradient.setColorAt(0, self.COLORS['bg_start'])
        gradient.setColorAt(1, self.COLORS['bg_end'])
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(bg_path)

        # 3. 边框
        pen = QPen(self.COLORS['border'], 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(bg_path)

        # 4. 文本
        painter.setPen(self.COLORS['text'])
        painter.setFont(self._font)

        padding = self.cfg.padding + 4
        if self._tail_up:
            # 尾巴在顶部，文本从 tail_h 下方开始
            text_rect = QRect(
                padding,
                tail_h + padding,
                w - 2 * padding,
                h - 2 * padding - tail_h
            )
        else:
            text_rect = QRect(
                padding,
                padding,
                w - 2 * padding,
                h - 2 * padding - tail_h
            )

        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self._text
        )

        painter.end()

    def _paint_typing(self, painter: QPainter):
        """绘制 typing 三点波浪动画

        三个圆点水平居中，y 偏移用正弦波驱动，相邻点相位错开 1/3 周期。
        气泡形状复用 _create_bubble_path（保留尾巴朝向逻辑）。
        """
        import math

        w = self.width()
        h = self.height()
        tail_h = self.cfg.tail_height
        tail_w = self.cfg.tail_width
        # typing 气泡尺寸小，限制圆角半径为 body 高度/宽度的一半
        # 让左右两边形成完整半圆（药丸形状），避免半径过大导致圆角交叉变形
        body_h = h - tail_h
        radius = min(self.cfg.corner_radius, body_h // 2, w // 2)
        # 尾巴水平位置：靠左偏一点，和普通气泡一致
        tail_center_x = int(w * 0.45)

        # 1. 阴影
        shadow_path = self._create_bubble_path(
            w, h, tail_h, tail_w, radius, tail_center_x,
            offset_x=3, offset_y=3, tail_up=self._tail_up
        )
        painter.setBrush(QBrush(self.COLORS['shadow']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(shadow_path)

        # 2. 背景（typing 用更柔和的渐变）
        bg_path = self._create_bubble_path(
            w, h, tail_h, tail_w, radius, tail_center_x,
            tail_up=self._tail_up
        )
        if self._tail_up:
            gradient = QLinearGradient(0, tail_h, 0, h)
        else:
            gradient = QLinearGradient(0, 0, 0, h - tail_h)
        # typing 用淡蓝灰底色，区分于普通消息的暖黄色
        gradient.setColorAt(0, QColor(250, 250, 255, 245))
        gradient.setColorAt(1, QColor(235, 240, 250, 245))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(bg_path)

        # 3. 边框（淡蓝色，更轻盈）
        pen = QPen(QColor(180, 200, 230, 200), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(bg_path)

        # 4. 三个圆点波浪动画
        dot_size = 7
        dot_gap = 10
        total_w = dot_size * 3 + dot_gap * 2
        start_x = (w - total_w) // 2

        # 圆点 y 基线（主体中心）
        if self._tail_up:
            base_y = tail_h + (h - tail_h) // 2
        else:
            base_y = (h - tail_h) // 2

        # 正弦波幅度
        amp = 3.0
        # 三点相位错开 1/3 周期
        for i in range(3):
            # 每个点在 phase 0..1 内完成一个完整正弦周期
            phase = (self._typing_phase + i / 3.0) % 1.0
            # sin(2πt)：phase=0 → 0, 0.25 → 1（最高点）, 0.5 → 0, 0.75 → -1（最低点）
            offset = math.sin(phase * 2 * math.pi) * amp
            cx = start_x + i * (dot_size + dot_gap) + dot_size // 2
            cy = base_y - offset  # -offset：正值时圆点上移

            # 透明度：波峰时最亮，波谷时暗一点
            alpha = int(120 + 100 * (0.5 + 0.5 * math.sin(phase * 2 * math.pi)))
            dot_color = QColor(120, 150, 200, alpha)

            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(cx - dot_size // 2, int(cy - dot_size // 2),
                                dot_size, dot_size)

    def _create_bubble_path(self, w, h, tail_h, tail_w, radius, tail_center_x,
                            offset_x=0, offset_y=0, tail_up=False) -> QPainterPath:
        """创建气泡形状

        整体内缩 1px，避免 2px 描边被窗口边界裁剪。

        Args:
            tail_up: True=尾巴在顶部朝上（气泡在宠物下方时指向宠物）
                     False=尾巴在底部朝下（默认，气泡在宠物上方时指向宠物）
        """
        path = QPainterPath()
        # 内缩 1px 给描边留余量
        inset = 1
        x = offset_x + inset
        y = offset_y + inset
        bw = w - 2 * inset  # body width
        bh = h - 2 * inset  # body height
        r = radius
        tail_left = tail_center_x - tail_w // 2 + offset_x
        tail_right = tail_center_x + tail_w // 2 + offset_x
        tail_ctrl = tail_w * 0.3

        if tail_up:
            # 尾巴在顶部，朝上
            tail_tip_y = y                       # 尾巴尖（最高点）
            tail_base_y = y + tail_h             # 尾巴根（与主体相接）
            body_bottom = y + bh

            path.moveTo(x + r, tail_base_y)
            path.lineTo(tail_left + tail_ctrl, tail_base_y)
            path.quadTo(tail_center_x - tail_w * 0.2, tail_base_y, tail_center_x, tail_tip_y)
            path.quadTo(tail_center_x + tail_w * 0.2, tail_base_y, tail_right - tail_ctrl, tail_base_y)
            path.lineTo(x + bw - r, tail_base_y)
            path.quadTo(x + bw, tail_base_y, x + bw, tail_base_y + r)
            path.lineTo(x + bw, body_bottom - r)
            path.quadTo(x + bw, body_bottom, x + bw - r, body_bottom)
            path.lineTo(x + r, body_bottom)
            path.quadTo(x, body_bottom, x, body_bottom - r)
            path.lineTo(x, tail_base_y + r)
            path.quadTo(x, tail_base_y, x + r, tail_base_y)
            path.closeSubpath()
        else:
            # 尾巴在底部，朝下
            tail_top_y = y + bh - tail_h         # 尾巴根
            tail_tip_y = y + bh                  # 尾巴尖（最低点）

            path.moveTo(x + r, y)
            path.lineTo(x + bw - r, y)
            path.quadTo(x + bw, y, x + bw, y + r)
            path.lineTo(x + bw, tail_top_y - r)
            path.quadTo(x + bw, tail_top_y, x + bw - r, tail_top_y)
            path.lineTo(tail_right - tail_ctrl, tail_top_y)
            path.quadTo(tail_center_x + tail_w * 0.2, tail_top_y, tail_center_x, tail_tip_y)
            path.quadTo(tail_center_x - tail_w * 0.2, tail_top_y, tail_left + tail_ctrl, tail_top_y)
            path.lineTo(x + r, tail_top_y)
            path.quadTo(x, tail_top_y, x, tail_top_y - r)
            path.lineTo(x, y + r)
            path.quadTo(x, y, x + r, y)
            path.closeSubpath()

        return path
    
    def mousePressEvent(self, event):
        event.accept()
    
    def mouseReleaseEvent(self, event):
        event.accept()
