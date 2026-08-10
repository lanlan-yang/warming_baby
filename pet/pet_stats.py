"""
pet.stats - 宠物数值状态系统

职责：
1. 维护 4 项核心状态（饱食度/心情/体力/亲密度）
2. 自然衰减（按真实时间流逝，支持离线衰减）
3. 动作应用（feed/play/pet/sleep 改变数值）
4. 持久化（JSON 文件，跨平台）
5. 生成 LLM 可读的状态描述（to_prompt）

设计原则：
- 纯数值管理，不涉及 LLM、不涉及动画
- 与 Pet 对象解耦，通过 apply() 被 ActionHandler 调用
- 状态变化通过 apply() 返回值通知调用方（用于触发动画/气泡）

Usage:
    stats = PetStats()
    stats.load()                       # 启动时加载
    changes = stats.apply('feed')      # 动作应用，返回变化详情
    stats.tick()                       # 定时调用，自然衰减
    prompt = stats.to_prompt()         # 给 LLM 的状态文本
    stats.save()                       # 持久化
"""
import json
import time
from enum import StrEnum
from pathlib import Path
from typing import Optional

from core.logger import setup_logger
from config.storage import get_config_dir

logger = setup_logger()


# ============================================================================
# 1. 动作类型枚举
# ============================================================================
class ActionType(StrEnum):
    """宠物可执行的动作（与 UI 动作栏按钮一一对应）"""
    FEED = 'feed'      # 投喂
    PLAY = 'play'      # 玩耍
    PET = 'pet'        # 抚摸
    SLEEP = 'sleep'    # 睡觉


# ============================================================================
# 2. 动作配置表（数值变化 + 冷却）
# ============================================================================
# 冷却时间（秒）：避免短时间内重复触发
ACTION_COOLDOWNS: dict[ActionType, float] = {
    ActionType.FEED: 30.0,       # 30 秒
    ActionType.PLAY: 60.0,       # 1 分钟
    ActionType.PET: 10.0,        # 10 秒
    ActionType.SLEEP: 300.0,     # 5 分钟
}

# 冷却触发阈值：状态值 >= 此值时才启用冷却
# 低于此值时不限制，让用户能快速恢复宠物状态
ACTION_COOLDOWN_THRESHOLDS: dict[ActionType, tuple[str, float]] = {
    ActionType.FEED: ('satiety', 80.0),   # 饱食度 >= 80 才冷却
    ActionType.PLAY: ('mood', 80.0),      # 心情 >= 80 才冷却
    ActionType.PET: ('intimacy', 80.0),   # 亲密度 >= 80 才冷却
    ActionType.SLEEP: ('energy', 80.0),   # 体力 >= 80 才冷却
}

# 动作效果：每个动作对各项状态的增减
# None 表示该动作不影响这项状态
ACTION_EFFECTS: dict[ActionType, dict[str, int]] = {
    ActionType.FEED: {
        'satiety': +20,
        'mood': +5,
        'energy': None,
        'intimacy': None,
    },
    ActionType.PLAY: {
        'satiety': None,
        'mood': +15,
        'energy': -10,
        'intimacy': None,
    },
    ActionType.PET: {
        'satiety': None,
        'mood': +10,
        'energy': None,
        'intimacy': +3,
    },
    ActionType.SLEEP: {
        'satiety': None,
        'mood': None,
        'energy': +50,
        'intimacy': None,
    },
}


# ============================================================================
# 3. 自然衰减配置
# ============================================================================
# 每项状态每分钟衰减的数值（正数表示减少）
DECAY_PER_MINUTE: dict[str, float] = {
    'satiety': 1.0 / 5,      # 5 分钟 -1（每小时 -12）
    'mood': 1.0 / 10,        # 10 分钟 -1（每小时 -6）
    'energy': 1.0 / 8,       # 8 分钟 -1（每小时 -7.5）
    'intimacy': 0.0,         # 亲密度不衰减
}


