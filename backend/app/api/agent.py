"""Agent 对话 API（Stage 3 + Stage 4）：LLM Function Calling + SSE 流式。

POST /api/agent/chat：非流式，返回 {reply, tool_calls, map_layers}。
POST /api/agent/chat/stream：SSE 流式（tool_call → tool_result → text → done）。
回复组装与工具执行全部委托给 agent_service，本层不做业务逻辑。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent.memory import AgentContextRuntime, get_agent_context_runtime
from app.agent.memory.context import scoped_identifier
from app.agent.memory.runtime import ThreadBusyError
from app.agent.schemas import ArtifactResponse, ChatRequest, ChatResponse, ResumeRequest
from app.agent.service import AgentService
from app.agent.stream import ChatStreamEvent, sse_format
from app.api.dependencies.agent import get_agent_service
from app.core.response import ApiResponse
from app.db.database import get_db

router = APIRouter()


@router.post("/chat", response_model=ApiResponse[ChatResponse])
def agent_chat(
    req: ChatRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> ApiResponse[ChatResponse]:
    """自然语言 → LLM 意图路由（降级规则）→ 工具执行 → 回复 + 地图图层描述。"""
    if not req.message.strip():
        raise HTTPException(status_code=422, detail="message cannot be empty.")
    return ApiResponse(
        data=service.chat(
            message=req.message,
            session_id=req.session_id,
            user_id=req.user_id,
        )
    )


@router.post("/chat/stream", response_class=StreamingResponse)
def agent_chat_stream(
    req: ChatRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> StreamingResponse:
    """SSE 流式对话：tool_call → tool_result → text → done 事件流。

    工具校验失败（422 语义）以 error 事件下发（HTTP 保持 200，错误走事件通道）。
    """
    if not req.message.strip():
        raise HTTPException(status_code=422, detail="message cannot be empty.")

    def generate():
        """SSE 事件生成器：转发服务事件流，工具校验错误转 error 事件。"""
        try:
            for event in service.chat_stream(
                message=req.message,
                session_id=req.session_id,
                user_id=req.user_id,
            ):
                yield sse_format(event)
        except ValueError as exc:
            yield sse_format(ChatStreamEvent(kind="error", payload={"message": str(exc)}))
        except ThreadBusyError as exc:
            yield sse_format(ChatStreamEvent(kind="error", payload={"message": str(exc)}))

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/chat/resume", response_model=ApiResponse[ChatResponse])
def resume_agent_chat(
    req: ResumeRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> ApiResponse[ChatResponse]:
    """从失败/中断前的最近 LangGraph checkpoint 继续。"""
    return ApiResponse(
        data=service.resume(session_id=req.session_id, user_id=req.user_id)
    )


@router.get("/artifacts/{artifact_id}", response_model=ApiResponse[ArtifactResponse])
def get_agent_artifact(
    artifact_id: str,
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    context_runtime: Annotated[
        AgentContextRuntime,
        Depends(get_agent_context_runtime),
    ],
    user_id: str = "",
) -> ApiResponse[ArtifactResponse]:
    """按脱敏后的 user/session thread 边界读取完整工具结果。"""
    thread_id = scoped_identifier(user_id or "anonymous", session_id)
    repository = context_runtime.artifact_repository_factory(db)
    payload = repository.get(artifact_id, thread_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Artifact 不存在或无权访问。")
    return ApiResponse(data=ArtifactResponse(artifact_id=artifact_id, data=payload))
