"""AgentRunner：LangGraph 图执行器（替代原 AgentLoop 的自研循环）。

对外提供同步、流式和检查点恢复入口：
- run(db, message, session_id, user_id)：同步执行
- iter_run(db, message, session_id, user_id)：边执行边产出 AgentLoopEvent
- resume(db, session_id, user_id)：从失败/中断检查点继续
  生成器返回值为终态 AgentLoopResult（SSE 流式使用）

iter_run 使用 stream_mode="values" 逐节点取得完整状态快照，
通过消息增量和请求级完整结果旁路提取事件，
保证事件顺序与原实现一致：tool_call → tool_result → ... → 终态。
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from sqlalchemy.orm import Session

from app.agent.graph.builder import build_agent_graph
from app.agent.graph.state import (
    AgentRunContext,
    AgentState,
    ResultCollector,
    ToolExecution,
)
from app.agent.memory.artifacts import sqlalchemy_artifact_repository
from app.agent.memory.context import (
    ContextBuilder,
    ContextCache,
    ContextPolicy,
    LongTermMemory,
    NullContextCache,
    scoped_identifier,
)
from app.agent.registry import ToolRegistry
from app.agent.router_llm import LLMIntentRouter
from app.llm.schemas import LLMMessage


@dataclass(frozen=True)
class AgentLoopEvent:
    """循环内部事件，供 SSE 适配层按执行顺序输出。"""

    kind: Literal["tool_call", "tool_result"]
    name: str
    args: dict[str, Any]
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentLoopResult:
    """一次完整推理循环的终态。"""

    reply: str
    executions: list[ToolExecution] = field(default_factory=list)


class AgentRunner:
    """基于 LangGraph StateGraph 的 Agent 推理执行器。"""

    def __init__(
        self,
        registry: ToolRegistry,
        router: LLMIntentRouter | None = None,
        fallback_reply=None,
        max_steps: int = 3,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        context_cache: ContextCache | None = None,
        context_policy: ContextPolicy | None = None,
        artifact_repository_factory=None,
    ) -> None:
        """构造执行器：校验步数并编译 LangGraph 图（router 缺省时新建）。"""
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1.")
        self._router = router or LLMIntentRouter(registry)
        self._checkpointer = checkpointer
        self._store = store
        self._context_policy = context_policy or ContextPolicy()
        self._context_builder = ContextBuilder(
            self._context_policy,
            LongTermMemory(store, context_cache or NullContextCache()),
        )
        self._artifact_repository_factory = (
            artifact_repository_factory or sqlalchemy_artifact_repository
        )
        self._stateful_graph = build_agent_graph(
            registry=registry,
            router=self._router,
            context_builder=self._context_builder,
            context_policy=self._context_policy,
            fallback_reply=fallback_reply,
            max_steps=max_steps,
            checkpointer=checkpointer,
            store=store,
        )
        self._stateless_graph = (
            build_agent_graph(
                registry=registry,
                router=self._router,
                context_builder=self._context_builder,
                context_policy=self._context_policy,
                fallback_reply=fallback_reply,
                max_steps=max_steps,
                store=store,
            )
            if checkpointer is not None
            else self._stateful_graph
        )

    def run(
        self,
        db: Session,
        message: str,
        session_id: str = "",
        user_id: str = "",
    ) -> AgentLoopResult:
        """执行完整推理；session_id 非空时自动恢复该 thread 的历史状态。"""
        graph, config, run_context = self._execution(db, message, session_id, user_id)
        final_state = graph.invoke(
            self._input(message),
            config,
            context=run_context,
        )
        return self._to_result(final_state, run_context)

    def iter_run(
        self,
        db: Session,
        message: str,
        session_id: str = "",
        user_id: str = "",
    ) -> Generator[AgentLoopEvent, None, AgentLoopResult]:
        """边执行边产出 Tool 事件；生成器返回值为最终 AgentLoopResult。"""
        graph, config, run_context = self._execution(db, message, session_id, user_id)
        previous_state = graph.get_state(config) if session_id and self._checkpointer else None
        prev_msg_count = (
            len(previous_state.values.get("messages", [])) if previous_state else 0
        )
        prev_result_count = 0
        final_state: AgentState | None = None
        for update in graph.stream(
            self._input(message),
            config,
            stream_mode="values",
            context=run_context,
        ):
            final_state = update
            yield from self._diff_events(
                update,
                prev_msg_count,
                run_context.collector,
                prev_result_count,
            )
            prev_msg_count = len(update.get("messages", []))
            prev_result_count = len(run_context.collector.executions)
        return self._to_result(final_state, run_context)

    def resume(
        self,
        db: Session,
        session_id: str,
        user_id: str = "",
    ) -> AgentLoopResult:
        """从失败/中断前的最近检查点继续，不追加新的用户消息。"""
        if not session_id or self._checkpointer is None:
            raise ValueError("A persistent session_id is required to resume a thread.")
        graph, config, run_context = self._execution(db, "", session_id, user_id)
        snapshot = graph.get_state(config)
        if not snapshot.next:
            raise ValueError("The thread has no interrupted execution to resume.")
        final_state = graph.invoke(None, config, context=run_context)
        return self._to_result(final_state, run_context)

    @staticmethod
    def _input(message: str) -> dict:
        """只追加当前用户消息；历史由 checkpointer 按 thread_id 恢复。"""
        return {
            "messages": [LLMMessage(role="user", content=message)],
            "executions": [],
            "seen_calls": set(),
            "step": 0,
            "reply": "",
        }

    def _execution(
        self,
        db: Session,
        message: str,
        session_id: str,
        user_id: str,
    ):
        """选择有/无 checkpoint 的图，并构造不持久化的 Runtime 上下文。"""
        persistent = bool(session_id and self._checkpointer is not None)
        thread_id = (
            scoped_identifier(user_id or "anonymous", session_id)
            if session_id
            else scoped_identifier("ephemeral", uuid4().hex)
        )
        config = {"configurable": {"thread_id": thread_id}} if persistent else {}
        collector = ResultCollector(executions=[])
        run_context = AgentRunContext(
            db=db,
            input_message=message,
            thread_id=thread_id,
            user_id=user_id,
            user_id_hash=scoped_identifier(user_id) if user_id else None,
            artifact_repository=self._artifact_repository_factory(db),
            collector=collector,
        )
        graph = self._stateful_graph if persistent else self._stateless_graph
        return graph, config, run_context

    @staticmethod
    def _diff_events(
        update: AgentState,
        prev_msg_count: int,
        collector: ResultCollector,
        prev_result_count: int,
    ) -> list[AgentLoopEvent]:
        """对比状态快照，提取新增消息/执行对应的增量事件。"""
        events: list[AgentLoopEvent] = []
        messages = update.get("messages", [])
        for msg in messages[prev_msg_count:]:
            if msg.role == "assistant":
                for call in msg.tool_calls:
                    events.append(
                        AgentLoopEvent(
                            kind="tool_call",
                            name=call.name,
                            args=call.arguments,
                        )
                    )
        for execution in collector.executions[prev_result_count:]:
            events.append(
                AgentLoopEvent(
                    kind="tool_result",
                    name=execution.name,
                    args=execution.args,
                    result=execution.result,
                )
            )
        return events

    @staticmethod
    def _to_result(
        final_state: AgentState | None,
        run_context: AgentRunContext,
    ) -> AgentLoopResult:
        """终态快照 → AgentLoopResult（空状态时返回空回复）。"""
        if final_state is None:
            return AgentLoopResult(reply="", executions=[])
        executions = list(run_context.collector.executions)
        collected_ids = {execution.artifact_id for execution in executions}
        for checkpoint_execution in final_state.get("executions", []):
            if checkpoint_execution.artifact_id in collected_ids:
                continue
            payload = run_context.artifact_repository.get(
                checkpoint_execution.artifact_id,
                run_context.thread_id,
            )
            if payload is not None:
                executions.append(
                    ToolExecution(
                        name=checkpoint_execution.name,
                        args=checkpoint_execution.args,
                        result=payload,
                        artifact_id=checkpoint_execution.artifact_id,
                    )
                )
        return AgentLoopResult(reply=final_state.get("reply", ""), executions=executions)

    def get_state(self, session_id: str, user_id: str = ""):
        """读取指定会话的最新检查点，供恢复、调试和测试使用。"""
        if not session_id or self._checkpointer is None:
            return None
        config = {
            "configurable": {
                "thread_id": scoped_identifier(user_id or "anonymous", session_id)
            }
        }
        return self._stateful_graph.get_state(config)

    def get_state_history(self, session_id: str, user_id: str = ""):
        """返回 LangGraph checkpoint 历史迭代器。"""
        if not session_id or self._checkpointer is None:
            return iter(())
        config = {
            "configurable": {
                "thread_id": scoped_identifier(user_id or "anonymous", session_id)
            }
        }
        return self._stateful_graph.get_state_history(config)
