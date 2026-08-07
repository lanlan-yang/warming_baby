"""
memory/store.py - ChromaDB 向量存储

实现 MemoryStore 类，负责向量数据库的存储和检索操作。
"""
import os
import platform
import time
import math
from typing import Optional, List, Dict, Any
from pathlib import Path

from core.logger import setup_logger
from .types import MemoryType, MemoryItem
from .normalizer import get_normalizer

logger = setup_logger()


def get_available_device() -> str:
    """
    自动检测并返回最佳可用的推理设备

    优先级: CUDA (NVIDIA GPU) > MPS (Apple Silicon) > CPU

    Returns:
        设备名称: 'cuda', 'mps', 或 'cpu'
    """
    # 1. 检查 NVIDIA GPU (CUDA)
    try:
        import torch
        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            gpu_name = torch.cuda.get_device_name(0) if device_count > 0 else "Unknown"
            logger.info(f"[Memory] 检测到 CUDA 可用，GPU: {gpu_name}，共 {device_count} 个")
            return "cuda"
    except (ImportError, Exception) as e:
        # torch 未安装或 CUDA 不可用
        pass

    # 2. 检查 Apple Silicon (MPS) - macOS + Apple Silicon
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin" and machine == "arm64":
        try:
            import torch
            if torch.backends.mps.is_available():
                logger.info("[Memory] 检测到 Apple Silicon，使用 MPS 加速")
                return "mps"
        except (ImportError, Exception) as e:
            # torch 未安装或 MPS 不可用
            pass

    # 3. 回退到 CPU
    logger.info("[Memory] 未检测到 GPU 加速，使用 CPU 推理")
    return "cpu"


class BGEEmbeddingFunction:
    """BGE Embedding 函数 (直接用 transformers + torch，绕过 sentence_transformers)

    sentence_transformers 的 __init__.py 导入链依赖 sklearn/scipy/pandas/datasets 等，
    且 transformers 的懒加载机制在 PyInstaller frozen 环境中不稳定
    (第一次启动成功，之后每次导入失败)。
    这里直接用 transformers.AutoModel + AutoTokenizer 加载 BGE 模型，
    手动实现 mean pooling，功能等价但依赖更少、打包稳定。
    """

    def __init__(self, model_path: str, device: str = 'cpu'):
        from transformers import AutoTokenizer, AutoModel
        import torch

        self.device = device
        self.model_path = model_path
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModel.from_pretrained(model_path)
        self.model.to(device)
        self.model.eval()
        self.torch = torch

    def __call__(self, input):
        """生成 embedding 向量 (mean pooling)"""
        if isinstance(input, str):
            input = [input]

        encoded = self.tokenizer(
            input,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors='pt',
        )
        encoded = {k: v.to(self.device) for k, v in encoded.items()}

        with self.torch.no_grad():
            outputs = self.model(**encoded)

        # Mean Pooling - 按 attention_mask 加权平均
        attention_mask = encoded['attention_mask']
        token_embeddings = outputs.last_hidden_state
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sum_embeddings = self.torch.sum(token_embeddings * input_mask_expanded, 1)
        sum_mask = self.torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        embeddings = (sum_embeddings / sum_mask).cpu().numpy()

        return [e.tolist() for e in embeddings]

    def embed_query(self, input):
        """编码查询文本 (chromadb search 时调用)"""
        return self.__call__(input)

    def embed_documents(self, input):
        """编码文档 (chromadb add 时调用)"""
        return self.__call__(input)

    @staticmethod
    def name() -> str:
        return "bge_embedded"

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list:
        return ["cosine", "l2", "ip"]

    @staticmethod
    def build_from_config(config):
        return BGEEmbeddingFunction(
            model_path=config.get("model_path", ""),
            device=config.get("device", "cpu"),
        )

    def get_config(self) -> dict:
        return {"model_path": self.model_path, "device": self.device}


