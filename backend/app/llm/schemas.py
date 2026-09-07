"""LLM 层数据载体（Stage 4）。

LLMMessage / LLMToolCall / LLMResponse 是 LLMClient 与 Agent 编排层之间的
统一数据结构，与具体厂商 API 格式解耦。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMToolCall(BaseModel):
    """LLM 生成的函数调用：工具名 + 参数（已解析为 dict）。"""

    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="仅供 Agent 内部维护任务上下文，不发送给 Tool 或模型服务。",
    )


class LLMMessage(BaseModel):
    """Provider-neutral 对话消息，支持标准 Function Calling 回填。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)


class LLMResponse(BaseModel):
    """LLM 一次调用的统一结果：直接文本回复或工具调用（可同时存在）。"""

    text: str = ""
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
