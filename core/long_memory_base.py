"""
core/long_memory_base.py - 长记忆管理基类

功能说明:
    这个模块实现了一个基于向量数据库（ChromaDB）和本地 embedding 模型（bge-small-zh）的长记忆系统。
    它可以存储用户的各种信息（姓名、偏好、习惯等），并支持语义检索，让 AI 能够"记住"用户。

架构设计:
    1. MemoryType     - 记忆类型枚举，支持 5 种类型：事实、偏好、事件、上下文、技能
    2. MemoryItem     - 记忆项数据结构，包含内容、类型、元数据、时间戳等
    3. MemoryStore    - ChromaDB 向量存储封装，负责实际的存储和检索操作
    4. MemoryManager  - 统一入口管理器，使用单例模式，提供简洁的 API

技术栈:
    - ChromaDB: 轻量级向量数据库，支持持久化存储
    - bge-small-zh-v1.5: 本地中文 embedding 模型，512 维向量
    - sentence-transformers: 加载和运行 embedding 模型

使用示例:
    from core.long_memory_base import MemoryManager, MemoryType, get_memory_manager

    # 初始化（应用启动时调用一次）
    manager = get_memory_manager()
    if not manager.is_ready:
        manager.initialize()

    # 存储记忆
    manager.add_memory("我叫小明", MemoryType.FACT)
    manager.add_memory("我喜欢吃苹果", MemoryType.PREFERENCE)

    # 检索记忆（用于 LLM prompt）
    memory_text = manager.get_relevant_memories("我叫什么")
    # 返回: "- [fact] (置信度 65%) 我叫小明"

设计特点:
    - 单例模式: 全局只有一个 MemoryManager 实例
    - 语义检索: 基于向量相似度，支持模糊匹配
    - 类型过滤: 可以按记忆类型过滤结果
    - 置信度阈值: 只返回相关度高的结果
    - 持久化存储: 数据保存在本地，重启不丢失
"""

#todo
# 现在开始一系列任务：
# 1.LLM 自动提取对话类型
# 2.Chroma策略 2：同类覆盖，添加智能方法
# 3.优化预热模型
# 4.添加兜底机制，如果未检索到任何记忆要有兜底机制

import os
import sys
import time
import uuid
from enum import StrEnum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

from core.logger import setup_logger

logger = setup_logger()


# ============================================================================
# 1. MemoryType - 记忆类型枚举
# ============================================================================

class MemoryType(StrEnum):
    """
    记忆类型枚举

    用于对记忆进行分类存储和检索，不同类型的记忆在检索时可以单独过滤。

    类型说明:
        - FACT:      事实信息，如"我叫小明"、"我的生日是1月1日"
        - PREFERENCE: 偏好信息，如"我喜欢吃苹果"、"我讨厌香菜"
        - EVENT:     事件记录，如"昨天去公园玩了"、"今天买了新衣服"
        - CONTEXT:   上下文信息，如"最近在聊机器学习"、"刚看完一部电影"
        - SKILL:     技能信息，如"我会Python编程"、"我会弹吉他"

    使用示例:
        MemoryType.FACT          # 返回 'fact' 字符串
        MemoryType.FACT.value    # 返回 'fact'（和上面一样）
        MemoryType.get_display_name(MemoryType.FACT)  # 返回 '事实'
    """
    
    FACT = "fact"               # 事实：我叫小明、我的生日是1月1日
    PREFERENCE = "preference"   # 偏好：我喜欢吃苹果、我讨厌香菜
    EVENT = "event"             # 事件：昨天去公园、今天买了新衣服
    CONTEXT = "context"         # 上下文：最近在聊什么话题
    SKILL = "skill"             # 技能：我会Python、我会弹吉他
    
    @classmethod
    def get_display_name(cls, mtype: 'MemoryType') -> str:
        """
        获取记忆类型的中文显示名称

        Args:
            mtype: MemoryType 枚举值

        Returns:
            中文名称字符串，如 '事实'、'偏好' 等
        """
        names = {
            cls.FACT: "事实",
            cls.PREFERENCE: "偏好",
            cls.EVENT: "事件",
            cls.CONTEXT: "上下文",
            cls.SKILL: "技能",
        }
        return names.get(mtype, "未知")


