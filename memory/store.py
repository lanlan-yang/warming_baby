"""
memory/store.py - ChromaDB 向量存储

实现 MemoryStore 类，负责向量数据库的存储和检索操作。
"""
import os
import time
import math
from typing import Optional, List, Dict, Any
from pathlib import Path

from core.logger import setup_logger
from core.errors import AgentError, ErrorCode
from .types import MemoryType, MemoryItem
from .normalizer import get_normalizer

logger = setup_logger()


class CloudEmbeddingFunction:
    """云端 Embedding 函数 (OpenAI 兼容 API)

    通过 OpenAI SDK 调用云端 embedding 服务 (如 DashScope/阿里云)，
    替代本地 BGE 模型，无需打包 torch/transformers，大幅减小打包体积。

    配置从 .env 读取:
        embedding_model:         模型名称
        embedding_model_url:     API base_url
        embedding_model_api_key: API Key
    """

    def __init__(self, model: str, base_url: str, api_key: str):
        from openai import OpenAI

        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._batch_size = 64  # API 单次请求最大文本数

    # LLM_* → EMBED_* 映射
    # classify() 根据异常类型/消息判断，但 embedding API 抛的异常
    # 消息里没有 "embedding/dashscope" 上下文，会误判为 LLM_*。
    # 这里手动映射到对应的 EMBED_*，确保用户看到"记忆模型"而非"对话模型"。
    _LLM_TO_EMBED = {
        ErrorCode.LLM_AUTH_INVALID: ErrorCode.EMBED_AUTH_INVALID,
        ErrorCode.LLM_AUTH_EXPIRED: ErrorCode.EMBED_AUTH_INVALID,
        ErrorCode.LLM_QUOTA_EXHAUSTED: ErrorCode.EMBED_QUOTA_EXHAUSTED,
        ErrorCode.LLM_RATE_LIMIT: ErrorCode.EMBED_SERVER_ERROR,
        ErrorCode.LLM_TIMEOUT: ErrorCode.EMBED_TIMEOUT,
        ErrorCode.LLM_SERVER_ERROR: ErrorCode.EMBED_SERVER_ERROR,
        ErrorCode.LLM_BAD_REQUEST: ErrorCode.EMBED_SERVER_ERROR,
    }

    @classmethod
    def _is_embedding_error(cls, e: Exception) -> Optional[AgentError]:
        """检测异常是否来自 embedding API（ChromaDB 会包装 embedding 异常）

        ChromaDB 的 collection.query()/add() 内部调用 embedding function，
        如果 embedding function 抛异常，ChromaDB 会 catch 后重新抛为
        普通 Exception（附加 " in query." / " in add." 后缀），
        原始异常类型丢失。

        所以 store.search()/add() 的 except Exception 块需要调用本方法，
        根据消息前缀 [embedding/dashscope] 判断是否是 embedding 错误，
        是则返回 AgentError 让上层上抛，不是则返回 None 让上层降级。

        注意：因为 ChromaDB 把异常类型变成了普通 Exception，
        classify() 无法根据类型名判断，所以这里直接用消息关键词匹配。
        """
        msg = str(e)
        if "[embedding/dashscope" not in msg:
            return None

        msg_lower = msg.lower()

        # 根据 _embed() 抛出的消息里的异常类型名 + API 错误关键词匹配
        if any(k in msg_lower for k in (
            "authenticationerror", "authentication_error",
            "incorrect api key", "invalid api key", "api key.*invalid",
            "authentication fails", "鉴权失败",
        )):
            return AgentError._build(ErrorCode.EMBED_AUTH_INVALID, original=msg)

        if any(k in msg_lower for k in (
            "ratelimiterror", "rate_limit", "429", "too many requests",
            "quota", "额度", "余额不足", "insufficient",
        )):
            return AgentError._build(ErrorCode.EMBED_QUOTA_EXHAUSTED, original=msg)

        if any(k in msg_lower for k in (
            "timeouterror", "timeout", "timed out",
        )):
            return AgentError._build(ErrorCode.EMBED_TIMEOUT, original=msg)

        if any(k in msg_lower for k in (
            "internalservererror", "internal_error", "500",
            "server error", "service unavailable", "bad gateway",
        )):
            return AgentError._build(ErrorCode.EMBED_SERVER_ERROR, original=msg)

        # 兜底：确认是 embedding 错误但无法细分，用通用 embedding 服务端错误
        return AgentError._build(ErrorCode.EMBED_SERVER_ERROR, original=msg)

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """调用云端 API 生成 embedding 向量

        注意：不抛 AgentError！ChromaDB 会 catch embedding function 抛的
        异常并重新包装为普通 Exception（类型丢失），导致下游
        except AgentError 匹配不到。

        改为抛带 [embedding/dashscope] 前缀的普通 Exception，
        下游 store.search()/add() 的 except Exception 块通过
        _is_embedding_error() 检测前缀并分类。
        """
        all_embeddings = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            try:
                response = self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                )
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                logger.error(
                    f"[Memory] 云端 Embedding API 调用失败 (batch {i}): "
                    f"{type(e).__name__}: {e}"
                )
                # 不抛 AgentError（ChromaDB 会吞类型），抛带前缀的普通异常
                raise Exception(
                    f"[embedding/dashscope model={self._model}] "
                    f"{type(e).__name__}: {e}"
                ) from e

        return all_embeddings

    def __call__(self, input):
        """生成 embedding 向量"""
        if isinstance(input, str):
            input = [input]
        return self._embed(input)

    def embed_query(self, input):
        """编码查询文本 (chromadb search 时调用)"""
        return self.__call__(input)

    def embed_documents(self, input):
        """编码文档 (chromadb add 时调用)"""
        return self.__call__(input)

    @staticmethod
    def name() -> str:
        return "cloud_embedding"

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list:
        return ["cosine", "l2", "ip"]

    @staticmethod
    def build_from_config(config):
        return CloudEmbeddingFunction(
            model=config.get("model", ""),
            base_url=config.get("base_url", ""),
            api_key=config.get("api_key", ""),
        )

    def get_config(self) -> dict:
        return {"model": self._model, "base_url": self._base_url}


