"""Agent 图构建器：把节点组装成编译后的 LangGraph StateGraph。

图结构（有向环，步数上限由 call_model 节点保证）：

    START → call_model ──有工具调用──→ execute_tools ──→ call_model
                        └──无工具调用──→ summarize_context → END

build_agent_graph 返回编译后的图对象，调用方（AgentRunner）通过
graph.invoke / graph.stream 驱动执行；thread_id 通过 configurable 提供，
数据库、原始输入和 artifact 仓储通过不持久化的 Runtime context 注入。
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from app.agent.graph.nodes import (
    ROUTE_END,
    ROUTE_EXECUTE,
    make_call_model_node,
    make_execute_tools_node,
    make_summarize_context_node,
    route_after_model,
)
from app.agent.graph.state import AgentRunContext, AgentState
from app.agent.memory.context import ContextBuilder, ContextPolicy
from app.agent.registry import ToolRegistry
from app.agent.router_llm import LLMIntentRouter

# 模型调用节点名（图内固定标识）
_NODE_CALL_MODEL = "call_model"
# 工具执行节点名（图内固定标识）
_NODE_EXECUTE_TOOLS = "execute_tools"
_NODE_SUMMARIZE_CONTEXT = "summarize_context"


def build_agent_graph(
    registry: ToolRegistry,
    router: LLMIntentRouter,
    context_builder: ContextBuilder,
    context_policy: ContextPolicy,
    fallback_reply: Callable[[str, dict], str],
    max_steps: int = 3,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
):
    """构建并编译 Agent 图，返回 CompiledStateGraph。

    参数与节点闭包绑定（构造期固定）；请求级依赖由 Runtime context 提供。
    """
    graph = StateGraph(AgentState, context_schema=AgentRunContext)
    graph.add_node(
        _NODE_CALL_MODEL,
        make_call_model_node(router, context_builder, fallback_reply, max_steps),
    )
    graph.add_node(
        _NODE_EXECUTE_TOOLS,
        make_execute_tools_node(registry, context_policy),
    )
    graph.add_node(
        _NODE_SUMMARIZE_CONTEXT,
        make_summarize_context_node(context_builder),
    )
    graph.add_edge(START, _NODE_CALL_MODEL)
    graph.add_conditional_edges(
        _NODE_CALL_MODEL,
        route_after_model,
        {
            ROUTE_EXECUTE: _NODE_EXECUTE_TOOLS,
            ROUTE_END: _NODE_SUMMARIZE_CONTEXT,
        },
    )
    graph.add_edge(_NODE_EXECUTE_TOOLS, _NODE_CALL_MODEL)
    graph.add_edge(_NODE_SUMMARIZE_CONTEXT, END)
    return graph.compile(checkpointer=checkpointer, store=store)