# ============================================================================
# 2. MemoryItem - 记忆项数据结构
# ============================================================================

@dataclass
class MemoryItem:
    """
    记忆项数据结构

    每条记忆包含以下信息：
        - content:       记忆内容（文本）
        - memory_type:   记忆类型（MemoryType 枚举）
        - memory_id:     唯一标识（自动生成 UUID）
        - metadata:      额外元数据（如来源、标签等）
        - created_at:    创建时间戳
        - updated_at:    更新时间戳
        - access_count:  被检索次数（用于统计）

    使用示例:
        item = MemoryItem(
            content="我叫小明",
            memory_type=MemoryType.FACT,
            metadata={"source": "user_message"}
        )
        item.to_dict()  # 转换为字典便于存储
    """
    
    content: str                                              # 记忆内容文本
    memory_type: MemoryType                                   # 记忆类型
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))  # 唯一 ID
    metadata: Dict[str, Any] = field(default_factory=dict)    # 额外元数据
    created_at: float = field(default_factory=time.time)     # 创建时间戳
    updated_at: float = field(default_factory=time.time)     # 更新时间戳
    access_count: int = 0                                     # 被检索次数
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将记忆项转换为字典格式（用于存储到 ChromaDB）

        Returns:
            包含所有字段的字典
        """
        return {
            "id": self.memory_id,
            "content": self.content,
            "type": self.memory_type.value,  # 转为字符串存储
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
        }


# ============================================================================
# 3. MemoryStore - ChromaDB 向量存储封装
# ============================================================================

class MemoryStore:
    """
    ChromaDB 向量存储封装

    负责实际的向量存储和语义检索操作。使用 ChromaDB 的 SentenceTransformerEmbeddingFunction
    来加载本地的 bge-small-zh-v1.5 模型进行向量编码。

    核心功能:
        - initialize():  初始化数据库和 embedding 模型
        - add():         添加记忆向量
        - search():      语义检索记忆
        - delete():      删除记忆
        - get_all():     获取所有记忆
        - clear():       清空所有记忆

    向量空间配置:
        - 维度: 512（由 bge-small-zh 决定）
        - 距离度量: cosine（余弦相似度）
        - 归一化: 开启（便于相似度计算）

    使用示例:
        store = MemoryStore('/path/to/memory', './models/bge-small-zh-v1.5')
        store.initialize()
        store.add([MemoryItem(content='我叫小明', memory_type=MemoryType.FACT)])
        results = store.search('我叫什么', n_results=1)
    """
    
    def __init__(self, storage_path: str, model_path: str):
        """
        初始化向量存储

        Args:
            storage_path: ChromaDB 数据存储路径（目录）
            model_path:   Embedding 模型路径
        """
        self._storage_path = storage_path    # 数据存储目录
        self._model_path = model_path        # Embedding 模型路径
        self._client = None                   # ChromaDB 客户端
        self._collection = None               # 向量集合（类似数据库表）
        self._embedding_func = None           # Embedding 函数
        self._initialized = False             # 是否初始化完成
    
    def initialize(self) -> bool:
        """
        初始化向量存储

        执行以下操作:
            1. 加载本地 bge-small-zh-v1.5 embedding 模型
            2. 创建 ChromaDB 持久化客户端
            3. 获取或创建 'user_memory' 集合

        Returns:
            True:  初始化成功
            False: 初始化失败（会打印错误日志）

        注意:
            首次加载模型约需 2-3 秒，后续启动会快很多。
            模型文件约 100MB，请确保磁盘空间充足。
        """
        if self._initialized:
            return True
        
        try:
            import chromadb
            from chromadb.config import Settings
            from chromadb.utils import embedding_functions
            
            logger.info(f"[Memory] 正在初始化向量存储...")
            
            # 创建 Embedding 函数
            # SentenceTransformerEmbeddingFunction 会自动加载本地模型
            self._embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self._model_path,
                device='cpu',  # 使用 CPU 推理
            )
            
            # 确保存储目录存在
            Path(self._storage_path).mkdir(parents=True, exist_ok=True)
            
            # 创建 ChromaDB 客户端
            # PersistentClient 会将数据保存到磁盘，重启不丢失
            self._client = chromadb.PersistentClient(
                path=self._storage_path,
                settings=Settings(anonymized_telemetry=False)  # 禁用遥测
            )
            
            # 获取或创建向量集合
            # 如果已存在则直接使用，不存在则创建
            self._collection = self._client.get_or_create_collection(
                name="user_memory",                           # 集合名称
                embedding_function=self._embedding_func,      # 向量编码函数
                metadata={"hnsw:space": "cosine"}             # 使用余弦距离
            )
            
            self._initialized = True
            logger.info(f"[Memory] 向量存储初始化完成: {self._storage_path}")
            logger.info(f"[Memory] 当前记忆数量: {self._collection.count()}")
            return True
            
        except Exception as e:
            logger.error(f"[Memory] 向量存储初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    @property
    def is_ready(self) -> bool:
        """检查存储是否就绪"""
        return self._initialized and self._collection is not None
    
    @property
    def count(self) -> int:
        """返回当前记忆总数"""
        if not self.is_ready:
            return 0
        return self._collection.count()
    
    def add(self, items: List[MemoryItem]) -> bool:
        """
        添加一批记忆到向量数据库

        Args:
            items: MemoryItem 列表

        Returns:
            True:  添加成功
            False: 添加失败或未初始化

        注意:
            每条记忆会自动生成唯一 ID，如果 ID 重复会报错。
            metadata 中的 'type' 字段用于后续过滤查询。
        """
        if not self.is_ready or not items:
            return False
        
        try:
            # 使用 ChromaDB 的批量添加接口
            self._collection.add(
                ids=[item.memory_id for item in items],              # 唯一 ID 列表
                documents=[item.content for item in items],          # 文本内容列表
                metadatas=[
                    {
                        "type": item.memory_type.value,                # 记忆类型（用于过滤）
                        "created_at": item.created_at,                 # 创建时间
                        "updated_at": item.updated_at,                 # 更新时间
                        "access_count": item.access_count,             # 访问次数
                        **item.metadata,                                # 额外元数据
                    }
                    for item in items
                ]
            )
            logger.info(f"[Memory] 添加了 {len(items)} 条记忆")
            return True
            
        except Exception as e:
            logger.error(f"[Memory] 添加记忆失败: {e}")
            return False
    
    def smart_add(self, items: List[MemoryItem], similarity_threshold: float = 0.5) -> bool:
        """
        智能添加：自动检测并替换同类相似的旧记忆
        
        使用场景：
        用户第一次说"我叫小明"，第二次说"我叫小红"
        系统自动识别为同类型（fact）的相似内容，替换旧的
        
        智能判断：
        - 对于 preference 类型，会提取方向(喜欢/不喜欢)和核心内容
        - 只有核心内容相同时，才会考虑替换（无论方向是否改变）
        - 核心内容不同的偏好会共存
        
        Args:
            items: MemoryItem 列表
            similarity_threshold: 相似度阈值（0-1），超过则认为是同一条记忆
        
        Returns:
            True: 添加成功
            False: 添加失败
        
        Example:
            # 用户改喜好，核心内容相同，替换
            old = "用户喜欢吃苹果"
            new = "用户不喜欢吃苹果"  # 核心都是"吃苹果"，会替换
            
            # 用户说不同的喜好，核心内容不同，共存
            old = "用户喜欢吃梨"
            new = "用户不喜欢苹果"   # 核心不同，会共存
        """
        def _extract_preference(text: str) -> tuple:
            """提取偏好的(方向, 核心内容)"""
            # 使用更长的关键词优先匹配，避免破坏完整短语
            like_keywords = [
                "非常喜欢", "特别喜欢", "真的喜欢", "确实喜欢",
                "非常爱", "特别爱", "真的爱", "确实爱", "爱吃",
                "喜欢", "爱", "想", "要", "偏好", "热爱",
            ]
            dislike_keywords = [
                "非常不喜欢", "特别不喜欢", "真的不喜欢", "确实不喜欢",
                "非常讨厌", "特别讨厌", "真的讨厌", "确实讨厌",
                "不喜欢", "不爱", "讨厌", "恨", "厌恶", "反感",
            ]
            # 修饰词/噪声词 - 需要移除但不影响核心识别
            noise_words = [
                # 时间/状态
                "其实", "原来", "本来", "原本", "以前", "之前", "后来", "现在",
                "刚才", "突然",
                # 连词
                "也", "还", "而且", "并且", "然后", "还有", "但是",
                # 程度副词（移除后不影响核心）
                "特别", "非常", "真的", "确实", "有点", "稍微", "挺", "蛮",
                "一点", "一些", "经常", "偶尔", "总是",
                # 主语/自我
                "我觉得", "我认为", "我想", "可能", "大概", "应该",
                "用户", "自己",
            ]
            
            direction = "unknown"
            core = text
            
            # 先移除噪声词/修饰词
            for noise in noise_words:
                core = core.replace(noise, "")
            core = core.strip()
            
            # 先检查 dislike（更长的关键词优先匹配）
            for kw in dislike_keywords:
                if kw in core:
                    direction = "dislike"
                    core = core.replace(kw, "", 1).strip()
                    break
            
            # 再检查 like（更长的关键词优先匹配）
            if direction == "unknown":
                for kw in like_keywords:
                    if kw in core:
                        direction = "like"
                        core = core.replace(kw, "", 1).strip()
                        break
            
            return direction, core
        
        def _should_replace(old_content: str, new_content: str, memory_type: MemoryType) -> bool:
            """判断是否应该替换旧记忆"""
            if memory_type == MemoryType.PREFERENCE:
                # 提取方向和核心内容
                old_dir, old_core = _extract_preference(old_content)
                new_dir, new_core = _extract_preference(new_content)
                
                # 如果核心内容都能提取，且不同，则不替换
                if old_dir != "unknown" and new_dir != "unknown":
                    if old_core != new_core:
                        logger.debug(f"[Memory.smart_add] 核心内容不同，不替换: '{old_core}' vs '{new_core}'")
                        return False
                    # 核心内容相同（无论方向是否改变），允许替换
                    logger.debug(f"[Memory.smart_add] 核心内容相同，允许替换: '{old_content}' -> '{new_content}'")
                else:
                    # 如果有无法提取的，保守不替换
                    return False
            
            return True
        
        if not self.is_ready or not items:
            return False
        
        try:
            items_to_add = []
            
            for item in items:
                # 搜索同类型的相似记忆
                similar_results = self.search(
                    query=item.content,
                    n_results=3,
                    memory_type=item.memory_type,
                    min_score=similarity_threshold
                )
                
                # 如果有相似的旧记忆，检查是否应该替换
                if similar_results:
                    old_ids = []
                    for r in similar_results:
                        # 不删除完全相同的
                        if r['content'] == item.content:
                            continue
                        # 检查是否应该替换（处理偏好的核心内容匹配）
                        if _should_replace(r['content'], item.content, item.memory_type):
                            old_ids.append(r['id'])
                    
                    if old_ids:
                        self.delete(old_ids)
                        logger.info(f"[Memory.smart_add] 删除了 {len(old_ids)} 条相似旧记忆")
                
                items_to_add.append(item)
            
            # 添加新记忆
            return self.add(items_to_add)
            
        except Exception as e:
            logger.error(f"[Memory.smart_add] 失败: {e}")
            return False
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        memory_type: Optional[MemoryType] = None,
        min_score: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        语义检索相关记忆

        根据查询文本的向量表示，在向量空间中寻找最相似的记忆。

        Args:
            query:       查询文本（如 '我叫什么名字'）
            n_results:   返回结果数量（默认 5 条）
            memory_type: 可选，只在指定类型的记忆中检索
            min_score:   最低相似度阈值（0-1，默认 0.3）

        Returns:
            记忆列表，每条包含:
                - content:  记忆内容
                - metadata: 元数据（类型、时间等）
                - similarity: 相似度分数（0-1，越高越相关）

        相似度说明:
            - 0.3-0.4: 弱相关
            - 0.4-0.5: 中等相关
            - 0.5-0.7: 较强相关
            - 0.7+:    非常相关

        使用示例:
            # 基本检索
            results = store.search('我叫什么', n_results=3)

            # 只在事实类型中检索
            results = store.search('我的生日', memory_type=MemoryType.FACT)

            # 高阈值检索（只返回最相关的）
            results = store.search('我喜欢什么', min_score=0.6)
        """
        if not self.is_ready:
            return []
        
        try:
            # 构建过滤条件
            # ChromaDB 的 where 参数用于 metadata 过滤
            where_filter = None
            if memory_type:
                where_filter = {"type": memory_type.value}
            
            # 确保请求数量不超过实际记忆数
            # ChromaDB 不支持 n_results > count
            actual_results = min(n_results, self.count) if self.count > 0 else 1
            
            # 执行向量检索
            # query_texts 会自动转换为向量
            # 返回的 distances 是余弦距离，需要转换为相似度
            results = self._collection.query(
                query_texts=[query],                 # 查询文本
                n_results=actual_results,            # 返回数量
                where=where_filter,                  # 过滤条件
                include=["documents", "metadatas", "distances"]  # 返回字段
            )
            
            # 解析结果并计算相似度
            memories = []
            if results["documents"] and results["documents"][0]:
                for doc, meta, dist, rid in zip(
                    results["documents"][0],     # 文档内容
                    results["metadatas"][0],     # 元数据
                    results["distances"][0],     # 余弦距离
                    results["ids"][0]            # 文档 ID
                ):
                    # 余弦相似度 = 1 - 余弦距离
                    # 距离越小，相似度越高
                    similarity = 1 - dist
                    
                    # 只保留超过阈值的结果
                    if similarity >= min_score:
                        memories.append({
                            "id": rid,
                            "content": doc,
                            "metadata": meta,
                            "similarity": round(similarity, 4),
                        })
            
            return memories
            
        except Exception as e:
            logger.error(f"[Memory] 检索失败: {e}")
            return []
    
    def delete(self, memory_ids: List[str]) -> bool:
        """
        删除指定的记忆

        Args:
            memory_ids: 要删除的记忆 ID 列表

        Returns:
            True:  删除成功
            False: 删除失败或未初始化

        注意:
            删除不存在的 ID 不会报错。
        """
        if not self.is_ready or not memory_ids:
            return False
        
        try:
            self._collection.delete(ids=memory_ids)
            logger.info(f"[Memory] 删除了 {len(memory_ids)} 条记忆")
            return True
        except Exception as e:
            logger.error(f"[Memory] 删除失败: {e}")
            return False
    
    def get_all(self, memory_type: Optional[MemoryType] = None) -> List[Dict[str, Any]]:
        """
        获取所有记忆（不进行向量检索）

        Args:
            memory_type: 可选，只返回指定类型的记忆

        Returns:
            记忆列表，每条包含 content 和 metadata

        注意:
            这会返回所有匹配的记忆，数量大时可能较慢。
            用于管理界面显示、数据导出等场景。
        """
        if not self.is_ready:
            return []
        
        try:
            # 构建过滤条件
            where_filter = None
            if memory_type:
                where_filter = {"type": memory_type.value}
            
            # 获取所有匹配的文档
            results = self._collection.get(
                where=where_filter,                 # 过滤条件
                include=["documents", "metadatas"]  # 返回字段
            )
            
            # 整理结果（id 在 results 中是单独的字段）
            memories = []
            if results["documents"]:
                for i, (doc, meta) in enumerate(zip(results["documents"], results["metadatas"])):
                    memories.append({
                        "id": results["ids"][i],  # 从 ids 数组获取
                        "content": doc,
                        "metadata": meta,
                    })
            
            return memories
            
        except Exception as e:
            logger.error(f"[Memory] 获取所有记忆失败: {e}")
            return []
    
    def clear(self) -> bool:
        """
        清空所有记忆

        删除当前集合，然后重新创建一个空的。

        Returns:
            True:  清空成功
            False: 清空失败

        警告:
            此操作不可撤销，所有记忆将永久删除！
        """
        if not self.is_ready:
            return False
        
        try:
            # 保存 embedding 函数的引用
            embedding_func = self._collection._embedding_function
            
            # 删除旧集合
            self._client.delete_collection("user_memory")
            
            # 创建新集合（保持相同配置）
            self._collection = self._client.get_or_create_collection(
                name="user_memory",
                embedding_function=embedding_func,
                metadata={"hnsw:space": "cosine"}
            )
            
            logger.info("[Memory] 清空了所有记忆")
            return True
        except Exception as e:
            logger.error(f"[Memory] 清空失败: {e}")
            return False
    
    @staticmethod
    def _extract_preference(text: str) -> tuple:
        """
        静态方法：提取偏好的(方向, 核心内容)
        
        Returns:
            (direction, core): direction 是 'like'/'dislike'/'unknown'
                              core 是去除修饰词和方向词后的核心内容
        """
        # 使用更长的关键词优先匹配，避免破坏完整短语
        like_keywords = [
            "非常喜欢", "特别喜欢", "真的喜欢", "确实喜欢",
            "非常爱", "特别爱", "真的爱", "确实爱", "爱吃",
            "喜欢", "爱", "想", "要", "偏好", "热爱",
        ]
        dislike_keywords = [
            "非常不喜欢", "特别不喜欢", "真的不喜欢", "确实不喜欢",
            "非常讨厌", "特别讨厌", "真的讨厌", "确实讨厌",
            "不喜欢", "不爱", "讨厌", "恨", "厌恶", "反感",
        ]
        # 修饰词/噪声词 - 需要移除但不影响核心识别
        noise_words = [
            # 时间/状态
            "其实", "原来", "本来", "原本", "以前", "之前", "后来", "现在",
            "刚才", "突然",
            # 连词
            "也", "还", "而且", "并且", "然后", "还有", "但是",
            # 程度副词（移除后不影响核心）
            "特别", "非常", "真的", "确实", "有点", "稍微", "挺", "蛮",
            "一点", "一些", "经常", "偶尔", "总是",
            # 主语/自我
            "我觉得", "我认为", "我想", "可能", "大概", "应该",
            "用户", "自己",
        ]
        
        direction = "unknown"
        core = text
        
        # 先移除噪声词/修饰词
        for noise in noise_words:
            core = core.replace(noise, "")
        core = core.strip()
        
        # 先检查 dislike（更长的关键词优先匹配）
        for kw in dislike_keywords:
            if kw in core:
                direction = "dislike"
                core = core.replace(kw, "", 1).strip()
                break
        
        # 再检查 like（更长的关键词优先匹配）
        if direction == "unknown":
            for kw in like_keywords:
                if kw in core:
                    direction = "like"
                    core = core.replace(kw, "", 1).strip()
                    break
        
        return direction, core
    
    def _should_replace_keyword(
        self, 
        old_content: str, 
        new_content: str, 
        memory_type: MemoryType
    ) -> bool:
        """
        判断是否应该替换旧记忆（使用关键词匹配）
        
        Args:
            old_content: 旧记忆内容
            new_content: 新记忆内容
            memory_type: 记忆类型
            
        Returns:
            True: 应该替换
            False: 不应该替换（无法确定）
        """
        # 对于偏好类型，使用更智能的判断
        if memory_type == MemoryType.PREFERENCE:
            # 提取方向和核心内容
            old_dir, old_core = self._extract_preference(old_content)
            new_dir, new_core = self._extract_preference(new_content)
            
            # 如果核心内容都能提取，判断是否相同
            if old_dir != "unknown" and new_dir != "unknown":
                return old_core == new_core
            
            # 如果有无法提取的，返回 False（不确定）
            return False
        
        # 对于其他类型，如果是完全相同的，不替换
        if old_content == new_content:
            return False
        
        # 对于其他类型，默认允许替换（由相似度来控制）
        return True


