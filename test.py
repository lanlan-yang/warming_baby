"""
测试 AI -> UI 事件
模拟 AI 返回 "happy" 时触发动画
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from pet.pet import NuanbaoPet


class MockAI:
    """模拟 AI"""
    
    def __init__(self, pet):
        self.pet = pet
        
        # 监听 UI 事件
        self.pet.signals.on_click.connect(self.on_click)
        self.pet.signals.on_drag_start.connect(self.on_drag_start)
        self.pet.signals.on_drag_end.connect(self.on_drag_end)
        self.pet.signals.on_hover_enter.connect(self.on_hover_enter)
        self.pet.signals.on_hover_leave.connect(self.on_hover_leave)
        self.pet.signals.on_animation_end.connect(self.on_animation_end)
    
    def on_click(self):
        print('[AI] 用户点击了宠物')
        # 模拟 AI 思考，返回 "happy"
        QTimer.singleShot(1000, self.mock_ai_response)
    
    def on_drag_start(self):
        print('[AI] 用户开始拖拽')
    
    def on_drag_end(self):
        print('[AI] 用户结束拖拽')
    
    def on_hover_enter(self):
        print('[AI] 用户鼠标悬停')
    
    def on_hover_leave(self):
        print('[AI] 用户鼠标离开')
    
    def on_animation_end(self, anim_name):
        print(f'[AI] 动画结束: {anim_name}')
    
    def mock_ai_response(self):
        """模拟 AI 返回 happy"""
        print('[AI] 模拟 AI 调用...')
        print('[AI] AI 返回: {"emotion": "happy"}')
        # 触发 happy 动画（映射到 touch）
        self.pet.trigger_animation('happy', play_once=True)


def main():
    app = QApplication(sys.argv)
    
    pet = NuanbaoPet()
    pet.show()
    
    ai = MockAI(pet)
    
    print('\n=== 测试说明 ===')
    print('1. 点击宠物 -> 1秒后 AI 返回 happy -> 播放 touch 动画')
    print('2. 拖拽宠物 -> 播放 fly 动画')
    print('3. 鼠标悬停 -> 播放 stand 动画')
    print('4. 右键 -> 退出\n')
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
