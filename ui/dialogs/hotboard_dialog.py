"""
ui/dialogs/hotboard_dialog.py - 热榜看板弹窗

多平台热榜在同一窗口通过 Tab 页展示。
无边框、圆角、自绘背景，风格与 stats_panel 一致。
支持拖拽移动、ESC 关闭。

继承 ManagedDialog 统一窗口行为：
- dock_visible=True: 打开时出现在程序坞/任务栏，关闭后恢复
- frameless=True: 无边框 + 半透明背景
"""
from PyQt6.QtCore import Qt, QSize, QRectF, QPoint, QRect, QPointF
from PyQt6.QtGui import (
    QFont, QColor, QDesktopServices, QCursor, QPainter, QBrush, QPen,
)
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QWidget, QLabel, QScrollArea, QVBoxLayout, QHBoxLayout,
    QPushButton, QFrame, QSizePolicy, QTabWidget, QTabBar,
)

from ui.base.managed_dialog import ManagedDialog
from core.logger import setup_logger

logger = setup_logger()

# 配色（与 stats_panel 一致）
BG_COLOR = QColor(255, 245, 230, 250)
TEXT_COLOR = QColor(80, 60, 40)
HOT_COLOR = QColor(220, 80, 60)
BORDER_COLOR = QColor(255, 190, 80, 200)
TITLE_COLOR = QColor(160, 110, 50)
HOVER_BG = QColor(255, 245, 220)
# Tab 配色
TAB_BG = QColor(250, 230, 195)
TAB_BG_TEXT = QColor(140, 100, 60)
TAB_ACTIVE = QColor(255, 248, 235)
TAB_ACTIVE_TEXT = QColor(210, 110, 30)
TAB_ACCENT = QColor(255, 160, 60)


