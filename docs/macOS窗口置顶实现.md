# macOS PyQt6 窗口置顶实现

## 问题背景

在 macOS 上使用 PyQt6 实现窗口置顶功能，与 Windows 有很大差异。Windows 上可以直接使用 `Qt.WindowStaysOnTopHint`，但在 macOS 上会失效或导致异常行为。

## 失败的尝试方案

### ❌ 方案一：使用 Qt 标准标志

```python
# 这种方式在 macOS 上不工作
self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
```

**问题**：macOS 上 `WindowStaysOnTopHint` 会被转换为 `NSFloatingWindowLevel`，不是最高层级。

### ❌ 方案二：使用 Tool + AppKit

```python
# 这种方式会导致冲突
self.setWindowFlags(
    Qt.WindowType.FramelessWindowHint |
    Qt.WindowType.WindowStaysOnTopHint |
    Qt.WindowType.Tool  # Tool 会创建 NSPanel
)
# 然后再用 AppKit 设置 level
ns_window.setLevel_(NSStatusWindowLevel)
```

**问题**：`Qt.WindowType.Tool` 创建的 NSPanel 有自己的窗口管理逻辑，会覆盖 AppKit 的设置。

### ❌ 方案三：修改 styleMask

```python
# 修改 NSPanel 的 styleMask
ns_window.setStyleMask_(NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel)
```

**问题**：会导致窗口无法正常交互，或者 Qt 的事件处理失效。

## ✅ 最终成功方案

### 核心原理

1. **不要使用 Qt 的 WindowFlags**（特别是 `WindowStaysOnTopHint` 和 `Tool`）
2. **只使用 `FramelessWindowHint`** 实现无边框
3. **所有置顶设置都用原生 AppKit** 完成
4. **定时刷新 level** 防止被系统重置

### 完整代码示例

```python
import sys
import objc
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication

class TopMostWidget(QWidget):
    def __init__(self):
        super().__init__()
        
        # ============================================
        # 1. Qt 窗口设置 - 只设置必要的属性
        # ============================================
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint  # 只保留无边框，不要其他标志
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        
        # 位置和大小
        self.setGeometry(200, 200, 200, 200)
        
        # ============================================
        # 2. macOS 原生设置 - 在 showEvent 后调用
        # ============================================
        if sys.platform == 'darwin':
            QTimer.singleShot(10, self._setup_topmost)
            QTimer.singleShot(100, self._setup_topmost)  # 多次调用确保成功
            QTimer.singleShot(500, self._setup_topmost)
    
    def showEvent(self, event):
        """显示时重新应用置顶设置"""
        super().showEvent(event)
        if sys.platform == 'darwin':
            QTimer.singleShot(10, self._setup_topmost)
            QTimer.singleShot(100, self._setup_topmost)
    
    def _setup_topmost(self):
        """macOS 原生置顶设置 - 关键方法"""
        try:
            from AppKit import (
                NSStatusWindowLevel,  # 值 = 25，最高层级
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary,
            )
            
            # 获取原生窗口
            win_id = int(self.winId())
            if not win_id:
                return
            
            ns_view = objc.objc_object(c_void_p=win_id)
            ns_window = ns_view.window()
            
            if ns_window is None:
                return
            
            # ============================================
            # 关键设置（顺序很重要）
            # ============================================
            
            # 1. 设置最高层级（比 Dock 还高）
            ns_window.setLevel_(NSStatusWindowLevel)
            
            # 2. 设置跨 Space 显示
            ns_window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces |
                NSWindowCollectionBehaviorStationary
            )
            
            # 3. 强制置顶显示（不激活应用）
            ns_window.orderFrontRegardless()
            
            # ============================================
            # 4. 保存引用，用于定时刷新
            # ============================================
            self._ns_window_ref = ns_window
            self._ns_level = NSStatusWindowLevel
            
            # 5. 启动定时刷新（防止系统重置）
            if not hasattr(self, '_topmost_timer'):
                self._topmost_timer = QTimer(self)
                self._topmost_timer.timeout.connect(self._refresh_topmost)
                self._topmost_timer.start(500)  # 每 500ms 刷新一次
                
        except Exception as e:
            print(f"[Topmost] 设置失败: {e}")
    
    def _refresh_topmost(self):
        """定时刷新窗口层级"""
        if hasattr(self, '_ns_window_ref') and self._ns_window_ref:
            try:
                self._ns_window_ref.setLevel_(self._ns_level)
                self._ns_window_ref.orderFrontRegardless()
            except Exception:
                pass
```

## 关键 API 说明