# ============================================================================
# 4. MemoryManager - 统一入口管理器
# ============================================================================

class MemoryManager:
    """
    长记忆管理器（单例模式）

    这是长记忆系统的主入口，对外提供简洁的 API。
    内部使用 MemoryStore 进行实际的存储和检索操作。

    单例模式说明:
        使用 __new__ 实现单例，整个应用只会有一个 MemoryManager 实例。
        通过 get_instance() 获取实例，通过构造函数初始化配置。

    核心功能:
        - add_memory():      添加记忆
        - search():          语义检索
        - get_relevant_memories(): 获取格式化的记忆（用于 LLM prompt）
        - delete_memory():   删除单条记忆
        - get_all_memories(): 获取所有记忆
        - get_memory_stats(): 获取统计信息
        - clear_all():       清空所有记忆

    使用示例:
        # 方式 1: 直接获取单例（使用默认配置）
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
        model_path: str = "./models/bge-small-zh-v1.5",
        storage_path: Optional[str] = None
    ):
        """
        初始化 MemoryManager

        Args:
            model_path:   Embedding 模型路径（默认 bge-small-zh）
            storage_path: ChromaDB 存储路径（默认项目本地 data/memory）

        路径说明:
            默认存储路径: {项目根目录}/data/memory/
            如果已有实例，后续调用会被忽略（单例保证）
        """
        # 防止重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self._initialized = False
        self._init_error = None
        
        # 设置存储路径（默认项目本地路径）
        if storage_path is None:
            # 项目根目录：long_memory_base.py -> core -> 项目根
            project_root = Path(__file__).resolve().parent.parent
            storage_path = str(project_root / "data" / "memory")
        
        # 创建底层存储
        self._store = MemoryStore(storage_path, model_path)
    
    @classmethod
    def get_instance(cls) -> "MemoryManager":
        """
        获取全局 MemoryManager 实例

        Returns:
            MemoryManager 实例（如果不存在则创建默认配置的）

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
        这个过程可能需要几秒钟（首次加载模型）。

        Returns:
            True:  初始化成功
            False: 初始化失败（检查 init_error 获取错误信息）

        注意:
            必须在使用其他方法之前调用！
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
        """初始化错误信息（如果初始化失败）"""
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
            content:     记忆内容（如 '我叫小明'）
            memory_type: 记忆类型（默认 FACT）
            metadata:    额外元数据（可选）

        Returns:
            记忆的唯一 ID，失败返回 None

        使用示例:
            # 添加用户姓名
            memory_id = manager.add_memory('我叫小明', MemoryType.FACT)

            # 添加偏好（带元数据）
            manager.add_memory('我喜欢吃苹果', MemoryType.PREFERENCE, {
                'source': 'chat',
                'timestamp': time.time()
            })

        何时调用:
            - 用户主动告知信息（"我叫..."、"我喜欢..."）
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

    def batch_add(self, items: List[MemoryItem]) -> bool:
        """
        批量添加记忆（简单版本，不做智能处理）

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
        查找相似记忆（用于智能判断是否需要替换）

        Args:
            query: 查询文本
            memory_type: 可选，只搜索指定类型
            n_results: 返回数量（默认 3）
            min_score: 最小相似度（默认 0.5）

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
        return self._store._should_replace_keyword(old_content, new_content, memory_type)

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
            query:       查询文本（自然语言即可）
            n_results:   返回数量（默认 5）
            memory_type: 类型过滤（可选）
            min_score:   最低相似度（默认 0.3）

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
            max_items: 最多返回几条（默认 3）

        Returns:
            格式化的记忆文本，如:
                "- [fact] (置信度 65%) 我叫小明
                 - [preference] (置信度 45%) 我喜欢苹果"
            如果没有相关记忆，返回空字符串 ''

        使用示例（在系统提示词中）:
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
        获取所有记忆（用于管理界面）

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
            此操作不可撤销！
            建议在清空前让用户确认。

        使用示例:
            if confirm('确定要清空所有记忆吗？'):
                manager.clear_all()
        """
        if not self.is_ready:
            return False
        return self._store.clear()


