"""宠物状态面板

右键菜单 → "📊 查看状态" 弹出的窗口，显示 4 项状态进度条 + 段位名。

风格：暖黄色系（与 action_bar / input_panel 一致）
- 背景：rgba(255, 245, 230, 250) 暖白
- 进度条：rgba(255, 190, 80, 255) 暖黄
- 边框：圆角
"""
from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QSize, QTimer
from PyQt6.QtGui import QFont, QColor, QBrush, QPainter, QPen, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QWidget, QLabel, QProgressBar, QVBoxLayout, QHBoxLayout,
    QDialog, QPushButton
)

from core.logger import setup_logger
from core.paths import get_resource_path
from pet.pet_stats import PetStats

logger = setup_logger()


# ============================================================================
# 状态项配置：字段 → (中文名, emoji, 段位名映射)
# ============================================================================
# 段位名：根据数值范围返回文字描述
def _satiety_tier(v: float) -> str:
    if v >= 90: return "饱饱的"
    if v >= 60: return "不饿"
    if v >= 30: return "有点饿"
    return "饿坏了"

def _mood_tier(v: float) -> str:
    if v >= 80: return "超开心"
    if v >= 60: return "开心"
    if v >= 30: return "一般"
    return "低落"

def _energy_tier(v: float) -> str:
    if v >= 80: return "精力充沛"
    if v >= 50: return "还行"
    if v >= 20: return "有点累"
    return "快倒了"

def _intimacy_tier(v: float) -> str:
    if v >= 80: return "挚友"
    if v >= 50: return "熟悉"
    if v >= 30: return "认识"
    return "陌生"


# 状态项配置表
# icon_file: assets/icons/app/ 下的文件名；None 则回退用 emoji
# 进度条颜色统一为暖黄色（图标和段位名已区分各项，无需再用颜色区分）
STAT_ITEMS = [
    # (字段名, 显示名, emoji, 图标文件名, 段位函数)
    ('satiety',  '饱食度', '🍎', 'guazi_icon.png',     _satiety_tier),
    ('mood',     '心情',   '😊', 'mood_icon.png',      _mood_tier),
    ('energy',   '体力',   '⚡', 'lightning_icon.png', _energy_tier),
    ('intimacy', '亲密度', '❤️', 'close_icon.png',     _intimacy_tier),
]

# 进度条按数值分三档着色（所有状态统一规则）
# 高（≥60）：暖黄；中（30~59）：橙；低（<30）：红
# 使用 Qt 支持的十六进制颜色格式 #AARRGGBB（透明度在前）
def _bar_color_by_value(v: float) -> str:
    if v < 30:
        return '#FFEB5A5A'    # 低 - 红 (rgba(235, 90, 90, 255))
    if v < 60:
        return '#FFFF963C'   # 中 - 橙 (rgba(255, 150, 60, 255))
    return '#FFFFBE50'       # 高 - 暖黄 (rgba(255, 190, 80, 255))

# 图标目录（assets/icons/app/）
ICON_DIR = 'assets/icons/app'
# 状态项图标尺寸
ICON_SIZE = 20
# 关闭按钮图标尺寸
CLOSE_ICON_SIZE = 16


