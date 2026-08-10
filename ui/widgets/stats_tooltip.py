"""
宠物状态悬停浮层

鼠标悬停在宠物上 0.5 秒后显示，移开即消失。
轻量级自绘组件，实时读取 PetStats 数值。

风格：暖黄色系（与 stats_panel / action_bar 一致）
"""
from typing import Optional, Callable

from PyQt6.QtCore import Qt, QTimer, QRect, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QFontMetrics
from PyQt6.QtWidgets import QWidget

from core import get_default_font, IS_MAC
from core.logger import setup_logger
from core.topmost import set_window_topmost
from pet.pet_stats import PetStats

logger = setup_logger()


# 状态项配置：(字段名, 显示名, emoji)
STAT_ITEMS = [
    ('satiety',  '饱食', '🍎'),
    ('mood',     '心情', '😊'),
    ('energy',   '体力', '⚡'),
    ('intimacy', '亲密', '❤️'),
]


def _bar_color_by_value(v: float) -> QColor:
    """进度条颜色按数值分档（与 stats_panel 一致）"""
    if v < 30:
        return QColor(235, 90, 90)      # 低 - 红
    if v < 60:
        return QColor(255, 150, 60)     # 中 - 橙
    return QColor(255, 190, 80)         # 高 - 暖黄


