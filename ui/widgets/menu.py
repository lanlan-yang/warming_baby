"""统一菜单管理：右键菜单 + 托盘菜单

将菜单逻辑从 pet.py 和 app.py 解耦，统一在此管理。
Windows 上菜单显示前暂停置顶定时器，关闭后恢复，避免菜单无法消失。
"""

import os
from PyQt6.QtCore import Qt, QPoint, QSize
from PyQt6.QtGui import QAction, QIcon, QPixmap, QCursor
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from core.platform import IS_WINDOWS, IS_MAC
from core.paths import get_resource_path
from version import __version__, __app_name__


def _pause_topmost(pet):
    """暂停宠物置顶定时器，返回是否需要恢复"""
    if hasattr(pet, '_topmost_timer') and pet._topmost_timer.isActive():
        pet._topmost_timer.stop()
        return True
    return False


def _resume_topmost(pet, was_running):
    """恢复宠物置顶定时器"""
    if was_running and not getattr(pet, '_is_exiting', False):
        pet._topmost_timer.start(200)


def _exec_menu(menu, pos):
    """统一的菜单弹出逻辑：置顶 + 暂停 topmost timer"""
    # Windows: 菜单加置顶标志，否则会被宠物 Tool 窗口盖住
    if IS_WINDOWS:
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    menu.exec(pos)


def create_context_menu(pet):
    """创建宠物右键菜单

    Args:
        pet: Pet 实例

    Returns:
        QMenu
    """
    menu = QMenu(pet)
    menu.addAction("🙈 隐藏暖宝", pet._hide_with_hint)
    menu.addSeparator()
    menu.addAction("📊 查看状态", pet.show_stats_panel)
    menu.addSeparator()
    menu.addAction("⚙️ 设置...", pet.open_settings)
    menu.addSeparator()
    menu.addAction("❤️ 关于暖宝", pet.show_about)
    menu.addSeparator()
    menu.addAction("🚪 退出", pet._exit_with_animation)
    menu.addSeparator()
    menu.addAction("⭐ 给我个 Star 吧！", pet.show_github_star)
    return menu


def show_context_menu(pet, global_pos):
    """显示宠物右键菜单

    Args:
        pet: Pet 实例
        global_pos: 全局坐标 (QPoint)
    """
    if getattr(pet, '_is_warming_up', False):
        return

    menu = create_context_menu(pet)

    was_running = _pause_topmost(pet)
    _exec_menu(menu, global_pos)
    _resume_topmost(pet, was_running)


def create_tray_icon(pet):
    """创建系统托盘图标 + 菜单

    Args:
        pet: Pet 实例

    Returns:
        QSystemTrayIcon
    """
    icon = QIcon()

    if IS_MAC:
        # macOS: 使用模板图标，自动适配深浅色
        tray_dir = str(get_resource_path('assets/icons/tray'))
        icon.addFile(os.path.join(tray_dir, 'tray_16.png'), QSize(16, 16))
        icon.addFile(os.path.join(tray_dir, 'tray_16@2x.png'), QSize(32, 32))
        icon.addFile(os.path.join(tray_dir, 'tray_16@3x.png'), QSize(48, 48))
        icon.addFile(os.path.join(tray_dir, 'tray_32.png'), QSize(32, 32))
        icon.addFile(os.path.join(tray_dir, 'tray_32@2x.png'), QSize(64, 64))
        icon.addFile(os.path.join(tray_dir, 'tray_32@3x.png'), QSize(96, 96))
        icon.addFile(os.path.join(tray_dir, 'tray_128.png'), QSize(128, 128))
        icon.addFile(os.path.join(tray_dir, 'tray_128@2x.png'), QSize(256, 256))
        icon.addFile(os.path.join(tray_dir, 'tray_256.png'), QSize(256, 256))
        icon.addFile(os.path.join(tray_dir, 'tray_256@2x.png'), QSize(512, 512))
        icon.addFile(os.path.join(tray_dir, 'tray_512.png'), QSize(512, 512))
        icon.addFile(os.path.join(tray_dir, 'tray_512@2x.png'), QSize(1024, 1024))
        icon.setIsMask(True)
    else:
        # Windows: 使用彩色图标，用 QPixmap 手动缩放确保高 DPI 下清晰
        tray_win_dir = str(get_resource_path('assets/icons/tray/tray_win'))
        icon_path = os.path.join(tray_win_dir, 'icon.png')
        for sz in (16, 24, 32, 48, 64):
            pix = QPixmap(icon_path)
            pix.setDevicePixelRatio(1)
            icon.addPixmap(
                pix.scaled(sz, sz, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation),
                QIcon.Mode.Normal, QIcon.State.Off
            )

    tray = QSystemTrayIcon(icon)
    tray.setToolTip(f'{__app_name__} v{__version__} - 你的桌宠')

    # 托盘菜单
    menu = QMenu()
    menu.addAction('显示/隐藏暖宝', lambda: pet.setVisible(not pet.isVisible()))
    menu.addSeparator()
    menu.addAction('设置...', pet.open_settings)
    menu.addSeparator()
    menu.addAction('退出暖宝', pet._exit_with_animation)
    menu.addSeparator()
    menu.addAction('⭐ 给我个 Star 吧！', pet.show_github_star)

    tray.setContextMenu(menu)

    # 托盘点击行为：
    # Windows: 左键单击弹出菜单（右键也弹菜单，Windows 标准）
    # macOS: 双击切换显示/隐藏
    if IS_WINDOWS:
        def _on_tray_activated(reason):
            if reason != QSystemTrayIcon.ActivationReason.Trigger:
                return
            was_running = _pause_topmost(pet)
            _exec_menu(menu, QCursor.pos())
            _resume_topmost(pet, was_running)
        tray.activated.connect(_on_tray_activated)
    else:
        tray.activated.connect(
            lambda reason: pet.setVisible(not pet.isVisible())
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )

    return tray