def _load_icon(file_name: str, size: int) -> QPixmap:
    """加载图标资源，返回缩放后的 QPixmap；失败返回空 pixmap

    高 DPI 处理：按 logical size * devicePixelRatio 缩放位图，
    再设置 devicePixelRatio，Retina 屏才不会模糊。
    """
    icon_path = get_resource_path(f'{ICON_DIR}/{file_name}')
    pix = QPixmap(str(icon_path))
    if pix.isNull():
        logger.warning(f"[StatsPanel] 图标加载失败: {icon_path}")
        return QPixmap()

    # 取屏幕设备像素比（macOS Retina 通常为 2.0）
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0

    # 物理像素 = 逻辑像素 × dpr
    physical_size = int(size * dpr)
    pix = pix.scaled(
        physical_size, physical_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    # 设置 devicePixelRatio，绘制时 Qt 会自动按逻辑尺寸显示
    pix.setDevicePixelRatio(dpr)
    return pix


# ============================================================================
# 自定义圆角进度条（解决 Qt QSS 在低值时圆角失效的问题）
# ============================================================================
class RoundProgressBar(QProgressBar):
    """
    自定义圆角进度条。
    通过重写 paintEvent，手动绘制带圆角的进度条，
    确保即使在进度值很低时，也能保持完美的胶囊状外观。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._chunk_color = QColor(255, 190, 80)  # 默认暖黄色
        self._bar_height = 14  # 进度条高度
        self._corner_radius = self._bar_height // 2  # 圆角半径设为高度一半，形成胶囊

        # 去掉默认的样式，由 paintEvent 绘制
        self.setStyleSheet("QProgressBar { border: none; background: transparent; }")

    def set_chunk_color(self, color: str):
        """设置进度块颜色"""
        self._chunk_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        # 垂直居中
        y = rect.y() + (rect.height() - self._bar_height) // 2
        bar_rect = QRect(rect.x(), y, rect.width(), self._bar_height)

        # 1. 绘制背景轨道
        bg_color = QColor(255, 255, 255, 180)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(bar_rect, self._corner_radius, self._corner_radius)

        # 2. 绘制进度块
        value = self.value()
        max_val = self.maximum()
        if max_val > 0 and value > 0:
            progress_width = int((value / max_val) * bar_rect.width())
            progress_rect = QRect(bar_rect.x(), bar_rect.y(), progress_width, bar_rect.height())
            
            painter.setBrush(self._chunk_color)
            # 关键：使用 drawRoundedRect，Qt 会自动处理圆角
            # 当 progress_width 较小时，Qt 会将圆角半径限制为宽度的一半，
            # 从而自然地形成一个胶囊/圆形，这正是我们想要的效果！
            painter.drawRoundedRect(progress_rect, self._corner_radius, self._corner_radius)

        painter.end()


class StatsPanel(QDialog):
    """宠物状态面板对话框"""

    def __init__(self, stats: PetStats, parent=None):
        """
        Args:
            stats: PetStats 实例（读取当前数值）
            parent: 父窗口（一般为 None，独立窗口）
        """
        super().__init__(parent)
        self.stats = stats
        self._progress_bars: dict[str, RoundProgressBar] = {}
        self._tier_labels: dict[str, QLabel] = {}

        self.setWindowTitle("宠物状态")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |    # 无边框
            Qt.WindowType.WindowStaysOnTopHint     # 置顶
        )
        # 透明背景：让圆角外的区域透明
        # 注意：透明窗口下 QDialog 样式表的 background-color 不会绘制，
        # 必须在 paintEvent 中用 QPainter 自绘圆角背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # 拖拽状态
        self._dragging = False
        self._drag_offset = QPoint()

        # 实时刷新定时器：每 10 秒刷新一次状态值
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(10000)  # 10 秒
        self._refresh_timer.timeout.connect(self._refresh_values)

        # 子控件样式（QDialog 自身背景由 paintEvent 绘制）
        self.setStyleSheet("""
            QLabel {
                color: #6b4423;
                font-size: 14px;
                background: transparent;
            }
            QLabel#title {
                font-size: 18px;
                font-weight: bold;
                color: #8b5a2b;
            }
            QLabel#tier {
                font-size: 12px;
                color: #a0734a;
            }
            QLabel#intimacy_today {
                font-size: 11px;
                color: #b08560;
            }
            QPushButton#close_btn {
                background-color: rgba(255, 190, 80, 255);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 6px 20px;
                font-size: 13px;
            }
            QPushButton#close_btn:hover {
                background-color: rgba(255, 180, 60, 255);
            }
        """)

        self._build_ui()
        self._refresh_values()
        self.adjustSize()

        logger.info("[StatsPanel] 状态面板已显示")

    def _build_ui(self):
        """构建 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # 标题
        title = QLabel("🐾 暖宝的状态")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 4 个状态条
        for field, name, emoji, icon_file, tier_fn in STAT_ITEMS:
            row = self._build_stat_row(field, name, emoji, icon_file, tier_fn)
            layout.addLayout(row)

        # 亲密度今日进度（特殊项，显示在亲密度下方）
        self._today_label = QLabel(
            f"今日亲密度 +{self.stats._intimacy_today:.0f}/"
            f"{PetStats.INTIMACY_DAILY_LIMIT}"
        )
        self._today_label.setObjectName("intimacy_today")
        self._today_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._today_label)

        # 关闭按钮（带图标）
        close_btn = QPushButton("知道了")
        close_btn.setObjectName("close_btn")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_pix = _load_icon('close_icon.png', CLOSE_ICON_SIZE)
        if not close_pix.isNull():
            close_btn.setIcon(QIcon(close_pix))
            close_btn.setIconSize(QSize(CLOSE_ICON_SIZE, CLOSE_ICON_SIZE))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _build_stat_row(self, field, name, emoji, icon_file, tier_fn):
        """构建单行状态：图标 + 名称 + 进度条 + 段位名"""
        row = QHBoxLayout()
        row.setSpacing(8)

        # 左侧：图标（固定宽高对齐，避免不同图标视觉差异撑高行）
        if icon_file:
            icon_label = QLabel()
            pix = _load_icon(icon_file, ICON_SIZE)
            if not pix.isNull():
                icon_label.setPixmap(pix)
            else:
                icon_label.setText(emoji)
        else:
            icon_label = QLabel(emoji)
        icon_label.setFixedSize(ICON_SIZE + 4, ICON_SIZE + 4)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 透明背景：避免在 WA_TranslucentBackground 窗口上显示成方块
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        icon_label.setAutoFillBackground(False)
        icon_label.setStyleSheet("background: transparent;")
        row.addWidget(icon_label)

        # 名称（固定宽度对齐）
        name_label = QLabel(name)
        name_label.setFixedWidth(56)
        row.addWidget(name_label)

        # 中间：进度条（使用自定义 RoundProgressBar 保证圆角）
        bar = RoundProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.setFixedHeight(14)
        bar.set_chunk_color(_bar_color_by_value(100))  # 初始用高档色
        self._progress_bars[field] = bar
        row.addWidget(bar, stretch=1)

        # 右侧：段位名
        tier_label = QLabel("")
        tier_label.setObjectName("tier")
        tier_label.setFixedWidth(70)
        tier_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._tier_labels[field] = tier_label
        row.addWidget(tier_label)

        return row

    def _refresh_values(self):
        """刷新所有状态条的数值（含今日亲密度）"""
        snapshot = self.stats.snapshot()
        for field, name, emoji, icon_file, tier_fn in STAT_ITEMS:
            value = snapshot.get(field, 0)
            bar = self._progress_bars[field]
            tier_label = self._tier_labels[field]

            bar.setValue(int(value))
            # 按数值档位更新进度条颜色
            bar.set_chunk_color(_bar_color_by_value(value))
            tier_label.setText(tier_fn(value))

        # 今日亲密度进度
        self._today_label.setText(
            f"今日亲密度 +{self.stats._intimacy_today:.0f}/"
            f"{PetStats.INTIMACY_DAILY_LIMIT}"
        )

    # ========================================================================
    # 自绘背景：透明窗口下用 QPainter 画圆角暖黄色背景
    # ========================================================================
    def showEvent(self, event):
        """面板显示时启动刷新定时器"""
        super().showEvent(event)
        self._refresh_timer.start()
        logger.info("[StatsPanel] 刷新定时器已启动 (10s)")

    def hideEvent(self, event):
        """面板隐藏时停止刷新定时器"""
        super().hideEvent(event)
        self._refresh_timer.stop()

    def closeEvent(self, event):
        """面板关闭时停止刷新定时器"""
        self._refresh_timer.stop()
        super().closeEvent(event)

    def paintEvent(self, event):
        """绘制圆角背景（透明窗口下样式表 background 不生效）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect())
        # 收缩 1px 避免边框被裁切
        rect.adjust(1, 1, -1, -1)

        # 暖黄色背景
        painter.setBrush(QBrush(QColor(255, 245, 230, 250)))
        painter.setPen(QPen(QColor(255, 190, 80, 200), 2))
        painter.drawRoundedRect(rect, 16, 16)

    # ========================================================================
    # 事件处理：拖拽 + ESC 关闭
    # ========================================================================
    def mousePressEvent(self, event):
        """按下左键：开始拖拽"""
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
