"""Agent 图状态定义（LangGraph StateGraph 的状态通道）。

AgentState 是节点之间传递的全部数据：
- messages：完整对话消息流（使用 operator.add 作为 reducer，
  节点只返回新增消息，LangGraph 自动追加到历史）
- executions：已执行工具调用记录（execute_tools 节点整体覆盖）
- seen_calls：已见工具调用签名集合（防止 LLM 重复调用死循环）
- step：模型调用步数（达到 max_steps 后强制终止）
- reply：终态回复文本（由 call_model 节点写入）

ToolExecution 记录一次工具调用的名称、参数与结构化结果，
是 AgentRunner 事件流与终态结果共用的数据结构。
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from app.llm.schemas import LLMMessage


@dataclass(frozen=True)
class ToolExecution:
    """一次已经完成的工具调用及其结构化结果。"""

    name: str
    args: dict[str, Any]
    result: dict[str, Any]


class AgentState(TypedDict):
    """LangGraph Agent 状态：消息流 + 执行记录 + 循环控制字段。"""

    messages: Annotated[list[LLMMessage], operator.add]
    executions: list[ToolExecution]
    seen_calls: set[str]
    step: int
    reply: str
