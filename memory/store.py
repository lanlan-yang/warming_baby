"""
memory/store.py - ChromaDB 向量存储

实现 MemoryStore 类，负责向量数据库的存储和检索操作。
"""
from typing import Optional, List, Dict, Any
from pathlib import Path

from core.logger import setup_logger
from .types import MemoryType, MemoryItem

logger = setup_logger()


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
        - 维度: 512 (由 bge-small-zh 决定)
        - 距离度量: cosine (余弦相似度)
        - 归一化: 开启 (便于相似度计算)

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
            storage_path: ChromaDB 数据存储路径 (目录)
            model_path:   Embedding 模型路径
        """
        self._storage_path = storage_path  # 数据存储目录
        self._model_path = model_path      # Embedding 模型路径
        self._client = None                 # ChromaDB 客户端
        self._collection = None             # 向量集合 (类似数据库表)
        self._embedding_func = None         # Embedding 函数
        self._initialized = False           # 是否初始化完成
    
    def initialize(self) -> bool:
        """
        初始化向量存储

        执行以下操作:
            1. 加载本地 bge-small-zh-v1.5 embedding 模型
            2. 创建 ChromaDB 持久化客户端
            3. 获取或创建 'user_memory' 集合

        Returns:
            True:  初始化成功
            False: 初始化失败 (会打印错误日志)

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
                name="user_memory",                          # 集合名称
                embedding_function=self._embedding_func,     # 向量编码函数
                metadata={"hnsw:space": "cosine"}            # 使用余弦距离
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
                        "type": item.memory_type.value,                # 记忆类型 (用于过滤)
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
        智能添加: 自动检测并替换同类相似的旧记忆

        使用场景:
        用户第一次说"我叫小明"，第二次说"我叫小红"
        系统自动识别为同类型 (fact) 的相似内容，替换旧的

        智能判断:
        - 对于 preference 类型，会提取方向 (喜欢/不喜欢) 和核心内容
        - 只有核心内容相同时，才会考虑替换 (无论方向是否改变)
        - 核心内容不同的偏好会共存

        Args:
            items: MemoryItem 列表
            similarity_threshold: 相似度阈值 (0-1)，超过则认为是同一条记忆

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
            """提取偏好的 (方向, 核心内容)"""
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
                # 程度副词 (移除后不影响核心)
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
            
            # 先检查 dislike (更长的关键词优先匹配)
            for kw in dislike_keywords:
                if kw in core:
                    direction = "dislike"
                    core = core.replace(kw, "", 1).strip()
                    break
            
            # 再检查 like (更长的关键词优先匹配)
            if direction == "unknown":
                for kw in like_keywords:
                    if kw in core:
                        direction = "like"
                        core = core.replace(kw, "", 1).strip()
                        break
            
            return direction, core
        
        def _should_replace(old_content: str, new_content: str, memory_type: MemoryType) -> bool:
            """
            判断是否应该替换旧记忆
            
            规则:
            1. PREFERENCE 类型: 需要核心内容相同才能替换
            2. FACT 类型: 默认不替换，除非内容高度相似 (>0.85)
               - 避免不同事实被错误删除 (如 "用户叫XX" vs "用户在XX")
            """
            if memory_type == MemoryType.PREFERENCE:
                # 提取方向和核心内容
                old_dir, old_core = _extract_preference(old_content)
                new_dir, new_core = _extract_preference(new_content)
                
                # 如果核心内容都能提取，且不同，则不替换
                if old_dir != "unknown" and new_dir != "unknown":
                    if old_core != new_core:
                        logger.debug(f"[Memory.smart_add] 核心内容不同，不替换: '{old_core}' vs '{new_core}'")
                        return False
                    # 核心内容相同 (无论方向是否改变)，允许替换
                    logger.debug(f"[Memory.smart_add] 核心内容相同，允许替换: '{old_content}' -> '{new_content}'")
                else:
                    # 如果有无法提取的，保守不替换
                    return False
            
            elif memory_type == MemoryType.FACT:
                # FACT 类型: 默认不替换，使用更高的阈值
                # 需要超过 0.85 的相似度才能替换
                # 这是因为不同的事实可能在向量空间中有一些相似性
                # 比如 "用户叫杨程巍" 和 "用户在成都" 都会有 "用户" 这个关键词
                logger.debug(f"[Memory.smart_add] FACT类型，默认不替换: '{old_content}' vs '{new_content}'")
                return False
            
            # 其他类型: 默认允许替换
            logger.debug(f"[Memory.smart_add] 其他类型，允许替换: '{old_content}' -> '{new_content}'")
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
                        # 检查是否应该替换 (处理偏好的核心内容匹配)
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
            query:       查询文本 (如 '我叫什么名字')
            n_results:   返回结果数量 (默认 5 条)
            memory_type: 可选，只在指定类型的记忆中检索
            min_score:   最低相似度阈值 (0-1，默认 0.3)

        Returns:
            记忆列表，每条包含:
                - content:  记忆内容
                - metadata: 元数据 (类型、时间等)
                - similarity: 相似度分数 (0-1，越高越相关)

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

            # 高阈值检索 (只返回最相关的)
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
        获取所有记忆 (不进行向量检索)

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
            
            # 整理结果 (id 在 results 中是单独的字段)
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
            此操作不可撤销，所有记忆将永久删除!
        """
        if not self.is_ready:
            return False
        
        try:
            # 保存 embedding 函数的引用
            embedding_func = self._collection._embedding_function
            
            # 删除旧集合
            self._client.delete_collection("user_memory")
            
            # 创建新集合 (保持相同配置)
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
    def extract_preference(text: str) -> tuple:
        """
        静态方法: 提取偏好的 (方向, 核心内容)

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
            # 程度副词 (移除后不影响核心)
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
        
        # 先检查 dislike (更长的关键词优先匹配)
        for kw in dislike_keywords:
            if kw in core:
                direction = "dislike"
                core = core.replace(kw, "", 1).strip()
                break
        
        # 再检查 like (更长的关键词优先匹配)
        if direction == "unknown":
            for kw in like_keywords:
                if kw in core:
                    direction = "like"
                    core = core.replace(kw, "", 1).strip()
                    break
        
        return direction, core
    
    def should_replace_keyword(
        self, 
        old_content: str, 
        new_content: str, 
        memory_type: MemoryType
    ) -> bool:
        """
        判断是否应该替换旧记忆 (使用关键词匹配)

        Args:
            old_content: 旧记忆内容
            new_content: 新记忆内容
            memory_type: 记忆类型

        Returns:
            True: 应该替换
            False: 不应该替换 (无法确定)
        """
        # 对于偏好类型，使用更智能的判断
        if memory_type == MemoryType.PREFERENCE:
            # 提取方向和核心内容
            old_dir, old_core = self.extract_preference(old_content)
            new_dir, new_core = self.extract_preference(new_content)
            
            # 如果核心内容都能提取，判断是否相同
            if old_dir != "unknown" and new_dir != "unknown":
                return old_core == new_core
            
            # 如果有无法提取的，返回 False (不确定)
            return False
        
        # 对于其他类型，如果是完全相同的，不替换
        if old_content == new_content:
            return False
        
        # 对于其他类型，默认允许替换 (由相似度来控制)
        return True
