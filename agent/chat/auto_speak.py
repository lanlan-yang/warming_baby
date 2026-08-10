"""
agent/chat/auto_speak.py - 宠物主动说话功能

根据时间、场景、宠物状态生成提示词，让 LLM 产生自然的自言自语或提醒。

架构:
    AutoSpeakPrompt: 生成不同场景的 prompt（状态感知）
    SceneDetector: 根据时间、状态检测当前场景
    AutoSpeakManager: 管理触发逻辑（时机、频率、过滤）
"""
import time
import random
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from core.logger import setup_logger

if TYPE_CHECKING:
    from pet.pet_stats import PetStats

logger = setup_logger()


# ============================================================================
# 1. 场景枚举
# ============================================================================
class SpeakScene(StrEnum):
    """主动说话的场景"""
    # 负面状态场景 (状态驱动, 优先级最高)
    HUNGRY = 'hungry'           # 饥饿了
    SAD = 'sad'                 # 心情不好
    DOZE_OFF = 'doze_off'       # 困了犯困
    BORING = 'boring'           # 无聊了

    # 时间/行为场景
    IDLE = 'idle'                # 随机自言自语
    WATER_REMIND = 'water'      # 喝水提醒
    EXERCISE_REMIND = 'exercise' # 起身活动提醒
    REST_REMIND = 'rest'        # 休息提醒
    SLEEP_REMIND = 'sleep'      # 早睡提醒
    MORNING_GREET = 'morning'   # 早上问候
    NIGHT_GREET = 'night'       # 晚上问候
    WORK_STRESS = 'stress'      # 工作压力大


# ============================================================================
# 1.1 负面状态 prompt 配置表（统一数据，消除重复代码）
# ============================================================================
NEGATIVE_STATE_CONFIG: dict[SpeakScene, dict] = {
    SpeakScene.HUNGRY: {
        'stat_key': 'satiety', 'stat_name': '饱食度',
        'desc': '很饿，肚子咕咕叫', 'feeling': '饥饿感，向主人求投喂',
        'emotion': 'hungry',
        'types': [
            ('直接求助', '好饿啊...'),
            ('撒娇求食', '肚子咕咕叫了~'),
            ('可爱暗示', '有没有好吃的呀'),
            ('可怜巴巴', '能给我点吃的吗'),
            ('念叨食物', '好想吃瓜子...'),
        ],
    },
    SpeakScene.SAD: {
        'stat_key': 'mood', 'stat_name': '心情',
        'desc': '很难过，心情不好', 'feeling': '难过，寻求安慰',
        'emotion': 'sad',
        'types': [
            ('委屈', '呜呜...不开心'),
            ('求安慰', '摸摸我好吗'),
            ('叹气', '唉...今天好闷'),
            ('低落', '心情不太好...'),
            ('想哭', '想哭哭...'),
        ],
    },
    SpeakScene.DOZE_OFF: {
        'stat_key': 'energy', 'stat_name': '体力',
        'desc': '很困，眼皮在打架', 'feeling': '困倦',
        'emotion': 'doze_off',
        'types': [
            ('打哈欠', '哈欠...好困啊'),
            ('想睡觉', '眼皮好重...'),
            ('求陪伴', '陪我睡一会儿好吗'),
            ('迷糊', '我好像快睡着了...'),
            ('撒娇', '困了...抱我睡觉'),
        ],
    },
    SpeakScene.BORING: {
        'stat_key': None, 'stat_name': None,
        'desc': '觉得好无聊', 'feeling': '无聊感',
        'emotion': 'boring',
        'types': [
            ('感慨', '时间过得好慢呀'),
            ('想玩', '好无聊啊，有人陪我吗'),
            ('好奇', '主人在忙什么呢'),
            ('撒娇', '主人~理理我嘛'),
            ('发呆', '发呆中...'),
            ('找事做', '找点事做吧'),
        ],
    },
}


