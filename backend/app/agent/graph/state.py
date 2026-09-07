"""Agent 图状态定义（LangGraph StateGraph 的状态通道）。

AgentState 是节点之间传递并由 checkpointer 保存的数据：
- messages：最近原始消息（更早信息进入结构化摘要）
- executions：本轮已执行工具的安全摘要和 artifact 引用
- seen_calls：已见工具调用签名集合（防止 LLM 重复调用死循环）
- step：模型调用步数（达到 max_steps 后强制终止）
- reply：终态回复文本（由 call_model 节点写入）
- summary / task_context：压缩摘要与结构化任务状态

完整工具结果只存在于请求级 ResultCollector 与 artifact 仓储，不写入 checkpoint。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from app.agent.memory.artifacts import ArtifactRepository
from app.agent.memory.models import (
    ConversationSummary,
    TaskContext,
    merge_recent_messages,
)
from app.llm.schemas import LLMMessage


@dataclass(frozen=True)
class ToolExecution:
    """一次工具调用；result 在检查点中必须是 ContextPolicy 摘要。"""

    name: str
    args: dict[str, Any]
    result: dict[str, Any]
    artifact_id: str = ""


@dataclass
class ResultCollector:
    """请求级完整结果旁路，不写入 LangGraph checkpoint。"""

    executions: list[ToolExecution]


@dataclass
class AgentRunContext:
    """不持久化的请求级依赖，通过 LangGraph Runtime 注入节点。"""

    db: Any
    input_message: str
    thread_id: str
    user_id: str
    user_id_hash: str | None
    artifact_repository: ArtifactRepository
    collector: ResultCollector


class AgentState(TypedDict, total=False):
    """LangGraph Agent 状态：消息流 + 执行记录 + 循环控制字段。"""

    messages: Annotated[list[LLMMessage], merge_recent_messages]
    executions: list[ToolExecution]
    seen_calls: set[str]
    step: int
    reply: str
    summary: ConversationSummary
    task_context: TaskContext
    artifact_refs: list[str]
    context_version: int
