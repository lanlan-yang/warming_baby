"""
ui/dialogs/hotboard_dialog.py - 热榜看板弹窗

多平台热榜在同一窗口通过 Tab 页展示。
无边框、圆角、自绘背景，风格与 stats_panel 一致。
支持拖拽移动、ESC 关闭。
"""
from PyQt6.QtCore import Qt, QSize, QRectF, QPoint
from PyQt6.QtGui import (
    QFont, QColor, QDesktopServices, QCursor, QPainter, QBrush, QPen,
)
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QDialog, QWidget, QLabel, QScrollArea, QVBoxLayout, QHBoxLayout,
    QPushButton, QFrame, QSizePolicy, QTabWidget, QTabBar,
)

from core.logger import setup_logger

logger = setup_logger()

# 配色（与 stats_panel 一致）
BG_COLOR = QColor(255, 245, 230, 250)
TEXT_COLOR = QColor(80, 60, 40)
HOT_COLOR = QColor(220, 80, 60)
BORDER_COLOR = QColor(255, 190, 80, 200)
TITLE_COLOR = QColor(160, 110, 50)
HOVER_BG = QColor(255, 245, 220)
# Tab 配色：整体浅色，选中态用底部橙色高亮线突出
TAB_BG = QColor(250, 230, 195)         # 未选中 Tab 背景（浅杏）
TAB_BG_TEXT = QColor(140, 100, 60)      # 未选中 Tab 文字（深棕）
TAB_ACTIVE = QColor(255, 248, 235)      # 选中 Tab + 面板背景（暖白）
TAB_ACTIVE_TEXT = QColor(210, 110, 30)   # 选中 Tab 文字（暖橙）
TAB_ACCENT = QColor(255, 160, 60)        # 选中 Tab 底部高亮线


