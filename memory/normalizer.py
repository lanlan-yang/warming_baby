"""
memory/normalizer.py - 记忆内容归一化器

将不同表述的同类信息归一化为统一形式，用于去重判断。
归一化只影响"去重判断"，不改变原始存储内容。

核心功能:
    - normalize(content, memory_type):      归一化内容 (用于 exact match 去重)
    - extract_field(content, memory_type):  提取字段类别 (用于 where 过滤同字段记忆)
    - extract_preference(content):          提取偏好方向和核心 (兼容旧接口)

支持的记忆类型:
    - FACT:      字段归一化 (name/birthday/location/contact/allergy)
    - PREFERENCE: 方向+核心归一化 (like/dislike + 核心内容)
    - 其他类型:   只做噪声词移除

设计说明:
    - 配置文件: memory/res/normalize_rules.yaml
    - 配置文件修改后自动重新加载 (基于 mtime 检测)
    - 归一化规则按从长到短排列，避免短模式误伤长模式

使用示例:
    normalizer = MemoryNormalizer()

    # FACT 归一化: "我叫小明" → "用户叫小明"
    norm = normalizer.normalize("我叫小明", MemoryType.FACT)
    # norm == "用户叫小明"

    # PREFERENCE 归一化: "我喜欢苹果" → "用户喜欢苹果"
    norm = normalizer.normalize("我喜欢苹果", MemoryType.PREFERENCE)
    # norm == "用户喜欢苹果"

    # FACT 字段提取: "我叫小明" → "name"
    field = normalizer.extract_field("我叫小明", MemoryType.FACT)
    # field == "name"

    # PREFERENCE 字段提取: "我喜欢苹果" → "苹果" (核心内容)
    field = normalizer.extract_field("我喜欢苹果", MemoryType.PREFERENCE)
    # field == "苹果"

    # 去重判断: "我叫小明" 和 "用户叫小明" 归一化后相同
    n1 = normalizer.normalize("我叫小明", MemoryType.FACT)
    n2 = normalizer.normalize("用户叫小明", MemoryType.FACT)
    # n1 == n2 → 视为重复，跳过添加

    # 同字段替换: "用户叫小明" 和 "用户叫杨程巍" 同字段(name)，新值替换旧值
    # 同核心替换: "我喜欢苹果" 和 "我讨厌苹果" 同核心(苹果)，新值替换旧值
"""
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import yaml

from core.logger import setup_logger
from .types import MemoryType

logger = setup_logger()

# 配置文件路径 (打包模式下自动解析到 _MEIPASS)
from core.paths import get_resource_path
_RULES_PATH = get_resource_path("memory/res/normalize_rules.yaml")


