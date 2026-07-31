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
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field

from core.schemas import BaseSchema


# ============================================================================
# 1. 动画类型枚举 (兼容 Python 3.10)
# ============================================================================
class AnimationType(str, Enum):
    """动画类型 - 新增动画需在此添加枚举值"""
    WALK = 'walk'
    STAND = 'stand'
    FLY = 'fly'
    TOUCH = 'touch'
    CONFUSED = 'confused'


# ============================================================================
# 2. 动画配置 (Pydantic BaseSchema)
# ============================================================================
class AnimationConfig(BaseSchema):
    """
    单个动画的完整配置

    Attributes:
        animation_type: 枚举值
        file_name: GIF 文件名 (相对于 images/action/)
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

    # 动画资源目录 (相对于 pet/ 目录)
    ASSET_DIR = 'images/action'

    # 默认单次播放时长 (毫秒)
    DEFAULT_DURATION_MS = 4340

    # ========================================================================
    # 配置表 - 唯一定义源
    # ========================================================================
    _configs: dict[AnimationType, AnimationConfig] = {
        AnimationType.WALK: AnimationConfig(
            animation_type=AnimationType.WALK,
            file_name='walk_left.gif',
            aliases=['wander', 'walk_around', 'stroll', 'move'],
            description='闲逛/走路 (宠物默认状态)',
        ),
        AnimationType.STAND: AnimationConfig(
            animation_type=AnimationType.STAND,
            file_name='stand_by.gif',
            aliases=['idle', 'stand_still', 'waiting', 'stop'],
            description='站立/发呆/等待',
        ),
        AnimationType.FLY: AnimationConfig(
            animation_type=AnimationType.FLY,
            file_name='fly.gif',
            aliases=['flying', 'fly_away', 'excited', 'cheerful'],
            description='飞起来/很激动',
        ),
        AnimationType.TOUCH: AnimationConfig(
            animation_type=AnimationType.TOUCH,
            file_name='touch.gif',
            aliases=['happy', 'hug', 'pet_touch', 'love', 'greet'],
            description='开心/被抚摸 (单次播放)',
            play_once=True,
            duration_ms=4340,
        ),
        AnimationType.CONFUSED: AnimationConfig(
            animation_type=AnimationType.CONFUSED,
            file_name='confused.gif',
            aliases=['thinking', 'wonder', 'question', 'puzzled'],
            description='困惑/思考中',
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
                lines.append(f'    别名: {", ".join(config.aliases)}')
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
