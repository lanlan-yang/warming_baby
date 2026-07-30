"""
测试 AI -> UI 事件总线
模拟 AI 返回 "happy" 时触发动画
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from core import (
    event_bus, EventCategory,
    UIEvent, PetEvent, AgentEvent, SystemEvent
)
from pet.pet import NuanbaoPet


class MockAI:
    """模拟 AI Agent"""
    
    def __init__(self, pet):
        self.pet = pet
        
        # 使用事件总线订阅 UI 事件
        event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_CLICK, self.on_click)
        event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_DRAG_START, self.on_drag_start)
        event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_DRAG_END, self.on_drag_end)
        event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_HOVER_ENTER, self.on_hover_enter)
        event_bus.subscribe(EventCategory.UI, UIEvent.MOUSE_HOVER_LEAVE, self.on_hover_leave)
        
        # 订阅宠物事件
        event_bus.subscribe(EventCategory.PET, PetEvent.ANIMATION_START, self.on_animation_start)
        event_bus.subscribe(EventCategory.PET, PetEvent.ANIMATION_END, self.on_animation_end)
        event_bus.subscribe(EventCategory.PET, PetEvent.ANIMATION_CHANGED, self.on_animation_changed)
        event_bus.subscribe(EventCategory.PET, PetEvent.DIRECTION_CHANGED, self.on_direction_changed)
    
    # ==================== UI 事件处理 ====================
    
    def on_click(self, x, y):
        print(f'[AI] 用户点击 ({x}, {y})')
        # 模拟 AI 思考1秒后返回响应
        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)
        QTimer.singleShot(1000, self.mock_ai_response)
    
    def on_drag_start(self):
        print('[AI] 用户开始拖拽')
    
    def on_drag_end(self):
        print('[AI] 用户结束拖拽')
    
    def on_hover_enter(self):
        print('[AI] 用户鼠标悬停')
    
    def on_hover_leave(self):
        print('[AI] 用户鼠标离开')
    
    # ==================== 宠物事件处理 ====================
    
    def on_animation_start(self, anim_name):
        print(f'[Pet] 动画开始: {anim_name}')
    
    def on_animation_end(self, anim_name):
        print(f'[Pet] 动画结束: {anim_name}')
    
    def on_animation_changed(self, from_, to):
        print(f'[Pet] 动画切换: {from_} -> {to}')
    
    def on_direction_changed(self, facing_right):
        direction = '右' if facing_right else '左'
        print(f'[Pet] 朝向改变: {direction}')
    
    # ==================== AI 模拟 ====================
    
    def mock_ai_response(self):
        """模拟 AI 返回 happy"""
        print('[AI] 模拟 AI 调用...')
        print('[AI] AI 返回: {"emotion": "happy"}')
        
        # 方式1: 直接调用 pet 方法
        # self.pet.trigger_animation('happy', play_once=True)
        
        # 方式2: 通过事件总线 (推荐)
        event_bus.publish(EventCategory.AGENT, AgentEvent.RESPONSE, 
                         response={'emotion': 'happy', 'play_once': True})


def main():
    app = QApplication(sys.argv)
    
    # 订阅系统事件
    def on_app_started():
        print('\n=== 应用启动 ===\n')
    event_bus.subscribe(EventCategory.SYSTEM, 'app_started', on_app_started)
    
    pet = NuanbaoPet()
    pet.show()
    
    ai = MockAI(pet)
    
    print('\n=== 测试说明 ===')
    print('1. 点击宠物 -> 1秒后 AI 返回 happy -> 播放 touch 动画')
    print('2. 拖拽宠物 -> 播放 fly 动画')
    print('3. 鼠标悬停 -> 播放 stand 动画')
    print('4. 右键 -> 退出\n')
    
    # 订阅应用启动后自动打印事件列表
    def print_event_list():
        print(f'已订阅事件: {event_bus.list_events()}\n')
    QTimer.singleShot(100, print_event_list)
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
