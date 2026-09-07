"""Agent 图节点：模型调用、工具执行与路由决策。

节点职责划分：
- make_call_model_node：调用 LLM（不可用/输出非法时降级规则路由），
  产出「终态回复」或「带工具调用的 assistant 消息」，并做步数与去重保护
- make_execute_tools_node：执行最新 assistant 消息里的全部工具调用，
  完整结果落 artifact 仓储，只把安全摘要回填模型与 checkpoint
- make_summarize_context_node：维护结构化会话摘要和明确的长期偏好
- route_after_model：判断最新消息是否携带待执行工具调用，决定走向

节点通过闭包持有 router / registry / fallback_reply / max_steps；
请求级依赖（数据库、原始输入、完整结果旁路）通过 Runtime 注入。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from langgraph.runtime import Runtime

from app.agent.graph.state import AgentRunContext, AgentState, ToolExecution
from app.agent.memory.context import ContextBuilder, ContextPolicy
from app.agent.memory.models import (
    TaskContext,
    merge_artifact_refs,
    update_conversation_summary,
    update_task_context,
)
from app.agent.registry import AgentTool, ToolRegistry
from app.agent.router_llm import LLMIntentRouter
from app.llm.schemas import LLMMessage, LLMToolCall

# 路由决策：有未执行工具调用时进入工具执行节点
ROUTE_EXECUTE = "execute_tools"
# 路由决策：无工具调用时结束
ROUTE_END = "end"


def make_call_model_node(
    router: LLMIntentRouter,
    context_builder: ContextBuilder,
    fallback_reply: Callable[[str, dict], str],
    max_steps: int,
) -> Callable[[AgentState, Runtime[AgentRunContext]], dict[str, Any]]:
    """构造模型调用节点：LLM 推理 + 步数/去重保护 + 终态判定。

    - 步数达到上限：直接产出基于已执行结果的兜底回复
    - LLM 未返回工具调用：产出文本回复（空文本时用兜底回复）
    - 工具调用签名与历史重复：判定死循环，产出兜底回复
    - 其余情况：产出带工具调用的 assistant 消息，交由 execute_tools 执行
    """
    fallback = _fallback_factory(fallback_reply)
    tool_schema_tokens = context_builder.estimate_tokens(
        json.dumps(router.tools_schema(), ensure_ascii=False, default=str)
    )

    def _node(
        state: AgentState,
        runtime: Runtime[AgentRunContext],
    ) -> dict[str, Any]:
        """节点实现：按步数/去重保护执行一次模型推理并产出状态更新。"""
        step = state.get("step", 0)
        executions = state.get("executions", [])
        if step >= max_steps:
            return {"reply": fallback(executions), "step": step + 1}
        input_message = runtime.context.input_message
        messages = context_builder.build(
            messages=state.get("messages", []),
            summary=state.get("summary"),
            task_context=state.get("task_context"),
            user_id=runtime.context.user_id,
            reserved_tokens=tool_schema_tokens,
        )
        response = router.chat(messages, fallback_message=input_message)
        if not response.tool_calls:
            reply = response.text.strip() or fallback(executions)
            return {
                "reply": reply,
                "messages": [LLMMessage(role="assistant", content=reply)],
                "step": step + 1,
            }
        calls = response.tool_calls
        if _repeat_calls(calls, state.get("seen_calls", set())):
            return {"reply": fallback(executions), "step": step + 1}
        assistant_message = LLMMessage(
            role="assistant",
            content=response.text,
            tool_calls=calls,
        )
        return {"messages": [assistant_message], "step": step + 1}

    return _node


def make_execute_tools_node(
    registry: ToolRegistry,
    context_policy: ContextPolicy,
) -> Callable[[AgentState, Runtime[AgentRunContext]], dict[str, Any]]:
    """构造工具执行节点：按序执行 assistant 消息中的全部工具调用。

    每个调用：注册表校验 → 工具参数校验与执行 → 回填 tool 结果消息。
    结果消息内容为结果的 JSON 序列化，供下一轮模型调用读取。
    """
    def _node(
        state: AgentState,
        runtime: Runtime[AgentRunContext],
    ) -> dict[str, Any]:
        """节点实现：执行全部工具调用并回填结果消息。"""
        db = runtime.context.db
        messages = list(state["messages"])
        calls = messages[-1].tool_calls
        tool_messages: list[LLMMessage] = []
        executions = list(state.get("executions", []))
        seen_calls = set(state.get("seen_calls", set()))
        task_context = cast(TaskContext, dict(state.get("task_context", {})))
        artifact_refs = list(state.get("artifact_refs", []))
        context_version = state.get("context_version", 0)
        for call in calls:
            tool = _require_tool(registry, call.name)
            result = tool.run(db, call.arguments)
            artifact_id = runtime.context.artifact_repository.save(
                thread_id=runtime.context.thread_id,
                user_id_hash=runtime.context.user_id_hash,
                tool_name=call.name,
                payload=result,
            )
            model_result = context_policy.summarize_tool_result(
                call.name,
                result,
                artifact_id,
            )
            executions.append(
                ToolExecution(
                    name=call.name,
                    args=call.arguments,
                    result=model_result,
                    artifact_id=artifact_id,
                )
            )
            runtime.context.collector.executions.append(
                ToolExecution(
                    name=call.name,
                    args=call.arguments,
                    result=result,
                    artifact_id=artifact_id,
                )
            )
            seen_calls.add(_call_signature(call))
            task_context = update_task_context(
                task_context,
                call,
                model_result,
                artifact_id,
            )
            artifact_refs = merge_artifact_refs(artifact_refs, artifact_id)
            context_version += 1
            tool_messages.append(
                LLMMessage(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=json.dumps(model_result, ensure_ascii=False, default=str),
                )
            )
        return {
            "messages": tool_messages,
            "executions": executions,
            "seen_calls": seen_calls,
            "task_context": task_context,
            "artifact_refs": artifact_refs,
            "context_version": context_version,
        }

    return _node


def make_summarize_context_node(
    context_builder: ContextBuilder,
) -> Callable[[AgentState, Runtime[AgentRunContext]], dict[str, Any]]:
    """构造终态摘要节点，并只记忆用户明确表达的长期偏好。"""

    def _node(
        state: AgentState,
        runtime: Runtime[AgentRunContext],
    ) -> dict[str, Any]:
        executions = [
            {
                "name": execution.name,
                "artifact_id": execution.artifact_id,
                "result": execution.result,
            }
            for execution in state.get("executions", [])
        ]
        summary = update_conversation_summary(
            state.get("summary"),
            executions,
            state.get("task_context"),
            runtime.context.input_message,
        )
        context_builder.long_term_memory.remember_explicit(
            runtime.context.user_id,
            runtime.context.input_message,
            state.get("task_context"),
        )
        return {"summary": summary}

    return _node


def route_after_model(state: AgentState) -> str:
    """路由决策：最新消息带工具调用则执行工具，否则结束。"""
    messages = state.get("messages", [])
    if messages and messages[-1].tool_calls:
        return ROUTE_EXECUTE
    return ROUTE_END


def _fallback_factory(
    fallback_reply: Callable[[str, dict], str],
) -> Callable[[list[ToolExecution]], str]:
    """把 (tool_name, result) 形式的回复函数适配为 (executions) 形式。

    无执行记录时调用 fallback_reply("", {})，否则用最后一次执行的结果。
    """

    def _build(executions: list[ToolExecution]) -> str:
        """按执行记录生成兜底回复；无记录时使用空参数模板。"""
        if not executions:
            return fallback_reply("", {})
        last = executions[-1]
        return fallback_reply(last.name, last.result)

    return _build


def _repeat_calls(calls: list[LLMToolCall], seen_calls: set[str]) -> bool:
    """判断本次工具调用是否全部与历史重复（LLM 死循环保护）。"""
    signatures = {_call_signature(call) for call in calls}
    return bool(signatures & seen_calls)


def _require_tool(registry: ToolRegistry, name: str) -> AgentTool:
    """从注册表取工具，未注册时抛 RuntimeError（保护并发注册表修改）。"""
    tool = registry.get(name)
    if tool is None:
        raise RuntimeError(f"Agent tool '{name}' is not registered.")
    return tool


def _call_signature(call: LLMToolCall) -> str:
    """生成工具调用的去重签名（名称 + 排序后的参数 JSON）。"""
    return f"{call.name}:{json.dumps(call.arguments, sort_keys=True, default=str)}"
