"""Agent 输入输出结构（Stage 3）。

POST /api/agent/chat 的请求与响应模型：
    请求: {message: str}
    响应: {reply: str, tool_calls: [{tool, args}], map_layers: [{type, data}]}
外层统一由 ApiResponse{code, message, data} 包裹。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Agent 对话请求：一条自然语言消息 + 可选会话 ID（多轮记忆）。"""

    message: str = Field(min_length=1, max_length=500, description="用户输入的自然语言消息")
    session_id: str = Field(default="", max_length=64, description="会话 ID（多轮记忆用；为空则不启用记忆）")
    user_id: str = Field(default="", max_length=64, description="用户 ID（用于隔离跨会话长期偏好）")


class ResumeRequest(BaseModel):
    """恢复失败或中断 thread 的请求。"""

    session_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(default="", max_length=64)


class ToolCallInfo(BaseModel):
    """一次工具调用的记录：工具名 + 实际参数。"""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    artifact_id: str = ""


class MapLayer(BaseModel):
    """地图图层描述：前端 MapLayerRenderer 按 type 分派到对应图层模块。"""

    type: Literal["heatmap", "poi", "trajectory"]
    data: list[dict[str, Any]] = Field(default_factory=list)


class AgentArtifact(BaseModel):
    """可由前端直接消费的结构化 Tool 产物。"""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Agent 对话响应：LLM 总结 + 工具记录 + 地图图层 + 结构化产物。"""

    reply: str
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)
    map_layers: list[MapLayer] = Field(default_factory=list)
    artifacts: list[AgentArtifact] = Field(default_factory=list)


class ArtifactResponse(BaseModel):
    """按会话权限读取的完整工具结果。"""

    artifact_id: str
    data: dict[str, Any]
