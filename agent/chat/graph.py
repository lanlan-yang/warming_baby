"""
agent/chat/graph.py - LangGraph 组装

使用 LangGraph v1.0+ API 组装 ReAgent (Reasoning + Acting) 图。

图结构：
    START → agent_node → [有 tool_calls?] → tools_node → agent_node (循环)
                       → [无 tool_calls?] → format_node → END

职责：
    1. 定义图结构（节点和边）
    2. 编译图（返回 CompiledGraph）
    3. 提供 run() 和 run_chat() 方法供外部调用
"""

import os

# 禁用 LangGraph msgpack 严格模式警告
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "false")

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from core.logger import setup_logger
from tools.tool_base import AgentTool
from .state import ChatState
from .nodes import (
    create_agent_node,
    CustomToolNode,
    create_format_node,
    route_tools,
)
from .chat_schema import ChatResponse

logger = setup_logger()


class ChatGraph:
    """
    Chat Graph - 对话图

    封装 LangGraph 的创建和调用逻辑。
    
    使用示例：
        graph = ChatGraph(llm=my_llm, tools=[weather_tool])
        result = await graph.run(messages)  # 返回 dict{"messages": [...]}
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: Optional[list[AgentTool]] = None,
        max_iterations: int = 5,
    ):
        """
        初始化 ChatGraph

        Args:
            llm: LangChain ChatModel 实例
            tools: 工具列表
            max_iterations: 最大循环次数（防止死循环）
        """
        self.llm = llm
        self.tools = tools or []
        self.max_iterations = max_iterations

        # 构建并编译图
        self.graph = self._build_graph()

        logger.info(
            f"[ChatGraph] 初始化完成，工具数: {len(self.tools)}, "
            f"最大迭代次数: {self.max_iterations}"
        )

    def _build_graph(self):
        """
        构建并编译 LangGraph

        图结构：
            START → agent_node → [有 tool_calls?] → tools_node → agent_node (循环)
                               → [无 tool_calls?] → format_node → END

        Returns:
            CompiledGraph: 编译后的图
        """
        # 1. 创建 StateGraph
        workflow = StateGraph(ChatState)

        # 2. 绑定工具到 LLM（集中在 graph 层处理）
        if self.tools:
            bound_llm = self.llm.bind_tools(self.tools)
            logger.info(f"[ChatGraph] LLM 已绑定 {len(self.tools)} 个工具")
        else:
            bound_llm = self.llm
            logger.info("[ChatGraph] 无工具绑定")

        # 3. 为 FormatNode 创建禁用 thinking 的 LLM（解决 tool_choice 不兼容问题）
        try:
            from providers import get_llm
            from core.enums import ModelTask
            
            # 获取与主 LLM 相同的配置，但禁用 thinking
            format_llm = get_llm(
                task=ModelTask.CHAT, 
                thinking_enabled=False
            )
            logger.info("[ChatGraph] FormatNode 使用禁用 thinking 的 LLM")
        except Exception as e:
            logger.warning(f"[ChatGraph] 无法创建 format_llm: {e}, 使用主 LLM")
            format_llm = self.llm

        # 4. 创建节点（使用闭包绑定依赖）
        agent_node = create_agent_node(llm=bound_llm)
        tools_node = CustomToolNode(self.tools)
        format_node = create_format_node(llm=format_llm)

        # 5. 添加节点到图
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("format", format_node)

        # 6. 添加边
        # START → agent
        workflow.add_edge(START, "agent")

        # agent → [tools 或 format] (条件分支)
        workflow.add_conditional_edges(
            "agent",
            route_tools,
            {
                "tools": "tools",
                "format": "format",
            },
        )

        # tools → agent (循环)
        workflow.add_edge("tools", "agent")

        # format → END
        workflow.add_edge("format", END)

        # 6. 创建 MemorySaver 并配置允许的模块
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        
        # 配置允许的 msgpack 类型
        serde = JsonPlusSerializer().with_msgpack_allowlist([
            ("agent.chat.chat_schema", "ChatResponse"),
            ("agent.chat.chat_schema", "Emotion"),
            ("agent.chat.chat_schema", "MemoryExtract"),
        ])
        
        # 创建带配置的 MemorySaver
        checkpointer = MemorySaver(serde=serde)

        # 7. 编译图
        compiled_graph = workflow.compile(checkpointer=checkpointer)

        logger.info("[ChatGraph] 图构建完成")
        return compiled_graph

    async def run(
        self,
        messages: list,
    ) -> dict:
        """
        运行图（返回原始 state dict）

        Args:
            messages: 初始消息列表 [SystemMessage, HumanMessage, ...]

        Returns:
            dict: 包含最终 state 的结果
                {
                    "messages": [...],  # 所有消息（包括工具调用结果）
                    "iteration": 3,      # 实际迭代次数
                    "final_response": ChatResponse,  # 最终响应
                }
        """
        initial_state = {
            "messages": messages,
            "max_iterations": self.max_iterations,
            "iteration": 0,
        }

        logger.info(
            f"[ChatGraph] 开始运行，初始消息数: {len(messages)}"
        )

        result = await self.graph.ainvoke(initial_state)

        logger.info(
            f"[ChatGraph] 运行完成，总消息数: {len(result['messages'])}, "
            f"迭代次数: {result['iteration']}"
        )

        return result

    async def run_chat(
        self,
        messages: list[BaseMessage],
    ) -> ChatResponse:
        """
        运行图并直接返回 ChatResponse

        Args:
            messages: 初始消息列表 [SystemMessage, HumanMessage, ...]

        Returns:
            ChatResponse: 结构化的聊天响应（由 format 节点生成）
        """
        try:
            result = await self.run(messages)
            
            final_response = result.get("final_response")
            if final_response is None:
                logger.warning("[ChatGraph] final_response 为空")
                return ChatResponse(
                    text="抱歉，我处理你的消息时遇到了问题...",
                    emotion="neutral",
                )
            
            return final_response
            
        except Exception as e:
            logger.error(f"[ChatGraph] run_chat 失败: {e}")
            return ChatResponse(
                text="抱歉，我处理你的消息时遇到了问题...",
                emotion="neutral",
            )

    def update_tools(self, tools: list[AgentTool]) -> None:
        """
        更新工具列表（需要重新构建图）

        Args:
            tools: 新的工具列表
        """
        self.tools = tools
        self.graph = self._build_graph()
        logger.info(f"[ChatGraph] 工具更新完成，新工具数: {len(self.tools)}")
