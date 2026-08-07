"""
core.animations - 动画注册表 (Single Source of Truth)

所有动画相关的定义都在这里，新增动画只需修改这一个文件。

Usage:
    from core.animations import AnimationRegistry, AnimationType

    # 根据字符串解析动画
    anim = AnimationRegistry.resolve('happy')  # -> AnimationType.TOUCH

    # 获取配置
    config = AnimationRegistry.get_config(AnimationType.TOUCH)
    # -> AnimationConfig(file_name='touch.gif', play_once=True, ...)

    # 获取 LLM 描述 (可放 system prompt)
    print(AnimationRegistry.get_llm_description())
"""
from enum import StrEnum
from pathlib import Path
from typing import Optional

from pydantic import Field

from core.schemas import BaseSchema


# ============================================================================
# 1. 动画类型枚举
# ============================================================================
class AnimationType(StrEnum):
    """
    动画类型 - 所有可用的动画

    根据 assets/gif_sprites/ 目录下的 GIF 文件定义

    新增动画步骤:
    1. 在枚举中添加新值
    2. 在 _configs 中添加对应配置
    """
    # 基础动画 (无特定情绪)
    WALK = 'walk'           # 走路/闲逛
    STAND = 'stand'         # 站立/发呆
    FLY = 'fly'             # 飞起来
    CONFUSED = 'confused'   # 困惑/思考

    # 情绪动画 (单次播放)
    TOUCH = 'touch'         # 被抚摸/开心
    HAPPY = 'happy'         # 开心/兴奋
    SAD = 'sad'             # 难过/委屈
    ANGRY = 'angry'         # 愤怒/生气

    # 状态动画 (循环播放)
    SLEEP = 'sleep'         # 睡觉/犯困
    PLAYING = 'playing'     # 玩游戏/娱乐
    SEARCHING = 'searching' # 搜索/寻找
    EATING = 'eating'       # 吃东西/吃饭
    NEUTRAL = 'neutral'     # 正常说话/中性

    # 动作动画 (单次播放)
    LEAVE = 'leave'         # 离开/道别
    DRAG = 'drag'           # 被拖拽中


# ============================================================================
# 2. 动画配置 (Pydantic BaseSchema)
# ============================================================================
class AnimationConfig(BaseSchema):
    """
    单个动画的完整配置

    Attributes:
        animation_type: 枚举值
        file_name: GIF 文件名 (相对于 assets/gif_sprites/)
        aliases: 别名列表 (小写，用于 LLM 和外部调用)
        description: LLM 友好描述
        play_once: 是否默认单次播放
        duration_ms: 单次播放时长 (None 表示用默认值)
    """
    animation_type: AnimationType
    file_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ''
    play_once: bool = False
    duration_ms: Optional[int] = None


