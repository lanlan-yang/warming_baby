"""
ui/dialogs/mcp_manager.py - MCP 能力管理器

左列表（server 卡片 + 状态徽标）+ 右详情（配置表单 + 操作按钮）布局。
支持：添加/编辑/删除、stdio/remote 两种传输、测试连接、启停、
Claude Desktop JSON 批量导入、未授权 server 的安装授权确认。

风格与 stats_panel / hotboard_dialog 一致：暖黄色系、无边框圆角、白卡片。

继承 ManagedDialog 统一窗口行为：
- dock_visible=True: 打开时出现在程序坞/任务栏，关闭后恢复
- frameless=True: 无边框 + 半透明背景（自绘圆角）

状态事件：订阅 SystemEvent.MCP_SERVER_STATE，server 状态变化实时刷新列表；
异步操作（测试/启停）通过 asyncio 任务跑在 qasync 主循环上，
结果经 Qt 信号回到 UI 线程。
"""
import asyncio
import re
import shlex
import time

from PyQt6.QtCore import Qt, QRectF, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ui.base.managed_dialog import ManagedDialog
from core.logger import setup_logger
from tools.mcp import mcp_client_manager
from tools.mcp.mcp_schema import (
    McpServerState, RemoteTransport, StdioTransport, McpServerConfig,
    McpErrorCode, McpManagerError,
)
from tools.mcp.mcp_store import parse_claude_config

logger = setup_logger()

# 配色（与 stats_panel / hotboard_dialog 一致）
BG_COLOR = QColor(255, 245, 230, 250)
TEXT_COLOR = QColor(80, 60, 40)
RED_COLOR = QColor(220, 80, 60)
BORDER_COLOR = QColor(255, 190, 80, 200)
TITLE_COLOR = QColor(160, 110, 50)
GRAY_COLOR = QColor(150, 120, 90)
GREEN_COLOR = QColor(76, 160, 80)
ORANGE_COLOR = QColor(240, 150, 40)
TAB_BG = QColor(250, 230, 195)

# 工具数告警阈值（绑定给 LLM 的工具总数）
TOOL_COUNT_WARN = 20

# 状态渲染表: 状态 → (圆点色, 状态文字)
STATE_STYLES = {
    McpServerState.DISABLED: (GRAY_COLOR, "已禁用"),
    McpServerState.IDLE: (GRAY_COLOR, "已就绪"),
    McpServerState.STARTING: (ORANGE_COLOR, "启动中…"),
    McpServerState.RUNNING: (GREEN_COLOR, "运行中"),
    McpServerState.STOPPING: (ORANGE_COLOR, "停止中…"),
    McpServerState.FAILED: (RED_COLOR, "连接失败"),
}

# 错误码 → 中文提示（卡片与操作结果共用；未收录的码回退原始错误）
_ERROR_HINTS = {
    McpErrorCode.START_TIMEOUT: "启动超时（stdio 首次启动可能需要下载依赖，可再试一次）",
    McpErrorCode.HANDSHAKE_FAILED: "握手失败：已连上 server，但初始化协议未通过",
    McpErrorCode.DISCOVERY_FAILED: "获取工具列表失败：连接已建立，但 server 未正常响应",
    McpErrorCode.CONNECTION_LOST: "运行中连接断开，可尝试重新启动",
    McpErrorCode.HTTP_ERROR: "HTTP 连接失败：检查地址是否正确、网络是否可达",
    McpErrorCode.INVALID_CONFIG: "配置无效，请检查填写内容",
}

# 命令名 → 需要安装的运行环境
_CMD_RUNTIME = {
    "npx": "Node.js",
    "node": "Node.js",
    "uvx": "uv（pip install uv）",
    "uv": "uv（pip install uv）",
    "python": "Python",
    "docker": "Docker",
}


def _friendly_error(error_code, raw: str) -> str:
    """把底层英文报错翻译成用户能看懂的中文提示"""
    if error_code == McpErrorCode.RUNTIME_NOT_FOUND:
        # 取最后一个引号串: McpManagerError 文本里还带 server 名（第一个引号串）
        quoted = re.findall(r"'([^']+)'", raw)
        cmd = quoted[-1] if quoted else "启动命令"
        runtime = _CMD_RUNTIME.get(cmd, f"运行 {cmd} 所需的环境")
        return f"没找到 {cmd} 命令，请先安装 {runtime}"
    return _ERROR_HINTS.get(error_code, raw)


