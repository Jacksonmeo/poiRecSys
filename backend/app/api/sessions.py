"""Session trajectory APIs backed by PostgreSQL.
会话轨迹 API，提供单个会话的详细轨迹点查询。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.response import ApiResponse
from app.db.database import get_db
from app.schemas.user_trajectory import (
    SessionSummaryResponse,
    SessionTrajectoryResponse,
    TrajectoryPointResponse,
)
from app.services.session_service import get_session_by_id, get_session_points

router = APIRouter()


@router.get("/{session_id}/trajectory", response_model=ApiResponse[SessionTrajectoryResponse])
def get_session_trajectory(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ApiResponse[SessionTrajectoryResponse]:
    """返回指定会话的完整轨迹，包含会话摘要和按顺序排列的轨迹点列表。"""
    if not session_id.strip():
        raise HTTPException(status_code=422, detail="session_id cannot be empty.")

    session = get_session_by_id(db=db, session_id=session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' was not found.")
    rows = get_session_points(db=db, session_id=session_id)

    # 将数据库行转换为轨迹点响应对象，sequence_no 为空的点用遍历索引兜底
    points = []
    for index, row in enumerate(rows, start=1):
        payload = dict(row._mapping)
        if not payload.get("sequence_no"):
            payload["sequence_no"] = index
        points.append(TrajectoryPointResponse.model_validate(payload))

    return ApiResponse(
        data=SessionTrajectoryResponse(
            session=SessionSummaryResponse.model_validate(session),
            points=points,
        )
    )
