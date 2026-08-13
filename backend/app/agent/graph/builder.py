"""Agent 图构建器：把节点组装成编译后的 LangGraph StateGraph。

图结构（有向环，步数上限由 call_model 节点保证）：

    START → call_model ──有工具调用──→ execute_tools ──→ call_model
                        └──无工具调用──→ END

build_agent_graph 返回编译后的图对象，调用方（AgentRunner）通过
graph.invoke / graph.stream 驱动执行；请求级依赖（db / 原始输入）
由调用方通过 config["configurable"] 注入。
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from app.agent.graph.nodes import (
    ROUTE_END,
    ROUTE_EXECUTE,
    make_call_model_node,
    make_execute_tools_node,
    route_after_model,
)
from app.agent.graph.state import AgentState
from app.agent.registry import ToolRegistry
from app.agent.router_llm import LLMIntentRouter

# 模型调用节点名（图内固定标识）
_NODE_CALL_MODEL = "call_model"
# 工具执行节点名（图内固定标识）
_NODE_EXECUTE_TOOLS = "execute_tools"


def build_agent_graph(
    registry: ToolRegistry,
    router: LLMIntentRouter,
    fallback_reply: Callable[[str, dict], str],
    max_steps: int = 3,
):
    """构建并编译 Agent 图，返回 CompiledStateGraph。

    参数与节点闭包绑定（构造期固定）；数据库会话不在此绑定，
    由每次执行的 config["configurable"]["db"] 提供。
    """
    graph = StateGraph(AgentState)
    graph.add_node(_NODE_CALL_MODEL, make_call_model_node(router, fallback_reply, max_steps))
    graph.add_node(_NODE_EXECUTE_TOOLS, make_execute_tools_node(registry))
    graph.add_edge(START, _NODE_CALL_MODEL)
    graph.add_conditional_edges(
        _NODE_CALL_MODEL,
        route_after_model,
        {ROUTE_EXECUTE: _NODE_EXECUTE_TOOLS, ROUTE_END: END},
    )
    graph.add_edge(_NODE_EXECUTE_TOOLS, _NODE_CALL_MODEL)
    return graph.compile()