# ============================================================================
# 3. 动画注册表
# ============================================================================
class AnimationRegistry:
    """
    动画注册表 - 统一管理所有动画定义

    设计原则:
    - 配置集中在 _configs 字典，新增动画只需加一条
    - 提供多种查询方式，满足不同模块需求
    - 与 config.py 解耦，配置硬编码在动画定义里

    Example:
        # 新增 SLEEP 动画
        # 1. AnimationType 加一行: SLEEP = 'sleep'
        # 2. _configs 加一行:
        #    AnimationType.SLEEP: AnimationConfig(
        #        animation_type=AnimationType.SLEEP,
        #        file_name='sleep.gif',
        #        aliases=['zzz', 'tired'],
        #        description='睡觉中...',
        #    ),
    """

    # 动画资源目录 (相对于项目根目录)
    ASSET_DIR = 'assets/gif_sprites'

    # 默认单次播放时长 (毫秒)
    DEFAULT_DURATION_MS = 4340

    # ========================================================================
    # 配置表 - 唯一定义源 (按功能分组)
    # ========================================================================
    _configs: dict[AnimationType, AnimationConfig] = {
        # ---- 基础动画 (循环播放) ----
        AnimationType.WALK: AnimationConfig(
            animation_type=AnimationType.WALK,
            file_name='walk_left.gif',
            aliases=[
                'walk', 'walking',
                'wander', 'wandering', 'wondering',
                'stroll', 'strolling', 'stroll_around',
                'move', 'moving', 'moving_around',
                'roam', 'roaming',
                'go', 'going', 'go_out',
            ],
            description='走路/闲逛 (宠物默认状态)',
        ),
        AnimationType.STAND: AnimationConfig(
            animation_type=AnimationType.STAND,
            file_name='stand_by.gif',
            aliases=[
                'stand', 'standing',
                'idle', 'standing_by', 'stand_by',
                'wait', 'waiting', 'await',
                'stop', 'stopped', 'halt',
                'stay', 'staying', 'stay_put',
                'still', 'remains',
            ],
            description='站立/发呆/等待',
        ),
        AnimationType.FLY: AnimationConfig(
            animation_type=AnimationType.FLY,
            file_name='fly.gif',
            aliases=[
                'fly', 'flying',
                'fly_away', 'fly_up', 'fly_high',
                'soar', 'soaring',
                'glide', 'gliding',
                'hover', 'hovering',
                'airborne', 'takeoff', 'take_off',
            ],
            description='飞起来/在空中',
        ),
        AnimationType.CONFUSED: AnimationConfig(
            animation_type=AnimationType.CONFUSED,
            file_name='confused.gif',
            aliases=[
                'confused', 'confusion', 'confusing',
                'think', 'thinking', 'thought',
                'wonder', 'wondering',
                'question', 'questioning',
                'puzzle', 'puzzled', 'puzzling',
                'consider', 'considering',
                'hesitate', 'hesitating',
                'doubt', 'doubting',
                'uncertain', 'unsure',
            ],
            description='困惑/思考中',
        ),

        # ---- 情绪动画 (单次播放) ----
        AnimationType.TOUCH: AnimationConfig(
            animation_type=AnimationType.TOUCH,
            file_name='touch.gif',
            aliases=[
                'touch', 'touched', 'touching',
                'pet', 'petting', 'pet_pet',
                'hug', 'hugging', 'embrace', 'embracing',
                'caress', 'caressing', 'caressed',
                'tickle', 'tickling', 'tickled',
                'scratch', 'scratching', 'scratched',
                'rub', 'rubbing', 'rubbed',
                'pat', 'patting', 'patted',
                'love', 'lovely', 'loving',
                'affection', 'affectionate',
            ],
            description='被摸/撒娇 (对抚摸的反应)',
            play_once=True,
        ),
        AnimationType.HAPPY: AnimationConfig(
            animation_type=AnimationType.HAPPY,
            file_name='happy.gif',
            aliases=[
                'happy', 'happiness', 'happily',
                'joy', 'joyful', 'joyfully', 'joyous',
                'smile', 'smiling',
                'glad', 'pleased', 'pleasing',
                'excited', 'exciting', 'excitement', 'excitedly',
                'delight', 'delighted', 'delightful',
                'cheer', 'cheerful', 'cheerfully',
                'celebrate', 'celebrating', 'celebration',
                'greet', 'greeting', 'greetings',
            ],
            description='开心/笑',
            play_once=True,
        ),
        AnimationType.ANGRY: AnimationConfig(
            animation_type=AnimationType.ANGRY,
            file_name='anger.gif',
            aliases=[
                'angry', 'anger', 'angrily', 'angered',
                'mad', 'madness', 'madly', 'maddened',
                'furious', 'furiously', 'fury',
                'rage', 'enraged', 'enrage',
                'hate', 'hated', 'hateful',
                'annoyed', 'annoying', 'annoy',
                'irritated', 'irritating', 'irritate',
                'frustrated', 'frustrating', 'frustration',
                'upset', 'upsetting',
                'pissed', 'pissed off',
                'crazy', 'going crazy',
            ],
            description='愤怒/生气',
            play_once=False,
        ),
        AnimationType.SAD: AnimationConfig(
            animation_type=AnimationType.SAD,
            file_name='sad.gif',
            aliases=[
                'sad', 'sadly', 'sadden', 'sadness',
                'cry', 'crying', 'cried',
                'tear', 'tears', 'teary',
                'weep', 'weeping', 'wept',
                'sob', 'sobbing',
                'miserable', 'misery', 'miserably',
                'unhappy', 'unhappily',
                'depressed', 'depression',
                'heartbroken', 'heartbreak',
                'devastated', 'devastating',
                'grief', 'grieving', 'grieve',
                'lonely', 'loneliness',
                'blue', 'feeling blue',
                'down', 'feeling down',
                'disappointed', 'disappointing',
            ],
            description='难过/委屈/哭',
            play_once=True,
        ),
        # ---- 状态动画 (循环播放) ----
        AnimationType.SLEEP: AnimationConfig(
            animation_type=AnimationType.SLEEP,
            file_name='sleep.gif',
            aliases=[
                'sleep', 'sleeping', 'asleep',
                'zzz', 'zzZ', 'Zzz', 'ZZZ',
                'tired', 'tiring',
                'sleepy', 'drowsy',
                'rest', 'resting', 'restful',
                'doze', 'dozing', 'dozes',
                'nap', 'napping', 'naps',
                'snooze', 'snoozing',
                'yawn', 'yawning',
                'bed', 'going_to_bed',
            ],
            description='睡觉/打盹',
        ),
        AnimationType.PLAYING: AnimationConfig(
            animation_type=AnimationType.PLAYING,
            file_name='playing.gif',
            aliases=[
                'play', 'playing', 'playful', 'plays',
                'game', 'gaming', 'games', 'gamer', 'gamers',
                'fun', 'funny', 'enjoyable',
                'entertain', 'entertaining', 'entertained', 'entertainment',
                'amusement', 'amusing',
                'toy', 'toying', 'playing_toys',
                'ball', 'playing_ball',
                'jump', 'jumping',
                'bounce', 'bouncing',
            ],
            description='玩游戏/欢乐',
        ),
        AnimationType.SEARCHING: AnimationConfig(
            animation_type=AnimationType.SEARCHING,
            file_name='searching.gif',
            aliases=[
                'search', 'searching', 'searches',
                'find', 'finding', 'found', 'find_it',
                'look', 'looking', 'looking_for',
                'seek', 'seeking', 'seeks',
                'explore', 'exploring', 'exploration',
                'hunt', 'hunting', 'hunter',
                'track', 'tracking', 'trace', 'tracing',
                'investigate', 'investigating', 'investigation',
                'scan', 'scanning', 'scans',
                'detect', 'detecting', 'detection',
            ],
            description='搜索/找东西',
        ),

        AnimationType.EATING: AnimationConfig(
            animation_type=AnimationType.EATING,
            file_name='eatting.gif',
            aliases=[
                'eat', 'eating', 'eaten',
                'food', 'eating_food',
                'eat_something', 'grab_a_bite',
                'snack', 'snacking',
                'chew', 'chewing',
                'munch', 'munching',
                'devour', 'devouring',
                'dine', 'dining',
                'feast', 'feasting',
                'hungry', 'hunger',
                'meal', 'mealtime',
                'lunch', 'dinner', 'breakfast',
                'eat_up', 'finish_eating',
            ],
            description='吃东西/吃饭/零食',
            play_once=True,
        ),

        AnimationType.NEUTRAL: AnimationConfig(
            animation_type=AnimationType.NEUTRAL,
            file_name='neutral.gif',
            aliases=[
                'neutral', 'normal', 'usual',
                'speak', 'speaking', 'say', 'saying',
                'talk', 'talking', 'chat', 'chatting',
                'response', 'responding', 'reply', 'replying',
                'tell', 'telling', 'express', 'expressing',
                'communicate', 'communicating',
                'calm', 'calmly',
                'plain', 'ordinary', 'regular',
            ],
            description='正常说话/平静',
        ),

        # ---- 动作动画 (单次播放) ----
        AnimationType.LEAVE: AnimationConfig(
            animation_type=AnimationType.LEAVE,
            file_name='leave.gif',
            aliases=[
                'leave', 'leaving', 'left',
                'bye', 'goodbye', 'farewell',
                'byebye', 'bye bye', 'bai bai',
                'later', 'see_you_later', 'see you', 'see ya',
                'cya', 'Cu_ya', 'ttyl', 'talk_to_you_later',
                'wave', 'waving', 'wave_bye',
                'depart', 'departing', 'departure',
                'go_away', 'going_away', 'go_out', 'going_out',
                'exit', 'exiting',
                'out', 'going_out',
            ],
            description='离开/挥手道别',
            play_once=True,
        ),
        AnimationType.DRAG: AnimationConfig(
            animation_type=AnimationType.DRAG,
            file_name='drag.gif',
            aliases=[
                'drag', 'dragging', 'dragged',
                'pull', 'pulling', 'pulled',
                'pick', 'picking', 'picks',
                'pickup', 'picking_up', 'pick_up',
                'picked', 'picked_up',
                'carry', 'carrying', 'carried', 'carries',
                'lift', 'lifting', 'lifted', 'lifts',
                'grab', 'grabbing', 'grabbed', 'grabs',
                'take', 'taking', 'taken',
                'hold', 'holding', 'held',
                'raise', 'raising', 'raised',
            ],
            description='被拖拽/被抱起',
            play_once=True,
        ),
    }

    # ========================================================================
    # 查询方法
    # ========================================================================

    @classmethod
    def resolve(cls, name: str) -> Optional[AnimationType]:
        """
        根据字符串解析成 AnimationType

        匹配优先级:
        1. 枚举成员名 (大写)
        2. 枚举值 (小写字符串)
        3. 配置里的别名 (aliases)

        Args:
            name: 字符串 (大小写不敏感)

        Returns:
            AnimationType 或 None (找不到时)

        Example:
            >>> AnimationRegistry.resolve('happy')      # alias
            <AnimationType.TOUCH: 'touch'>
            >>> AnimationRegistry.resolve('WALK')       # enum name
            <AnimationType.WALK: 'walk'>
            >>> AnimationRegistry.resolve('walk')       # enum value
            <AnimationType.WALK: 'walk'>
            >>> AnimationRegistry.resolve('unknown')
            None
        """
        if not name:
            return None

        normalized = name.lower().strip()

        # 1. 匹配枚举成员名 (大写)
        if normalized.upper() in AnimationType.__members__:
            return AnimationType[normalized.upper()]

        # 2. 匹配枚举值 (小写)
        for anim_type in AnimationType:
            if anim_type.value == normalized:
                return anim_type

        # 3. 匹配别名
        for anim_type, config in cls._configs.items():
            if normalized in config.aliases:
                return anim_type

        return None

    @classmethod
    def get_config(cls, anim_type: AnimationType) -> Optional[AnimationConfig]:
        """获取某个动画的配置"""
        return cls._configs.get(anim_type)

    @classmethod
    def get_file_path(cls, anim_type: AnimationType, base_dir: str = '') -> str:
        """
        获取 GIF 文件完整路径

        Args:
            anim_type: 动画类型
            base_dir: 基础目录 (通常是 pet/ 目录的绝对路径)

        Returns:
            完整文件路径，找不到返回空字符串
        """
        config = cls.get_config(anim_type)
        if not config:
            return ''

        if base_dir:
            return str(Path(base_dir) / cls.ASSET_DIR / config.file_name)
        return config.file_name

    @classmethod
    def get_duration(cls, anim_type: AnimationType) -> int:
        """
        获取单次播放时长 (毫秒)

        优先使用配置里的值，没有则用默认值
        """
        config = cls.get_config(anim_type)
        if config and config.duration_ms:
            return config.duration_ms
        return cls.DEFAULT_DURATION_MS

    @classmethod
    def should_play_once(cls, anim_type: AnimationType) -> bool:
        """判断动画是否默认单次播放"""
        config = cls.get_config(anim_type)
        return config.play_once if config else False

    # ========================================================================
    # LLM 友好接口
    # ========================================================================

    @classmethod
    def get_all_animations(cls) -> list[dict]:
        """
        获取所有动画的列表 (给 LLM prompt 或工具参数描述用)

        Returns:
            [{'name': 'walk', 'description': '...', 'aliases': [...], 'play_once': bool}, ...]
        """
        result = []
        for anim_type, config in cls._configs.items():
            result.append({
                'name': anim_type.value,
                'description': config.description,
                'aliases': config.aliases,
                'play_once': config.play_once,
            })
        return result

    @classmethod
    def get_llm_description(cls) -> str:
        """
        生成 LLM 可读的动画说明

        适合放在 system prompt 或工具的 description 里

        Example Output:
            可用动画类型:
              - walk: 闲逛/走路 (宠物默认状态)
                别名: wander, walk_around, stroll, move
              - touch: 开心/被抚摸 (单次播放)
                别名: hug, pet_touch, love, greet
        """
        lines = ['可用动画类型:']
        for anim_type, config in cls._configs.items():
            tag = ' (单次播放)' if config.play_once else ''
            lines.append(f'  - {anim_type.value}: {config.description}{tag}')
            if config.aliases:
                lines.append(f'    别名: {", ".join(config.aliases[:10])}{"..." if len(config.aliases) > 10 else ""}')
        return '\n'.join(lines)

    # ========================================================================
    # 便捷生成方法
    # ========================================================================

    @classmethod
    def generate_movies_dict(cls, base_dir: str) -> dict[AnimationType, str]:
        """
        生成 QMovie 需要的路径字典

        在 pet.py 里这样用:
            self.movies = {
                atype: QMovie(path)
                for atype, path in AnimationRegistry.generate_movies_dict(base_dir).items()
            }
        """
        return {
            anim_type: cls.get_file_path(anim_type, base_dir)
            for anim_type in cls._configs.keys()
        }