# ============================================================================
# 2. Prompt 生成器
# ============================================================================
class AutoSpeakPrompt:
    """根据场景生成 prompt"""

    @staticmethod
    def get_prompt(
        scene: SpeakScene,
        context: dict = None,
        stats: 'PetStats' = None,
    ) -> str:
        """
        获取指定场景的 prompt

        Args:
            scene: 说话场景
            context: 额外上下文信息
            stats: 宠物状态 (用于状态感知 prompt)

        Returns:
            给 LLM 的 prompt
        """
        context = context or {}
        current_time = datetime.now()
        time_str = current_time.strftime('%H:%M')

        # 负面状态场景 (统一走配置表 + 通用方法)
        if scene in NEGATIVE_STATE_CONFIG:
            return AutoSpeakPrompt._negative_state_prompt(time_str, stats, scene)

        # 时间/行为场景
        prompts = {
            SpeakScene.IDLE: AutoSpeakPrompt._idle_prompt(time_str),
            SpeakScene.WATER_REMIND: AutoSpeakPrompt._water_prompt(time_str),
            SpeakScene.EXERCISE_REMIND: AutoSpeakPrompt._exercise_prompt(time_str),
            SpeakScene.REST_REMIND: AutoSpeakPrompt._rest_prompt(time_str),
            SpeakScene.SLEEP_REMIND: AutoSpeakPrompt._sleep_prompt(time_str),
            SpeakScene.MORNING_GREET: AutoSpeakPrompt._morning_prompt(time_str),
            SpeakScene.NIGHT_GREET: AutoSpeakPrompt._night_prompt(time_str),
            SpeakScene.WORK_STRESS: AutoSpeakPrompt._stress_prompt(time_str),
        }

        prompt = prompts.get(scene, prompts[SpeakScene.IDLE])

        # 有状态信息时, 追加状态提示到非状态场景
        if stats:
            state_hint = AutoSpeakPrompt._build_state_hint(stats)
            if state_hint:
                prompt = prompt + '\n\n' + state_hint

        return prompt

    # ---- 负面状态 prompt (通用) ----

    @staticmethod
    def _negative_state_prompt(
        time_str: str,
        stats: 'PetStats',
        scene: SpeakScene,
    ) -> str:
        """
        通用负面状态 prompt（饥饿/难过/困倦/无聊共用）

        从 NEGATIVE_STATE_CONFIG 读取配置，生成结构统一的 prompt。
        """
        config = NEGATIVE_STATE_CONFIG[scene]
        types = config['types']

        chosen_type, chosen_example = random.choice(types)
        shuffled = random.sample(types, len(types))
        types_str = '\n'.join(f'- {t[0]}：{t[1]}' for t in shuffled)

        # 有 stat_key 时注入数值，无则用纯描述
        if config['stat_key']:
            stat_value = getattr(stats, config['stat_key'], 0)
            stat_line = f"你的{config['stat_name']}只有 {stat_value:.0f}/100，你{config['desc']}。"
        else:
            stat_line = f"你{config['desc']}。"

        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}。
{stat_line}
说一句 5-15 字的话，表达{config['feeling']}。

今天想尝试的类型是：【{chosen_type}】，例如：{chosen_example}

可选择的类型：
{types_str}

请随机选一种类型说，不要总是说同一句话。
不要用 markdown，就说一句自然的话。

请返回 emotion: {config['emotion']}"""

    @staticmethod
    def _build_state_hint(stats: 'PetStats') -> str:
        """生成状态提示，追加到非状态场景的 prompt 末尾"""
        hints = []
        if stats.is_hungry():
            hints.append(f"你现在很饿(饱食度{stats.satiety:.0f})")
        if stats.is_sad():
            hints.append(f"你心情不好(心情{stats.mood:.0f})")
        if stats.is_tired():
            hints.append(f"你很困(体力{stats.energy:.0f})")

        # 亲密度影响语气
        if stats.intimacy < 20:
            hints.append("你和主人还不太熟，说话会客气一些")
        elif stats.intimacy >= 80:
            hints.append("你和主人是挚友，可以更亲昵撒娇")

        if not hints:
            return ''

        return f"注意：{'，'.join(hints)}。说话时自然地带出这些感受。"

    # ---- 时间/行为场景 prompt ----

    @staticmethod
    def _idle_prompt(time_str: str) -> str:
        """随机自言自语"""
        types = [
            ('感慨', '时间过得真快呀'),
            ('小发现', '窗外有只鸟飞过'),
            ('想玩', '好无聊啊，有人陪我吗'),
            ('好奇', '今天会发生什么呢'),
            ('撒娇', '主人~你在干嘛'),
            ('哈欠', '有点困了呢'),
            ('摸头', '摸摸我嘛'),
            ('吐槽', '今天天气真热'),
        ]
        chosen_type, chosen_example = random.choice(types)

        shuffled_types = random.sample(types, len(types))
        types_str = '\n'.join(f'- {t[0]}：{t[1]}' for t in shuffled_types)

        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}，你有点无聊。
说一句 5-15 字的自言自语，像真宠物一样。

今天想尝试的类型是：【{chosen_type}】，例如：{chosen_example}

可选择的类型：
{types_str}

请随机选一种类型说，不要总是说同一句话。
不要用 markdown，就说一句自然的话。"""

    @staticmethod
    def _water_prompt(time_str: str) -> str:
        """喝水提醒"""
        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}。
提醒主人喝水，说一句 5-12 字的话。

可以说的类型:
- 直接提醒：记得喝水哦
- 撒娇提醒：喝水水~
- 关心提醒：要多喝水呀