class StatsTooltip(QWidget):
    """宠物状态悬停浮层

    使用方式：
        tooltip = StatsTooltip(stats_provider=lambda: pet.stats)
        tooltip.show_at(pet.x(), pet.y())
        tooltip.hide()

    特点：
    - 无边框、透明背景、置顶
    - 自绘 4 行迷你状态条
    - 实时读取数值（每次 show 前刷新）
    """

    # 浮层尺寸
    TOOLTIP_W = 180
    TOOLTIP_H = 96
    PADDING = 12
    ROW_H = 18
    BAR_H = 8
    BAR_RADIUS = 4

    def __init__(self, stats_provider: Callable[[], Optional[PetStats]], parent=None):
        """
        Args:
            stats_provider: 返回 PetStats 实例的可调用对象（实时读取数值）
        """
        super().__init__(parent)
        self._stats_provider = stats_provider

        # 窗口标志完全照搬宠物自身（pet.py）
        # 不用 Qt.Tool（macOS 下反而会触发激活），靠 set_window_topmost 在系统层置顶
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # 不抢焦点
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # 字体
        self._font = get_default_font(11)
        self._font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.setFont(self._font)

        self.resize(self.TOOLTIP_W, self.TOOLTIP_H)

    # ========================================================================
    # 显示/隐藏
    # ========================================================================
    def show_at(self, pet_x: int, pet_y: int, pet_w: int, pet_h: int,
                screen_w: int, screen_h: int, avoid_above: bool = False):
        """在宠物上方显示浮层（水平居中），空间不够时放下方

        Args:
            pet_x, pet_y: 宠物窗口左上角坐标
            pet_w, pet_h: 宠物宽高
            screen_w, screen_h: 屏幕可用区域尺寸
            avoid_above: True=宠物上方有气泡，浮层强制放下方
        """
        # 水平：相对宠物水平居中
        x = pet_x + (pet_w - self.TOOLTIP_W) // 2
        # 边界兜底
        x = max(0, min(x, screen_w - self.TOOLTIP_W))

        # 垂直：默认放宠物上方（头顶），空间不够或避让气泡时放下方
        gap = 8
        if avoid_above:
            y = pet_y + pet_h + gap
        else:
            y = pet_y - gap - self.TOOLTIP_H
            if y < 0:
                y = pet_y + pet_h + gap

        # 垂直边界兜底
        y = max(0, min(y, screen_h - self.TOOLTIP_H))

        self.move(x, y)
        # macOS 关键：在 show() 之前先配置 NSWindow，否则 show() 会触发 makeKeyAndOrderFront 抢焦点
        # winId() 会触发窗口创建（如果还没创建），此时 NSWindow 已可用
        self._configure_nswindow_before_show()
        self.show()
        # show 之后再确认一次置顶（show 可能重置 level）
        self._setup_topmost()

    def _configure_nswindow_before_show(self):
        """show() 之前配置 NSWindow：禁止成为 key/main window"""
        if not IS_MAC:
            return
        try:
            import objc
            # winId() 触发窗口创建，此时 NSWindow 已存在
            win_id = int(self.winId())
            if not win_id:
                return
            ns_view = objc.objc_object(c_void_p=win_id)
            ns_window = ns_view.window()
            if ns_window is not None:
                ns_window.setCanBecomeKey_(False)
                ns_window.setCanBecomeMain_(False)
        except Exception:
            pass

    def hide_tooltip(self):
        """隐藏浮层"""
        self.hide()

    def _setup_topmost(self):
        """系统级置顶 + 禁止成为 key window（彻底不抢焦点）

        macOS: setCanBecomeKey_(False) 必须在窗口 show() 之后立即调用，
              防止 Qt 默认让它成为 key window 抢走焦点。
        Windows: SWP_NOACTIVATE 标志保证不抢焦点。
        """
        if IS_MAC:
            try:
                import objc
                from AppKit import NSStatusWindowLevel
                win_id = int(self.winId())
                if win_id:
                    ns_view = objc.objc_object(c_void_p=win_id)
                    ns_window = ns_view.window()
                    if ns_window is not None:
                        # 关键：禁止窗口成为 key/main window，彻底避免抢焦点
                        ns_window.setCanBecomeKey_(False)
                        ns_window.setCanBecomeMain_(False)
                        ns_window.setLevel_(NSStatusWindowLevel)
                        # orderFrontRegardless 不会激活应用
                        ns_window.orderFrontRegardless()
                        return
            except Exception:
                pass
        # fallback / Windows
        set_window_topmost(self)

    # ========================================================================
    # 绘制
    # ========================================================================
    def paintEvent(self, event):
        """自绘浮层"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        radius = 10

        # 1. 阴影
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(QRectF(2, 2, w - 2, h - 2), radius, radius)
        painter.setBrush(QBrush(QColor(0, 0, 0, 50)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(shadow_path)

        # 2. 背景（暖白渐变）
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(1, 1, w - 3, h - 3), radius, radius)
        from PyQt6.QtGui import QLinearGradient
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0, QColor(255, 250, 235, 250))
        gradient.setColorAt(1, QColor(255, 245, 220, 250))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(bg_path)

        # 3. 边框
        pen = QPen(QColor(255, 200, 100, 200), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(bg_path)

        # 4. 4 行状态
        stats = self._stats_provider() if self._stats_provider else None
        if stats is None:
            painter.end()
            return

        fm = QFontMetrics(self._font)
        name_w = 36   # 名称固定宽度
        emoji_w = 20  # emoji 固定宽度
        bar_x = self.PADDING + emoji_w + name_w
        bar_w = w - bar_x - self.PADDING - 30  # 右侧留 30 给数值
        value_x = bar_x + bar_w + 4

        for i, (field, name, emoji) in enumerate(STAT_ITEMS):
            y = self.PADDING + i * self.ROW_H

            # emoji
            painter.setPen(QColor(100, 70, 40))
            painter.drawText(
                QRect(self.PADDING, y - 2, emoji_w, self.ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                emoji
            )

            # 名称
            painter.setPen(QColor(110, 80, 50))
            painter.drawText(
                QRect(self.PADDING + emoji_w, y - 2, name_w, self.ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name
            )

            # 数值
            value = getattr(stats, field, 0.0)
            value_int = int(round(value))

            # 进度条背景
            bar_y = y + (self.ROW_H - self.BAR_H) // 2
            painter.setBrush(QBrush(QColor(255, 255, 255, 180)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(
                QRect(bar_x, bar_y, bar_w, self.BAR_H),
                self.BAR_RADIUS, self.BAR_RADIUS
            )

            # 进度条填充
            fill_w = int((value / 100.0) * bar_w)
            if fill_w > 0:
                painter.setBrush(QBrush(_bar_color_by_value(value)))
                painter.drawRoundedRect(
                    QRect(bar_x, bar_y, fill_w, self.BAR_H),
                    self.BAR_RADIUS, self.BAR_RADIUS
                )

            # 数值文字
            painter.setPen(QColor(100, 70, 40))
            painter.drawText(
                QRect(value_x, y - 2, 28, self.ROW_H),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(value_int)
            )

        painter.end()
