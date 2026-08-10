"""
动作栏组件 - 显示动作按钮（投喂/玩耍/抚摸/睡觉）

点击按钮触发对应动作，动作栏与输入框一起显示/隐藏。
鼠标悬停按钮时 tooltip 立即显示，无等待延迟。
"""
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QObject, QEvent, QPoint
from PyQt6.QtGui import QIcon, QPixmap, QCursor
from PyQt6.QtWidgets import QWidget, QPushButton, QHBoxLayout, QToolTip

from core.platform import IS_WINDOWS
from core.paths import get_resource_path


class _TooltipFilter(QObject):
    """事件过滤器：鼠标进入按钮立即显示 tooltip，离开立即隐藏"""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if isinstance(obj, QPushButton):
            if event.type() == QEvent.Type.Enter:
                tip = obj.toolTip()
                if tip:
                    # 在按钮中心下方一点的位置显示 tooltip
                    global_pos = obj.mapToGlobal(QPoint(obj.width() // 2, obj.height() + 2))
                    QToolTip.showText(global_pos, tip, obj)
            elif event.type() == QEvent.Type.Leave:
                QToolTip.hideText()
        return super().eventFilter(obj, event)


class ActionBar(QWidget):
    """
    动作栏组件

    功能:
        - 4 个动作按钮：投喂/玩耍/抚摸/睡觉
        - 水平排列，大小一致
        - 透明背景，不抢焦点
        - 鼠标悬停按钮立即显示 tooltip（无延迟）
        - 点击按钮发出 action_triggered 信号

    信号:
        action_triggered(str): 动作 ID ('feed'/'play'/'pet'/'sleep')
    """

    # 动作触发信号
    action_triggered = pyqtSignal(str)

    # 动作定义: (action_id, 图标文件名, tooltip)
    ACTIONS = [
        ('feed', 'eatting_icon.png', '投喂'),
        ('play', 'playing_icon.png', '玩耍'),
        ('pet', 'touch_icon.png', '抚摸'),
        ('sleep', 'sleeping_icon.png', '睡觉'),
    ]

    BUTTON_SIZE = 48
    ICON_SIZE = 28

    def __init__(self, parent=None):
        super().__init__(parent)

        # 窗口属性：无边框 + Tool + 透明背景 + 不抢焦点
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.setFixedHeight(self.BUTTON_SIZE + 8)

        self._tooltip_filter = _TooltipFilter(self)

        self._init_ui()

    def _load_icon(self, filename: str) -> QIcon:
        """从 assets/icons/app 加载图标，适配高 DPI"""
        icon_path = str(get_resource_path(f'assets/icons/app/{filename}'))
        pix = QPixmap(icon_path)
        icon = QIcon()
        # 多尺寸: 1x, 2x, 3x，确保 Retina 屏清晰
        for dpr in (1, 2, 3):
            scaled = pix.scaled(
                self.ICON_SIZE * dpr, self.ICON_SIZE * dpr,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            icon.addPixmap(scaled)
        return icon

    def _init_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self._buttons = {}
        for action_id, icon_file, tip in self.ACTIONS:
            btn = QPushButton(self)
            btn.setFixedSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setIcon(self._load_icon(icon_file))
            btn.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
            btn.setStyleSheet(self._button_style())
            btn.clicked.connect(
                lambda checked, aid=action_id: self.action_triggered.emit(aid)
            )
            # 安装事件过滤器，让 tooltip 立即显示
            btn.installEventFilter(self._tooltip_filter)
            layout.addWidget(btn)
            self._buttons[action_id] = btn

    @staticmethod
    def _button_style() -> str:
        """按钮样式（白色底板 + 圆角，与输入框风格一致）"""
        return """
        QPushButton {
            background-color: rgba(255, 255, 255, 235);
            border: 2px solid rgba(220, 220, 220, 200);
            border-radius: 14px;
        }
        QPushButton:hover {
            background-color: rgba(255, 245, 230, 250);
            border-color: rgba(255, 200, 100, 230);
        }
        QPushButton:pressed {
            background-color: rgba(255, 235, 200, 250);
        }
        """

    def show_bar(self):
        """显示动作栏"""
        if IS_WINDOWS:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.show()
        self.raise_()
        if IS_WINDOWS:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def hide_bar(self):
        """隐藏动作栏"""
        QToolTip.hideText()  # 隐藏时同时清掉可能残留的 tooltip
        self.hide()

    def mousePressEvent(self, event):
        """拦截鼠标事件，防止穿透到下层"""
        event.accept()

    def mouseReleaseEvent(self, event):
        """拦截鼠标事件，防止穿透到下层"""
        event.accept()