语气要可爱，不要说教。"""

    @staticmethod
    def _exercise_prompt(time_str: str) -> str:
        """起身活动提醒"""
        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}。
提醒主人站起来活动一下，说一句 5-12 字的话。

可以说的类型:
- 直接提醒：站起来动动吧
- 可爱提醒：要活动活动哦
- 关心提醒：别坐太久呀

语气要可爱，不要说教。"""

    @staticmethod
    def _rest_prompt(time_str: str) -> str:
        """休息提醒"""
        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}。
提醒主人休息一下眼睛，说一句 5-12 字的话。

可以说的类型:
- 直接提醒：休息一下眼睛吧
- 可爱提醒：看看远方~
- 关心提醒：别太累了呀

语气要可爱，不要说教。"""

    @staticmethod
    def _sleep_prompt(time_str: str) -> str:
        """早睡提醒"""
        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}，已经很晚了。
提醒主人早点睡觉，说一句 5-15 字的话。

可以说的类型:
- 直接提醒：该睡觉啦
- 担心提醒：熬夜对身体不好哦
- 撒娇提醒：我困了，陪我睡吧

语气要温柔，不要说教。"""

    @staticmethod
    def _morning_prompt(time_str: str) -> str:
        """早上问候"""
        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}，早上。
说一句 5-15 字的早安问候。

可以说的类型:
- 问候：早上好呀
- 鼓励：新的一天，加油！
- 活力：元气满满！

语气要活泼可爱。"""

    @staticmethod
    def _night_prompt(time_str: str) -> str:
        """晚上问候"""
        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}，晚上。
说一句 5-15 字的晚安问候。

可以说的类型:
- 问候：晚上好呀
- 关心：今天辛苦了
- 温馨：早点休息吧

语气要温柔可爱。"""

    @staticmethod
    def _stress_prompt(time_str: str) -> str:
        """工作压力大时"""
        return f"""你是一只可爱的机甲小仓鼠，现在是 {time_str}。
主人看起来工作有点累，说一句 5-15 字的安慰。

可以说的类型:
- 鼓励：加油！你可以的
- 关心：别太累了，休息一下
- 陪伴：我陪着你哦

语气要温暖可爱。"""


# ============================================================================
# 3. 场景检测器
# ============================================================================
class SceneDetector:
    """根据时间和状态检测当前场景"""

    @staticmethod
    def detect_scene(
        since_last_move: float,
        stats: 'PetStats' = None,
    ) -> SpeakScene:
        """
        检测当前最适合说话的场景

        优先级:
        1. 负面状态 (饥饿/悲伤/困倦) - 70% 概率触发
        2. 无低状态但长时间无互动 → 无聊
        3. 时间场景 (早睡/问候/久坐...)
        4. 默认: BORING 或 IDLE 随机

        Args:
            since_last_move: 距离上次鼠标移动的秒数
            stats: 宠物状态

        Returns:
            推荐的说话场景
        """
        now = datetime.now()
        hour = now.hour
        minute = now.minute

        # 1. 负面状态检测 (优先级最高, 70% 概率)
        if stats:
            low_stats = stats.get_low_stats()
            if low_stats and random.random() < 0.7:
                # 多个低状态时随机选一个
                stat = random.choice(low_stats)
                if stat == 'satiety':
                    return SpeakScene.HUNGRY
                elif stat == 'mood':
                    return SpeakScene.SAD
                elif stat == 'energy':
                    return SpeakScene.DOZE_OFF

        # 2. 深夜早睡提醒 (23:00 - 02:00)
        if 23 <= hour or hour < 2:
            return SpeakScene.SLEEP_REMIND

        # 3. 早上问候 (7:00 - 9:00)
        if 7 <= hour < 9:
            return SpeakScene.MORNING_GREET

        # 4. 晚上问候 (21:00 - 23:00)
        if 21 <= hour < 23:
            return SpeakScene.NIGHT_GREET

        # 5. 久坐提醒 (45分钟没动)
        if since_last_move > 2700:  # 45分钟
            return random.choice([
                SpeakScene.WATER_REMIND,
                SpeakScene.EXERCISE_REMIND,
                SpeakScene.REST_REMIND,
            ])

        # 6. 固定喝水时间 (整点)
        if minute == 0 and 9 <= hour < 21:
            return SpeakScene.WATER_REMIND

        # 7. 下午时段的变化 (14:00 - 18:00)
        if 14 <= hour < 18:
            if random.random() < 0.3:
                return random.choice([
                    SpeakScene.WATER_REMIND,
                    SpeakScene.REST_REMIND,
                    SpeakScene.WORK_STRESS,
                ])

        # 8. 默认: BORING 或 IDLE 随机
        return random.choice([SpeakScene.BORING, SpeakScene.IDLE])


