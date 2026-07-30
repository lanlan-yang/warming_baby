"""
字体配置 - 跨平台字体管理
"""
import sys
from PyQt6.QtGui import QFont, QFontDatabase


def get_default_font(size: int = 10) -> QFont:
    """
    获取系统默认中文字体
    
    Args:
        size: 字体大小
        
    Returns:
        合适的 QFont 对象
    """
    available_fonts = QFontDatabase.families()
    
    # 根据系统和可用性选择字体
    if sys.platform == 'darwin':  # macOS
        # macOS 优先使用苹方，其次是黑体
        preferred = ['PingFang SC', 'Heiti SC', 'STHeiti', '华文黑体']
    elif sys.platform == 'win32':  # Windows
        # Windows 优先使用微软雅黑
        preferred = ['Microsoft YaHei', '微软雅黑', 'SimHei', '黑体']
    else:  # Linux
        preferred = ['Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'Source Han Sans SC']
    
    # 查找可用字体
    for font_name in preferred:
        if font_name in available_fonts:
            font = QFont(font_name, size)
            return font
    
    # 找不到就用系统默认
    return QFont(size=size)


def get_font(size: int = 10, bold: bool = False) -> QFont:
    """
    获取指定大小的字体
    
    Args:
        size: 字体大小
        bold: 是否粗体
        
    Returns:
        QFont 对象
    """
    font = get_default_font(size)
    font.setBold(bold)
    return font
