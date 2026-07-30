"""
输入框组件 - 简洁风格
圆角输入框 + 发送按钮，与气泡搭配使用
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PyQt6.QtWidgets import QWidget, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout


class InputPanel(QWidget):
    """
    输入框组件
    
    功能:
    - 简洁的文本输入框
    - Enter 键发送
    - 发送按钮
    - 透明背景
    """
    
    # 发送信号
    send_requested = pyqtSignal(str)
    
    # 尺寸常量
    INPUT_HEIGHT = 36    # 输入框高度
    INPUT_WIDTH = 200    # 输入框宽度
    BUTTON_SIZE = 36     # 按钮大小
    MAX_TEXT_LENGTH = 100  # 最大字符数
    
    # 颜色常量
    BG_COLOR = QColor(255, 255, 255, 230)     # 背景: 90%透明度
    BORDER_COLOR = QColor(200, 200, 200)      # 边框: 浅灰
    INPUT_BG = QColor(255, 255, 255, 200)     # 输入框背景
    BUTTON_COLOR = QColor(255, 200, 100)      # 按钮: 暖黄
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 设置窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.setFixedHeight(self.INPUT_HEIGHT + 8)  # 固定高度
        
        self._init_ui()
        self._connect_signals()
    
    def _init_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        
        # 输入框
        self.input_edit = QLineEdit(self)
        self.input_edit.setPlaceholderText("和暖宝说点什么...")
        self.input_edit.setMaxLength(self.MAX_TEXT_LENGTH)
        self.input_edit.setFixedHeight(self.INPUT_HEIGHT)
        self.input_edit.setStyleSheet(self._get_input_style())
        
        # 发送按钮
        self.send_button = QPushButton("发送", self)
        self.send_button.setFixedSize(self.BUTTON_SIZE + 10, self.INPUT_HEIGHT)
        self.send_button.setStyleSheet(self._get_button_style())
        
        layout.addWidget(self.input_edit, 1)  # 输入框占满剩余空间
        layout.addWidget(self.send_button)
    
    def _get_input_style(self) -> str:
        """获取输入框样式"""
        return """
        QLineEdit {
            background-color: rgba(255, 255, 255, 230);
            border: 1px solid rgba(200, 200, 200, 200);
            border-radius: 18px;
            padding: 0 15px;
            color: #333;
            font-size: 12px;
        }
        QLineEdit:focus {
            border-color: rgba(255, 200, 100, 255);
        }
        QLineEdit::placeholder {
            color: rgba(180, 180, 180, 200);
        }
        """
    
    def _get_button_style(self) -> str:
        """获取按钮样式"""
        return """
        QPushButton {
            background-color: rgba(255, 200, 100, 230);
            border: none;
            border-radius: 18px;
            color: #555;
            font-size: 12px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: rgba(255, 190, 80, 255);
        }
        QPushButton:pressed {
            background-color: rgba(255, 180, 60, 255);
        }
        """
    
    def _connect_signals(self):
        """连接信号"""
        self.send_button.clicked.connect(self._on_send_clicked)
        self.input_edit.returnPressed.connect(self._on_send_clicked)
    
    def _on_send_clicked(self):
        """发送按钮点击"""
        text = self.input_edit.text().strip()
        if text:
            self.send_requested.emit(text)
            self.input_edit.clear()
    
    def show_panel(self):
        """显示面板"""
        self.show()
        self.raise_()
        self.input_edit.setFocus()
    
    def hide_panel(self):
        """隐藏面板"""
        self.hide()
    
    def clear_input(self):
        """清空输入"""
        self.input_edit.clear()
        self.input_edit.setFocus()
    
    def set_placeholder(self, text: str):
        """设置占位文本"""
        self.input_edit.setPlaceholderText(text)
    
    def mousePressEvent(self, event):
        """拦截鼠标事件，防止穿透到下层"""
        event.accept()
    
    def mouseReleaseEvent(self, event):
        """拦截鼠标事件，防止穿透到下层"""
        event.accept()
