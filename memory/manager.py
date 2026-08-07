"""
memory/manager.py - 记忆管理器 (单例)

作为记忆系统的主入口，提供存储、检索、管理 API。
被以下组件调用：
    - CoreMemoryCache: 启动时加载核心记忆
    - memory_node: 确定性节点存储新记忆
    - QueryMemoryTool: LLM 按需查询记忆
"""
from pathlib import Path
from typing import Optional, List, Dict, Any

from core.logger import setup_logger
from .types import MemoryType, MemoryItem
from .store import MemoryStore

logger = setup_logger()


class MemoryManager:
    """
    长记忆管理器 (单例模式)

    这是长记忆系统的主入口，对外提供简洁的 API。
    内部使用 MemoryStore 进行实际的存储和检索操作。

    单例模式说明:
        使用 __new__ 实现单例，整个应用只会有一个 MemoryManager 实例。
        通过 get_instance() 获取实例，通过构造函数初始化配置。

    核心功能:
        - add_memory():      添加记忆
        - search():          语义检索
        - get_relevant_memories(): 获取格式化的记忆 (用于 LLM prompt)
        - delete_memory():   删除单条记忆
        - get_all_memories(): 获取所有记忆
        - get_memory_stats(): 获取统计信息
        - clear_all():       清空所有记忆

    使用示例:
        # 方式 1: 直接获取单例 (使用默认配置)
        manager = MemoryManager.get_instance()
        manager.initialize()

        # 方式 2: 使用自定义配置
        manager = MemoryManager(
            model_path='./models/bge-small-zh-v1.5',
            storage_path='/custom/path'
        )

        # 添加和检索
        manager.add_memory('我叫小明', MemoryType.FACT)
        results = manager.search('我叫什么')
        print(results[0]['content'])  # '我叫小明'
    """
    
    # 单例实例
    _instance: Optional["MemoryManager"] = None
    
    def __new__(cls, *args, **kwargs):
        """单例模式: 确保全局只有一个实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        model_path: Optional[str] = None,
        storage_path: Optional[str] = None
    ):
        """
        初始化 MemoryManager

        Args:
            model_path:   Embedding 模型路径 (默认项目根目录的 models/bge-small-zh-v1.5)
            storage_path: ChromaDB 存储路径 (默认项目根目录的 data/memory)

        路径说明:
            默认模型路径: {项目根目录}/models/bge-small-zh-v1.5/
            默认存储路径: {项目根目录}/data/memory/
            如果已有实例，后续调用会被忽略 (单例保证)
        """
        # 防止重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return

        self._initialized = False
        self._init_error = None

        # 项目根目录: manager.py -> memory -> 项目根
        project_root = Path(__file__).resolve().parent.parent

        # 设置模型路径 (绝对路径)
        if model_path is None:
            model_path = str(project_root / "models" / "bge-small-zh-v1.5")

        # 设置存储路径 (绝对路径)
        if storage_path is None:
            storage_path = str(project_root / "data" / "memory")

        # 创建底层存储
        self._store = MemoryStore(storage_path, model_path)
    
    @classmethod
    def get_instance(cls) -> "MemoryManager":
        """
        获取全局 MemoryManager 实例

        Returns:
            MemoryManager 实例 (如果不存在则创建默认配置的)

        使用示例:
            manager = MemoryManager.get_instance()
            if not manager.is_ready:
                manager.initialize()
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def initialize(self) -> bool:
        """
        初始化记忆系统

        会加载 embedding 模型并打开/创建数据库。
        这个过程可能需要几秒钟 (首次加载模型)。

        Returns:
            True:  初始化成功
            False: 初始化失败 (检查 init_error 获取错误信息)

        注意:
            必须在使用其他方法之前调用!
            建议在应用启动时异步调用，避免阻塞 UI。
        """
        if self._initialized:
            return True
        
        try:
            # 初始化底层存储
            if not self._store.initialize():
                raise RuntimeError("存储初始化失败")
            
            self._initialized = True
            logger.info("[Memory] MemoryManager 初始化完成")
            return True
            
        except Exception as e:
            self._init_error = str(e)
            logger.error(f"[Memory] MemoryManager 初始化失败: {e}")
            return False
    
    @property
    def is_ready(self) -> bool:
        """检查记忆系统是否就绪"""
        return self._initialized
    
    @property
    def init_error(self) -> Optional[str]:
        """初始化错误信息 (如果初始化失败)"""
        return self._init_error
    
    def add_memory(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.FACT,
        metadata: Optional[Dict[str, Any]] = None,
        score_importance: bool = True,
        manual_importance: Optional[float] = None
    ) -> Optional[str]:
        """
        添加一条记忆

        评分策略：
        - manual_importance: 手动指定，立即生效
        - score_importance=True: LLM 同步评分
        - score_importance=False: 用默认值 0.5，不评分

        注意: 本方法是同步的。LLM 评分会阻塞几秒。
        调用方应在 async 环境用 asyncio.to_thread() 调用，避免阻塞 event loop。

        Args:
            content:          记忆内容 (如 '我叫小明')
            memory_type:      记忆类型 (默认 FACT)
            metadata:         额外元数据 (可选)
            score_importance: 是否用 LLM 评分 (默认 True)
            manual_importance: 手动指定重要性 (可选，优先级高于 LLM)

        Returns:
            记忆的唯一 ID，失败返回 None
        """
        if not self.is_ready:
            logger.warning("[Memory] MemoryManager 未初始化")
            return None

        # 计算重要性
        importance = 0.5  # 默认值
        if manual_importance is not None:
            importance = manual_importance
        elif score_importance:
            try:
                from .scorer import evaluate_importance_sync
                importance = evaluate_importance_sync(content, memory_type)
                logger.info(f"[Memory] LLM 评分: '{content[:20]}...' -> {importance}")
            except Exception as e:
                logger.warning(f"[Memory] LLM 评分失败，使用默认值: {e}")

        # 创建记忆项
        item = MemoryItem(
            content=content,
            memory_type=memory_type,
            metadata=metadata or {},
            importance=importance
        )

        # 添加到底层存储
        if self._store.add([item]):
            return item.memory_id
        return None

    def smart_add_memory(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.FACT,
        metadata: Optional[Dict[str, Any]] = None,
        similarity_threshold: float = 0.5,
        score_importance: bool = True,
        manual_importance: Optional[float] = None
    ) -> Optional[str]:
        """
        智能添加一条记忆 (自动检测并替换相似旧记忆)

        注意: 本方法是同步的。LLM 评分会阻塞几秒。
        调用方应在 async 环境用 asyncio.to_thread() 调用，避免阻塞 event loop。

        Args:
            content:          记忆内容
            memory_type:      记忆类型
            metadata:         额外元数据
            similarity_threshold: 相似度阈值 (默认 0.5)
            score_importance: 是否用 LLM 评分 (默认 True)
            manual_importance: 手动指定重要性 (可选)

        Returns:
            记忆的唯一 ID，失败返回 None
        """
        if not self.is_ready:
            logger.warning("[Memory] MemoryManager 未初始化")
            return None

        # 计算重要性
        importance = 0.5  # 默认值
        if manual_importance is not None:
            importance = manual_importance
        elif score_importance:
            try:
                from .scorer import evaluate_importance_sync
                importance = evaluate_importance_sync(content, memory_type)
                logger.info(f"[Memory] LLM 评分: '{content[:20]}...' -> {importance}")
            except Exception as e:
                logger.warning(f"[Memory] LLM 评分失败，使用默认值: {e}")

        item = MemoryItem(
            content=content,
            memory_type=memory_type,
            metadata=metadata or {},
            importance=importance
        )

        if self._store.smart_add([item], similarity_threshold):
            return item.memory_id
        return None

    def batch_add(self, items: List[MemoryItem]) -> bool:
        """
        批量添加记忆 (简单版本，不做智能处理)

        Args:
            items: MemoryItem 列表

        Returns:
            True/False 表示是否成功
        """
        if not self.is_ready:
            logger.warning("[Memory] MemoryManager 未初始化")
            return False
        return self._store.add(items)
    
    def delete_by_ids(self, ids: List[str]) -> bool:
        """
        根据 ID 列表删除记忆

        Args:
            ids: 要删除的记忆 ID 列表

        Returns:
            True/False 表示是否成功
        """
        if not self.is_ready:
            logger.warning("[Memory] MemoryManager 未初始化")
            return False
        return self._store.delete(ids)
    
    def find_similar(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        n_results: int = 3,
        min_score: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        查找相似记忆 (用于智能判断是否需要替换)

        注意：此方法用于判断"是否有语义相似的旧记忆"，是纯语义判断，
        所以不使用时间衰减也不使用重要性加权（use_weighting=False）。

        Args:
            query: 查询文本
            memory_type: 可选，只搜索指定类型
            n_results: 返回数量 (默认 3)
            min_score: 最小相似度 (默认 0.5)

        Returns:
            相似记忆列表，包含 id, content, similarity 等字段
        """
        if not self.is_ready:
            return []
        return self._store.search(
            query=query,
            n_results=n_results,
            memory_type=memory_type,
            min_score=min_score,
            use_weighting=False  # 纯语义判断，不考虑时间和重要性
        )

    def search(
        self,
        query: str,
        n_results: int = 5,
        memory_type: Optional[MemoryType] = None,
        min_score: float = 0.3,
        time_decay: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        语义检索记忆（带时间衰减）

        底层调用 MemoryStore.search()，支持模糊匹配和时间衰减。

        Args:
            query:       查询文本 (自然语言即可)
            n_results:   返回数量 (默认 5)
            memory_type: 类型过滤 (可选)
            min_score:   最低综合分数 (默认 0.3)
            time_decay:  时间衰减系数 (默认 0.3)
                        - 0 = 不衰减
                        - 0.3 = 推荐值，30天衰减到约37%

        Returns:
            记忆列表，按综合分数排序，每条包含:
            - content: 记忆内容
            - similarity: 纯相似度分数
            - time_decay: 时间衰减因子
            - score: 综合分数 (加权求和: 0.6×相似度 + 0.2×时间衰减 + 0.2×重要性)

        使用示例:
            results = manager.search('我叫什么名字', n_results=3)
            for r in results:
                print(f"{r['content']}: {r['score']:.2%}")

            # 不使用时间衰减
            results = manager.search('我叫什么', time_decay=0)
        """
        if not self.is_ready:
            return []
        return self._store.search(query, n_results, memory_type, min_score, time_decay)
    
    def get_relevant_memories(
        self,
        query: str,
        max_items: int = 3,
        time_decay: float = 0.3
    ) -> str:
        """
        获取相关记忆并格式化为文本（带时间衰减）

        这是给 LLM prompt 用的便捷方法，返回格式化的记忆片段。

        Args:
            query:      查询文本
            max_items:  最多返回几条 (默认 3)
            time_decay: 时间衰减系数 (默认 0.3)

        Returns:
            格式化的记忆文本，如:
                - [fact] (相关度 65%, 新鲜度 100%) 我叫小明
                - [preference] (相关度 45%, 新鲜度 37%) 我喜欢苹果
            如果没有相关记忆，返回空字符串 ''

        新鲜度说明:
            - 100% = 刚添加的记忆
            - 74% = 30天前的记忆 (time_decay=0.3)
            - 22% = 90天前的记忆 (time_decay=0.3)

        使用示例 (在系统提示词中):
            # 先获取记忆
            memory_text = memory_manager.get_relevant_memories(user_message)
            # 然后拼接到系统提示词
            system_prompt = f'你好，我记得关于你的信息: {memory_text}'

        注意:
            - 排序由 search() 完成，结果已按综合分数降序排列
            - 综合分数 = 0.6×相似度 + 0.2×时间衰减 + 0.2×重要性
            - 无需再次排序
        """
        results = self.search(query, n_results=max_items, min_score=0.3, time_decay=time_decay)
        
        if not results:
            return ""
        
        # search() 已按 score 排好序，这里直接格式化即可
        memory_texts = []
        for r in results:
            memory_type = r["metadata"].get("type", "unknown")
            # 使用综合分数作为相关度
            relevance = r.get("score", r.get("similarity", 0))
            # 显示新鲜度 (时间衰减因子)
            freshness = r.get("time_decay", 1.0)
            # 显示重要性
            importance = r.get("importance", 0.5)
            memory_texts.append(
                f"- [{memory_type}] (相关度 {relevance:.0%}, 新鲜度 {freshness:.0%}, 重要性 {importance:.0%}) "
                f"{r['content']}"
            )
        
        return "\n".join(memory_texts)
    
    def get_all_memories(
        self,
        memory_type: Optional[MemoryType] = None
    ) -> List[Dict[str, Any]]:
        """
        获取所有记忆 (用于管理界面)

        Args:
            memory_type: 可选，只返回指定类型

        Returns:
            所有记忆列表

        适用场景:
            - 记忆管理界面显示
            - 数据导出备份
            - 统计分析
        """
        if not self.is_ready:
            return []
        return self._store.get_all(memory_type)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """
        获取记忆统计信息

        Returns:
            统计字典，如:
                {
                    "total": 100,
                    "by_type": {
                        "fact": 30,
                        "preference": 25,
                        "event": 20,
                        "context": 15,
                        "skill": 10
                    }
                }

        适用场景:
            - 设置界面显示统计
            - 定期清理策略
            - 系统健康检查
        """
        all_memories = self.get_all_memories()
        
        stats = {
            "total": len(all_memories),
            "by_type": {},
        }
        
        # 按类型计数
        for item in all_memories:
            mtype = item["metadata"].get("type", "unknown")
            stats["by_type"][mtype] = stats["by_type"].get(mtype, 0) + 1
        
        return stats
    
    def clear_all(self) -> bool:
        """
        清空所有记忆

        Returns:
            True/False 表示是否成功

        警告:
            此操作不可撤销!
            建议在清空前让用户确认。

        使用示例:
            if confirm('确定要清空所有记忆吗?'):
                manager.clear_all()
        """
        if not self.is_ready:
            return False
        return self._store.clear()


def get_memory_manager() -> MemoryManager:
    """
    获取全局 MemoryManager 实例

    推荐使用这个函数来获取实例，而不是直接 new。

    使用示例:
        from memory import get_memory_manager

        manager = get_memory_manager()
        if not manager.is_ready:
            manager.initialize()
    """
    return MemoryManager.get_instance()


def init_memory() -> bool:
    """
    初始化记忆系统 (一键操作)

    使用示例:
        from memory import init_memory

        if init_memory():
            print('记忆系统初始化成功')
        else:
            print('初始化失败')
    """
    return get_memory_manager().initialize()
