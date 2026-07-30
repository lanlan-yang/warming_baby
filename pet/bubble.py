"""
对话气泡组件 - 漫画风格
圆角矩形 + 底部小三角尾巴，指向宠物头部
"""
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QPoint, QPointF, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QPolygonF
from PyQt6.QtWidgets import QWidget
from core import get_default_font


class SpeechBubble(QWidget):
    """
    漫画风格对话气泡
    
    样式:
    - 圆角矩形背景 (80% 白色透明度)
    - 暖黄色边框
    - 底部中央小三角尾巴
    
    功能:
    - 淡入淡出动画
    - 自动消失 (默认3秒)
    - 支持多行文本
    """
    
    # 气泡尺寸常量
    PADDING = 12          # 内边距
    MIN_WIDTH = 80        # 最小宽度
    MAX_WIDTH = 200       # 最大宽度
    MIN_HEIGHT = 30       # 最小高度
    TAIL_HEIGHT = 10      # 尾巴高度
    TAIL_WIDTH = 12       # 尾巴宽度
    CORNER_RADIUS = 15    # 圆角半径
    
    # 颜色常量
    BG_COLOR = QColor(255, 255, 255, 220)       # 背景: 86%透明度白色
    BORDER_COLOR = QColor(255, 200, 100)        # 边框: 暖黄色
    TEXT_COLOR = QColor(60, 60, 60)             # 文字: 深灰色
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
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
        
        # 透明度动画
        self._opacity = 0
        self._fade_in_duration = 200   # 淡入 200ms
        self._fade_out_duration = 300  # 淡出 300ms
        self._auto_hide_delay = 3000   # 自动隐藏 3秒
        
        # 创建透明度属性
        self._opacity_anim = QPropertyAnimation(self, b"opacity")
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        
        # 自动隐藏定时器
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.start_fade_out)
        
        # 设置字体（跨平台自动选择）
        self._font = get_default_font(10)
        self.setFont(self._font)
    
    def show_message(self, text: str, auto_hide: bool = True, duration: int = None):
        """
        显示消息
        
        Args:
            text: 要显示的文本 (最多2行)
            auto_hide: 是否自动隐藏
            duration: 自动隐藏延迟 (毫秒), 默认 3000
        """
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
        显示"正在输入"状态 (...)
        
        Args:
            auto_hide: 是否自动隐藏
        """
        self.show_message("...", auto_hide=auto_hide)
    
    def hide_bubble(self):
        """立即隐藏气泡"""
        self._auto_hide_timer.stop()
        self._opacity_anim.stop()
        self._opacity = 0
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
        
        # 限制为2行
        lines = self._text.split('\n')[:2]
        max_line_width = 0
        
        for line in lines:
            line_width = fm.horizontalAdvance(line)
            max_line_width = max(max_line_width, line_width)
        
        # 添加内边距
        width = min(max_line_width + 2 * self.PADDING, self.MAX_WIDTH)
        width = max(width, self.MIN_WIDTH)
        
        # 计算高度: 2行 * 行高 + 内边距 + 尾巴
        line_height = fm.height()
        height = len(lines) * line_height + 2 * self.PADDING + self.TAIL_HEIGHT
        height = max(height, self.MIN_HEIGHT + self.TAIL_HEIGHT)
        
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
        self._opacity_anim.finished.connect(self.hide)
        self._opacity_anim.start()
    
    def paintEvent(self, event):
        """绘制气泡"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 设置透明度
        painter.setOpacity(self._opacity)
        
        width = self.width()
        height = self.height()
        
        # 计算尾巴位置 (水平居中)
        tail_center_x = width // 2
        
        # 创建路径
        path = QPainterPath()
        
        # 1. 圆角矩形主体
        rect_height = height - self.TAIL_HEIGHT
        path.addRoundedRect(
            0, 0, width, rect_height,
            self.CORNER_RADIUS, self.CORNER_RADIUS
        )
        
        # 2. 底部三角形尾巴
        tail_left = tail_center_x - self.TAIL_WIDTH // 2
        tail_right = tail_center_x + self.TAIL_WIDTH // 2
        
        # 绘制带尾巴的路径
        tail_polygon = QPolygonF([
            QPointF(tail_left, rect_height),
            QPointF(tail_right, rect_height),
            QPointF(tail_center_x, height)
        ])
        
        path.addPolygon(tail_polygon)
        
        # 绘制背景
        painter.setBrush(QBrush(self.BG_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
        
        # 绘制边框
        pen = QPen(self.BORDER_COLOR, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        
        # 绘制文本
        painter.setPen(self.TEXT_COLOR)
        painter.setFont(self._font)
        
        text_rect = self.rect()
        text_rect.setBottom(text_rect.bottom() - self.TAIL_HEIGHT)
        
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter,
            self._text
        )
        
        painter.end()
    
    def mousePressEvent(self, event):
        """拦截鼠标事件，防止穿透到下层"""
        event.accept()
    
    def mouseReleaseEvent(self, event):
        """拦截鼠标事件，防止穿透到下层"""
        event.accept()
