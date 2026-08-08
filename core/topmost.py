"""
跨平台窗口置顶工具
- macOS: 使用 AppKit (pyobjc)
- Windows: 使用 ctypes + Win32 API
"""
from core.platform import IS_MAC, IS_WINDOWS


def set_window_topmost(window):
    """
    将窗口设为系统级置顶（跨平台）
    
    Args:
        window: QWidget 窗口实例
    Returns:
        bool: 是否成功设置
    """
    if IS_MAC:
        return _set_topmost_macos(window)
    elif IS_WINDOWS:
        return _set_topmost_windows(window)
    return False


def _set_topmost_macos(window):
    """macOS: 使用 AppKit 设置窗口置顶"""
    try:
        import objc
        from AppKit import (
            NSStatusWindowLevel,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorStationary,
        )
        
        win_id = int(window.winId())
        if not win_id:
            return False
        
        ns_view = objc.objc_object(c_void_p=win_id)
        ns_window = ns_view.window()
        
        if ns_window is None:
            return False
        
        # 设置最高层级
        ns_window.setLevel_(NSStatusWindowLevel)
        
        # 跨 Space 显示
        ns_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | 
            NSWindowCollectionBehaviorStationary
        )
        
        # 强制置顶显示（不激活应用）
        ns_window.orderFrontRegardless()
        
        return True
    except Exception:
        return False


def _set_topmost_windows(window):
    """Windows: 使用 Win32 API 设置窗口置顶"""
    try:
        import ctypes
        from ctypes import wintypes
        
        # 确保 user32.dll 可用
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        
        # 获取窗口句柄
        win_id = int(window.winId())
        if not win_id:
            return False
        
        hwnd = wintypes.HWND(win_id)
        
        # 验证窗口句柄有效
        if not user32.IsWindow(hwnd):
            return False
        
        # SetWindowPos 参数
        HWND_TOPMOST = -1
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        
        # 设置 SetWindowPos 的参数类型
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT
        ]
        
        # 窗口已隐藏时不强制显示（防止 timer 把隐藏的窗口拉回来）
        if not user32.IsWindowVisible(hwnd):
            return False

        # 设置 WS_EX_TOOLWINDOW 扩展样式，让窗口不出现在任务栏
        # 等同于 macOS 的 LSUIElement 效果，但不会像 Qt.Tool 那样在失去焦点时自动隐藏
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_TOOLWINDOW)
        
        # 延迟执行置顶（避免刚创建窗口时的问题）
        # SetWindowPos: TOPMOST + NOSIZE + NOMOVE + NOACTIVATE + SHOWWINDOW
        result = user32.SetWindowPos(
            hwnd,
            wintypes.HWND(HWND_TOPMOST),
            0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
        
        if not result:
            # 获取错误码用于调试
            error_code = kernel32.GetLastError()
            print(f"[Topmost] SetWindowPos failed, error code: {error_code}")
            return False
        
        return True
    except Exception as e:
        print(f"[Topmost] Windows set topmost error: {e}")
        return False
