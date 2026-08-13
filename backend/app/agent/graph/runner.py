"""AgentRunner：LangGraph 图执行器（替代原 AgentLoop 的自研循环）。

对外接口与原 AgentLoop 完全一致，AgentService 无需感知内部实现：
- run(db, message, history)：同步执行，返回终态 AgentLoopResult
- iter_run(db, message, history)：生成器，边执行边产出 AgentLoopEvent，
  生成器返回值为终态 AgentLoopResult（SSE 流式使用）

iter_run 使用 stream_mode="values" 逐节点取得完整状态快照，
通过与上一快照的 messages / executions 长度差提取增量事件，
保证事件顺序与原实现一致：tool_call → tool_result → ... → 终态。
"""

from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.agent.graph.builder import build_agent_graph
from app.agent.graph.state import AgentState, ToolExecution
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
    ) -> None:
        """构造执行器：校验步数并编译 LangGraph 图（router 缺省时新建）。"""
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1.")
        self._router = router or LLMIntentRouter(registry)
        self._graph = build_agent_graph(
            registry=registry,
            router=self._router,
            fallback_reply=fallback_reply,
            max_steps=max_steps,
        )

    def run(
        self,
        db: Session,
        message: str,
        history: list[LLMMessage] | None = None,
    ) -> AgentLoopResult:
        """执行完整推理并返回终态；同步 API 使用此入口。"""
        final_state = self._graph.invoke(
            self._input(message, history),
            self._config(db, message),
        )
        return self._to_result(final_state)

    def iter_run(
        self,
        db: Session,
        message: str,
        history: list[LLMMessage] | None = None,
    ) -> Generator[AgentLoopEvent, None, AgentLoopResult]:
        """边执行边产出 Tool 事件；生成器返回值为最终 AgentLoopResult。"""
        prev_msg_count = 0
        prev_exec_count = 0
        final_state: AgentState | None = None
        for update in self._graph.stream(
            self._input(message, history),
            self._config(db, message),
            stream_mode="values",
        ):
            final_state = update
            yield from self._diff_events(update, prev_msg_count, prev_exec_count)
            prev_msg_count = len(update.get("messages", []))
            prev_exec_count = len(update.get("executions", []))
        return self._to_result(final_state)

    def _input(self, message: str, history: list[LLMMessage] | None) -> dict:
        """构造图输入：完整消息流 + 初始空状态。"""
        return {
            "messages": self._router.build_messages(message, history),
            "executions": [],
            "seen_calls": set(),
            "step": 0,
            "reply": "",
        }

    @staticmethod
    def _config(db: Session, message: str) -> dict:
        """构造图执行配置：注入请求级数据库会话与原始用户输入。"""
        return {"configurable": {"db": db, "input_message": message}}

    @staticmethod
    def _diff_events(
        update: AgentState,
        prev_msg_count: int,
        prev_exec_count: int,
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
        executions = update.get("executions", [])
        for execution in executions[prev_exec_count:]:
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
    def _to_result(final_state: AgentState | None) -> AgentLoopResult:
        """终态快照 → AgentLoopResult（空状态时返回空回复）。"""
        if final_state is None:
            return AgentLoopResult(reply="", executions=[])
        return AgentLoopResult(
            reply=final_state.get("reply", ""),
            executions=final_state.get("executions", []),
        )