### AppKit 常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `NSStatusWindowLevel` | 25 | 最高层级，与菜单栏同级 |
| `NSFloatingWindowLevel` | 3 | 浮动窗口层级（不够高） |
| `NSNormalWindowLevel` | 0 | 普通窗口层级 |

### 窗口行为常量

| 常量 | 说明 |
|------|------|
| `NSWindowCollectionBehaviorCanJoinAllSpaces` | 在所有桌面/Space 都显示 |
| `NSWindowCollectionBehaviorStationary` | 不随 Space 切换而移动 |
| `NSWindowCollectionBehaviorFullScreenAuxiliary` | 全屏时也显示 |

### 关键方法

| 方法 | 说明 |
|------|------|
| `setLevel_(level)` | 设置窗口层级 |
| `orderFrontRegardless()` | 强制置顶显示（不激活应用） |
| `orderFront()` | 置顶但会激活应用（慎用） |
| `setCollectionBehavior_(flags)` | 设置窗口在不同 Space 的行为 |

## 注意事项

### 1. 多次调用确保成功

macOS 的窗口创建是异步的，第一次调用可能窗口还没完全初始化：

```python
# 建议调用 3 次，间隔递增
QTimer.singleShot(10, self._setup_topmost)
QTimer.singleShot(100, self._setup_topmost)
QTimer.singleShot(500, self._setup_topmost)
```

### 2. 定时刷新很重要

macOS 会在某些时机重置窗口层级（如切换应用、显示 Mission Control 等）：

```python
# 每 500ms 刷新一次
self._topmost_timer.start(500)
```

### 3. 不要修改 styleMask

修改 `setStyleMask_` 会导致 Qt 的事件处理失效：

```python
# ❌ 不要这样做
ns_window.setStyleMask_(someMask)

# ✅ 保持 Qt 设置的 styleMask
```

### 4. orderFrontRegardless vs orderFront

- `orderFrontRegardless()` - 置顶但不激活应用，**推荐使用**
- `orderFront()` - 置顶并激活应用，会抢焦点

## 完整示例：桌面宠物窗口

```python
import sys
import os
import objc
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QPainter, QColor, QGuiApplication

class DesktopPet(QWidget):
    def __init__(self):
        super().__init__()
        
        # Qt 设置
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        
        # 大小和位置
        self.setFixedSize(150, 150)
        self.move(200, 300)
        
        # 拖动相关
        self._dragging = False
        self._drag_offset = QPoint()
        
        # macOS 置顶
        if sys.platform == 'darwin':
            QTimer.singleShot(10, self._setup_topmost)
            QTimer.singleShot(100, self._setup_topmost)
            QTimer.singleShot(500, self._setup_topmost)
    
    def paintEvent(self, event):
        """绘制宠物"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 画个红色圆形代表宠物
        painter.setBrush(QColor(255, 0, 0, 200))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(25, 25, 100, 100)
    
    def mousePressEvent(self, event):
        """开始拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
    
    def mouseMoveEvent(self, event):
        """拖动中"""
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
    
    def mouseReleaseEvent(self, event):
        """结束拖动"""
        self._dragging = False
    
    # ========== macOS 置顶相关 ==========
    
    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == 'darwin':
            QTimer.singleShot(10, self._setup_topmost)
    
    def _setup_topmost(self):
        try:
            from AppKit import (
                NSStatusWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary,
            )
            
            win_id = int(self.winId())
            if not win_id:
                return
            
            ns_view = objc.objc_object(c_void_p=win_id)
            ns_window = ns_view.window()
            
            if ns_window is None:
                return
            
            ns_window.setLevel_(NSStatusWindowLevel)
            ns_window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces |
                NSWindowCollectionBehaviorStationary
            )
            ns_window.orderFrontRegardless()
            
            self._ns_window_ref = ns_window
            self._ns_level = NSStatusWindowLevel
            
            if not hasattr(self, '_topmost_timer'):
                self._topmost_timer = QTimer(self)
                self._topmost_timer.timeout.connect(self._refresh_topmost)
                self._topmost_timer.start(500)
                
        except Exception:
            pass
    
    def _refresh_topmost(self):
        if hasattr(self, '_ns_window_ref') and self._ns_window_ref:
            try:
                self._ns_window_ref.setLevel_(self._ns_level)
                self._ns_window_ref.orderFrontRegardless()
            except Exception:
                pass

if __name__ == '__main__':
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    pet = DesktopPet()
    pet.show()
    sys.exit(app.exec())
```

## 参考资源

- [NSWindow Level Constants](https://developer.apple.com/documentation/appkit/nswindow/level)
- [NSWindow Class Reference](https://developer.apple.com/documentation/appkit/nswindow)
- [PyObjC Documentation](https://pyobjc.readthedocs.io/)