def _parse_kv(text: str) -> dict:
    """解析 'KEY=VALUE,KEY=VALUE' 形式的键值对（VALUE 中允许含 =）"""
    result = {}
    for part in text.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def _format_kv(data: dict) -> str:
    """dict → 'KEY=VALUE, KEY=VALUE'（回显用）"""
    return ", ".join(f"{k}={v}" for k, v in data.items())


def _parse_args(text: str) -> list:
    """参数字符串 → argv（shlex 处理引号）"""
    text = text.strip()
    return shlex.split(text) if text else []


class ServerCard(QFrame):
    """左侧列表的单个 server 卡片（可点击选中）"""

    def __init__(self, name: str, display: str, state_text: str,
                 dot_color: QColor, sub_text: str, selected: bool, parent=None):
        super().__init__(parent)
        self._name = name
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        border = QColor(255, 160, 60) if selected else BORDER_COLOR
        bg = QColor(255, 248, 235) if selected else QColor(255, 255, 255)
        self.setStyleSheet(f"""
            ServerCard {{
                background-color: {bg.name()};
                border: 1px solid {border.name()};
                border-radius: 8px;
            }}
            ServerCard:hover {{
                background-color: {QColor(255, 245, 220).name()};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {dot_color.name()}; font-size: 12px;")
        top.addWidget(dot)
        name_label = QLabel(display)
        name_label.setStyleSheet(
            f"color: {TEXT_COLOR.name()}; font-size: 13px; font-weight: bold;"
        )
        top.addWidget(name_label, 1)
        state_label = QLabel(state_text)
        state_label.setStyleSheet(
            f"color: {dot_color.name()}; font-size: 11px;"
        )
        top.addWidget(state_label)
        layout.addLayout(top)

        sub = QLabel(sub_text)
        sub.setStyleSheet(f"color: {GRAY_COLOR.name()}; font-size: 10px;")
        sub.setWordWrap(True)
        layout.addWidget(sub)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if hasattr(window, "select_server"):
                window.select_server(self._name)
        super().mousePressEvent(event)


class McpManagerDialog(ManagedDialog):
    """MCP 能力管理器（左列表 + 右详情）"""

    # 状态事件 payload（McpServerStatus.model_dump()）→ UI 线程
    _state_changed = pyqtSignal(dict)
    # 异步操作完成: (操作名, 是否成功, 消息)
    _op_done = pyqtSignal(str, bool, str)

    def __init__(self, parent=None):
        super().__init__(parent, dock_visible=True, frameless=True)
        self.setWindowTitle("🔌 MCP 能力管理")

        self.setMinimumSize(QSize(680, 540))
        self.resize(QSize(780, 620))

        self._selected: str = ""      # 当前选中的 server name
        self._is_new_draft: bool = False  # 右侧是否为"新建草稿"
        self._trusted_draft: bool = False

        self._dragging = False
        self._drag_offset = QPoint()

        self._build_ui()
        self._apply_styles()
        self._refresh_list()
        self._load_editor_empty()

        self._state_changed.connect(self._on_state_changed)
        self._op_done.connect(self._on_op_done)

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # ---- 头部 ----
        header = QHBoxLayout()
        header.setSpacing(8)
        self._title_label = QLabel("🔌 MCP 能力管理")
        self._title_label.setObjectName("title")
        header.addWidget(self._title_label)
        self._count_label = QLabel("")
        self._count_label.setObjectName("countHint")
        header.addWidget(self._count_label)
        header.addStretch()

        import_btn = QPushButton("📥 粘贴 JSON")
        import_btn.setObjectName("warmBtn")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(self._on_import_json)
        header.addWidget(import_btn)

        close_btn = QPushButton("✕ 关闭")
        close_btn.setObjectName("closeBtn")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # ---- 主体: 左列表 + 右详情 ----
        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._build_left_panel(), 0)
        body.addWidget(self._build_right_panel(), 1)
        layout.addLayout(body, 1)

        # ---- 底部状态栏 ----
        self._status_label = QLabel(" ")
        self._status_label.setObjectName("statusBar")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("leftPanel")
        panel.setFixedWidth(210)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: transparent; width: 6px; margin: 0;
            }
            QScrollBar:handle:vertical {
                background: rgba(255, 190, 80, 200); border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 6, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll, 1)

        add_btn = QPushButton("＋ 添加 Server")
        add_btn.setObjectName("warmBtn")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_clicked)
        layout.addWidget(add_btn)
        return panel

    def _build_right_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: transparent; width: 6px; margin: 0;
            }
            QScrollBar:handle:vertical {
                background: rgba(255, 190, 80, 200); border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

        self._editor = QWidget()
        self._editor.setStyleSheet("background: transparent;")
        root = QVBoxLayout(self._editor)
        root.setContentsMargins(6, 0, 6, 6)
        root.setSpacing(10)

        # ---- 状态卡 ----
        self._status_card = QFrame()
        self._status_card.setObjectName("card")
        status_layout = QVBoxLayout(self._status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(4)

        self._state_line = QHBoxLayout()
        self._state_dot = QLabel("○")
        self._state_dot.setStyleSheet("font-size: 13px;")
        self._state_line.addWidget(self._state_dot)
        self._state_text = QLabel("未选择")
        self._state_text.setStyleSheet(
            f"color: {GRAY_COLOR.name()}; font-size: 13px; font-weight: bold;"
        )
        self._state_line.addWidget(self._state_text)
        self._state_line.addStretch()
        self._transport_badge = QLabel("")
        self._transport_badge.setStyleSheet(
            f"color: {TITLE_COLOR.name()}; font-size: 11px;"
            f"background: {TAB_BG.name()}; border-radius: 6px; padding: 2px 8px;"
        )
        self._state_line.addWidget(self._transport_badge)
        status_layout.addLayout(self._state_line)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            f"color: {RED_COLOR.name()}; font-size: 11px;"
        )
        self._error_label.hide()
        status_layout.addWidget(self._error_label)

        self._tools_label = QLabel("")
        self._tools_label.setWordWrap(True)
        self._tools_label.setStyleSheet(
            f"color: {GRAY_COLOR.name()}; font-size: 11px;"
        )
        status_layout.addWidget(self._tools_label)
        root.addWidget(self._status_card)

        # ---- 表单卡 ----
        form_card = QFrame()
        form_card.setObjectName("card")
        form = QVBoxLayout(form_card)
        form.setContentsMargins(12, 10, 12, 12)
        form.setSpacing(8)

        self._add_form_row(form, "名称:", self._mk_input("name_input", "如 my-search"))
        self._add_form_row(form, "描述:", self._mk_input("desc_input", "展示名/用途（可选）"))

        type_row = QHBoxLayout()
        type_label = QLabel("传输类型:")
        type_label.setFixedWidth(64)
        type_row.addWidget(type_label)
        self._type_combo = QComboBox()
        self._type_combo.addItem("本地进程 (stdio)", "stdio")
        self._type_combo.addItem("远程 HTTP (remote)", "remote")
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo, 1)
        form.addLayout(type_row)

        # stdio 分组
        self._stdio_box = QFrame()
        stdio_layout = QVBoxLayout(self._stdio_box)
        stdio_layout.setContentsMargins(0, 0, 0, 0)
        stdio_layout.setSpacing(8)
        self._add_form_row(stdio_layout, "命令:", self._mk_input("cmd_input", "npx / node / uvx …"))
        self._add_form_row(stdio_layout, "参数:", self._mk_input("args_input", "-y xxx-yyy-mcp"))
        self._add_form_row(stdio_layout, "环境变量:", self._mk_input("env_input", "KEY=VALUE, …"))
        form.addWidget(self._stdio_box)

        # remote 分组
        self._remote_box = QFrame()
        remote_layout = QVBoxLayout(self._remote_box)
        remote_layout.setContentsMargins(0, 0, 0, 0)
        remote_layout.setSpacing(8)
        self._add_form_row(remote_layout, "URL:", self._mk_input("url_input", "https://host/mcp"))
        self._add_form_row(remote_layout, "请求头:", self._mk_input("headers_input", "Authorization=Bearer xxx"))
        form.addWidget(self._remote_box)

        self._enable_check = QCheckBox("启用（应用启动时自动加载）")
        self._enable_check.setStyleSheet(f"color: {TEXT_COLOR.name()}; font-size: 12px;")
        form.addWidget(self._enable_check)
        root.addWidget(form_card)

        # ---- 按钮区 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._save_btn = self._mk_action_btn("💾 保存", self._on_save_clicked)
        self._test_btn = self._mk_action_btn("🔌 测试连接", self._on_test_clicked)
        self._start_btn = self._mk_action_btn("▶ 启动", self._on_start_clicked)
        self._stop_btn = self._mk_action_btn("■ 停止", self._on_stop_clicked)
        self._delete_btn = self._mk_action_btn("🗑 删除", self._on_delete_clicked, danger=True)
        for b in (self._save_btn, self._test_btn, self._start_btn,
                  self._stop_btn, self._delete_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        root.addLayout(btn_row)
        root.addStretch()

        scroll.setWidget(self._editor)
        return scroll

    def _add_form_row(self, layout: QVBoxLayout, label_text: str, editor: QWidget):
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setFixedWidth(64)
        label.setStyleSheet(f"color: {TEXT_COLOR.name()}; font-size: 12px;")
        row.addWidget(label)
        row.addWidget(editor, 1)
        layout.addLayout(row)

    def _mk_input(self, attr_name: str, placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        setattr(self, f"_{attr_name}", edit)
        return edit

    def _mk_action_btn(self, text: str, slot, danger: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("dangerBtn" if danger else "plainBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QLabel#title {{
                color: {TITLE_COLOR.name()};
                font-size: 15px;
                font-weight: bold;
                background: transparent;
            }}
            QLabel#countHint {{
                color: {GRAY_COLOR.name()};
                font-size: 12px;
                background: transparent;
            }}
            QLabel#statusBar {{
                color: {GRAY_COLOR.name()};
                font-size: 12px;
                background: transparent;
                padding: 2px 4px;
            }}
            QFrame#leftPanel {{
                background: transparent;
                border: none;
            }}
            QFrame#card {{
                background-color: white;
                border: 1px solid {BORDER_COLOR.name()};
                border-radius: 8px;
            }}
            QLineEdit, QComboBox {{
                background-color: white;
                border: 1px solid {BORDER_COLOR.name()};
                border-radius: 6px;
                padding: 5px 8px;
                color: {TEXT_COLOR.name()};
                font-size: 12px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {QColor(255, 160, 60).name()};
            }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QPushButton#warmBtn {{
                background-color: rgba(255, 190, 80, 220);
                border: none;
                border-radius: 8px;
                padding: 6px 14px;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton#warmBtn:hover {{
                background-color: rgba(255, 170, 60, 240);
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
            QPushButton#plainBtn {{
                background-color: {TAB_BG.name()};
                border: 1px solid {BORDER_COLOR.name()};
                border-radius: 8px;
                padding: 6px 14px;
                color: {TITLE_COLOR.name()};
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton#plainBtn:hover {{
                background-color: {QColor(255, 240, 215).name()};
            }}
            QPushButton#plainBtn:disabled {{
                color: {QColor(190, 175, 160).name()};
                background-color: {QColor(245, 240, 232).name()};
            }}
            QPushButton#dangerBtn {{
                background-color: {QColor(250, 235, 230).name()};
                border: 1px solid {QColor(235, 160, 140).name()};
                border-radius: 8px;
                padding: 6px 14px;
                color: {RED_COLOR.name()};
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton#dangerBtn:hover {{
                background-color: {QColor(248, 225, 218).name()};
            }}
            QPushButton#dangerBtn:disabled {{
                color: {QColor(210, 180, 170).name()};
                background-color: {QColor(245, 240, 232).name()};
            }}
        """)

    # ============================================================
    # 绘制圆角背景 + 拖拽 + ESC
    # ============================================================
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        rect.adjust(1, 1, -1, -1)
        painter.setBrush(QBrush(BG_COLOR))
        painter.setPen(QPen(BORDER_COLOR, 2))
        painter.drawRoundedRect(rect, 16, 16)

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

    # ============================================================
    # 事件订阅（状态实时刷新）
    # ============================================================
    def showEvent(self, event):
        super().showEvent(event)
        try:
            from core import event_bus, EventCategory, SystemEvent
            event_bus.subscribe(
                EventCategory.SYSTEM, SystemEvent.MCP_SERVER_STATE,
                self._on_event_published,
            )
        except Exception as e:
            logger.warning(f"[McpManager] 订阅状态事件失败: {e}")
        self._refresh_list()

    def done(self, result):
        try:
            from core import event_bus, EventCategory, SystemEvent
            event_bus.unsubscribe(
                EventCategory.SYSTEM, SystemEvent.MCP_SERVER_STATE,
                self._on_event_published,
            )
        except Exception:
            pass
        super().done(result)

    def _on_event_published(self, data: dict):
        """event_bus 回调 → Qt 信号转到 UI 线程"""
        self._state_changed.emit(dict(data or {}))

    def _on_state_changed(self, data: dict):
        """UI 线程: 某个 server 状态变化 → 刷新列表与详情"""
        name = (data or {}).get("name", "")
        self._refresh_list()
        if name and name == self._selected:
            # 只刷新状态区（不动表单，避免打断输入）
            self._refresh_status_area()

    # ============================================================
    # 列表与编辑器渲染
    # ============================================================
    def _refresh_list(self):
        statuses = mcp_client_manager.list_statuses()

        # 清空旧卡片（hide 保证立即不可见，deleteLater 负责析构）
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        if not statuses:
            hint = QLabel("还没有 MCP 能力\n点下方添加，或用「粘贴 JSON」批量导入")
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet(
                f"color: {GRAY_COLOR.name()}; font-size: 12px; padding: 24px 8px;"
            )
            self._list_layout.addWidget(hint)
        else:
            for st in statuses:
                dot, state_text = STATE_STYLES.get(st.state, (GRAY_COLOR, str(st.state)))
                if st.state == McpServerState.RUNNING and st.tool_count:
                    sub = f"{st.tool_count} 个工具"
                elif st.transport_type == "remote":
                    sub = "远程 HTTP"
                else:
                    sub = "本地进程"
                display = mcp_client_manager.get_display_name(st.name)
                card = ServerCard(
                    st.name, display or st.name, state_text, dot, sub,
                    selected=(st.name == self._selected),
                )
                self._list_layout.addWidget(card)
        self._list_layout.addStretch()

        # 头部统计: 运行数 + 工具总数告警（绑给 LLM 的工具越多越贵、选择越差）
        running = sum(1 for s in statuses if s.state == McpServerState.RUNNING)
        total_tools = sum(s.tool_count for s in statuses)
        if total_tools > TOOL_COUNT_WARN:
            self._count_label.setText(
                f"共 {len(statuses)} 个 · 运行 {running} · ⚠ 工具总数 {total_tools}（偏多，建议精简）"
            )
            self._count_label.setStyleSheet(
                f"color: {ORANGE_COLOR.name()}; font-size: 12px; background: transparent;"
            )
        else:
            self._count_label.setText(f"共 {len(statuses)} 个 · 运行 {running}")
            self._count_label.setStyleSheet(
                f"color: {GRAY_COLOR.name()}; font-size: 12px; background: transparent;"
            )

    def select_server(self, name: str):
        """左列表点击选中 → 加载详情"""
        cfg = mcp_client_manager.get_config(name)
        if cfg is None:
            return
        self._selected = name
        self._is_new_draft = False
        self._trusted_draft = cfg.trusted

        self._name_input.setText(cfg.name)
        self._name_input.setReadOnly(True)  # name 是身份标识，编辑态不可改
        self._desc_input.setText(cfg.description)
        if isinstance(cfg.transport, RemoteTransport):
            self._type_combo.setCurrentIndex(1)
            self._url_input.setText(cfg.transport.url)
            self._headers_input.setText(_format_kv(cfg.transport.headers))
        else:
            self._type_combo.setCurrentIndex(0)
            self._cmd_input.setText(cfg.transport.command)
            self._args_input.setText(" ".join(cfg.transport.args))
            self._env_input.setText(_format_kv(cfg.transport.env))
        self._enable_check.setChecked(cfg.enabled)

        self._on_type_changed()
        self._refresh_status_area()
        self._refresh_list()

    def _load_editor_empty(self):
        """右侧空态"""
        self._selected = ""
        self._is_new_draft = False
        self._state_dot.setText("○")
        self._state_dot.setStyleSheet(
            f"color: {GRAY_COLOR.name()}; font-size: 13px;"
        )
        self._state_text.setText("未选择 server")
        self._transport_badge.setText("")
        self._error_label.hide()
        self._tools_label.setText("从左侧选择一个 server，或点击「＋ 添加 Server」")
        self._name_input.setReadOnly(False)
        for edit in (self._name_input, self._desc_input, self._cmd_input,
                     self._args_input, self._env_input, self._url_input,
                     self._headers_input):
            edit.clear()
        self._enable_check.setChecked(True)
        self._type_combo.setCurrentIndex(0)
        self._on_type_changed()
        self._set_actions_enabled(False)

    def _refresh_status_area(self):
        """刷新右侧状态卡（不动表单输入）"""
        name = self._selected
        if not name:
            return
        st = mcp_client_manager.get_status(name)
        if st is None:
            return
        dot_color, state_text = STATE_STYLES.get(st.state, (GRAY_COLOR, str(st.state)))
        self._state_dot.setText("●")
        self._state_dot.setStyleSheet(f"color: {dot_color.name()}; font-size: 13px;")
        self._state_text.setText(state_text)
        badge = "远程 HTTP" if st.transport_type == "remote" else "本地进程"
        if not st.enabled:
            badge += " · 已禁用"
        if st.trusted:
            badge += " · 已授权"
        self._transport_badge.setText(badge)

        if st.error and st.state == McpServerState.FAILED:
            self._error_label.setText(f"✗ {_friendly_error(st.error_code, st.error)}")
            self._error_label.show()
        else:
            self._error_label.hide()

        if st.tool_names:
            self._tools_label.setText(
                f"🛠 提供工具 ({st.tool_count}): {', '.join(st.tool_names)}"
            )
        elif st.last_test and st.last_test.ok:
            self._tools_label.setText(
                f"上次测试: {st.last_test.tool_count} 个工具 · {st.last_test.duration_ms}ms"
            )
        else:
            self._tools_label.setText("")

        self._set_actions_enabled(True, st)

    def _set_actions_enabled(self, enabled: bool, status=None):
        """按状态控制操作按钮可用性"""
        self._save_btn.setEnabled(enabled)
        self._test_btn.setEnabled(enabled)
        self._delete_btn.setEnabled(enabled)
        if not enabled or status is None:
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            return
        can_start = status.state in (McpServerState.IDLE, McpServerState.FAILED) \
            and status.enabled
        can_stop = status.state in (McpServerState.RUNNING, McpServerState.FAILED)
        # 删除按钮任何状态都可用: 忙态 server 会自动"先停止再删除"
        self._start_btn.setEnabled(can_start)
        self._stop_btn.setEnabled(can_stop)

    def _on_type_changed(self):
        is_remote = self._type_combo.currentData() == "remote"
        self._stdio_box.setVisible(not is_remote)
        self._remote_box.setVisible(is_remote)

    # ============================================================
    # 表单 ↔ 配置
    # ============================================================
    def _form_to_config(self, name: str = None, trusted: bool = False) -> McpServerConfig:
        """从表单构造 McpServerConfig；校验失败抛 McpManagerError/pydantic 错误"""
        name = (name or self._name_input.text()).strip()
        if self._type_combo.currentData() == "remote":
            url = self._url_input.text().strip().strip("`").strip()
            transport = RemoteTransport(
                url=url, headers=_parse_kv(self._headers_input.text()),
            )
        else:
            transport = StdioTransport(
                command=self._cmd_input.text().strip() or "npx",
                args=_parse_args(self._args_input.text()),
                env=_parse_kv(self._env_input.text()),
            )
        return McpServerConfig(
            name=name,
            description=self._desc_input.text().strip(),
            transport=transport,
            enabled=self._enable_check.isChecked(),
            trusted=trusted,
        )

    # ============================================================
    # 异步操作（qasync 主循环）
    # ============================================================
    def _run_async(self, op_name: str, coro):
        """把协程挂到主事件循环，结果经信号回 UI"""
        async def _wrapper():
            try:
                await coro
                self._op_done.emit(op_name, True, "")
            except McpManagerError as e:
                # 管理器错误: 翻译成中文提示（底层英文细节进日志）
                logger.debug(f"[McpManager] {op_name}失败: {e}")
                self._op_done.emit(op_name, False, _friendly_error(e.code, str(e)))
            except Exception as e:
                self._op_done.emit(op_name, False, str(e))

        try:
            asyncio.ensure_future(_wrapper())
        except RuntimeError as e:
            self._set_status(False, f"事件循环不可用: {e}")

    def _on_op_done(self, op_name: str, ok: bool, message: str):
        """异步操作完成（UI 线程）"""
        if op_name == "删除":
            # 删除完成: 清理列表；若当前选中的正是被删的 server，重置编辑器
            self._refresh_list()
            if self._selected and mcp_client_manager.get_status(self._selected) is None:
                self._load_editor_empty()
            if ok:
                self._set_status(True, message or "✓ 已删除")
            else:
                self._set_status(False, f"✗ 删除失败: {message}")
            return

        # 重新启用按钮并刷新（按最新状态）
        if self._selected and not self._is_new_draft:
            self._refresh_status_area()
        else:
            self._set_actions_enabled(self._is_new_draft)
            if self._is_new_draft:
                self._start_btn.setEnabled(False)
                self._stop_btn.setEnabled(False)
                self._delete_btn.setEnabled(False)
        if ok:
            self._set_status(True, message or f"✓ {op_name}完成")
        else:
            self._set_status(False, f"✗ {op_name}失败: {message}")

    def _set_status(self, ok: bool, text: str):
        self._status_label.setText(text)
        color = GREEN_COLOR if ok else RED_COLOR
        self._status_label.setStyleSheet(
            f"color: {color.name()}; font-size: 12px;"
            f"background: transparent; padding: 2px 4px;"
        )

    # ============================================================
    # 按钮动作
    # ============================================================
    def _on_add_clicked(self):
        self._load_editor_empty()
        self._is_new_draft = True
        self._trusted_draft = False
        self._set_actions_enabled(True)  # 允许 保存/测试
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._state_dot.setText("＋")
        self._state_dot.setStyleSheet(
            f"color: {ORANGE_COLOR.name()}; font-size: 13px;"
        )
        self._state_text.setText("新建 server")
        self._transport_badge.setText("")
        self._tools_label.setText("填写后先「测试连接」，通过再「保存」")
        self._name_input.setFocus()

    def _on_save_clicked(self):
        try:
            if self._is_new_draft:
                config = self._form_to_config()
                mcp_client_manager.add_server(config)
                self._is_new_draft = False
                self._selected = config.name
                self._name_input.setReadOnly(True)
                self._set_status(True, f"✓ 已添加 '{config.name}'")
            elif self._selected:
                # 保留原 trusted 标记
                config = self._form_to_config(name=self._selected, trusted=self._trusted_draft)
                mcp_client_manager.update_server(config)
                self._set_status(True, f"✓ 已保存 '{config.name}'（运行中会自动重启）")
            self._refresh_list()
            self._refresh_status_area()
        except Exception as e:
            self._set_status(False, f"保存失败: {e}")

    def _on_test_clicked(self):
        try:
            config = self._form_to_config(
                name=self._name_input.text().strip() or "test",
                trusted=True,  # 测试是临时连接，无需授权
            )
        except Exception as e:
            self._set_status(False, f"配置无效: {e}")
            return

        self._test_btn.setEnabled(False)
        self._set_status(True, "⏳ 正在测试连接…")
        self._run_async("测试", self._test_and_report(config))

    async def _test_and_report(self, config: McpServerConfig):
        result = await mcp_client_manager.test_config(config)
        if result.ok:
            msg = f"✓ 连接成功，{result.tool_count} 个工具（{result.duration_ms}ms）"
            if result.tool_names:
                names = ", ".join(result.tool_names[:6])
                more = "…" if len(result.tool_names) > 6 else ""
                msg += f": {names}{more}"
            self._op_done.emit("测试", True, msg)
        else:
            self._op_done.emit("测试", False, result.message or result.error_code)

    def _on_start_clicked(self):
        name = self._selected
        if not name:
            return
        st = mcp_client_manager.get_status(name)
        if st and not st.trusted:
            cfg = mcp_client_manager.get_config(name)
            desc = cfg.description if cfg and cfg.description else name
            answer = QMessageBox.question(
                self, "授权第三方能力",
                f"「{desc}」是第三方 MCP 能力，启动后它的工具将可供暖宝调用"
                f"（可能访问网络、读写数据）。\n\n确认信任并启用吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            mcp_client_manager.set_trusted(name, True)
            self._trusted_draft = True

        self._start_btn.setEnabled(False)
        self._set_status(True, "⏳ 启动中…（stdio 首次启动可能需要下载依赖）")
        self._run_async("启动", self._start_and_report(name))

    async def _start_and_report(self, name: str):
        count = await mcp_client_manager.start_server(name)
        self._op_done.emit("启动", True, f"✓ '{name}' 已运行，提供 {count} 个工具")

    def _on_stop_clicked(self):
        name = self._selected
        if not name:
            return
        self._stop_btn.setEnabled(False)
        self._set_status(True, "⏳ 停止中…")
        self._run_async("停止", mcp_client_manager.stop_server(name))

    def _on_delete_clicked(self):
        name = self._selected
        if not name:
            return
        st = mcp_client_manager.get_status(name)
        busy = st is not None and st.state in (
            McpServerState.STARTING, McpServerState.RUNNING, McpServerState.STOPPING,
        )
        tip = "\n（正在启动/运行中的会先自动停止，再删除）" if busy else ""
        answer = QMessageBox.question(
            self, "删除 server",
            f"确定删除 '{name}' 吗？配置将一并移除。{tip}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if busy:
            # 忙态: 异步等启动/停止流程结束后先停再删，删除不再被状态卡住
            self._delete_btn.setEnabled(False)
            self._set_status(True, f"⏳ 正在停止并删除 '{name}'…")
            self._run_async("删除", self._stop_and_delete(name))
            return

        try:
            mcp_client_manager.remove_server(name)
            self._set_status(True, f"✓ 已删除 '{name}'")
            self._load_editor_empty()
            self._refresh_list()
        except Exception as e:
            self._set_status(False, f"删除失败: {e}")

    async def _stop_and_delete(self, name: str):
        """忙态 server 的删除流程: 等待启动/停止结束 → 停止 → 删除"""
        deadline = time.monotonic() + 35  # 启动/停止流程自身有超时，必然自结束
        while True:
            st = mcp_client_manager.get_status(name)
            if st is None:
                return  # 已被其他入口删除
            if st.state not in (McpServerState.STARTING, McpServerState.STOPPING):
                break
            if time.monotonic() > deadline:
                raise RuntimeError(f"'{name}' 启动/停止长时间未结束，请稍后重试")
            await asyncio.sleep(0.2)

        if st.state in (McpServerState.RUNNING, McpServerState.FAILED):
            try:
                await mcp_client_manager.stop_server(name)
            except Exception:
                pass  # 竞态下已转静态态则直接删
        mcp_client_manager.remove_server(name)

    def _on_import_json(self):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(
            self, "导入 MCP 配置",
            "粘贴 MCP Servers JSON（支持 stdio / http / streamable_http）:",
            '{"mcpServers": {"demo": {"command": "npx", "args": ["-y", "xxx"]}}}',
        )
        if not ok or not text.strip():
            return
        try:
            configs, errors = parse_claude_config(text)
        except Exception as e:
            self._set_status(False, f"JSON 解析失败: {e}")
            return

        added, skipped = [], []
        for cfg in configs:
            try:
                mcp_client_manager.add_server(cfg)
                added.append(cfg.name)
            except Exception:
                skipped.append(cfg.name)

        parts = []
        if added:
            parts.append(f"✓ 导入 {len(added)} 个: {', '.join(added)}")
        if skipped:
            parts.append(f"跳过(重名) {len(skipped)} 个: {', '.join(skipped)}")
        if errors:
            parts.append(f"解析失败 {len(errors)} 条: {'; '.join(errors[:3])}")
        ok_all = bool(added)
        self._set_status(ok_all, " ｜ ".join(parts) if parts else "没有可导入的配置")
        self._refresh_list()
