"""
pet.actions - 动作执行层

职责：
1. 接收 UI 按钮触发的 action_id（feed/play/pet/sleep）
2. 调用 PetStats.apply() 改变数值状态
3. 构造伪用户消息，通过 event_bus 发布给 ChatAgent，复用现有 LLM + 动画链路
4. 冷却中时，直接发一条本地气泡（不调 LLM）

设计原则：
- 完全解耦：ActionHandler 不依赖 Pet 类，不依赖 Qt
- 与用户聊天走同一条 LLM 链路（USER_MESSAGE → chat() → RESPONSE → 气泡+动画）
  保证动作回复和普通聊天回复风格一致
"""
from typing import Callable, Optional

from core.logger import setup_logger
from core.event_bus import event_bus, EventCategory, AgentEvent

from pet.pet_stats import PetStats, ActionType

logger = setup_logger()


# ============================================================================
# 动作 → 伪用户消息 映射
# ============================================================================
# 构造一段"用户对宠物说了什么"的文本，喂给 ChatAgent。
# 这样 LLM 会根据这段输入生成合适的回复和 emotion。
# 规则写得越明确，LLM 返回的 emotion 和回复越准确。
ACTION_USER_MESSAGES: dict[ActionType, str] = {
    ActionType.FEED: (
        "【用户主动投喂了你一些好吃的食物】\n"
        "请表达开心和感谢。"
        "重要：请严格根据 system prompt 中的当前饱食度数值决定回复，"
        "不要根据'之前被喂过几次'来推断是否吃饱。"
        "饱食度低(<30)时表达还想吃，饱食度高(>90)时表达吃不下。"
    ),
    ActionType.PLAY: (
        "【用户邀请你一起玩耍】\n"
        "请表达开心和兴奋。"
        "重要：请严格根据 system prompt 中的当前心情和体力数值决定回复，"
        "不要根据'之前玩过几次'来推断。"
        "体力低(<20)时说想歇一会儿，心情高时蹦蹦跳跳。"
    ),
    ActionType.PET: (
        "【用户抚摸了你的头/抱抱你】\n"
        "请表达被抚摸的舒服和满足，根据亲密度调整语气："
        "亲密度低时礼貌说谢谢，亲密度高时撒娇黏人。"
    ),
    ActionType.SLEEP: (
        "【用户哄你去睡觉休息】\n"
        "请表达困倦、安心地去睡觉。"
        "重要：请严格根据 system prompt 中的当前体力数值决定回复。"
        "体力充足时有点舍不得去睡，体力低时立刻去睡。"
    ),
}

# 冷却提示语（直接显示气泡，不走 LLM，避免消耗 token）
COOLDOWN_MESSAGES: dict[ActionType, str] = {
    ActionType.FEED: "刚刚吃过啦，不饿~",
    ActionType.PLAY: "有点累了，等会儿再玩吧~",
    ActionType.PET: "嘿嘿，脸都红啦~",
    ActionType.SLEEP: "刚睡过，现在精神得很~",
}