# ============================================================================
# 4. 管理器
# ============================================================================
class AutoSpeakManager:
    """主动说话管理器"""

    def __init__(
        self,
        min_interval: int = 300,      # 最少间隔 5 分钟
        max_interval: int = 900,      # 最大间隔 15 分钟
        enabled: bool = True,
    ):
        """
        初始化管理器

        Args:
            min_interval: 最少间隔秒数
            max_interval: 最大间隔秒数
            enabled: 是否启用
        """
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.enabled = enabled

        # 状态
        self._last_speak_time = time.time()
        self._last_mouse_time = time.time()
        # 首次说话给个随机短延迟 (30秒到2分钟)
        self._next_speak_time = time.time() + random.uniform(30, 120)

        logger.info(f"[AutoSpeak] Initialized: interval={min_interval}-{max_interval}s, enabled={enabled}, next speak in {self._next_speak_time - time.time():.0f}s")

    def _calculate_next_time(self) -> float:
        """计算下一次说话时间"""
        delay = random.uniform(self.min_interval, self.max_interval)
        return time.time() + delay

    def should_speak(
        self,
        is_chatting: bool = False,
        is_sleeping: bool = False,
        is_dragging: bool = False,
        stats: 'PetStats' = None,
    ) -> bool:
        """
        判断是否应该说话

        Args:
            is_chatting: 正在聊天中
            is_sleeping: 宠物在睡觉
            is_dragging: 用户在拖动宠物
            stats: 宠物状态 (低状态时缩短间隔)

        Returns:
            True 表示应该说话
        """
        now = time.time()

        if not self.enabled:
            logger.debug(f"[AutoSpeak] Should not speak: disabled")
            return False

        # 用户正在交互
        if is_chatting or is_sleeping or is_dragging:
            logger.debug(f"[AutoSpeak] Should not speak: interacting (chatting={is_chatting}, sleeping={is_sleeping}, dragging={is_dragging})")
            return False

        # 状态差时缩短间隔 (间隔减半)
        has_low_stats = bool(stats and stats.get_low_stats())

        # 检查下一次说话时间
        effective_next = self._next_speak_time
        if has_low_stats:
            # 低状态时允许提前说话 (等待时间减半)
            effective_next = self._last_speak_time + (self._next_speak_time - self._last_speak_time) / 2

        if now < effective_next:
            wait_sec = effective_next - now
            logger.debug(f"[AutoSpeak] Should not speak: not yet time (wait {wait_sec:.0f}s, low_stats={has_low_stats})")
            return False

        # 检查最小间隔
        elapsed = now - self._last_speak_time
        min_interval = self.min_interval / 2 if has_low_stats else self.min_interval
        if elapsed < min_interval:
            logger.debug(f"[AutoSpeak] Should not speak: min interval (elapsed={elapsed:.0f}s, min={min_interval:.0f}s, low_stats={has_low_stats})")
            return False

        logger.info(f"[AutoSpeak] Should speak now! (elapsed={elapsed:.0f}s, low_stats={has_low_stats})")
        return True

    def get_speak_params(self, stats: 'PetStats' = None) -> dict:
        """
        获取说话参数

        Args:
            stats: 宠物状态

        Returns:
            {'scene': SpeakScene, 'prompt': str}
        """
        # 计算距离上次鼠标移动的时间
        since_last_move = time.time() - self._last_mouse_time

        # 检测场景
        scene = SceneDetector.detect_scene(since_last_move, stats)

        # 生成 prompt
        prompt = AutoSpeakPrompt.get_prompt(scene, {'since_last_move': since_last_move}, stats)

        logger.info(f"[AutoSpeak] Scene: {scene.value}, Prompt: {prompt[:30]}...")

        return {
            'scene': scene,
            'prompt': prompt,
        }

    def on_mouse_move(self):
        """鼠标移动时调用"""
        self._last_mouse_time = time.time()

    def speak_done(self):
        """说话完成时调用"""
        self._last_speak_time = time.time()
        self._next_speak_time = self._calculate_next_time()
        logger.info(f"[AutoSpeak] Next speak at: {datetime.fromtimestamp(self._next_speak_time)}")

    def enable(self):
        """启用"""
        self.enabled = True
        logger.info("[AutoSpeak] Enabled")

    def disable(self):
        """禁用"""
        self.enabled = False
        logger.info("[AutoSpeak] Disabled")

    def set_interval(self, min_interval: int, max_interval: int):
        """设置间隔（重置下次说话时间使设置立即生效）"""
        self.min_interval = min_interval
        self.max_interval = max_interval
        # 重置下次说话时间，使新设置立即生效
        self._next_speak_time = self._calculate_next_time()
        logger.info(f"[AutoSpeak] Interval set to {min_interval}-{max_interval}s, next speak at {self._next_speak_time}")
