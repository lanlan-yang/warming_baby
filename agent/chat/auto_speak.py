"""
agent/chat/auto_speak.py - 宠物主动说话功能

根据时间、场景生成提示词，让 LLM 产生自然的自言自语或提醒。

架构:
    AutoSpeakPrompt: 生成不同场景的 prompt
    AutoSpeakManager: 管理触发逻辑（时机、频率、过滤）
"""
import time
import random
from datetime import datetime
from enum import StrEnum

from core.logger import setup_logger

logger = setup_logger()


# ============================================================================
# 1. 场景枚举
# ============================================================================
class SpeakScene(StrEnum):
    """主动说话的场景"""
    IDLE = 'idle'                # 无聊了
    WATER_REMIND = 'water'      # 喝水提醒
    EXERCISE_REMIND = 'exercise' # 起身活动提醒
    REST_REMIND = 'rest'        # 休息提醒
    SLEEP_REMIND = 'sleep'      # 早睡提醒
    MORNING_GREET = 'morning'   # 早上问候
    NIGHT_GREET = 'night'       # 晚上问候
    WORK_STRESS = 'stress'      # 工作压力大


# ============================================================================
# 2. Prompt 生成器
# ============================================================================
class AutoSpeakPrompt:
    """根据场景生成 prompt"""
    
    @staticmethod
    def get_prompt(scene: SpeakScene, context: dict = None) -> str:
        """
        获取指定场景的 prompt
        
        Args:
            scene: 说话场景
            context: 额外上下文信息
            
        Returns:
            给 LLM 的 prompt
        """
        context = context or {}
        current_time = datetime.now()
        time_str = current_time.strftime('%H:%M')
        
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
        
        return prompts.get(scene, prompts[SpeakScene.IDLE])
    
    @staticmethod
    def _idle_prompt(time_str: str) -> str:
        """无聊时的自言自语"""
        # 随机选择一个主要类型
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
        
        # 打乱顺序，让 LLM 更可能选择不同的类型
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
    def detect_scene(since_last_move: float) -> SpeakScene:
        """
        检测当前最适合说话的场景
        
        Args:
            since_last_move: 距离上次鼠标移动的秒数
            
        Returns:
            推荐的说话场景
        """
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        time_of_day = hour + minute / 60
        
        # 1. 深夜早睡提醒 (23:00 - 02:00)
        if 23 <= hour or hour < 2:
            return SpeakScene.SLEEP_REMIND
        
        # 2. 早上问候 (7:00 - 9:00)
        if 7 <= hour < 9:
            return SpeakScene.MORNING_GREET
        
        # 3. 晚上问候 (21:00 - 23:00)
        if 21 <= hour < 23:
            return SpeakScene.NIGHT_GREET
        
        # 4. 久坐提醒 (45分钟没动)
        if since_last_move > 2700:  # 45分钟
            # 随机选择提醒类型
            return random.choice([
                SpeakScene.WATER_REMIND,
                SpeakScene.EXERCISE_REMIND,
                SpeakScene.REST_REMIND,
            ])
        
        # 5. 固定喝水时间 (整点)
        if minute == 0 and hour >= 9 and hour < 21:
            return SpeakScene.WATER_REMIND
        
        # 6. 下午时段的变化 (14:00 - 18:00)
        if 14 <= hour < 18:
            # 有 30% 概率选择提醒，而不是都选 IDLE
            if random.random() < 0.3:
                return random.choice([
                    SpeakScene.WATER_REMIND,
                    SpeakScene.REST_REMIND,
                    SpeakScene.WORK_STRESS,
                ])
        
        # 7. 默认：无聊了，但随机选择一种变体
        return SpeakScene.IDLE
    


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
        self._last_speak_time = 0
        self._last_mouse_time = time.time()
        # 首次说话给个随机短延迟 (30秒到2分钟)，避免启动后立即说话
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
    ) -> bool:
        """
        判断是否应该说话
        
        Args:
            is_chatting: 正在聊天中
            is_sleeping: 宠物在睡觉
            is_dragging: 用户在拖动宠物
            
        Returns:
            True 表示应该说话
        """
        now = time.time()
        
        if not self.enabled:
            logger.info(f"[AutoSpeak] Should not speak: disabled")
            return False
        
        # 用户正在交互
        if is_chatting or is_sleeping or is_dragging:
            logger.info(f"[AutoSpeak] Should not speak: interacting (chatting={is_chatting}, sleeping={is_sleeping}, dragging={is_dragging})")
            return False
        
        # 检查下一次说话时间
        if now < self._next_speak_time:
            wait_sec = self._next_speak_time - now
            logger.info(f"[AutoSpeak] Should not speak: not yet time (wait {wait_sec:.0f}s, next={self._next_speak_time})")
            return False
        
        # 检查最小间隔
        elapsed = now - self._last_speak_time
        if elapsed < self.min_interval:
            logger.info(f"[AutoSpeak] Should not speak: min interval (elapsed={elapsed:.0f}s, min={self.min_interval}s)")
            return False
        
        logger.info(f"[AutoSpeak] Should speak now! (elapsed={elapsed:.0f}s, next_time={self._next_speak_time})")
        return True
    
    def get_speak_params(self) -> dict:
        """
        获取说话参数
        
        Returns:
            {'scene': SpeakScene, 'prompt': str}
        """
        # 计算距离上次鼠标移动的时间
        since_last_move = time.time() - self._last_mouse_time
        
        # 检测场景
        scene = SceneDetector.detect_scene(since_last_move)
        
        # 生成 prompt
        prompt = AutoSpeakPrompt.get_prompt(scene, {'since_last_move': since_last_move})
        
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