class MemoryStore:
    """
    ChromaDB 向量存储封装

    负责实际的向量存储和语义检索操作。使用 CloudEmbeddingFunction
    调用云端 API 进行向量编码，无需本地模型。

    核心功能:
        - initialize():  初始化数据库和 embedding 客户端
        - add():         添加记忆向量
        - search():      语义检索记忆
        - delete():      删除记忆
        - get_all():     获取所有记忆
        - clear():       清空所有记忆

    向量空间配置:
        - 距离度量: cosine (余弦相似度)
        - 维度: 由云端模型决定

    使用示例:
        store = MemoryStore('/path/to/memory')
        store.initialize()
        store.add([MemoryItem(content='我叫小明', memory_type=MemoryType.FACT)])
        results = store.search('我叫什么', n_results=1)
    """

    def __init__(self, storage_path: str):
        """
        初始化向量存储

        Args:
            storage_path: ChromaDB 数据存储路径 (目录)
        """
        self._storage_path = storage_path  # 数据存储目录
        self._client = None                 # ChromaDB 客户端
        self._collection = None             # 向量集合 (类似数据库表)
        self._embedding_func = None         # Embedding 函数
        self._initialized = False           # 是否初始化完成

    def initialize(self) -> bool:
        """
        初始化向量存储

        执行以下操作:
            1. 从 .env 读取云端 embedding 配置
            2. 创建 OpenAI 兼容客户端
            3. 创建 ChromaDB 持久化客户端
            4. 获取或创建 'user_memory' 集合

        Returns:
            True:  初始化成功
            False: 初始化失败 (会打印错误日志)
        """
        if self._initialized:
            return True

        try:
            import chromadb
            from chromadb.config import Settings

            logger.info("[Memory] 正在初始化向量存储...")

            # 从 config_manager 读取云端 embedding 配置
            # config_manager 在 load() 时已从 secure 存储读取 api_key
            try:
                from config import config_manager
                emb_cfg = config_manager.get("embedding", {}) or {}
                model = emb_cfg.get("model", "")
                base_url = emb_cfg.get("base_url", "")
                api_key = emb_cfg.get("api_key", "")
            except Exception:
                model, base_url, api_key = "", "", ""

            # 兜底：config_manager 没有则从 .env 读取
            if not model or not base_url or not api_key:
                try:
                    from dotenv import load_dotenv
                    from core.paths import _get_base_dir
                    load_dotenv(_get_base_dir() / ".env", override=False)
                    model = os.environ.get("embedding_model", "")
                    base_url = os.environ.get("embedding_model_url", "")
                    api_key = os.environ.get("embedding_model_api_key", "")
                except Exception:
                    pass

            if not model or not base_url or not api_key:
                # 从 core.errors 抛结构化 CONFIG_MISSING_EMBED_KEY，
                # 这样上层 ChatAgent 捕获后能给出精确提示，而不是"说不清的问题"
                # 注意: 不要在此函数内 import AgentError —— 局部导入会把它变成
                # 整个函数的局部变量，后面 except AgentError 求值时会 UnboundLocalError
                raise AgentError._build(ErrorCode.CONFIG_MISSING_EMBED_KEY)

            self._embedding_func = CloudEmbeddingFunction(
                model=model,
                base_url=base_url,
                api_key=api_key,
            )
            logger.info(f"[Memory] 云端 Embedding 客户端就绪: {model}")

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
            # 注意: 切换 embedding 模型后维度可能不同，需重建集合
            try:
                self._collection = self._client.get_or_create_collection(
                    name="user_memory",                          # 集合名称
                    embedding_function=self._embedding_func,     # 向量编码函数
                    metadata={"hnsw:space": "cosine"}            # 使用余弦距离
                )
                # 验证已有数据维度是否匹配 (如果集合非空)
                if self._collection.count() > 0:
                    peek = self._collection.peek(limit=1)
                    existing_dim = len(peek["embeddings"][0])
                    try:
                        test_emb = self._embedding_func.embed_query("test")
                        new_dim = len(test_emb[0])
                    except Exception as embed_err:
                        # embedding API 调用失败（Key 错/网络/超时等）：
                        # 不能 delete_collection！否则会清空所有记忆！
                        # 只跳过维度检查，保留已有记忆，上抛错误让用户知道
                        embed_ae = CloudEmbeddingFunction._is_embedding_error(embed_err)
                        if embed_ae:
                            logger.error(
                                f"[Memory] 维度检查时 Embedding API 失败，"
                                f"保留已有记忆并上抛错误: {embed_err}"
                            )
                            raise embed_ae from embed_err
                        # 非 embedding 错误（如本地异常），跳过维度检查
                        logger.warning(
                            f"[Memory] 维度检查异常，跳过: {embed_err}"
                        )
                        # 不做维度检查，直接用已有集合
                        pass
                    else:
                        if existing_dim != new_dim:
                            logger.warning(
                                f"[Memory] 向量维度不匹配 (旧={existing_dim}, 新={new_dim})，"
                                f"重建集合..."
                            )
                            self._client.delete_collection("user_memory")
                            self._collection = self._client.get_or_create_collection(
                                name="user_memory",
                                embedding_function=self._embedding_func,
                                metadata={"hnsw:space": "cosine"}
                            )
                            logger.info("[Memory] 集合已重建 (旧记忆已清除)")
            except AgentError:
                # embedding 鉴权/网络类错误：直接上抛
                raise
            except Exception as dim_err:
                # 非结构化异常（如集合维度不匹配）：重建集合
                logger.warning(f"[Memory] 集合初始化异常，尝试重建: {dim_err}")
                self._client.delete_collection("user_memory")
                self._collection = self._client.get_or_create_collection(
                    name="user_memory",
                    embedding_function=self._embedding_func,
                    metadata={"hnsw:space": "cosine"}
                )

            self._initialized = True
            logger.info(f"[Memory] 向量存储初始化完成: {self._storage_path}")
            logger.info(f"[Memory] 当前记忆数量: {self._collection.count()}")
            return True

        except AgentError:
            raise
        except Exception as e:
            logger.error(f"[Memory] 向量存储初始化失败: {e}")
            return False
    
    @property
    def is_ready(self) -> bool:
        """检查存储是否就绪"""
        return self._initialized and self._collection is not None

    def update_embedding_config(self) -> bool:
        """
        热更新 Embedding 配置（不改 ChromaDB 集合，不丢数据）

        用户在 Settings 改了 Embedding API Key / model / base_url 后，
        config_manager 会通知 listener，listener 调本方法：
        1. 重新读取 embedding 配置
        2. 创建新的 CloudEmbeddingFunction
        3. 用新 embedding function 重新获取已有 collection（不删除数据）

        Returns:
            True: 更新成功
            False: 更新失败（Key 错/缺配置等）
        """
        try:
            from config import config_manager
            emb_cfg = config_manager.get("embedding", {}) or {}
            model = emb_cfg.get("model", "")
            base_url = emb_cfg.get("base_url", "")
            api_key = emb_cfg.get("api_key", "")

            if not model or not base_url or not api_key:
                logger.warning("[Memory] 热更新: Embedding 配置不完整，跳过")
                return False

            # 创建新的 embedding function
            new_ef = CloudEmbeddingFunction(
                model=model,
                base_url=base_url,
                api_key=api_key,
            )

            # 用新 embedding function 重新获取已有 collection（不删除数据）
            self._embedding_func = new_ef
            if self._client is not None:
                self._collection = self._client.get_collection(
                    name="user_memory",
                    embedding_function=new_ef,
                )
                logger.info(f"[Memory] Embedding 配置已热更新: {model}")
            return True

        except Exception as e:
            logger.error(f"[Memory] Embedding 热更新失败: {e}")
            return False

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
            self._collection.add(
                ids=[item.memory_id for item in items],              # 唯一 ID 列表
                documents=[item.content for item in items],          # 文本内容列表
                metadatas=[
                    {
                        **item.metadata,                                    # 先展开额外元数据 (含调用方传入的 field)
                        "type": item.memory_type.value,                     # 固定字段：类型
                        "field": item.metadata.get("field", "other"),        # field 由上游 smart_add 已提取
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

        except AgentError:
            raise
        except Exception as e:
            # ChromaDB 包装 embedding 异常为普通 Exception，检测前缀
            embed_err = CloudEmbeddingFunction._is_embedding_error(e)
            if embed_err:
                logger.error(f"[Memory] 添加失败(embedding类,上抛): {e}")
                raise embed_err from e
            logger.error(f"[Memory] 添加记忆失败(降级): {e}")
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
            
        except AgentError:
            # 结构化错误（如 CONFIG_MISSING_EMBED_KEY / EMBED_AUTH_INVALID）：
            # 直接向上抛，最终 ChatAgent 会转成友好提示
            raise
        except Exception as e:
            # ChromaDB 包装 embedding 异常为普通 Exception，检测前缀
            embed_err = CloudEmbeddingFunction._is_embedding_error(e)
            if embed_err:
                logger.error(f"[Memory.smart_add] Embedding类错误,上抛: {e}")
                raise embed_err from e
            # 本地异常（如 ChromaDB 损坏）：降级，不打断对话
            logger.error(f"[Memory.smart_add] 失败(降级): {e}")
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
            use_weighting: 是否启用加权（相似度为主，时间和重要性为辅），默认 True
                           - True:  综合分数 = 0.6 × 相似度 + 0.2 × 时间衰减 + 0.2 × 重要性
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

        except AgentError:
            raise
        except Exception as e:
            # ChromaDB 包装 embedding 异常为普通 Exception，检测前缀
            embed_err = CloudEmbeddingFunction._is_embedding_error(e)
            if embed_err:
                logger.error(f"[Memory] 检索失败(embedding类,上抛): {e}")
                raise embed_err from e
            logger.error(f"[Memory] 检索失败(降级): {e}")
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
