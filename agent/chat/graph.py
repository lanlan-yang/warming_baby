"""
agent/chat/graph.py - LangGraph 组装

使用 LangGraph v1.0+ API 组装 ReAct (Reasoning + Acting) 图。

图结构：
        START → agent_node → [有 tool_calls?] → tools_node → agent_node (循环)
                           → [无 tool_calls?] → format_node → memory_node → END

职责：
    1. 定义图结构（节点和边）
    2. 编译图（返回 CompiledGraph）
    3. 提供 run() 和 run_chat() 方法供外部调用
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END

from core.logger import setup_logger
from tools.tool_base import tool_registry
from .state import ChatState
from .nodes import (
    create_agent_node,
    CustomToolNode,
    create_format_node,
    create_memory_node,
    route_tools,
)
from .chat_schema import ChatResponse

logger = setup_logger()


class ChatGraph:
    """
    Chat Graph - 对话图

    封装 LangGraph 的创建和调用逻辑。
    工具通过 ToolRegistry 自动获取，记忆存储由 memory_node 自动处理。

    使用示例：
        graph = ChatGraph(llm=my_llm)
        result = await graph.run(messages)  # 返回 dict{"messages": [...]}
    """

    def __init__(
        self,
        llm: BaseChatModel,
        max_iterations: int = 5,
    ):
        """
        初始化 ChatGraph

        Args:
            llm: LangChain ChatModel 实例
            max_iterations: 最大循环次数（防止死循环）
        """
        self.llm = llm
        self.tools = tool_registry.get_tools()
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
                               → [无 tool_calls?] → format_node → memory_node → END

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
        memory_node = create_memory_node()

        # 5. 添加节点到图
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("format", format_node)
        workflow.add_node("memory", memory_node)

        # 6. 添加边
        workflow.add_edge(START, "agent")

        workflow.add_conditional_edges(
            "agent",
            route_tools,
            {
                "tools": "tools",
                "format": "format",
            },
        )

        workflow.add_edge("tools", "agent")
        workflow.add_edge("format", "memory")
        workflow.add_edge("memory", END)

        # 7. 编译图
        compiled_graph = workflow.compile()

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

        logger.info(f"[ChatGraph] 开始运行，初始消息数={len(messages)}")

        result = await self.graph.ainvoke(initial_state)

        logger.info(
            f"[ChatGraph] 运行完成，"
            f"总消息数={len(result['messages'])}, 迭代次数={result['iteration']}"
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

    def refresh_tools(self) -> None:
        """
        刷新工具列表（从 ToolRegistry 获取最新工具，重新构建图）

        当新工具注册后调用此方法。
        """
        self.tools = tool_registry.get_tools()
        self.graph = self._build_graph()
        logger.info(f"[ChatGraph] 工具已刷新，当前工具数: {len(self.tools)}")