# ========================================================================
# 自绘关闭按钮的 QTabBar 子类
#   —— 完全抛弃 setTabsClosable / setTabButton / QSS image / setIcon
#   —— 关闭按钮在 paintEvent 里画，位置精确到 tab 右上角
# ========================================================================
class CustomTabBar(QTabBar):
    """关闭按钮完全自绘的 QTabBar：
    - 按钮画在每个 tab 的右上角（不是垂直居中）
    - 三态：normal 浅棕X / hover 暖红圆+白X / pressed 深红圆+白X
    - 不创建任何子 widget，不影响 tab 布局，不会导致拥挤或拉伸
    """

    CLOSE_BTN_SIZE = 16
    CLOSE_BTN_MARGIN = 3  # 按钮距 tab 右边缘和上边缘的距离

    def __init__(self, parent=None):
        super().__init__(parent)
        # 不用原生 close-button，完全自绘
        self.setTabsClosable(False)
        self.setExpanding(False)
        self.setMouseTracking(True)
        self._hovered_tab = -1
        self._hovered_close = False
        self._pressed_close = False

    # ------------------------------------------------------------------
    # 关闭按钮矩形计算
    # ------------------------------------------------------------------
    def _close_button_rect(self, index: int) -> QRect:
        """返回 tab index 对应的关闭按钮矩形（右上角）"""
        tab_rect = self.tabRect(index)
        s = self.CLOSE_BTN_SIZE
        m = self.CLOSE_BTN_MARGIN
        x = tab_rect.right() - s - m
        y = tab_rect.top() + m
        return QRect(x, y, s, s)

    # ------------------------------------------------------------------
    # 自绘
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        """先让 QTabBar 画 tab 本身，再叠加关闭按钮"""
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i in range(self.count()):
            self._draw_close_button(p, self._close_button_rect(i), i)

    def _draw_close_button(self, p: QPainter, rect: QRect, tab_index: int):
        """绘制单个关闭按钮"""
        is_hover = (tab_index == self._hovered_tab and self._hovered_close)
        is_pressed = is_hover and self._pressed_close

        rf = QRectF(rect)

        if is_pressed:
            p.setBrush(QBrush(QColor(200, 60, 50)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(rf)
            pen = QPen(QColor(255, 255, 255))
        elif is_hover:
            p.setBrush(QBrush(QColor(232, 88, 76)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(rf)
            pen = QPen(QColor(255, 255, 255))
        else:
            pen = QPen(QColor(150, 110, 70))

        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        # X 线段：在按钮矩形内缩 4px
        m = 4
        p.drawLine(
            QPointF(rect.left() + m, rect.top() + m),
            QPointF(rect.right() - m, rect.bottom() - m),
        )
        p.drawLine(
            QPointF(rect.right() - m, rect.top() + m),
            QPointF(rect.left() + m, rect.bottom() - m),
        )

    # ------------------------------------------------------------------
    # 鼠标交互
    # ------------------------------------------------------------------
    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        old_tab = self._hovered_tab
        old_close = self._hovered_close

        self._hovered_tab = -1
        self._hovered_close = False
        for i in range(self.count()):
            if self.tabRect(i).contains(pos):
                self._hovered_tab = i
                if self._close_button_rect(i).contains(pos):
                    self._hovered_close = True
                break

        if old_tab != self._hovered_tab or old_close != self._hovered_close:
            self.update()

        # 让 QTabBar 自己处理 tab hover 高亮
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            for i in range(self.count()):
                if self._close_button_rect(i).contains(pos):
                    self._pressed_close = True
                    self._hovered_tab = i
                    self._hovered_close = True
                    self.update()
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_close:
            self._pressed_close = False
            pos = event.position().toPoint()
            for i in range(self.count()):
                if self._close_button_rect(i).contains(pos):
                    self.update()
                    self.tabCloseRequested.emit(i)
                    event.accept()
                    return
            self.update()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._hovered_tab = -1
        self._hovered_close = False
        self._pressed_close = False
        self.update()
        super().leaveEvent(event)


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
        # 搜索结果字段（websearch 工具），热榜条目无这些字段则不显示
        snippet = item.get("snippet", "")
        domain = item.get("domain", "")
        publish_time = item.get("publish_time", "")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        rank_label = QLabel(f"{index}")
        rank_font = QFont()
        rank_font.setPointSize(14)
        rank_font.setBold(True)
        rank_label.setFont(rank_font)
        rank_label.setStyleSheet(f"color: {TITLE_COLOR.name()};")
        rank_label.setFixedWidth(28)
        rank_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(rank_label)

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

        # 搜索结果：摘要（截断避免卡片过高）
        if snippet:
            if len(snippet) > 110:
                snippet = snippet[:110] + "…"
            snippet_label = QLabel(snippet)
            snippet_font = QFont()
            snippet_font.setPointSize(9)
            snippet_label.setFont(snippet_font)
            snippet_label.setStyleSheet(f"color: {QColor(150, 120, 90).name()};")
            snippet_label.setWordWrap(True)
            text_layout.addWidget(snippet_label)

        # 搜索结果：来源域名 + 发布日期
        if domain or publish_time:
            meta_parts = []
            if domain:
                meta_parts.append(f"🌐 {domain}")
            if publish_time:
                meta_parts.append(f"🕒 {publish_time}")
            meta_label = QLabel(" · ".join(meta_parts))
            meta_font = QFont()
            meta_font.setPointSize(9)
            meta_label.setFont(meta_font)
            meta_label.setStyleSheet(f"color: {TITLE_COLOR.name()};")
            text_layout.addWidget(meta_label)

        layout.addLayout(text_layout, 1)
        self._url = url

    def mousePressEvent(self, event):
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))
        super().mousePressEvent(event)


class HotboardPage(QWidget):
    """单个平台的热榜/搜索结果页面（分批懒渲染）"""

    BATCH_SIZE = 15  # 初始渲染条数，滚动到底后再渲染一批

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: transparent;")

        self._all_items: list = list(items or [])
        self._rendered_count = 0
        self._loading_more = False

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
            QScrollBar:handle:vertical {{
                background: {BORDER_COLOR.name()};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {QColor(255, 180, 60).name()};
            }}
            QScrollBar:add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background-color: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(12, 4, 12, 12)
        self._list_layout.setSpacing(6)

        self._populate(self._all_items)

        scroll.setWidget(self._list_widget)
        # 滚动到底自动渲染下一批
        scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        layout.addWidget(scroll)
        self._scroll = scroll

    def _populate(self, items: list):
        """重置页面：保存全量数据，只渲染第一批"""
        self._all_items = list(items or [])
        self._rendered_count = 0
        self._clear_cards()
        self._render_next_batch()

    def _clear_cards(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 提示条已销毁，重置引用（下次重新创建）
        self._load_more_tip = None

    def _render_next_batch(self):
        """渲染下一批条目（BATCH_SIZE 条），保持布局顺序: 卡片 → 加载提示 → stretch"""
        if not self._all_items:
            tip = QLabel("😿 暂无数据\n可能是平台不支持或网络请求失败")
            tip_font = QFont()
            tip_font.setPointSize(13)
            tip_font.setBold(True)
            tip.setFont(tip_font)
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setStyleSheet(
                f"color: {TITLE_COLOR.name()}; padding: 40px 20px; line-height: 1.5;"
            )
            self._list_layout.addWidget(tip)
            self._list_layout.addStretch()
            self._rendered_count = 0
            return

        # 1) 移除尾部的提示条和 stretch（下一批渲染后重新追加）
        self._take_tail_items()

        # 2) 渲染新一批卡片
        start = self._rendered_count
        batch = self._all_items[start:start + self.BATCH_SIZE]
        for i, item in enumerate(batch, start + 1):
            self._list_layout.addWidget(HotboardItemCard(i, item))
        self._rendered_count += len(batch)

        # 3) 重新追加提示条（如还有剩余）和 stretch
        remaining = len(self._all_items) - self._rendered_count
        if remaining > 0:
            self._list_layout.addWidget(self._ensure_load_more_tip(remaining))
        self._list_layout.addStretch()

    def _take_tail_items(self):
        """从布局移除加载提示条和尾部 stretch（下一批渲染后重新追加）"""
        tip = getattr(self, "_load_more_tip", None)
        i = 0
        while i < self._list_layout.count():
            item = self._list_layout.itemAt(i)
            is_tip = tip is not None and item.widget() is tip
            is_spacer = item.widget() is None  # spacerItem（stretch）无 widget
            if is_tip or is_spacer:
                self._list_layout.takeAt(i)
            else:
                i += 1

    def _ensure_load_more_tip(self, remaining: int) -> QLabel:
        """获取（或创建）"加载更多"提示条，并更新剩余条数"""
        tip = getattr(self, "_load_more_tip", None)
        if tip is None:
            tip = QLabel()
            tip_font = QFont()
            tip_font.setPointSize(11)
            tip_font.setBold(True)
            tip.setFont(tip_font)
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            tip.setStyleSheet(f"color: {TITLE_COLOR.name()}; padding: 10px;")
            tip.mousePressEvent = lambda e: self._load_more()
            self._load_more_tip = tip
        tip.setText(f"↓ 加载更多（还有 {remaining} 条）")
        tip.setVisible(True)
        return tip

    def _load_more(self):
        """加载下一批（渲染中防重入）"""
        if self._loading_more:
            return
        self._loading_more = True
        try:
            if self._rendered_count < len(self._all_items):
                self._render_next_batch()
        finally:
            self._loading_more = False

    def _on_scroll(self, value: int):
        """滚动接近底部时自动加载下一批"""
        sb = self._scroll.verticalScrollBar()
        # 距底 < 60px 视为到底
        if sb.maximum() - value <= 60:
            if self._rendered_count < len(self._all_items):
                self._load_more()

    def update_items(self, items: list):
        self._populate(items)


class HotboardDialog(ManagedDialog):
    """多平台热榜看板弹窗（无边框、圆角、Tab 页结构）"""

    def __init__(self, parent=None):
        super().__init__(parent, dock_visible=True, frameless=True)
        self.setWindowTitle("🔥 热榜看板")

        self.setMinimumSize(QSize(480, 520))
        self.resize(QSize(560, 640))

        self._dragging = False
        self._drag_offset = QPoint()
        self._type_to_index: dict[str, int] = {}

        self._build_ui()

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

        # Tab 样式 —— 不含任何 close-button 规则（关闭按钮在 CustomTabBar.paintEvent 里自绘）
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
            QTabBar {{
                background: transparent;
                border: none;
                spacing: 4px;
            }}
            QTabBar::tab {{
                background-color: {TAB_BG.name()};
                color: {TAB_BG_TEXT.name()};
                /* 左右 padding 对称 → 文字居中；
                   右侧 22px 覆盖 close按钮(16px+3px边距+3px间隙) → 文字不会延伸到按钮下方 */
                padding: 6px 22px 6px 22px;
                /* 不设 min/max-width，tab 宽度随文字长短自适应 */
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

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 8)

        title_label = QLabel("🔥 热榜看板")
        title_label.setObjectName("title")
        self._title_label = title_label
        header.addWidget(title_label)
        header.addStretch()

        close_btn = QPushButton("✕ 关闭")
        close_btn.setObjectName("closeBtn")
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)

        layout.addLayout(header)

        # Tab 页 —— 用 CustomTabBar 替换默认 QTabBar
        self._tabs = QTabWidget()
        custom_bar = CustomTabBar(self._tabs)
        self._tabs.setTabBar(custom_bar)
        self._tabs.setAutoFillBackground(False)
        custom_bar.setAutoFillBackground(False)
        custom_bar.setMovable(True)
        custom_bar.tabCloseRequested.connect(self._on_tab_close)

        layout.addWidget(self._tabs, 1)

    # ========================================================================
    # 绘制圆角背景
    # ========================================================================
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        rect.adjust(1, 1, -1, -1)
        painter.setBrush(QBrush(BG_COLOR))
        painter.setPen(QPen(BORDER_COLOR, 2))
        painter.drawRoundedRect(rect, 16, 16)

    # ========================================================================
    # 拖拽 + ESC 关闭
    # ========================================================================
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)

    # ========================================================================
    # 公共接口
    # ========================================================================
    def set_board_title(self, title: str):
        """设置看板窗口标题（不同需求不同标题，如热榜/搜索结果）"""
        if title:
            self._title_label.setText(title)
            self.setWindowTitle(title)

    def add_or_update_hotboard(self, type: str, type_display: str, items: list, board_title: str = ""):
        # 不同需求不同标题（如搜索结果），不传则保持当前标题
        if board_title:
            self.set_board_title(board_title)

        if type in self._type_to_index:
            index = self._type_to_index[type]
            page = self._tabs.widget(index)
            if page:
                page.update_items(items)
                self._tabs.setTabText(index, type_display)
                logger.debug(f"[HotboardDialog] 更新标签: {type_display}")
        else:
            page = HotboardPage(items)
            index = self._tabs.addTab(page, type_display)
            self._type_to_index[type] = index
            self._tabs.setCurrentIndex(index)
            logger.debug(f"[HotboardDialog] 新增标签: {type_display}")

        self.show_dialog()

    def _on_tab_close(self, index: int):
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

        updated = {}
        for t, old_idx in self._type_to_index.items():
            new_idx = old_idx if old_idx < index else old_idx - 1
            updated[t] = new_idx
        self._type_to_index = updated

        cur = self._tabs.currentIndex()
        if cur >= 0 and index <= cur and self._tabs.count() > 0:
            self._tabs.setCurrentIndex(max(0, cur - 1))

        if self._tabs.count() == 0:
            self.accept()

    def show_dialog(self):
        if self.result() != 0:
            self.setResult(0)
        # showEvent 会由 ManagedDialog 自动处理 dock 可见性
        self.show()
        self.raise_()
        self.activateWindow()
        logger.debug(f"[HotboardDialog] show_dialog 完成, visible={self.isVisible()}, winId={int(self.winId())}")
