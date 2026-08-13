"""
ui/base/managed_dialog.py - 可托管对话框基类

统一封装三个常见的跨平台窗口行为，避免每个对话框重复实现：
1. dock_visible: 打开时临时切换到 Regular 模式 → 出现在 macOS 程序坞/Windows 任务栏，
                 关闭时恢复 Accessory 模式
                 （类级别引用计数：多个 dock 对话框同时打开时，关闭其中一个不会提前恢复）
2. topmost:      窗口级置顶（WindowStaysOnTopHint + set_window_topmost 原生置顶）
3. frameless:    无边框 + 半透明背景（自绘圆角窗口前置条件）

子类只需在 __init__ 中调用 super().__init__(dock_visible=..., topmost=..., frameless=...)。

应用图标通过 setup_app_icon() 设置，需在 activation policy 确定后调用
（setActivationPolicy 会重置 Dock 图标，所以必须在之后设置）。
"""
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QDialog

from core.logger import setup_logger

logger = setup_logger()


class ManagedDialog(QDialog):
    """可托管对话框基类。

    Args:
        parent: 父窗口
        dock_visible: 是否在 macOS 程序坞 / Windows 任务栏 显示该窗口
        topmost: 是否屏幕置顶（Qt 标志 + 原生 API 双保险）
        frameless: 是否无边框 + 半透明背景
    """

    # 类级别引用计数：当前有多少个 dock_visible 对话框打开
    # 用于避免多个 dock 对话框同时存在时，关闭一个导致其他对话框从 Dock 消失
    _dock_open_count: int = 0

    def __init__(
        self,
        parent=None,
        dock_visible: bool = False,
        topmost: bool = False,
        frameless: bool = False,
    ):
        super().__init__(parent)
        self._managed_dock_visible = dock_visible
        self._managed_topmost = topmost
        self._managed_frameless = frameless

        # 组合窗口 flags
        flags = Qt.WindowType(0)
        if frameless:
            flags |= Qt.WindowType.FramelessWindowHint
        if topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if flags:
            self.setWindowFlags(flags)

        if frameless:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    # ------------------------------------------------------------------
    # 应用图标
    # ------------------------------------------------------------------
    @staticmethod
    def _icon_path() -> str:
        """返回 AppIcon.iconset 中最大图标的绝对路径。"""
        here = os.path.dirname(os.path.abspath(__file__))
        # ui/base/managed_dialog.py → ui/ → 项目根
        root = os.path.abspath(os.path.join(here, "..", ".."))
        iconset = os.path.join(root, "assets", "AppIcon.iconset")
        candidates = [
            os.path.join(iconset, "icon_512x512@2x.png"),
            os.path.join(iconset, "icon_512x512.png"),
            os.path.join(iconset, "icon_256x256@2x.png"),
            os.path.join(iconset, "icon_256x256.png"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        if os.path.isdir(iconset):
            for name in sorted(os.listdir(iconset)):
                if name.endswith(".png"):
                    return os.path.join(iconset, name)
        return ""

    @classmethod
    def setup_app_icon(cls):
        """设置应用图标（Qt 层 + macOS NSApplication 层）。

        重要：必须在 setActivationPolicy 确定后调用，
        因为 setActivationPolicy 会重置 Dock 图标。
        通常在 Application._set_background_mode() 末尾调用。
        """
        icon_path = cls._icon_path()
        if not icon_path:
            logger.warning("[ManagedDialog] 未找到 AppIcon 图标")
            return

        # Qt 层：所有窗口默认图标
        qt_app = QApplication.instance()
        if qt_app:
            qt_app.setWindowIcon(QIcon(icon_path))

        # macOS NSApplication 层：Dock 图标
        if sys.platform == "darwin":
            try:
                from AppKit import NSApplication, NSImage
                ns_image = NSImage.alloc().initWithContentsOfFile_(icon_path)
                if ns_image:
                    NSApplication.sharedApplication().setApplicationIconImage_(ns_image)
                    logger.debug(f"[ManagedDialog] 应用图标已设置: {icon_path}")
                else:
                    logger.warning(f"[ManagedDialog] NSImage 加载失败: {icon_path}")
            except Exception as e:
                logger.warning(f"[ManagedDialog] 设置 NSApplication 图标失败: {e}")

    # ------------------------------------------------------------------
    # Dock 可见性（引用计数）
    # ------------------------------------------------------------------
    @classmethod
    def _dock_apply(cls, visible: bool):
        """切换应用的 Dock 可见性。

        使用类级别引用计数：
        - visible=True: 计数 +1，若之前为 0 则切换到 Regular 模式
        - visible=False: 计数 -1，若归 0 则恢复 Accessory 模式

        每次切换 activation policy 后都重新设置图标，
        因为 setActivationPolicy 会重置 Dock 图标。
        """
        if sys.platform != "darwin":
            return

        if visible:
            cls._dock_open_count += 1
            if cls._dock_open_count == 1:
                try:
                    from AppKit import (
                        NSApplication,
                        NSApplicationActivationPolicyRegular,
                    )
                    app = NSApplication.sharedApplication()
                    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
                    # 切换 policy 后重新设置图标（policy 变化会重置图标）
                    cls.setup_app_icon()
                    logger.debug(f"[ManagedDialog] Dock 可见 (count={cls._dock_open_count})")
                except Exception as e:
                    logger.warning(f"[ManagedDialog] Dock 可见性设置失败: {e}")
        else:
            cls._dock_open_count = max(0, cls._dock_open_count - 1)
            if cls._dock_open_count == 0:
                try:
                    from AppKit import (
                        NSApplication,
                        NSApplicationActivationPolicyAccessory,
                    )
                    app = NSApplication.sharedApplication()
                    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                    # 恢复 accessory 后也重新设置图标（避免被重置为默认）
                    cls.setup_app_icon()
                    logger.debug("[ManagedDialog] Dock 隐藏 (count=0)")
                except Exception as e:
                    logger.warning(f"[ManagedDialog] Dock 隐藏设置失败: {e}")

    # ------------------------------------------------------------------
    # Topmost（原生 API）
    # ------------------------------------------------------------------
    def _apply_topmost(self):
        """通过原生 API 设置窗口置顶（跨平台）。"""
        if not self._managed_topmost:
            return
        try:
            from core.topmost import set_window_topmost
            set_window_topmost(self)
        except Exception as e:
            logger.warning(f"[ManagedDialog] set_window_topmost 失败: {e}")

    # ------------------------------------------------------------------
    # 生命周期钩子
    # ------------------------------------------------------------------
    def showEvent(self, event):
        """窗口显示时：设置 Dock 可见性 + 原生置顶。"""
        super().showEvent(event)
        if self._managed_dock_visible:
            self._dock_apply(True)
        if self._managed_topmost:
            self._apply_topmost()

    def done(self, result):
        """窗口关闭时：如果是 dock 对话框则恢复引用计数。"""
        if self._managed_dock_visible:
            self._dock_apply(False)
        super().done(result)
