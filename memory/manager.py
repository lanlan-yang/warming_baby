"""
memory/manager.py - 记忆管理器 (单例)

实现 MemoryManager 类，作为记忆系统的主入口。
"""
import sys
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        添加一条记忆

        Args:
            content:     记忆内容 (如 '我叫小明')
            memory_type: 记忆类型 (默认 FACT)
            metadata:    额外元数据 (可选)

        Returns:
            记忆的唯一 ID，失败返回 None

        使用示例:
            # 添加用户姓名
            memory_id = manager.add_memory('我叫小明', MemoryType.FACT)

            # 添加偏好 (带元数据)
            manager.add_memory('我喜欢吃苹果', MemoryType.PREFERENCE, {
                'source': 'chat',
                'timestamp': 1234567890
            })

        何时调用:
            - 用户主动告知信息 ("我叫..."、"我喜欢...")
            - 系统提取的关键信息
            - 重要的上下文记录
        """
        if not self.is_ready:
            logger.warning("[Memory] MemoryManager 未初始化")
            return None
        
        # 创建记忆项
        item = MemoryItem(
            content=content,
            memory_type=memory_type,
            metadata=metadata or {}
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
        similarity_threshold: float = 0.5
    ) -> Optional[str]:
        """
        智能添加一条记忆 (自动检测并替换相似旧记忆)

        Args:
            content:     记忆内容
            memory_type: 记忆类型
            metadata:    额外元数据
            similarity_threshold: 相似度阈值 (默认 0.5)

        Returns:
            记忆的唯一 ID，失败返回 None

        使用示例:
            # 用户第一次说"我叫小明"，第二次说"我叫小红"
            # 系统自动识别为同类型 (fact) 的相似内容，替换旧的
            manager.smart_add_memory('我叫小明', MemoryType.FACT)  # 添加
            manager.smart_add_memory('我叫小红', MemoryType.FACT)  # 替换

        智能判断:
            - 对于 preference 类型，会提取方向和核心内容
            - 核心内容相同则替换，不同则共存
        """
        if not self.is_ready:
            logger.warning("[Memory] MemoryManager 未初始化")
            return None
        
        item = MemoryItem(
            content=content,
            memory_type=memory_type,
            metadata=metadata or {}
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
            min_score=min_score
        )

    def should_replace_keyword(
        self,
        old_content: str,
        new_content: str,
        memory_type: MemoryType
    ) -> bool:
        """
        使用关键词判断是否应该替换旧记忆

        Args:
            old_content: 旧记忆内容
            new_content: 新记忆内容
            memory_type: 记忆类型

        Returns:
            True 表示应该替换，False 表示不替换
        """
        return self._store.should_replace_keyword(old_content, new_content, memory_type)
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        memory_type: Optional[MemoryType] = None,
        min_score: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        语义检索记忆

        底层调用 MemoryStore.search()，支持模糊匹配。

        Args:
            query:       查询文本 (自然语言即可)
            n_results:   返回数量 (默认 5)
            memory_type: 类型过滤 (可选)
            min_score:   最低相似度 (默认 0.3)

        Returns:
            记忆列表，每条包含 content、metadata、similarity

        使用示例:
            results = manager.search('我叫什么名字', n_results=3)
            for r in results:
                print(f"{r['content']}: {r['similarity']:.2%}")

        检索技巧:
            - 查询越具体，结果越精确
            - 可以用自然语言提问
            - min_score 调高性能，调低召回
        """
        if not self.is_ready:
            return []
        return self._store.search(query, n_results, memory_type, min_score)
    
    def get_relevant_memories(
        self,
        query: str,
        max_items: int = 3
    ) -> str:
        """
        获取相关记忆并格式化为文本

        这是给 LLM prompt 用的便捷方法，返回格式化的记忆片段。

        Args:
            query:    查询文本
            max_items: 最多返回几条 (默认 3)

        Returns:
            格式化的记忆文本，如:
                "- [fact] (置信度 65%) 我叫小明
                 - [preference] (置信度 45%) 我喜欢苹果"
            如果没有相关记忆，返回空字符串 ''

        使用示例 (在系统提示词中):
            # 先获取记忆
            memory_text = memory_manager.get_relevant_memories(user_message)
            # 然后拼接到系统提示词
            system_prompt = f'你好，我记得关于你的信息: {memory_text}'

        这个方法的作用:
            - 将检索结果整理成易读格式
            - 按相似度排序
            - 显示记忆类型和置信度
            - 可以直接插入到 LLM prompt 中
        """
        results = self.search(query, n_results=max_items, min_score=0.3)
        
        if not results:
            return ""
        
        # 按相似度降序排列
        results.sort(key=lambda x: x["similarity"], reverse=True)
        
        # 格式化为可读文本
        memory_texts = []
        for r in results:
            memory_type = r["metadata"].get("type", "unknown")
            similarity = r["similarity"]
            memory_texts.append(f"- [{memory_type}] (置信度 {similarity:.0%}) {r['content']}")
        
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