# ============================================================================
# 4. PetStats 核心类
# ============================================================================
class PetStats:
    """
    宠物数值状态

    四项核心状态：
    - satiety   饱食度 (0-100)：低于 30 触发饥饿
    - mood      心情   (0-100)：低于 30 触发难过
    - energy    体力   (0-100)：低于 20 触发困倦
    - intimacy  亲密度 (0-100)：累积值，不衰减，影响说话语气

    状态范围：
    - 0-100 之间
    - 低于阈值会触发对应情绪（由 ActionHandler/auto_speak 读取判断）
    """

    # 状态阈值（低于此值触发对应行为）
    THRESHOLD_HUNGRY = 30      # 饱食度 < 30 → 饥饿
    THRESHOLD_SAD = 30         # 心情 < 30 → 难过
    THRESHOLD_TIRED = 20       # 体力 < 20 → 困倦

    # 亲密度边际递减阈值（A 方案）
    # 0-50: +3/次, 50-80: +2/次, 80-100: +1/次
    INTIMACY_TIER_1 = 50       # 0~50 每次加 3
    INTIMACY_TIER_2 = 80       # 50~80 每次加 2
    INTIMACY_GAIN_TIER_1 = 3
    INTIMACY_GAIN_TIER_2 = 2
    INTIMACY_GAIN_TIER_3 = 1

    # 亲密度每日上限（B 方案）
    INTIMACY_DAILY_LIMIT = 15

    # 默认初始值（首次启动用）
    DEFAULT_VALUES = {
        'satiety': 70,
        'mood': 80,
        'energy': 80,
        'intimacy': 20,
    }

    # 持久化文件名（相对 get_config_dir()）
    SAVE_FILE_NAME = 'pet_stats.json'

    def __init__(self):
        # 状态值
        self.satiety: float = self.DEFAULT_VALUES['satiety']
        self.mood: float = self.DEFAULT_VALUES['mood']
        self.energy: float = self.DEFAULT_VALUES['energy']
        self.intimacy: float = self.DEFAULT_VALUES['intimacy']

        # 上次更新时间（Unix 时间戳，秒）
        # 用于计算自然衰减的时间差
        self._last_update_ts: float = time.time()

        # 冷却记录：{action_type: 上次执行时间戳}
        self._cooldowns: dict[ActionType, float] = {}

        # 亲密度每日累积（B 方案）
        # _intimacy_today: 今日已增加的亲密度
        # _intimacy_date: 今日日期字符串 'YYYY-MM-DD'，用于跨日重置
        self._intimacy_today: float = 0.0
        self._intimacy_date: str = ''

        logger.info("[PetStats] 初始化完成")

    # ========================================================================
    # 状态读取（对外只读接口）
    # ========================================================================
    def get(self, key: str) -> float:
        """获取某项状态的当前值"""
        return getattr(self, key)

    def is_hungry(self) -> bool:
        """是否处于饥饿状态"""
        return self.satiety < self.THRESHOLD_HUNGRY

    def is_sad(self) -> bool:
        """是否处于难过状态"""
        return self.mood < self.THRESHOLD_SAD

    def is_tired(self) -> bool:
        """是否处于困倦状态"""
        return self.energy < self.THRESHOLD_TIRED

    def get_low_stats(self) -> list[str]:
        """
        返回所有低于阈值的状态名列表（用于 auto_speak 判断该说什么）

        Returns:
            ['satiety', 'energy'] 表示又饿又困
        """
        low = []
        if self.is_hungry():
            low.append('satiety')
        if self.is_sad():
            low.append('mood')
        if self.is_tired():
            low.append('energy')
        return low

    # ========================================================================
    # 自然衰减
    # ========================================================================
    def tick(self) -> dict[str, float]:
        """
        自然衰减（根据真实时间差计算）

        应由定时器周期性调用（如每分钟一次）。
        也会在 load() 时调用，处理离线期间的衰减。

        Returns:
            本次衰减的变化量 {'satiety': -2.0, 'mood': -1.0, ...}
            负数表示减少，0 表示无变化
        """
        now = time.time()
        elapsed_sec = now - self._last_update_ts

        # 不足 1 秒不处理（避免高频调用产生浮点误差）
        if elapsed_sec < 1.0:
            return {}

        elapsed_min = elapsed_sec / 60.0
        changes: dict[str, float] = {}

        for stat_key, decay_rate in DECAY_PER_MINUTE.items():
            if decay_rate <= 0:
                continue
            delta = -decay_rate * elapsed_min
            old_val = getattr(self, stat_key)
            new_val = max(0.0, old_val + delta)
            actual_delta = new_val - old_val
            if actual_delta != 0:
                setattr(self, stat_key, new_val)
                changes[stat_key] = actual_delta

        self._last_update_ts = now

        if changes:
            logger.debug(
                f"[PetStats] 自然衰减 ({elapsed_min:.1f}分钟): {changes}"
            )

        return changes

    # ========================================================================
    # 动作应用
    # ========================================================================
    def apply(self, action: ActionType) -> Optional[dict]:
        """
        应用一个动作，改变状态

        Args:
            action: 动作类型

        Returns:
            成功时返回 {'action': 'feed', 'changes': {...}, 'new_values': {...}}
            冷却中时返回 None
        """
        # 1. 检查冷却
        if self._is_in_cooldown(action):
            remaining = self._get_cooldown_remaining(action)
            logger.info(
                f"[PetStats] 动作 {action.value} 冷却中，"
                f"还需 {remaining:.0f}秒"
            )
            return None

        # 2. 跨日重置亲密度每日累积
        self._check_intimacy_daily_reset()

        # 3. 应用效果
        effects = ACTION_EFFECTS.get(action, {})
        changes: dict[str, float] = {}

        for stat_key, delta in effects.items():
            if delta is None or delta == 0:
                continue

            # 亲密度特殊处理：边际递减 + 每日上限
            if stat_key == 'intimacy':
                actual_delta = self._calc_intimacy_gain(delta)
                if actual_delta <= 0:
                    # 今日已达上限
                    logger.info(
                        f"[PetStats] 亲密度今日已达上限 "
                        f"({self._intimacy_today:.0f}/{self.INTIMACY_DAILY_LIMIT})"
                    )
                    # 仍记录冷却，避免用户疯狂点击
                    self._cooldowns[action] = time.time()
                    return {
                        'action': action.value,
                        'changes': {},
                        'new_values': self.snapshot(),
                        'intimacy_capped': True,
                    }
            else:
                old_val = getattr(self, stat_key)
                new_val = max(0.0, min(100.0, old_val + delta))
                actual_delta = new_val - old_val

            if actual_delta != 0:
                old_val = getattr(self, stat_key)
                new_val = max(0.0, min(100.0, old_val + actual_delta))
                setattr(self, stat_key, new_val)
                if stat_key == 'intimacy':
                    self._intimacy_today += actual_delta
                changes[stat_key] = actual_delta

        # 4. 记录冷却
        self._cooldowns[action] = time.time()

        logger.info(
            f"[PetStats] 应用动作 {action.value}: "
            f"变化={changes}, "
            f"当前=饱食{self.satiety:.0f}/心情{self.mood:.0f}/"
            f"体力{self.energy:.0f}/亲密{self.intimacy:.0f}"
            f"(今日+{self._intimacy_today:.0f}/{self.INTIMACY_DAILY_LIMIT})"
        )

        return {
            'action': action.value,
            'changes': changes,
            'new_values': self.snapshot(),
        }

    def _calc_intimacy_gain(self, base_delta: int) -> float:
        """
        计算亲密度实际增量（边际递减 + 每日上限）

        Args:
            base_delta: 基础增量（如 +3）

        Returns:
            实际增量（考虑边际递减和每日上限后）
            返回 0 表示今日已达上限或无法再增加
        """
        if base_delta <= 0:
            return 0.0

        # 每日上限检查
        remaining_daily = self.INTIMACY_DAILY_LIMIT - self._intimacy_today
        if remaining_daily <= 0:
            return 0.0

        # 边际递减：根据当前亲密度等级决定单次增量
        if self.intimacy < self.INTIMACY_TIER_1:
            tier_gain = self.INTIMACY_GAIN_TIER_1
        elif self.intimacy < self.INTIMACY_TIER_2:
            tier_gain = self.INTIMACY_GAIN_TIER_2
        else:
            tier_gain = self.INTIMACY_GAIN_TIER_3

        # 取基础增量和等级增量的较小值（如配置 base=3 但已在 80+ 等级，就只 +1）
        actual = min(base_delta, tier_gain)

        # 再受每日上限限制
        actual = min(actual, remaining_daily)

        # 不超过 100
        actual = min(actual, 100.0 - self.intimacy)

        return max(0.0, actual)

    def _check_intimacy_daily_reset(self):
        """跨日重置亲密度每日累积"""
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        if self._intimacy_date != today:
            if self._intimacy_date:  # 不是首次初始化
                logger.info(
                    f"[PetStats] 跨日重置亲密度累积: "
                    f"{self._intimacy_date} → {today}, "
                    f"昨日增加 {self._intimacy_today:.0f}"
                )
            self._intimacy_today = 0.0
            self._intimacy_date = today

    def _is_in_cooldown(self, action: ActionType) -> bool:
        """检查动作是否在冷却中

        状态值低于阈值时不冷却，让用户能快速恢复宠物状态。
        例如饱食度 15 时连续喂食不受 30 秒冷却限制。
        """
        last_used = self._cooldowns.get(action)
        if last_used is None:
            return False

        # 状态低于阈值 → 不冷却
        threshold_config = ACTION_COOLDOWN_THRESHOLDS.get(action)
        if threshold_config:
            stat_key, threshold = threshold_config
            current_val = getattr(self, stat_key, 0)
            if current_val < threshold:
                return False

        cooldown_sec = ACTION_COOLDOWNS.get(action, 0)
        return (time.time() - last_used) < cooldown_sec

    def _get_cooldown_remaining(self, action: ActionType) -> float:
        """获取冷却剩余时间（秒）"""
        last_used = self._cooldowns.get(action)
        if last_used is None:
            return 0.0
        cooldown_sec = ACTION_COOLDOWNS.get(action, 0)
        return max(0.0, cooldown_sec - (time.time() - last_used))

    # ========================================================================
    # 快照（当前所有状态的字典表示）
    # ========================================================================
    def snapshot(self) -> dict[str, float]:
        """返回当前所有状态的快照"""
        return {
            'satiety': round(self.satiety, 1),
            'mood': round(self.mood, 1),
            'energy': round(self.energy, 1),
            'intimacy': round(self.intimacy, 1),
        }

    # ========================================================================
    # LLM Prompt 生成
    # ========================================================================
    def to_prompt(self) -> str:
        """
        生成给 LLM 的状态描述文本

        LLM 看到这段文本后，回复会自然带状态感知：
        - 饱食度 20 + 投喂 → "谢谢...但还是好饿"
        - 饱食度 95 + 投喂 → "呜...吃不下了"

        Returns:
            状态描述字符串，可直接拼入 system prompt
        """
        # 数值转描述等级
        satiety_desc = self._level_desc(self.satiety)
        mood_desc = self._level_desc(self.mood)
        energy_desc = self._level_desc(self.energy)
        intimacy_desc = self._level_desc(self.intimacy, is_intimacy=True)

        lines = [
            "【宠物状态】",
            f"饱食度: {self.satiety:.0f}/100 ({satiety_desc})",
            f"心情: {self.mood:.0f}/100 ({mood_desc})",
            f"体力: {self.energy:.0f}/100 ({energy_desc})",
            f"亲密度: {self.intimacy:.0f}/100 ({intimacy_desc})",
        ]

        # 提示低状态
        low_hints = []
        if self.is_hungry():
            low_hints.append("你现在很饿，想求投喂")
        if self.is_sad():
            low_hints.append("你现在心情不好，需要安慰")
        if self.is_tired():
            low_hints.append("你现在很困，想睡觉")

        if low_hints:
            lines.append("提示: " + "；".join(low_hints))

        return "\n".join(lines)

    @staticmethod
    def _level_desc(value: float, is_intimacy: bool = False) -> str:
        """数值转等级描述"""
        if is_intimacy:
            if value < 20:
                return "陌生"
            elif value < 40:
                return "认识"
            elif value < 60:
                return "熟悉"
            elif value < 80:
                return "亲密"
            else:
                return "挚友"
        else:
            if value < 20:
                return "极低"
            elif value < 40:
                return "偏低"
            elif value < 60:
                return "一般"
            elif value < 80:
                return "良好"
            else:
                return "充足"

    # ========================================================================
    # 持久化
    # ========================================================================
    def save(self) -> bool:
        """
        保存状态到文件

        Returns:
            True 表示保存成功
        """
        try:
            save_path = self._get_save_path()
            save_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                'satiety': self.satiety,
                'mood': self.mood,
                'energy': self.energy,
                'intimacy': self.intimacy,
                'last_update_ts': time.time(),
                'cooldowns': {
                    action.value: ts
                    for action, ts in self._cooldowns.items()
                },
                # 亲密度每日累积（B 方案）
                'intimacy_today': self._intimacy_today,
                'intimacy_date': self._intimacy_date,
            }

            # 用 with + 显式 flush + os.fsync 确保数据落盘
            # 因为 _do_exit() 会 os._exit(0) 暴力杀进程，
            # 不刷盘的话 OS 文件系统缓存可能丢失最后写入
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                import os as _os
                _os.fsync(f.fileno())

            logger.debug(f"[PetStats] 保存成功 → {save_path}")
            return True

        except Exception as e:
            logger.error(f"[PetStats] 保存失败: {e}", exc_info=True)
            return False

    def load(self) -> bool:
        """
        从文件加载状态

        加载后会自动应用离线期间的衰减。

        Returns:
            True 表示加载成功，False 表示文件不存在或损坏（用默认值）
        """
        try:
            save_path = self._get_save_path()
            if not save_path.exists():
                logger.info(
                    f"[PetStats] 存档不存在，使用默认值: {self.DEFAULT_VALUES}"
                )
                self._last_update_ts = time.time()
                return False

            with open(save_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.satiety = float(data.get('satiety', self.DEFAULT_VALUES['satiety']))
            self.mood = float(data.get('mood', self.DEFAULT_VALUES['mood']))
            self.energy = float(data.get('energy', self.DEFAULT_VALUES['energy']))
            self.intimacy = float(data.get('intimacy', self.DEFAULT_VALUES['intimacy']))

            # 加载上次更新时间（用于离线衰减）
            self._last_update_ts = float(data.get('last_update_ts', time.time()))

            # 加载冷却记录
            self._cooldowns = {}
            for action_str, ts in data.get('cooldowns', {}).items():
                try:
                    action = ActionType(action_str)
                    self._cooldowns[action] = float(ts)
                except (ValueError, TypeError):
                    continue

            # 加载亲密度每日累积（B 方案）
            # 注意：加载后立即检查跨日重置，如果是新的一天，_intimacy_today 会归零
            self._intimacy_today = float(data.get('intimacy_today', 0.0))
            self._intimacy_date = data.get('intimacy_date', '')
            self._check_intimacy_daily_reset()

            # 应用离线期间的衰减
            self.tick()

            logger.info(
                f"[PetStats] 加载成功: "
                f"饱食{self.satiety:.0f}/心情{self.mood:.0f}/"
                f"体力{self.energy:.0f}/亲密{self.intimacy:.0f}"
                f"(今日+{self._intimacy_today:.0f}/{self.INTIMACY_DAILY_LIMIT})"
            )
            return True

        except Exception as e:
            logger.error(f"[PetStats] 加载失败: {e}", exc_info=True)
            # 重置为默认值
            self.satiety = self.DEFAULT_VALUES['satiety']
            self.mood = self.DEFAULT_VALUES['mood']
            self.energy = self.DEFAULT_VALUES['energy']
            self.intimacy = self.DEFAULT_VALUES['intimacy']
            self._last_update_ts = time.time()
            self._cooldowns = {}
            return False

    @staticmethod
    def _get_save_path() -> Path:
        """获取存档文件路径"""
        return get_config_dir() / PetStats.SAVE_FILE_NAME
