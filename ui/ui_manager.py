"""
ui/ui_manager.py - UI 组件统一管理器

职责：
    1. UI 组件生命周期管理（bubble, input_panel 及未来的 status_bar, action_bar）
    2. 位置联动（所有组件跟随宠物位置）
    3. 聊天 UI 的显示/隐藏编排

不负责：
    - 宠物自身状态（dragging, hovering, sleeping）→ 留在 PetWindow
    - 状态守卫（can_show_bubble 等）→ 留在 PetWindow
    - 事件总线订阅 → 留在 PetWindow
    - 动画播放 → 留在 PetWindow

依赖方向：UIManager → pet（单向）
    UIManager 持有 pet 的引用来获取位置和调用动画回调，
    pet 不需要知道 UIManager 内部怎么布局。
"""
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtWidgets import QApplication

from core.logger import setup_logger
from core.platform import IS_WINDOWS
from settings import settings
from .widgets import SpeechBubble, InputPanel, ActionBar, FloatingText, changes_to_lines

logger = setup_logger()


class UIManager:
    """
    UI 组件统一管理器

    管理宠物相关的所有 UI 组件（气泡、输入框等），
    负责组件的创建、位置联动和显示/隐藏编排。

    使用方式：
        # 在 PetWindow.__init__ 中
        self.ui_manager = UIManager(self)

        # 显示聊天 UI
        self.ui_manager.show_chat()

        # 显示消息
        self.ui_manager.show_message("你好呀～")

        # 隐藏所有聊天 UI
        self.ui_manager.hide_chat()
    """

    def __init__(self, pet):
        """
        初始化 UIManager

        Args:
            pet: PetWindow 实例（用于获取位置和调用动画回调）
        """
        self.pet = pet
        self.cfg = settings.chat

        # 创建 UI 组件
        self.bubble = SpeechBubble()
        self.input_panel = InputPanel()
        self.input_panel.send_requested.connect(self._on_user_input)

        # 动作栏（投喂/玩耍/抚摸/睡觉）
        self.action_bar = ActionBar()
        self.action_bar.action_triggered.connect(self._on_action_triggered)

        # 动作触发回调（由 Pet 设置，用于后续接入实际动作逻辑）
        self._action_callback = None

        # 飘字组件引用（防止被 GC 回收，动画结束后自动移除）
        self._floating_texts: list = []

        # 焦点检查定时器
        self._focus_check_timer = QTimer(self.pet)
        self._focus_check_timer.timeout.connect(self._check_app_focus)

        logger.info("[UIManager] 初始化完成")

    # ========================================================================
    # 位置联动
    # ========================================================================

    def update_positions(self):
        """
        更新所有 UI 组件位置，使其跟随宠物

        布局策略：
            默认（头顶上方有空间）：
                宠物 → 输入框 → 动作栏 → 气泡（从下到上堆叠）
            顶部空间不足（宠物走到屏幕顶部）：
                气泡 → 动作栏 → 输入框 → 宠物（从宠物脚底向下堆叠）

        空间不足的判断标准：显示所有可见 UI 所需总高度 > 宠物头顶到屏幕顶部的距离
        """
        bubble_visible = self.bubble.isVisible()
        panel_visible = self.input_panel.isVisible()
        action_visible = self.action_bar.isVisible()

        if not bubble_visible and not panel_visible and not action_visible:
            return

        pet_pos = self.pet.frameGeometry().topLeft()
        pet_height = self.pet.height()
        pet_width = self.pet.width()
        screen_width = self.pet.screen.width()
        screen_height = self.pet.screen.height()

        # ========== 计算所需总高度，判断布局方向 ==========
        total_height = 0
        if panel_visible:
            total_height += self.input_panel.height() + self.cfg.bubble_offset_y
        if action_visible:
            # 如果输入框也可见，动作栏在输入框上方，中间间隔 input_offset_y
            gap = self.cfg.input_offset_y if panel_visible else self.cfg.bubble_offset_y
            total_height += self.action_bar.height() + gap
        if bubble_visible:
            # 气泡在最上，需要一个 input_offset_y 与下方组件隔开
            has_below = panel_visible or action_visible
            gap = self.cfg.input_offset_y if has_below else self.cfg.bubble_offset_y
            total_height += self.bubble.height() + gap

        # 顶部空间 = 宠物头顶 y 坐标
        top_space = pet_pos.y()

        # 底部空间 = 屏幕高度 - 宠物脚底 y 坐标
        pet_bottom = pet_pos.y() + pet_height
        bottom_space = screen_height - pet_bottom

        # 决策：如果顶部空间不够 且 底部空间够用，就放脚底
        # （如果上下都不够，就优先放头顶，靠屏幕裁剪兜底）
        place_below = (total_height > top_space) and (bottom_space >= total_height)

        # 根据气泡在宠物上方还是下方，设置尾巴朝向
        # 头顶布局：气泡在宠物上方，尾巴朝下指向宠物
        # 脚底布局：气泡在宠物下方，尾巴朝上指向宠物
        self.bubble.set_tail_up(place_below)

        # ========== 水平居中计算 ==========
        def _center_x(width, parent_w=pet_width):
            raw_x = pet_pos.x() + (parent_w - width) // 2
            return max(0, min(raw_x, screen_width - width))

        if place_below:
            # ========== 脚底布局：从宠物脚底向下堆叠 ==========
            # 顺序（从上到下，越靠下 y 越大）：
            #   宠物脚底 → 气泡 → 动作栏 → 输入框
            # （气泡离宠物最近，输入框在最下方方便点击）

            current_y = pet_bottom + self.cfg.bubble_offset_y

            # 气泡：紧贴宠物脚底
            if bubble_visible:
                bubble_x = _center_x(self.bubble.width())
                self.bubble.move(bubble_x, current_y)
                current_y += self.bubble.height() + self.cfg.input_offset_y

            # 动作栏：气泡下方（或宠物脚底下方，如果没有气泡）
            if action_visible:
                if not bubble_visible:
                    current_y = pet_bottom + self.cfg.bubble_offset_y
                action_x = _center_x(self.action_bar.width())
                self.action_bar.move(action_x, current_y)
                current_y += self.action_bar.height() + self.cfg.input_offset_y

            # 输入框：最下方
            if panel_visible:
                if not action_visible and not bubble_visible:
                    current_y = pet_bottom + self.cfg.bubble_offset_y
                input_x = _center_x(self.input_panel.width())
                self.input_panel.move(input_x, current_y)

        else:
            # ========== 头顶布局（原逻辑）：从宠物头顶向上堆叠 ==========
            # 顺序（从下到上，越靠上 y 越小）：
            #   输入框 → 动作栏 → 气泡 → 宠物头顶

            # 输入框位置: 宠物头顶上方，水平居中
            input_y = 0
            if panel_visible:
                input_x = _center_x(self.input_panel.width())
                input_y = pet_pos.y() - self.input_panel.height() - self.cfg.bubble_offset_y
                input_y = max(0, input_y)
                self.input_panel.move(input_x, input_y)

            # 动作栏位置: 输入框上方（或宠物头顶，如果输入框不可见）
            action_y = 0
            if action_visible:
                action_x = _center_x(self.action_bar.width())
                base_y = input_y if panel_visible else pet_pos.y() - self.cfg.bubble_offset_y
                action_y = base_y - self.action_bar.height() - self.cfg.input_offset_y
                action_y = max(0, action_y)
                self.action_bar.move(action_x, action_y)

            # 气泡位置: 动作栏上方（或输入框上方，或宠物头顶）
            if bubble_visible:
                if action_visible:
                    base_y = action_y
                elif panel_visible:
                    base_y = input_y
                else:
                    base_y = pet_pos.y() - self.cfg.bubble_offset_y

                bubble_x = _center_x(self.bubble.width())
                bubble_y = base_y - self.bubble.height() - self.cfg.input_offset_y
                bubble_y = max(0, bubble_y)
                self.bubble.move(bubble_x, bubble_y)

    # ========================================================================
    # 聊天 UI 显示/隐藏编排
    # ========================================================================

    def show_chat(self):
        """
        显示聊天界面（输入框 + 动作栏）

        调用方应在此前后处理动画和状态标志。
        """
        self.input_panel.show_panel()
        self.action_bar.show_bar()

        # 启动焦点检查
        self._focus_check_timer.start(500)

        self.update_positions()

    def hide_chat(self):
        """
        隐藏所有聊天 UI（气泡 + 输入框 + 动作栏）

        调用方应在此后处理动画恢复。
        """
        # 停止焦点检查
        self._focus_check_timer.stop()

        self.bubble.hide_bubble()
        self.input_panel.hide_panel()
        self.action_bar.hide_bar()

    def show_message(self, text: str, auto_hide: bool = True,
                     duration: int = None, is_auto_speak: bool = False):
        """
        显示消息气泡

        Args:
            text: 要显示的文本
            auto_hide: 是否自动隐藏
            duration: 固定显示时间（毫秒），None 则动态计算
            is_auto_speak: 是否为自动说话（给予更长的显示时间）
        """
        self.bubble.show_message(
            text,
            auto_hide=auto_hide,
            duration=duration,
            is_auto_speak=is_auto_speak,
        )
        self.update_positions()
        QApplication.processEvents()

    def show_typing(self):
        """显示正在输入状态"""
        self.bubble.show_typing(auto_hide=False)
        self.update_positions()
        QApplication.processEvents()

    def hide_bubble(self, trigger_callback: bool = True):
        """隐藏气泡"""
        self.bubble.hide_bubble(trigger_callback=trigger_callback)

    def set_bubble_hidden_callback(self, callback):
        """设置气泡隐藏回调"""
        self.bubble.set_on_hidden_callback(callback)

    # ========================================================================
    # 输入框
    # ========================================================================

    def show_input(self):
        """显示输入框"""
        self.input_panel.show_panel()
        self.update_positions()

    def hide_input(self):
        """隐藏输入框"""
        self.input_panel.hide_panel()

    def is_input_visible(self) -> bool:
        """输入框是否可见"""
        return self.input_panel.isVisible()

    def is_bubble_visible(self) -> bool:
        """气泡是否可见"""
        return self.bubble.isVisible()

    def clear_input(self):
        """清空输入框"""
        self.input_panel.clear_input()

    # ========================================================================
    # 焦点检查
    # ========================================================================

    def _check_app_focus(self):
        """
        检查应用是否失去焦点

        只有在输入框可见时才检查焦点，因为：
        - 输入框需要用户交互，失去焦点意味着用户可能不想输入了
        - 自动说话时只有气泡，不需要焦点，不应该被隐藏
        """
        if not self.input_panel.isVisible():
            return

        app = QApplication.instance()
        active_window = app.activeWindow()
        focused_widget = app.focusWidget()

        # 如果既没有活动窗口，也没有焦点控件，说明应用失去了焦点
        if active_window is None and focused_widget is None:
            logger.info("[UIManager] App lost focus, hiding chat UI")
            self.pet.on_chat_focus_lost()

    # ========================================================================
    # 用户输入处理
    # ========================================================================

    def _on_user_input(self, text: str):
        """
        用户发送消息

        隐藏输入框和动作栏，显示 typing，然后转发给 PetWindow 处理。
        """
        logger.info(f"[User] 发送: {text}")

        # 隐藏输入框和动作栏
        self.input_panel.hide_panel()
        self.action_bar.hide_bar()

        # 显示正在输入
        self.show_typing()

        # 使用 QTimer.singleShot 让 Qt 先处理 UI 更新
        # 然后再发布事件给 Agent，确保 "...等待框" 先显示出来
        from core import event_bus, EventCategory, AgentEvent
        QTimer.singleShot(0, lambda: event_bus.publish(
            EventCategory.AGENT, AgentEvent.USER_MESSAGE, message=text
        ))

    # ========================================================================
    # 动作栏
    # ========================================================================

    def set_action_callback(self, callback):
        """设置动作触发回调（由 Pet 设置，用于接入实际动作逻辑）"""
        self._action_callback = callback

    def _on_action_triggered(self, action_id: str):
        """
        动作按钮触发

        隐藏输入框和动作栏，显示 typing 等待气泡，然后通知 Pet 处理实际动作逻辑。
        """
        logger.info(f"[UIManager] Action triggered: {action_id}")

        # 停止焦点检查
        self._focus_check_timer.stop()

        # 隐藏输入框和动作栏
        self.input_panel.hide_panel()
        self.action_bar.hide_bar()

        # 显示 typing 等待气泡（和聊天发消息一致的体验）
        # 冷却中时 ActionHandler 会直接显示本地气泡，不调 LLM，
        # 但 typing 会先显示一瞬间，RESPONSE 没来时由 pet._waiting_llm 兜底清除
        self.show_typing()

        # 通知 Pet 处理动作（后续接入实际逻辑）
        if self._action_callback:
            self._action_callback(action_id)

    # ========================================================================
    # 飘字反馈（动作加分提示）
    # ========================================================================
    def show_floating_changes(self, changes: dict):
        """
        在宠物头顶飘出状态变化提示（如 "+20 饱食度"）

        Args:
            changes: {'satiety': 20, 'mood': 5, ...}
        """
        lines = changes_to_lines(changes)
        if not lines:
            return

        floating = FloatingText(lines)
        # 持有引用，防止 Python 对象被 GC 导致窗口销毁
        self._floating_texts.append(floating)
        # 动画结束（close）后从列表移除
        floating.destroyed.connect(lambda: self._floating_texts.remove(floating)
                                   if floating in self._floating_texts else None)

        # 定位到宠物右侧，垂直居中，避开头顶气泡/输入框区域
        pet_pos = self.pet.frameGeometry().topLeft()
        pet_width = self.pet.width()
        pet_height = self.pet.height()
        floating.adjustSize()
        # 右侧留出 12px 间距，垂直方向居中偏上
        x = pet_pos.x() + pet_width + 12
        y = pet_pos.y() + (pet_height - floating.height()) // 2 - 10
        # 边界保护：右侧超出屏幕则放到左侧
        # self.pet.screen 是 QRect（可用区域），不是 QScreen 对象
        screen_right = self.pet.screen.right()
        if x + floating.width() > screen_right:
            x = pet_pos.x() - floating.width() - 12
        y = max(0, y)
        floating.move(x, y)
        floating.show()
        floating.raise_()  # 确保在所有窗口之上

    # ========================================================================
    # 退出清理
    # ========================================================================

    def cleanup(self):
        """退出时清理所有 UI 组件"""
        self._focus_check_timer.stop()
        self.bubble.hide_bubble(trigger_callback=False)
        self.input_panel.hide_panel()
        self.action_bar.hide_bar()