# ============================================================================
# 5. 便捷函数（简化使用）
# ============================================================================

def get_memory_manager() -> MemoryManager:
    """
    获取全局 MemoryManager 实例

    推荐使用这个函数来获取实例，而不是直接 new。

    使用示例:
        from core.long_memory_base import get_memory_manager

        manager = get_memory_manager()
        if not manager.is_ready:
            manager.initialize()
    """
    return MemoryManager.get_instance()


def init_memory() -> bool:
    """
    初始化记忆系统（一键操作）

    使用示例:
        from core.long_memory_base import init_memory

        if init_memory():
            print('记忆系统初始化成功')
        else:
            print('初始化失败')
    """
    return get_memory_manager().initialize()


# ============================================================================
# 6. 测试代码
# ============================================================================

if __name__ == "__main__":
    """
    模块测试入口

    直接运行此文件可以测试所有功能:
        python core/long_memory_base.py
    """
    print("=" * 60)
    print("长记忆系统测试")
    print("=" * 60)
    
    # 1. 初始化
    manager = MemoryManager(storage_path='/tmp/warmbaby_test_final')
    print(f"\n1. 初始化...")
    success = manager.initialize()
    print(f"   状态: {'成功' if success else '失败'}")
    
    if not success:
        print(f"   错误: {manager.init_error}")
        sys.exit(1)
    
    # 2. 添加记忆
    print(f"\n2. 添加记忆...")
    tests = [
        ("我叫小明", MemoryType.FACT),
        ("我喜欢吃苹果", MemoryType.PREFERENCE),
        ("我的生日是1月1日", MemoryType.FACT),
        ("昨天去公园玩了", MemoryType.EVENT),
        ("我会Python编程", MemoryType.SKILL),
        ("我讨厌吃香菜", MemoryType.PREFERENCE),
    ]
    for content, mtype in tests:
        mid = manager.add_memory(content, mtype)
        status = "✓" if mid else "✗"
        print(f"   {status} [{mtype.value}] {content}")
    
    # 3. 检索测试
    print(f"\n3. 语义检索测试...")
    queries = [
        "我叫什么名字",
        "我喜欢吃什么",
        "我会不会编程",
        "我的生日是什么时候",
    ]
    for query in queries:
        results = manager.search(query, n_results=1, min_score=0.3)
        if results:
            r = results[0]
            print(f"   查询: '{query}'")
            print(f"   结果: '{r['content']}'")
            print(f"   相似度: {r['similarity']:.2%}")
        else:
            print(f"   查询: '{query}' -> 未找到")
        print()
    
    # 4. 格式化输出测试
    print(f"\n4. LLM Prompt 格式化测试...")
    formatted = manager.get_relevant_memories("我喜欢吃什么")
    if formatted:
        print("   系统提示词片段:")
        print(f"   {'-'*40}")
        print(f"   关于用户，你记得:")
        for line in formatted.split('\n'):
            print(f"   {line}")
        print(f"   {'-'*40}")
    else:
        print("   (无相关记忆)")
    
    # 5. 统计信息
    print(f"\n5. 记忆统计...")
    stats = manager.get_memory_stats()
    print(f"   总记忆数: {stats['total']}")
    print(f"   按类型分布:")
    for mtype, count in stats["by_type"].items():
        display = MemoryType.get_display_name(MemoryType(mtype))
        print(f"     {display}: {count}")
    
    # 6. 清理测试数据
    print(f"\n6. 清理测试数据...")
    manager.clear_all()
    print(f"   ✓ 已清空所有记忆")
    
    print("\n" + "=" * 60)
    print("✓ 所有测试通过！")
    print("=" * 60)
