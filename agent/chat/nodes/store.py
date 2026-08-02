"""
agent/chat/nodes/store.py - 记忆存储节点

职责：智能处理新记忆的存储。

架构说明：
  - 存储层（long_memory_base.py）：只负责 CRUD，不做智能判断
  - 应用层（store.py）：负责智能判断逻辑，决定是否替换旧记忆

智能判断流程：
  1. 查找相似记忆
  2. 关键词判断（快速）
  3. LLM 判断（用 with_structured_output 保证格式）
  4. 执行存储操作（删除旧的，添加新的）
"""
from enum import StrEnum
from typing import List, Optional
from pydantic import BaseModel
from agent.chat.state import AgentState
from core.logger import setup_logger

logger = setup_logger()


class ReplaceDecision(StrEnum):
    """替换决策枚举"""
    REPLACE = "replace"
    KEEP_BOTH = "keep_both"
    KEEP_OLD = "keep_old"


class DecisionResult(BaseModel):
    """LLM 返回的决策结果"""
    decision: ReplaceDecision


async def judge_replace_with_llm(
    old_content: str,
    new_content: str,
    memory_type: str
) -> str:
    """
    使用 LLM 判断新旧记忆的关系（用 with_structured_output 保证格式）

    Args:
        old_content: 旧记忆内容
        new_content: 新记忆内容
        memory_type: 记忆类型 (fact/preference/event/context/skill)

    Returns:
        决策结果: 'replace' (替换), 'keep_both' (共存), 'keep_old' (保留旧的)
    """
    try:
        from providers import get_llm
        from langchain_core.messages import HumanMessage
        
        llm = get_llm()
        
        # 用 with_structured_output 保证返回格式
        structured_llm = llm.with_structured_output(DecisionResult, method="function_calling")
        
        prompt = f"""你是一个记忆管理专家。请判断以下两条{memory_type}类型记忆的关系。

旧记忆: {old_content}
新记忆: {new_content}

可选决策:
- replace: 新记忆完全替代旧记忆（如用户改变了对同一事物的看法）
- keep_both: 两条记忆应该共存（如用户有不同的喜好）
- keep_old: 保留旧记忆，忽略新记忆（如新记忆是临时的或错误的）"""
        
        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        decision = result.decision.value  # 直接获取枚举值
        
        logger.info(f"[StoreNode.LLM] 判断: {old_content} vs {new_content} -> {decision}")
        return decision

    except Exception as e:
        logger.warning(f"[StoreNode.LLM] 判断失败: {e}, 默认 keep_both")
        return ReplaceDecision.KEEP_BOTH.value


async def smart_store(
    mem_mgr,
    items: List,
    use_llm: bool = True,
    similarity_threshold: float = 0.5
) -> bool:
    """
    智能存储：自动判断是否需要替换旧记忆

    Args:
        mem_mgr: MemoryManager 实例
        items: 要存储的 MemoryItem 列表
        use_llm: 是否使用 LLM 进行智能判断
        similarity_threshold: 相似度阈值

    Returns:
        True/False 表示是否成功
    """
    items_to_add = []
    
    for item in items:
        # 查找相似记忆
        similar_results = mem_mgr.find_similar(
            query=item.content,
            memory_type=item.memory_type,
            n_results=3,
            min_score=similarity_threshold
        )
        
        if similar_results:
            old_ids_to_replace = []
            should_skip = False
            
            for r in similar_results:
                # 跳过完全相同的
                if r['content'] == item.content:
                    continue
                
                # 1. 关键词判断
                if mem_mgr.should_replace_keyword(r['content'], item.content, item.memory_type):
                    old_ids_to_replace.append(r['id'])
                    logger.debug(f"[StoreNode.KEYWORD] 替换: {r['content']} -> {item.content}")
                elif use_llm:
                    # 2. LLM 判断
                    decision = await judge_replace_with_llm(
                        r['content'],
                        item.content,
                        item.memory_type.value
                    )
                    
                    if decision == 'replace':
                        old_ids_to_replace.append(r['id'])
                        logger.info(f"[StoreNode.LLM] 替换: {r['content']} -> {item.content}")
                    elif decision == 'keep_old':
                        logger.info(f"[StoreNode.LLM] 保留旧的: {r['content']}")
                        should_skip = True
                        break
                else:
                    # 无 LLM，默认共存
                    logger.debug(f"[StoreNode] 共存: {r['content']} & {item.content}")
            
            if should_skip:
                continue
            
            if old_ids_to_replace:
                mem_mgr.delete_by_ids(old_ids_to_replace)
                logger.info(f"[StoreNode] 删除了 {len(old_ids_to_replace)} 条旧记忆")
        
        items_to_add.append(item)
    
    # 添加新记忆
    if items_to_add:
        return mem_mgr.batch_add(items_to_add)
    return True


async def store_node(state: AgentState) -> dict:
    """
    记忆存储节点：智能处理新记忆的存储

    职责：
    1. 接收 chat 提取的 new_memories
    2. 使用智能方法（关键词 + LLM）判断是否需要替换
    3. 执行存储操作
    4. 返回处理结果

    Args:
        state: 当前状态，包含 new_memories

    Returns:
        {"memory_save_result": dict} 处理结果
    """
    memories = state.get("new_memories", [])
    
    if not memories:
        return {"memory_save_result": {"status": "skipped", "reason": "no_memories"}}

    try:
        from core.long_memory_base import get_memory_manager, MemoryType, MemoryItem
        from datetime import datetime

        mem_mgr = get_memory_manager()

        if not mem_mgr.is_ready:
            logger.warning("[StoreNode] 记忆系统未就绪")
            return {"memory_save_result": {"status": "error", "reason": "not_ready"}}

        # 构建 MemoryItem 列表
        items_to_add = []
        for mem in memories:
            try:
                mtype = MemoryType(mem.memory_type)
                item = MemoryItem(
                    content=mem.content,
                    memory_type=mtype,
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat(),
                    metadata={"source": "llm_extract"}
                )
                items_to_add.append(item)
                logger.info(f"[StoreNode] 待存储: '{mem.content}' ({mem.memory_type})")
            except Exception as e:
                logger.warning(f"[StoreNode] 跳过无效记忆: {e}")

        if not items_to_add:
            return {"memory_save_result": {"status": "skipped", "reason": "all_invalid"}}

        # 智能存储（使用 LLM 判断）
        success = await smart_store(
            mem_mgr=mem_mgr,
            items=items_to_add,
            use_llm=True,
            similarity_threshold=0.5
        )

        if success:
            logger.info(f"[StoreNode] 存储成功: {len(items_to_add)} 条")
            return {
                "memory_save_result": {
                    "status": "success",
                    "count": len(items_to_add)
                }
            }
        else:
            logger.warning("[StoreNode] 存储失败")
            return {"memory_save_result": {"status": "failed", "count": 0}}

    except Exception as e:
        logger.error(f"[StoreNode] 异常: {e}")
        return {"memory_save_result": {"status": "error", "reason": str(e)}}