# ============================================================================
# ActionHandler 核心类
# ============================================================================
class ActionHandler:
    """
    动作执行层

    外部调用（Pet.__init__）：
        stats = PetStats()
        handler = ActionHandler(stats)
        handler.set_bubble_callback(pet.show_message)
        ui_manager.set_action_callback(handler.handle)

    数据流：
        用户点击"投喂"
          → handler.handle('feed')
          → stats.apply(FEED)              # 改数值
          → event_bus.publish(USER_MESSAGE) # 复用聊天链路
          → ChatAgent.chat("用户投喂了你...")  # LLM 生成回复
          → event_bus.publish(RESPONSE)    # 动画 + 气泡（Pet 已订阅）
    """

    def __init__(self, stats: PetStats):
        """
        Args:
            stats: 已初始化并加载过存档的 PetStats 实例
        """
        self.stats = stats
        self._bubble_callback: Optional[Callable] = None
        self._changes_callback: Optional[Callable] = None

        # 动作 ID（字符串）到 ActionType 枚举的映射
        # 与 action_bar.py 中的按钮 id 保持一致
        self._id_mapping: dict[str, ActionType] = {
            'feed': ActionType.FEED,
            'play': ActionType.PLAY,
            'pet': ActionType.PET,
            'sleep': ActionType.SLEEP,
        }

        logger.info("[ActionHandler] 初始化完成")

    # ========================================================================
    # 外部接口
    # ========================================================================
    def set_bubble_callback(self, callback: Callable[[str], None]):
        """
        设置气泡回调（冷却提示语用）

        Args:
            callback: 接收一个字符串，直接显示气泡
                      传 show_message 或包装后的方法
        """
        self._bubble_callback = callback

    def set_changes_callback(self, callback: Callable[[dict], None]):
        """
        设置状态变化回调（飘字反馈用）

        Args:
            callback: 接收 changes dict，如 {'satiety': 20, 'mood': 5}
                      由 UIManager 转成飘字显示
        """
        self._changes_callback = callback

    def handle(self, action_id: str) -> dict:
        """
        处理动作按钮触发（UIManager 回调）

        Args:
            action_id: 动作 ID，与 action_bar 按钮 id 一致
                       ('feed' / 'play' / 'pet' / 'sleep')

        Returns:
            dict: {'changes': {...}, 'cooldown': bool, 'intimacy_capped': bool}
                  调用方可用 changes 显示飘字
        """
        # 解析 action_id
        action = self._id_mapping.get(action_id)
        if action is None:
            logger.warning(f"[ActionHandler] 未知动作 ID: {action_id}")
            return {'changes': {}, 'cooldown': False, 'intimacy_capped': False}

        # 0. 快照操作前的状态（LLM 需要根据操作前的状态回复）
        #    例如：satiety=80 时被喂食，LLM 应看到 80 而非 100
        pre_status = self.stats.to_prompt()

        # 1. 改状态
        result = self.stats.apply(action)

        # 2. 冷却中 → 直接本地气泡提示，不走 LLM
        if result is None:
            remaining = self.stats._get_cooldown_remaining(action)
            logger.info(
                f"[ActionHandler] {action.value} 冷却中，"
                f"剩余 {remaining:.0f}s，显示本地气泡"
            )
            self._show_local_bubble(COOLDOWN_MESSAGES.get(action, "稍等一下哦~"))
            return {'changes': {}, 'cooldown': True, 'intimacy_capped': False}

        changes = result.get('changes', {})
        logger.info(
            f"[ActionHandler] 动作 {action.value} 执行完成: "
            f"状态变化={changes}，发送给 ChatAgent"
        )

        # 亲密度今日已达上限 → 显示本地提示，不调 LLM
        if result.get('intimacy_capped'):
            self._show_local_bubble("今天亲密度已经满啦，明天再来陪我玩吧~")
            return {'changes': changes, 'cooldown': False, 'intimacy_capped': True}

        # 3. 构造伪用户消息，发给 ChatAgent（复用现有聊天链路）
        #    携带操作前的状态快照，让 LLM 根据操作前的状态回复
        message = ACTION_USER_MESSAGES.get(action, "用户做了一个动作")
        event_bus.publish(
            EventCategory.AGENT,
            AgentEvent.USER_MESSAGE,
            message=message,
            pre_status=pre_status,
        )

        return {'changes': changes, 'cooldown': False, 'intimacy_capped': False}

    # ========================================================================
    # 内部方法
    # ========================================================================
    def _show_local_bubble(self, text: str):
        """显示本地气泡（冷却提示等不需要 LLM 的场景）"""
        if self._bubble_callback:
            try:
                self._bubble_callback(text, auto_hide=True)
            except TypeError:
                # 如果回调只接受一个参数（向后兼容）
                try:
                    self._bubble_callback(text)
                except Exception as e:
                    logger.error(f"[ActionHandler] 气泡回调失败: {e}")
        else:
            logger.info(f"[ActionHandler] 气泡提示: {text}（未设置回调，仅日志）")
