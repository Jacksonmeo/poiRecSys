"""Agent 对话 API（Stage 3 + Stage 4）：LLM Function Calling + SSE 流式。

POST /api/agent/chat：非流式，返回 {reply, tool_calls, map_layers}。
POST /api/agent/chat/stream：SSE 流式（tool_call → tool_result → text → done）。
回复组装与工具执行全部委托给 agent_service，本层不做业务逻辑。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.schemas import ChatRequest, ChatResponse
from app.agent.service import AgentService
from app.agent.stream import ChatStreamEvent, sse_format
from app.api.dependencies.agent import get_agent_service
from app.core.response import ApiResponse

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
        data=service.chat(message=req.message, session_id=req.session_id)
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
                message=req.message, session_id=req.session_id
            ):
                yield sse_format(event)
        except ValueError as exc:
            yield sse_format(ChatStreamEvent(kind="error", payload={"message": str(exc)}))

    return StreamingResponse(generate(), media_type="text/event-stream")
