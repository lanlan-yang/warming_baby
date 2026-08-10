"""飘字组件：动作加分反馈

点击投喂/玩耍/抚摸后，在宠物头顶飘出 "+20 饱食度" 小标签，
向上飘动并淡出（约 1.5 秒）。

风格：无边框透明窗口、不抢焦点、置顶。
"""
from PyQt6.QtCore import Qt, QPoint, QRectF, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QFont, QFontMetrics
from PyQt6.QtWidgets import QWidget

from core.logger import setup_logger

logger = setup_logger()


# 状态字段 → 中文名
STAT_NAMES_CN: dict[str, str] = {
    'satiety': '饱食度',
    'mood': '心情',
    'energy': '体力',
    'intimacy': '亲密度',
}


def changes_to_lines(changes: dict[str, float]) -> list[tuple[str, QColor]]:
    """
    把 changes dict 转成可显示的 (文本, 颜色) 列表

    Args:
        changes: {'satiety': 20.0, 'mood': 5.0, 'energy': -10.0}

    Returns:
        [('+20 饱食度', 绿色), ('+5 心情', 绿色), ('-10 体力', 红色)]
    """
    lines: list[tuple[str, QColor]] = []
    for key, delta in changes.items():
        name = STAT_NAMES_CN.get(key, key)
        # 去掉浮点尾数（+20.0 → +20，+3.5 → +3.5）
        if float(delta).is_integer():
            sign = '+' if delta >= 0 else ''
            text = f"{sign}{int(delta)} {name}"
        else:
            sign = '+' if delta >= 0 else ''
            text = f"{sign}{delta:.1f} {name}"
        # 正数绿色，负数红色（alpha=255 完全不透明）
        color = QColor(80, 170, 90, 255) if delta >= 0 else QColor(220, 80, 80, 255)
        lines.append((text, color))
    return lines


class FloatingText(QWidget):
    """飘字组件：向上飘动 + 淡出"""

    def __init__(self, lines: list[tuple[str, QColor]], parent=None):
        """
        Args:
            lines: [(文本, 颜色), ...] 由 changes_to_lines 生成
            parent: 父窗口
        """
        super().__init__(parent)
        self._lines = lines
        self._opacity = 1.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool  # 不抢焦点、不在任务栏显示
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        # 字体
        self._font = QFont()
        self._font.setPointSize(13)
        self._font.setBold(True)

        # 计算尺寸
        self._calc_size()

    def _calc_size(self):
        """根据文字内容计算窗口尺寸"""
        fm = QFontMetrics(self._font)
        max_w = 0
        total_h = 0
        line_h = fm.height() + 2
        for text, _ in self._lines:
            w = fm.horizontalAdvance(text)
            if w > max_w:
                max_w = w
            total_h += line_h
        # 加 padding
        self.setFixedSize(max_w + 16, total_h + 12)

    # ========================================================================
    # 透明度属性（供 QPropertyAnimation 驱动）
    # ========================================================================
    @pyqtProperty(float)
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float):
        self._opacity = value
        self.update()

    # ========================================================================
    # 绘制
    # ========================================================================
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)
        painter.setOpacity(self._opacity)

        fm = QFontMetrics(self._font)
        line_h = fm.height() + 2
        y = fm.ascent() + 4

        for text, color in self._lines:
            # 文字居中
            x = (self.width() - fm.horizontalAdvance(text)) // 2
            # 描边（白色阴影，提升可读性）
            painter.setPen(QColor(255, 255, 255, 220))
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                painter.drawText(x + dx, y + dy, text)
            # 主文字
            painter.setPen(color)
            painter.drawText(x, y, text)
            y += line_h

    # ========================================================================
    # 显示 + 动画
    # ========================================================================
    def showEvent(self, event):
        super().showEvent(event)
        self._start_animation()

    def _start_animation(self):
        """启动飘动 + 淡出动画"""
        # 延迟一帧启动，确保窗口已显示
        QTimer.singleShot(30, self._do_animate)

    def _do_animate(self):
        """向上飘 40px + 透明度 1→0，时长 2500ms（更从容）"""
        # 透明度动画（前 800ms 保持全不透明，后 1700ms 缓慢淡出）
        self._opacity_anim = QPropertyAnimation(self, b"opacity", self)
        self._opacity_anim.setDuration(2500)
        self._opacity_anim.setStartValue(1.0)
        self._opacity_anim.setKeyValueAt(0.32, 1.0)  # 前 800ms 保持全不透明
        self._opacity_anim.setKeyValueAt(1.0, 0.0)   # 后 1700ms 淡出
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 位移动画（向上飘 40px）
        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(2500)
        self._pos_anim.setStartValue(self.pos())
        self._pos_anim.setEndValue(self.pos() + QPoint(0, -40))
        self._pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 动画结束关闭窗口
        self._opacity_anim.finished.connect(self.close)

        self._pos_anim.start()
        self._opacity_anim.start()
