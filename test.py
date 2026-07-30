"""
测试对话 UI 功能
模拟完整对话流程: 用户输入 -> AI 响应 -> 显示气泡
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
from pet import NuanbaoPet


class MockAI:
    """模拟 AI Agent"""
    
    # 预设回复
    MOCK_REPLIES = [
        {"text": "好的，我来帮你处理！", "emotion": "happy"},
        {"text": "嗯嗯，我明白了~", "emotion": "happy"},
        {"text": "让我想想...", "emotion": "idle"},
        {"text": "这个有点难哦", "emotion": "idle"},
        {"text": "没问题！", "emotion": "happy"},
    ]
    
    def __init__(self):
        self.reply_index = 0
        
        # 订阅事件
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.USER_MESSAGE, self.on_user_message)
        event_bus.subscribe(EventCategory.AGENT, AgentEvent.THINKING, self.on_thinking)
    
    def on_user_message(self, message: str):
        """收到用户消息"""
        print(f'\n[AI] 收到消息: "{message}"')
        
        # 发布思考中状态
        event_bus.publish(EventCategory.AGENT, AgentEvent.THINKING)
        
        # 模拟 1-2 秒延迟
        delay = 1000 + (self.reply_index * 200) % 1000
        QTimer.singleShot(delay, self.send_response)
    
    def on_thinking(self):
        """AI 思考中"""
        print('[AI] 思考中...')
    
    def send_response(self):
        """发送 AI 响应"""
        reply = self.MOCK_REPLIES[self.reply_index % len(self.MOCK_REPLIES)]
        self.reply_index += 1
        
        print(f'[AI] 回复: "{reply["text"]}"')
        
        # 发布响应事件
        event_bus.publish(EventCategory.AGENT, AgentEvent.RESPONSE, response=reply)


def main():
    app = QApplication(sys.argv)
    
    # 创建模拟 AI
    mock_ai = MockAI()
    
    # 创建宠物
    pet = NuanbaoPet()
    pet.show()
    
    print('\n' + '='*50)
    print('暖宝对话功能测试')
    print('='*50)
    print('\n操作说明:')
    print('1. 点击暖宝 -> 显示气泡"和我说话吧~" + 输入框')
    print('2. 输入文字并按 Enter 或点击发送')
    print('3. 气泡显示"..." 表示 AI 正在思考')
    print('4. AI 回复后气泡显示回复内容 (3秒后消失)')
    print('5. 拖动暖宝 -> 隐藏对话, 显示飞行动画')
    print('\n开始测试吧!\n')
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