class MemoryNormalizer:
    """
    记忆内容归一化器

    基于配置规则将不同表述映射到统一形式，用于去重判断。
    规则配置在 memory/res/normalize_rules.yaml，修改后自动重新加载。

    FACT 归一化流程:
        1. 移除噪声词
        2. 匹配字段 (name/birthday/...)
        3. 应用 normalize_patterns 统一表述

    PREFERENCE 归一化流程:
        1. 移除噪声词
        2. 移除开头主语 (我/用户)
        3. 提取方向词 (like/dislike)
        4. 统一为 "用户喜欢{core}" 或 "用户不喜欢{core}"
    """

    def __init__(self, rules_path: Optional[Path] = None):
        """
        初始化归一化器

        Args:
            rules_path: 规则文件路径 (默认使用 memory/res/normalize_rules.yaml)
        """
        self._rules_path = rules_path if rules_path is not None else _RULES_PATH
        self._rules: Dict[str, Any] = {}
        self._rules_mtime: float = 0.0  # 配置文件最后修改时间
        self._load_rules()

    def _load_rules(self) -> None:
        """
        加载归一化规则 (带 mtime 检测，支持热更新)

        如果配置文件的 mtime 没变，则跳过加载。
        """
        try:
            current_mtime = self._rules_path.stat().st_mtime
        except OSError:
            logger.warning(f"[Normalizer] 规则文件不存在: {self._rules_path}")
            self._rules = {}
            return

        # mtime 没变，跳过加载
        if current_mtime == self._rules_mtime and self._rules:
            return

        try:
            with open(self._rules_path, "r", encoding="utf-8") as f:
                self._rules = yaml.safe_load(f) or {}
            self._rules_mtime = current_mtime
            field_count = len(self._rules.get("fields", {}))
            logger.info(f"[Normalizer] 规则加载完成: {field_count} 个字段定义")
        except Exception as e:
            logger.error(f"[Normalizer] 规则加载失败: {e}")
            self._rules = {}

    def _get_fields(self) -> Dict[str, Dict[str, Any]]:
        """获取 FACT 字段定义字典"""
        self._load_rules()
        return self._rules.get("fields", {})

    def _get_noise_words(self) -> List[str]:
        """获取噪声词列表"""
        self._load_rules()
        return self._rules.get("noise_words", [])

    def _get_preference_config(self) -> Dict[str, Any]:
        """获取 PREFERENCE 配置"""
        self._load_rules()
        return self._rules.get("preference", {})

    def _get_type_correction_config(self) -> Dict[str, Any]:
        """获取类型修正配置"""
        self._load_rules()
        return self._rules.get("type_correction", {})

    def _remove_noise(self, content: str) -> str:
        """
        移除噪声词 (修饰词、时间副词等)

        Args:
            content: 原始内容

        Returns:
            移除噪声词后的内容
        """
        result = content
        for noise in self._get_noise_words():
            result = result.replace(noise, "")
        return result.strip()

    # ========================================================================
    # FACT 类型处理
    # ========================================================================

    def _match_field(self, content: str) -> Optional[str]:
        """
        匹配内容所属的 FACT 字段类别

        遍历所有字段的 match_patterns，返回第一个匹配的字段名。
        match_patterns 使用 re.search 匹配。

        Args:
            content: 记忆内容 (建议先移除噪声词)

        Returns:
            字段名 (如 "name", "birthday")，未匹配返回 None
        """
        fields = self._get_fields()
        for field_name, field_def in fields.items():
            match_patterns = field_def.get("match_patterns", [])
            for pattern in match_patterns:
                if re.search(pattern, content):
                    return field_name
        return None

    def _normalize_fact(self, content: str) -> str:
        """
        FACT 类型归一化

        流程:
            1. 移除噪声词
            2. 匹配字段
            3. 应用字段的 normalize_patterns

        Args:
            content: 原始内容

        Returns:
            归一化后的字符串
        """
        # 1. 移除噪声词
        result = self._remove_noise(content)

        # 2. 匹配字段
        field_name = self._match_field(result)
        if field_name is None:
            return result  # 未匹配字段，只返回去噪后的内容

        # 3. 应用 normalize_patterns
        fields = self._get_fields()
        field_def = fields.get(field_name, {})
        normalize_patterns = field_def.get("normalize_patterns", [])

        for pattern, replacement in normalize_patterns:
            if pattern in result:
                result = result.replace(pattern, replacement, 1)
                break  # 只应用第一条匹配的规则

        return result

    # ========================================================================
    # PREFERENCE 类型处理
    # ========================================================================

    def extract_preference(self, content: str) -> Tuple[str, str]:
        """
        提取偏好的 (方向, 核心内容)

        流程:
            1. 移除噪声词
            2. 移除开头主语 (我/用户)
            3. 按关键词匹配方向 (dislike 优先，因为 dislike 关键词通常更长)
            4. 移除方向词，剩余部分即为核心内容

        Args:
            content: 偏好内容 (如 "我喜欢苹果")

        Returns:
            (direction, core):
            - direction: 'like' / 'dislike' / 'unknown'
            - core: 去除修饰词和方向词后的核心内容 (如 "苹果")

        使用示例:
            dir, core = normalizer.extract_preference("我喜欢苹果")
            # dir == "like", core == "苹果"

            dir, core = normalizer.extract_preference("我讨厌苹果")
            # dir == "dislike", core == "苹果"
        """
        pref_config = self._get_preference_config()
        like_keywords = pref_config.get("like_keywords", [])
        dislike_keywords = pref_config.get("dislike_keywords", [])

        # 1. 移除噪声词
        result = self._remove_noise(content)

        # 2. 移除开头主语 (我/用户)
        # 用正则只移除开头的主语，避免误伤中间的"我"
        result = re.sub(r'^(我|用户)', '', result).strip()

        direction = "unknown"
        core = result

        # 3. 先检查 dislike (更长的关键词优先匹配)
        for kw in dislike_keywords:
            if kw in core:
                direction = "dislike"
                core = core.replace(kw, "", 1).strip()
                break

        # 4. 再检查 like (更长的关键词优先匹配)
        if direction == "unknown":
            for kw in like_keywords:
                if kw in core:
                    direction = "like"
                    core = core.replace(kw, "", 1).strip()
                    break

        return direction, core

    def _normalize_preference(self, content: str) -> str:
        """
        PREFERENCE 类型归一化

        流程:
            1. 提取方向和核心内容
            2. 统一为 "用户喜欢{core}" 或 "用户不喜欢{core}"

        Args:
            content: 原始内容

        Returns:
            归一化后的字符串

        使用示例:
            n = self._normalize_preference("我喜欢苹果")
            # n == "用户喜欢苹果"

            n = self._normalize_preference("我讨厌苹果")
            # n == "用户不喜欢苹果"
        """
        direction, core = self.extract_preference(content)

        if direction == "like":
            return f"用户喜欢{core}"
        elif direction == "dislike":
            return f"用户不喜欢{core}"
        else:
            # 无法提取方向，返回去噪去主语后的内容
            result = self._remove_noise(content)
            result = re.sub(r'^(我|用户)', '', result).strip()
            return f"用户{result}" if result else content

    # ========================================================================
    # 统一入口
    # ========================================================================

    def correct_type(self, content: str, llm_type: MemoryType) -> MemoryType:
        """
        类型修正: 用确定性规则覆盖 LLM 的类型判断

        场景: LLM 对 "我喜欢打网球" 有时判 FACT 有时判 PREFERENCE，
        导致同一条信息以两种类型重复存在。规则强制统一类型。

        优先级: preference_keywords > fact_keywords > 保持 LLM 判断
        原因: 偏好关键词更具体（喜欢/讨厌/爱吃），事实关键词可能和偏好重叠
        （如"我喜欢苹果"含"我"，但应判 PREFERENCE 而非 FACT）

        Args:
            content:  记忆内容
            llm_type: LLM 判断的类型

        Returns:
            修正后的类型 (可能与 llm_type 相同)

        使用示例:
            # LLM 判 FACT，但含"喜欢"，强制改 PREFERENCE
            t = normalizer.correct_type("我喜欢打网球", MemoryType.FACT)
            # t == MemoryType.PREFERENCE

            # LLM 判 PREFERENCE，但含"我叫"，强制改 FACT
            t = normalizer.correct_type("我叫小明", MemoryType.PREFERENCE)
            # t == MemoryType.FACT

            # 无法识别的关键词，保持 LLM 判断
            t = normalizer.correct_type("今天天气不错", MemoryType.CONTEXT)
            # t == MemoryType.CONTEXT
        """
        config = self._get_type_correction_config()
        preference_keywords = config.get("preference_keywords", [])
        fact_keywords = config.get("fact_keywords", [])

        # 1. 先检查 preference 关键词 (优先级高)
        for kw in preference_keywords:
            if re.search(kw, content):
                return MemoryType.PREFERENCE

        # 2. 再检查 fact 关键词
        for kw in fact_keywords:
            if re.search(kw, content):
                return MemoryType.FACT

        # 3. 都不匹配，保持 LLM 判断
        return llm_type

    def normalize(self, content: str, memory_type: MemoryType) -> str:
        """
        归一化记忆内容 (用于去重判断)

        根据记忆类型选择归一化策略:
            - FACT: 字段归一化 (我叫小明 → 用户叫小明)
            - PREFERENCE: 方向+核心归一化 (我喜欢苹果 → 用户喜欢苹果)
            - 其他: 只移除噪声词

        注意:
            - 归一化结果只用于去重判断，不改变原始存储内容

        Args:
            content:     记忆内容
            memory_type: 记忆类型

        Returns:
            归一化后的字符串
        """
        if memory_type == MemoryType.FACT:
            return self._normalize_fact(content)
        elif memory_type == MemoryType.PREFERENCE:
            return self._normalize_preference(content)
        else:
            # 其他类型只移除噪声词
            return self._remove_noise(content)

    def extract_field(self, content: str, memory_type: MemoryType) -> str:
        """
        提取内容的字段类别 (用于 where 过滤同字段记忆)

        判断逻辑:
            - FACT 类型: 返回匹配的字段名 (name/birthday/...)，未匹配返回 "other"
            - PREFERENCE 类型: 返回核心内容 (如 "苹果")，无法提取返回 "other"
            - 其他类型: 返回 "other"

        Args:
            content:     记忆内容
            memory_type: 记忆类型

        Returns:
            字段类别字符串

        使用示例:
            # FACT 类型做字段细分
            field = normalizer.extract_field("我叫小明", MemoryType.FACT)
            # field == "name"

            # PREFERENCE 类型返回核心内容
            field = normalizer.extract_field("我喜欢苹果", MemoryType.PREFERENCE)
            # field == "苹果" (同核心的 like/dislike 会互相替换)

            field = normalizer.extract_field("我讨厌苹果", MemoryType.PREFERENCE)
            # field == "苹果" (与上面的 field 相同，会被 where 过滤到一起)
        """
        if memory_type == MemoryType.FACT:
            # 先移除噪声词再匹配字段
            cleaned = self._remove_noise(content)
            field = self._match_field(cleaned)
            return field if field is not None else "other"

        elif memory_type == MemoryType.PREFERENCE:
            # 返回核心内容，用于 where 过滤同核心的偏好
            _, core = self.extract_preference(content)
            return core if core else "other"

        else:
            return "other"


# 模块级单例 (延迟初始化)
_normalizer_instance: Optional[MemoryNormalizer] = None


def get_normalizer() -> MemoryNormalizer:
    """
    获取全局 MemoryNormalizer 实例 (单例)

    Returns:
        MemoryNormalizer 实例

    使用示例:
        from memory.normalizer import get_normalizer
        normalizer = get_normalizer()
        norm = normalizer.normalize("我叫小明", MemoryType.FACT)
    """
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = MemoryNormalizer()
    return _normalizer_instance