class HotboardItemCard(QFrame):
    """单条热榜条目卡片"""

    def __init__(self, index: int, item: dict, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            HotboardItemCard {{
                background-color: white;
                border: 1px solid {BORDER_COLOR.name()};
                border-radius: 8px;
            }}
            HotboardItemCard:hover {{
                background-color: {HOVER_BG.name()};
            }}
        """)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        title = item.get("title", "未知")
        hot = item.get("hot_value", "")
        url = item.get("url", "")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        # 排名
        rank_label = QLabel(f"{index}")
        rank_font = QFont()
        rank_font.setPointSize(14)
        rank_font.setBold(True)
        rank_label.setFont(rank_font)
        rank_label.setStyleSheet(f"color: {TITLE_COLOR.name()};")
        rank_label.setFixedWidth(28)
        rank_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(rank_label)

        # 标题 + 热度
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {TEXT_COLOR.name()};")
        title_label.setWordWrap(True)
        title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        text_layout.addWidget(title_label)

        if hot:
            hot_label = QLabel(f"🔥 {hot}")
            hot_font = QFont()
            hot_font.setPointSize(10)
            hot_label.setFont(hot_font)
            hot_label.setStyleSheet(f"color: {HOT_COLOR.name()};")
            text_layout.addWidget(hot_label)

        layout.addLayout(text_layout, 1)

        self._url = url

    def mousePressEvent(self, event):
        """点击打开链接"""
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))
        super().mousePressEvent(event)


class HotboardPage(QWidget):
    """单个平台的热榜页面"""

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {BORDER_COLOR.name()};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {QColor(255, 180, 60).name()};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background-color: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(12, 4, 12, 12)
        self._list_layout.setSpacing(6)

        self._populate(items)

        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll)

    def _populate(self, items: list):
        """填充热榜条目"""
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, item in enumerate(items, 1):
            card = HotboardItemCard(i, item)
            self._list_layout.addWidget(card)

        self._list_layout.addStretch()

    def update_items(self, items: list):
        """更新热榜条目"""
        self._populate(items)


class HotboardDialog(QDialog):
    """多平台热榜看板弹窗（无边框、圆角、Tab 页结构）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔥 热榜看板")

        # 无边框 + 透明背景（自绘圆角）
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.setMinimumSize(QSize(480, 520))
        self.resize(QSize(560, 640))

        # 拖拽状态
        self._dragging = False
        self._drag_offset = QPoint()

        # 已添加的平台 type → tab index 映射
        self._type_to_index: dict[str, int] = {}

        self._build_ui()

        # 子控件样式（QDialog 背景由 paintEvent 绘制）
        # 样式表在 _build_ui 之后应用，确保子控件创建后能正确继承样式
        self.setStyleSheet(f"""
            QDialog {{
                background: transparent;
            }}
            QLabel#title {{
                color: {TITLE_COLOR.name()};
                font-size: 15px;
                font-weight: bold;
                background: transparent;
            }}
            QPushButton#closeBtn {{
                background-color: rgba(255, 190, 80, 220);
                border: none;
                border-radius: 8px;
                padding: 6px 18px;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton#closeBtn:hover {{
                background-color: rgba(255, 170, 60, 240);
            }}
        """)

        # Tab 样式单独应用到 QTabWidget
        tab_style = f"""
            QTabWidget {{
                background: transparent;
                border: none;
            }}
            QTabWidget::pane {{
                border: 1px solid {BORDER_COLOR.name()};
                border-radius: 8px;
                background-color: {TAB_ACTIVE.name()};
                top: 6px;
            }}
            QTabWidget::tab-bar {{
                background: transparent;
                left: 10px;
            }}
            QTabWidget::corner-button {{
                background: transparent;
                border: none;
            }}
            QTabBar {{
                background: transparent;
                border: none;
                spacing: 4px;
            }}
            QTabBar::tab {{
                background-color: {TAB_BG.name()};
                color: {TAB_BG_TEXT.name()};
                padding: 6px 14px;
                min-width: 70px;
                max-width: 100px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border: 1px solid {BORDER_COLOR.name()};
                border-bottom: none;
                margin-right: 0px;
                font-weight: 600;
                font-size: 13px;
            }}
            QTabBar::tab:selected {{
                background-color: {TAB_ACTIVE.name()};
                color: {TAB_ACTIVE_TEXT.name()};
                border-bottom: 3px solid {TAB_ACCENT.name()};
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {TAB_ACTIVE.name()};
                color: {TAB_ACTIVE_TEXT.name()};
            }}
        """
        self._tabs.setStyleSheet(tab_style)
        self._tabs.tabBar().setStyleSheet("background: transparent;")

    def _build_ui(self):
        """构建 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(0)

        # 标题栏
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 8)

        title_label = QLabel("🔥 热榜看板")
        title_label.setObjectName("title")
        header.addWidget(title_label)
        header.addStretch()

        close_btn = QPushButton("✕ 关闭")
        close_btn.setObjectName("closeBtn")
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)

        layout.addLayout(header)

        # Tab 页
        self._tabs = QTabWidget()
        self._tabs.setAutoFillBackground(False)
        self._tabs.tabBar().setAutoFillBackground(False)
        self._tabs.tabBar().setMovable(True)
        # 注意：不要 setTabsClosable(True)，否则右侧 close-button 占位会把文字挤偏
        self._tabs.tabBar().setTabsClosable(False)

        layout.addWidget(self._tabs, 1)

    # ========================================================================
    # 绘制圆角背景
    # ========================================================================
    def paintEvent(self, event):
        """绘制圆角背景（透明窗口下样式表 background 不生效）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect())
        rect.adjust(1, 1, -1, -1)

        # 暖黄色背景
        painter.setBrush(QBrush(BG_COLOR))
        painter.setPen(QPen(BORDER_COLOR, 2))
        painter.drawRoundedRect(rect, 16, 16)

    # ========================================================================
    # 拖拽 + ESC 关闭
    # ========================================================================
    def mousePressEvent(self, event):
        """按下左键：开始拖拽（标题栏区域）"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        """拖拽中：移动窗口"""
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        """释放：结束拖拽"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()

    def keyPressEvent(self, event):
        """ESC 关闭"""
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)

    # ========================================================================
    # 公共接口
    # ========================================================================
    def add_or_update_hotboard(self, type: str, type_display: str, items: list):
        """添加或更新热榜标签页"""
        if type in self._type_to_index:
            index = self._type_to_index[type]
            page = self._tabs.widget(index)
            if page:
                page.update_items(items)
                self._tabs.setTabText(index, type_display)
                logger.info(f"[HotboardDialog] 更新标签: {type_display}")
        else:
            page = HotboardPage(items)
            index = self._tabs.addTab(page, type_display)
            self._type_to_index[type] = index
            self._tabs.setCurrentIndex(index)
            logger.info(f"[HotboardDialog] 新增标签: {type_display}")

        self.show_dialog()

    def _on_tab_close(self, index: int):
        """关闭标签页"""
        type_key = None
        for t, idx in self._type_to_index.items():
            if idx == index:
                type_key = t
                break
        if type_key:
            del self._type_to_index[type_key]

        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if widget:
            widget.deleteLater()

        if self._tabs.count() == 0:
            self.accept()

    def show_dialog(self):
        """显示弹窗。对已关闭(accept)的弹窗自动重置状态，确保每次都能弹出。"""
        # 如果窗口被 accept() 关闭过，result() == Accepted，此时再次
        # show() 不会显示内容，必须先 reset() 重置结果码。
        if self.result() != 0:
            self.setResult(0)

        # macOS 上 frameless + topmost 需要额外调用
        try:
            from core.topmost import set_window_topmost
            set_window_topmost(self)
        except Exception:
            pass
        self.show()
        self.raise_()
        self.activateWindow()
        logger.info(f"[HotboardDialog] show_dialog 完成, visible={self.isVisible()}, winId={int(self.winId())}")
