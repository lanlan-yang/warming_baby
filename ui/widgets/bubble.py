"""
对话气泡组件 - 可靠的文本渲染版本

关键改进:
1. 使用 QPainter.boundingRect() 计算文本尺寸，而非手动累加
2. 使用 QPainter.drawText() + TextWordWrap 自动换行
3. 尺寸计算和绘制使用相同的逻辑，保证一致性
4. 简化代码，减少出错可能性
"""
import sys

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QPointF, QTimer, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QLinearGradient, QFont, QFontMetrics
from PyQt6.QtWidgets import QWidget
from core import get_default_font
from core.topmost import set_window_topmost
from settings import settings


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
        
        # 设置窗口属性
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        
        # 内容
        self._text = ""
        
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
    
    def show_message(self, text: str, auto_hide: bool = True, duration: int = None):
        """
        显示消息
        
        关键改进:
        1. 先设置透明度为 1 (防止旧动画影响)
        2. 停止旧动画
        3. 计算尺寸
        4. 显示
        5. 开始新动画
        """
        saved_callback = self._on_hidden_callback
        
        # 重置透明度
        self._opacity = 1.0
        
        # 停止所有动画
        self._auto_hide_timer.stop()
        self._opacity_anim.stop()
        
        self._on_hidden_callback = saved_callback
        self._text = text
        
        # 计算尺寸
        self._calculate_size()
        
        # 显示
        self.show()
        
        # macOS 置顶
        if sys.platform == 'darwin':
            QTimer.singleShot(10, self._setup_topmost)
        
        # 淡入
        self._start_fade_in()
        
        # 自动隐藏
        if auto_hide:
            if duration is not None:
                delay = duration
            else:
                delay = self.cfg.calculate_hide_delay(len(text))
            self._auto_hide_timer.start(delay)
    
    def show_typing(self, auto_hide: bool = False):
        """显示打字状态"""
        self.show_message("...", auto_hide=auto_hide)
    
    def hide_bubble(self, trigger_callback: bool = True):
        """立即隐藏"""
        self._auto_hide_timer.stop()
        self._opacity_anim.stop()
        self._opacity = 0
        
        if trigger_callback and self._on_hidden_callback:
            callback = self._on_hidden_callback
            self._on_hidden_callback = None
            callback()
        
        self.hide()
    
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
        bubble_width = text_width + 2 * padding
        bubble_height = text_height + 2 * padding + self.cfg.tail_height
        
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
        self._opacity_anim.setStartValue(self._opacity)
        self._opacity_anim.setEndValue(0.0)
        self._opacity_anim.setDuration(self._fade_out_duration)
        self._opacity_anim.stop()
        self._opacity_anim.start()

    def _on_animation_finished(self):
        """动画结束处理"""
        if self._opacity <= 0.01:
            self.hide()
            if self._on_hidden_callback:
                callback = self._on_hidden_callback
                self._on_hidden_callback = None
                callback()
    
    def paintEvent(self, event):
        """
        绘制气泡 - 简化版
        
        关键: 使用 drawText + TextWordWrap 让 Qt 自动处理文字
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._opacity)
        
        w = self.width()
        h = self.height()
        tail_h = self.cfg.tail_height
        tail_w = self.cfg.tail_width
        radius = self.cfg.corner_radius
        tail_center_x = int(w * 0.55)
        
        # 1. 阴影
        shadow_path = self._create_bubble_path(
            w, h, tail_h, tail_w, radius, tail_center_x,
            offset_x=3, offset_y=3
        )
        painter.setBrush(QBrush(self.COLORS['shadow']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(shadow_path)
        
        # 2. 背景
        bg_path = self._create_bubble_path(w, h, tail_h, tail_w, radius, tail_center_x)
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
        
        # 4. 文本 - 使用 TextWordWrap 自动换行
        painter.setPen(self.COLORS['text'])
        painter.setFont(self._font)
        
        padding = self.cfg.padding + 4
        text_rect = QRect(
            padding,
            padding,
            w - 2 * padding,
            h - 2 * padding - tail_h  # 留给尾巴空间
        )
        
        # 关键: 用 drawText + TextWordWrap 自动处理换行
        # 这与 _calculate_size 使用的 boundingRect 逻辑一致
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self._text
        )
        
        painter.end()
    
    def _create_bubble_path(self, w, h, tail_h, tail_w, radius,
                           tail_center_x, offset_x=0, offset_y=0) -> QPainterPath:
        """创建气泡形状"""
        path = QPainterPath()
        x = offset_x
        y = offset_y
        r = radius
        tail_top = h - tail_h + offset_y
        tail_bottom = h + offset_y
        tail_left = tail_center_x - tail_w // 2 + offset_x
        tail_right = tail_center_x + tail_w // 2 + offset_x
        tail_ctrl = tail_w * 0.3
        
        path.moveTo(x + r, y)
        path.lineTo(x + w - r, y)
        path.quadTo(x + w, y, x + w, y + r)
        path.lineTo(x + w, tail_top - r)
        path.quadTo(x + w, tail_top, x + w - r, tail_top)
        path.lineTo(tail_right - tail_ctrl, tail_top)
        path.quadTo(tail_center_x + tail_w * 0.2, tail_top, tail_center_x, tail_bottom)
        path.quadTo(tail_center_x - tail_w * 0.2, tail_top, tail_left + tail_ctrl, tail_top)
        path.lineTo(x + r, tail_top)
        path.quadTo(x, tail_top, x, tail_top - r)
        path.lineTo(x, y + r)
        path.quadTo(x, y, x + r, y)
        path.closeSubpath()
        
        return path
    
    def mousePressEvent(self, event):
        event.accept()
    
    def mouseReleaseEvent(self, event):
        event.accept()
