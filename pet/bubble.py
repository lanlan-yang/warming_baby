"""
对话气泡组件 - 可爱风格
圆角矩形 + 小三角尾巴 + 阴影效果 + 柔和渐变
"""
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QPointF, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QPolygonF, QLinearGradient, QRadialGradient, QFont
from PyQt6.QtWidgets import QWidget, QGraphicsDropShadowEffect
from core import get_default_font
from config import settings


class SpeechBubble(QWidget):
    """
    可爱风格对话气泡
    
    样式改进:
    - 柔和渐变背景 (白色到浅黄)
    - 圆润的边框
    - 阴影效果增加立体感
    - 底部可爱小三角尾巴
    
    功能:
    - 淡入淡出动画
    - 自动消失 (可选回调)
    - 支持多行文本
    - 气泡消失时触发回调
    """
    
    # 颜色配置
    COLORS = {
        'bg_start': QColor(255, 255, 255, 245),      # 渐变起点: 几乎白色
        'bg_end': QColor(255, 248, 220, 245),        # 渐变终点: 浅黄色
        'border': QColor(255, 200, 100, 200),         # 边框: 半透明暖黄
        'text': QColor(80, 60, 40),                   # 文字: 深棕色 (更柔和)
        'shadow': QColor(0, 0, 0, 60),                # 阴影: 黑色半透明
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 加载配置
        self.cfg = settings.bubble
        
        # 设置窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # 文本内容
        self._text = ""
        self._target_size = None
        
        # 透明度属性
        self._opacity = 0
        self._fade_in_duration = self.cfg.fade_in_duration
        self._fade_out_duration = self.cfg.fade_out_duration
        self._auto_hide_delay = self.cfg.auto_hide_delay
        
        # 气泡消失回调
        self._on_hidden_callback = None
        
        # 创建透明度动画
        self._opacity_anim = QPropertyAnimation(self, b"opacity")
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._opacity_anim.finished.connect(self._on_animation_finished)
        
        # 自动隐藏定时器
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.start_fade_out)
        
        # 设置字体 (可爱圆体)
        self._font = self._create_cute_font()
        self.setFont(self._font)
    
    def _create_cute_font(self) -> QFont:
        """创建可爱风格的字体"""
        font = get_default_font(11)  # 稍微大一点
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        return font
    
    def set_on_hidden_callback(self, callback):
        """
        设置气泡完全隐藏后的回调
        
        Args:
            callback: 无参数的可调用对象
        """
        self._on_hidden_callback = callback
    
    def show_message(self, text: str, auto_hide: bool = True, duration: int = None):
        """
        显示消息
        
        Args:
            text: 要显示的文本 (最多2行)
            auto_hide: 是否自动隐藏
            duration: 自动隐藏延迟 (毫秒), 默认使用配置值
        """
        # 停止之前的定时器
        self._auto_hide_timer.stop()
        self._opacity_anim.stop()
        
        self._text = text
        self._calculate_size()
        self.update()
        
        self.show()
        self.raise_()
        
        # 淡入动画
        self._start_fade_in()
        
        # 自动隐藏
        if auto_hide:
            delay = duration or self._auto_hide_delay
            self._auto_hide_timer.start(delay)
    
    def show_typing(self, auto_hide: bool = False):
        """
        显示"正在输入"状态 (可爱的省略号)
        
        Args:
            auto_hide: 是否自动隐藏
        """
        self.show_message("...", auto_hide=auto_hide)
    
    def hide_bubble(self, trigger_callback: bool = True):
        """
        立即隐藏气泡
        
        Args:
            trigger_callback: 是否触发隐藏回调
        """
        self._auto_hide_timer.stop()
        self._opacity_anim.stop()
        self._opacity = 0
        
        # 触发回调
        if trigger_callback and self._on_hidden_callback:
            callback = self._on_hidden_callback
            self._on_hidden_callback = None  # 防止重复调用
            callback()
        
        self.hide()
    
    def set_auto_hide_delay(self, delay: int):
        """设置自动隐藏延迟"""
        self._auto_hide_delay = delay
    
    def set_opacity(self, value: float):
        """设置透明度 (0-1)"""
        self._opacity = value
        self.update()
    
    def get_opacity(self) -> float:
        """获取当前透明度"""
        return self._opacity
    
    # 使用 pyqtProperty 让 QPropertyAnimation 可以操作
    opacity = pyqtProperty(float, get_opacity, set_opacity)
    
    def _calculate_size(self):
        """根据文本计算气泡尺寸"""
        from PyQt6.QtGui import QFontMetrics
        
        fm = QFontMetrics(self._font)
        
        # 限制行数
        lines = self._text.split('\n')[:self.cfg.max_lines]
        max_line_width = 0
        
        for line in lines:
            line_width = fm.horizontalAdvance(line)
            max_line_width = max(max_line_width, line_width)
        
        # 添加内边距 (更宽松)
        padding = self.cfg.padding + 4  # 额外4px让文字不挤
        width = min(max_line_width + 2 * padding, self.cfg.max_width)
        width = max(width, self.cfg.min_width)
        
        # 计算高度
        line_height = fm.height()
        height = len(lines) * line_height + 2 * padding + self.cfg.tail_height
        height = max(height, self.cfg.min_height + self.cfg.tail_height)
        
        self._target_size = (width, height)
        self.resize(width, height)
    
    def _start_fade_in(self):
        """开始淡入动画"""
        self._opacity_anim.stop()
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.setDuration(self._fade_in_duration)
        self._opacity_anim.start()
    
    def start_fade_out(self):
        """开始淡出动画"""
        self._opacity_anim.stop()
        self._opacity_anim.setStartValue(self._opacity)
        self._opacity_anim.setEndValue(0.0)
        self._opacity_anim.setDuration(self._fade_out_duration)
        self._opacity_anim.start()
    
    def _on_animation_finished(self):
        """动画结束回调"""
        if self._opacity <= 0:
            # 完全透明，隐藏并触发回调
            self.hide()
            if self._on_hidden_callback:
                callback = self._on_hidden_callback
                self._on_hidden_callback = None
                callback()
    
    def paintEvent(self, event):
        """绘制气泡 (优化版)"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        # 设置透明度
        painter.setOpacity(self._opacity)
        
        width = self.width()
        height = self.height()
        tail_h = self.cfg.tail_height
        tail_w = self.cfg.tail_width
        radius = self.cfg.corner_radius
        
        # 尾巴位置 (水平居中，稍微偏右一点更自然)
        tail_center_x = int(width * 0.55)  # 尾巴在55%位置
        
        # 1. 绘制阴影 (先画，在最底层)
        shadow_offset = 3
        shadow_path = self._create_bubble_path(
            width, height, tail_h, tail_w, radius, tail_center_x,
            offset_x=shadow_offset, offset_y=shadow_offset
        )
        painter.setBrush(QBrush(self.COLORS['shadow']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(shadow_path)
        
        # 2. 绘制渐变背景
        bg_path = self._create_bubble_path(
            width, height, tail_h, tail_w, radius, tail_center_x
        )
        
        # 创建柔和的垂直渐变
        gradient = QLinearGradient(0, 0, 0, height - tail_h)
        gradient.setColorAt(0, self.COLORS['bg_start'])
        gradient.setColorAt(1, self.COLORS['bg_end'])
        
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(bg_path)
        
        # 3. 绘制边框
        pen = QPen(self.COLORS['border'], 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(bg_path)
        
        # 4. 绘制小高光点 (装饰)
        highlight_size = 8
        highlight_x = 15
        highlight_y = 15
        highlight_grad = QRadialGradient(
            highlight_x, highlight_y, highlight_size
        )
        highlight_grad.setColorAt(0, QColor(255, 255, 255, 180))
        highlight_grad.setColorAt(1, QColor(255, 255, 255, 0))
        
        painter.setBrush(QBrush(highlight_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            int(highlight_x - highlight_size/2),
            int(highlight_y - highlight_size/2),
            highlight_size, highlight_size
        )
        
        # 5. 绘制文本
        painter.setPen(self.COLORS['text'])
        painter.setFont(self._font)
        
        text_rect = self.rect()
        text_rect.setBottom(text_rect.bottom() - tail_h)
        
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter,
            self._text
        )
        
        painter.end()
    
    def _create_bubble_path(
        self, width, height, tail_h, tail_w, radius,
        tail_center_x, offset_x=0, offset_y=0
    ) -> QPainterPath:
        """
        创建气泡形状路径
        
        Args:
            width: 气泡宽度
            height: 气泡高度
            tail_h: 尾巴高度
            tail_w: 尾巴宽度
            radius: 圆角半径
            tail_center_x: 尾巴中心X坐标
            offset_x: X偏移 (用于阴影)
            offset_y: Y偏移 (用于阴影)
            
        Returns:
            QPainterPath: 气泡路径
        """
        path = QPainterPath()
        
        # 主体 (圆角矩形)
        body_rect = path.addRoundedRect(
            offset_x, offset_y,
            width, height - tail_h,
            radius, radius
        )
        
        # 尾巴三角形 (稍微圆润)
        tail_top = height - tail_h + offset_y
        tail_bottom = height + offset_y
        tail_left = tail_center_x - tail_w // 2 + offset_x
        tail_right = tail_center_x + tail_w // 2 + offset_x
        
        tail_polygon = QPolygonF([
            QPointF(tail_left, tail_top),
            QPointF(tail_right, tail_top),
            QPointF(tail_center_x, tail_bottom),
        ])
        
        path.addPolygon(tail_polygon)
        
        return path
    
    def mousePressEvent(self, event):
        """拦截鼠标事件，防止穿透"""
        event.accept()
    
    def mouseReleaseEvent(self, event):
        """拦截鼠标事件，防止穿透"""
        event.accept()