class MemoryStore:
    """
    ChromaDB 向量存储封装

    负责实际的向量存储和语义检索操作。使用自定义的 BGEEmbeddingFunction
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

    设备选择:
        - 自动检测最优设备：CUDA > MPS > CPU
        - 也可以通过环境变量 WARMING_BABY_DEVICE 手动指定
        - 例如: export WARMING_BABY_DEVICE=cuda

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
            1. 自动检测最佳设备 (GPU/CPU)
            2. 加载本地 bge-small-zh-v1.5 embedding 模型
            3. 创建 ChromaDB 持久化客户端
            4. 获取或创建 'user_memory' 集合

        Returns:
            True:  初始化成功
            False: 初始化失败 (会打印错误日志)

        注意:
            - 有 NVIDIA GPU 会自动用 CUDA 加速
            - Apple Silicon 会自动用 MPS 加速
            - 无 GPU 则用 CPU
            - 首次加载模型约需 2-3 秒 (GPU 会更快)
        """
        if self._initialized:
            return True

        try:
            import chromadb
            from chromadb.config import Settings

            logger.info("[Memory] 正在初始化向量存储...")

            # 自动检测最佳设备 (环境变量 > 自动检测 CUDA > MPS > CPU)
            env_device = os.environ.get("WARMING_BABY_DEVICE")
            if env_device and env_device.lower() in ("cuda", "mps", "cpu"):
                device = env_device.lower()
                logger.info(f"[Memory] 使用环境变量指定的设备: {device}")
            else:
                device = get_available_device()
                logger.info(f"[Memory] 自动检测设备: {device}")

            # 自定义 BGE Embedding 函数 (绕过 sentence_transformers，打包稳定)
            self._embedding_func = BGEEmbeddingFunction(
                model_path=self._model_path,
                device=device,
            )
            logger.info(f"[Memory] Embedding 模型加载完成，设备: {device}")
            
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
            # 注意：metadata 的构造顺序很重要！
            # 先展开 item.metadata，再设置固定字段，这样固定字段不会被覆盖
            normalizer = get_normalizer()
            self._collection.add(
                ids=[item.memory_id for item in items],              # 唯一 ID 列表
                documents=[item.content for item in items],          # 文本内容列表
                metadatas=[
                    {
                        **item.metadata,                                    # 先展开额外元数据 (含调用方传入的 field)
                        "type": item.memory_type.value,                     # 固定字段：类型
                        "field": item.metadata.get("field")                 # 优先用调用方传入的 field
                                if item.metadata.get("field")               # 没传才用规则提取
                                else normalizer.extract_field(
                                    item.content, item.memory_type
                                ),
                        "importance": item.importance,                      # 固定字段：重要性
                        "created_at": item.created_at,                      # 固定字段：创建时间（高优先级）
                        "updated_at": item.updated_at,                      # 固定字段：更新时间
                        "access_count": item.access_count,                  # 固定字段：访问次数
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

        归一化去重 (FACT + PREFERENCE):
        - FACT: 同字段(name/birthday/...)的新值替换旧值，不同字段共存
        - PREFERENCE: 同核心内容(如"苹果")的新方向替换旧方向，不同核心共存
        - 归一化后完全相同的表述跳过添加 (如"我叫小明"≈"用户叫小明")

        向量搜索兜底 (其他类型或无法识别字段的记忆):
        - 完全相同跳过，高度相似(>0.9)跳过
        - 相似记忆由相似度阈值控制

        Args:
            items: MemoryItem 列表
            similarity_threshold: 相似度阈值 (0-1)，超过则认为是同一条记忆

        Returns:
            True: 添加成功
            False: 添加失败
        """
        if not self.is_ready or not items:
            return False

        try:
            items_to_add = []

            for item in items:
                # === 归一化预检查（不依赖向量搜索）===
                # 对能识别字段的 FACT 和 PREFERENCE 类型，用 where 过滤只查同字段记忆
                # 解决向量相似度不够高、向量搜索召回不到的问题
                # 归一化去重是确定性的，基于规则而非向量相似度
                # 性能: 用 ChromaDB where 过滤，只返回同字段的少量记录，避免全量遍历
                normalizer = get_normalizer()
                # 优先用调用方传入的 field (metadata 里)，没有才用规则提取
                new_field = item.metadata.get("field") or normalizer.extract_field(
                    item.content, item.memory_type
                )

                if new_field != "other":
                    new_norm = normalizer.normalize(item.content, item.memory_type)
                    # 用 where 过滤，只取同字段的记忆（通常只有 1-2 条）
                    # 避免全量 get_all 遍历，记忆量大时性能差距明显
                    # ChromaDB 多条件过滤需要用 $and 操作符
                    field_results = self._collection.get(
                        where={
                            "$and": [
                                {"type": item.memory_type.value},
                                {"field": new_field},
                            ]
                        },
                        include=["documents", "metadatas"]
                    )
                    skip_this = False
                    replace_ids = []
                    if field_results["documents"]:
                        for doc, _, rid in zip(
                            field_results["documents"],
                            field_results["metadatas"],
                            field_results["ids"]
                        ):
                            old_norm = normalizer.normalize(doc, item.memory_type)
                            if old_norm == new_norm:
                                # 归一化后相同，跳过添加
                                logger.info(
                                    f"[Memory.smart_add] 归一化去重: "
                                    f"'{item.content}' ≈ '{doc}'"
                                )
                                skip_this = True
                                break
                            # 同字段不同值（如改名/改喜好方向），标记替换
                            replace_ids.append(rid)

                    if skip_this:
                        continue

                    if replace_ids:
                        self.delete(replace_ids)
                        logger.info(
                            f"[Memory.smart_add] 同字段({new_field})替换: "
                            f"删除 {len(replace_ids)} 条旧记忆"
                        )
                        items_to_add.append(item)
                        continue

                # === 向量搜索相似记忆（兜底：处理无法识别字段的记忆）===
                # 注意：use_weighting=False 表示用纯相似度，不乘时间衰减也不乘重要性
                # smart_add 的目的是判断"有没有语义相似的旧记忆"，这是纯语义判断
                # 时间和重要性不应该影响去重逻辑，否则老记忆或低重要性记忆会被误判为"不相似"
                similar_results = self.search(
                    query=item.content,
                    n_results=3,
                    memory_type=item.memory_type,
                    min_score=similarity_threshold,
                    use_weighting=False  # 去重用纯相似度，不考虑时间和重要性
                )

                # 如果有相似的旧记忆
                if similar_results:
                    # 检查是否存在完全相同的内容
                    exact_match = any(r['content'] == item.content for r in similar_results)
                    if exact_match:
                        # 完全相同，跳过添加（避免重复）
                        logger.info(f"[Memory.smart_add] 已存在完全相同的记忆，跳过: {item.content}")
                        continue

                    # 检查是否存在高度相似的内容（同主题不同表述）
                    # 相似度 > 0.9 视为同一内容的不同表述
                    high_similarity_threshold = 0.9
                    highly_similar = any(r.get('similarity', 0) > high_similarity_threshold for r in similar_results)
                    if highly_similar:
                        # 高度相似视为重复，跳过（适用于所有类型）
                        logger.info(f"[Memory.smart_add] 已存在高度相似的记忆({high_similarity_threshold})，跳过: {item.content}")
                        continue

                items_to_add.append(item)
            
            # 添加新记忆
            if items_to_add:
                return self.add(items_to_add)
            # 全部被跳过（归一化去重等），没有实际添加
            logger.info(f"[Memory.smart_add] 所有记忆被跳过，未添加新记忆")
            return False
            
        except Exception as e:
            logger.error(f"[Memory.smart_add] 失败: {e}")
            return False
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        memory_type: Optional[MemoryType] = None,
        min_score: float = 0.3,
        time_decay: float = 0.3,
        use_weighting: bool = True
    ) -> List[Dict[str, Any]]:
        """
        语义检索相关记忆（带时间衰减和重要性）

        根据查询文本的向量表示，在向量空间中寻找最相似的记忆。
        同时考虑时间和重要性因素：越新的、越重要的记忆权重越高。

        Args:
            query:         查询文本 (如 '我叫什么名字')
            n_results:     返回结果数量 (默认 5 条)
            memory_type:   可选，只在指定类型的记忆中检索
            min_score:     ⚠️ 最低分数阈值 (0-1，默认 0.3)
                           - use_weighting=True 时是"综合分数"阈值
                           - use_weighting=False 时是"纯相似度"阈值
            time_decay:    时间衰减系数 (0-1，默认 0.3)
                           - 0 = 不衰减（纯相似度判断）
                           - 0.3 = 推荐值，30天衰减到约 74%
                           - 0.5 = 较强衰减
            use_weighting: 是否启用加权（时间衰减 × 重要性），默认 True
                           - True:  综合分数 = 相似度 × 时间衰减 × 重要性
                           - False: 综合分数 = 纯相似度（用于内部判断，如去重）

        Returns:
            记忆列表，按分数排序
            每条包含:
            - content: 记忆内容
            - similarity: 纯语义相似度 (0-1)
            - time_decay: 时间衰减因子 (0-1)
            - importance: 重要性 (0-1)
            - score: 综合分数 (加权或纯相似度)

        评分公式 (use_weighting=True):
            time_decay_factor = exp(-λ × age_days)
            final_score = 0.6 × similarity + 0.2 × time_decay_factor + 0.2 × importance
            其中 λ = time_decay / 30

            权重说明:
            - 相似度 0.6: 主导因素，语义匹配最重要
            - 时间衰减 0.2: 调整因素，新记忆略有优势
            - 重要性 0.2: 调整因素，重要记忆略有优势

        评分公式 (use_weighting=False):
            final_score = similarity  (纯语义，不考虑时间和重要性)

        使用场景:
            # 场景1: 给用户展示（默认加权）
            results = search('我的爱好')

            # 场景2: 内部判断是否有相似记忆（纯语义，用于去重/替换判断）
            results = search('我的爱好', use_weighting=False)

            # 场景3: 只看很新的记忆（强时间衰减）
            results = search('我的爱好', time_decay=0.5)
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
            actual_results = min(n_results * 3, self.count) if self.count > 0 else 1
            
            # 执行向量检索
            # query_texts 会自动转换为向量
            # 返回的 distances 是余弦距离，需要转换为相似度
            results = self._collection.query(
                query_texts=[query],                 # 查询文本
                n_results=actual_results,            # 返回数量（多取一些，稍后筛选）
                where=where_filter,                  # 过滤条件
                include=["documents", "metadatas", "distances"]  # 返回字段
            )
            
            # 计算时间衰减函数
            current_time = time.time()
            decay_lambda = time_decay / 30  # 30 天半衰期

            def calculate_time_decay(created_at: float) -> float:
                """计算时间衰减因子"""
                age_days = (current_time - created_at) / (24 * 60 * 60)
                return math.exp(-decay_lambda * age_days)
            
            # 解析结果并计算综合分数
            memories = []
            if results["documents"] and results["documents"][0]:
                for doc, meta, dist, rid in zip(
                    results["documents"][0],     # 文档内容
                    results["metadatas"][0],     # 元数据
                    results["distances"][0],     # 余弦距离
                    results["ids"][0]            # 文档 ID
                ):
                    # 余弦相似度 = 1 - 余弦距离
                    similarity = 1 - dist
                    
                    # 时间衰减
                    created_at = meta.get("created_at", current_time) if meta else current_time
                    time_decay_factor = calculate_time_decay(created_at)
                    
                    # 重要性权重 (从 metadata 获取，默认 0.5)
                    importance = meta.get("importance", 0.5) if meta else 0.5
                    
                    # 计算最终分数
                    if use_weighting:
                        # 加权求和：相似度为主，时间和重要性为辅
                        # 避免三个 0-1 值相乘导致分数过度衰减
                        #   乘法: 0.8 × 0.8 × 0.8 = 0.51 (过低)
                        #   加权: 0.6×0.8 + 0.2×0.8 + 0.2×0.8 = 0.80 (合理)
                        final_score = (
                            0.6 * similarity
                            + 0.2 * time_decay_factor
                            + 0.2 * importance
                        )
                    else:
                        # 纯相似度（用于内部判断，如去重/替换）
                        final_score = similarity
                    
                    # 只保留超过阈值的结果
                    if final_score >= min_score:
                        memories.append({
                            "id": rid,
                            "content": doc,
                            "metadata": meta,
                            "similarity": round(similarity, 4),
                            "time_decay": round(time_decay_factor, 4),
                            "importance": importance,
                            "access_count": meta.get("access_count", 0) if meta else 0,
                            "score": round(final_score, 4),
                        })

            # 按综合分数排序
            memories.sort(key=lambda x: x["score"], reverse=True)

            # 截取前 n_results 条
            memories = memories[:n_results]

            # 更新被检索到的记忆的 access_count（仅在非内部判断时统计）
            if memories and use_weighting:
                self._increment_access_count([m["id"] for m in memories])

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

    def _increment_access_count(self, memory_ids: List[str]):
        """
        批量递增记忆的访问次数 (内部方法)

        每次 search 返回结果后调用，用于统计哪些记忆被频繁检索。
        内部判断（use_weighting=False，如去重）不统计。

        Args:
            memory_ids: 被检索到的记忆 ID 列表
        """
        if not self.is_ready or not memory_ids:
            return

        try:
            # 批量获取现有 metadata
            existing = self._collection.get(ids=memory_ids)
            if not existing or not existing["metadatas"]:
                return

            # 递增 access_count
            updated_metas = []
            for meta in existing["metadatas"]:
                if meta is None:
                    meta = {}
                meta["access_count"] = meta.get("access_count", 0) + 1
                meta["updated_at"] = time.time()
                updated_metas.append(meta)

            self._collection.update(
                ids=memory_ids,
                metadatas=updated_metas
            )
        except Exception as e:
            logger.warning(f"[Memory] 更新 access_count 失败: {e}")

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
