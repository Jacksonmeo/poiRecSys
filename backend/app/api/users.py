"""User and check-in APIs backed by PostgreSQL.
用户和签到相关 API，所有数据均从 PostgreSQL 查询。
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.user_trajectory import (
    CheckinResponse,
    SessionListResponse,
    SessionSummaryResponse,
    UserListResponse,
    UserResponse,
)
from app.services.session_service import get_user_sessions
from app.services.user_service import get_user_checkins, get_users, user_exists

router = APIRouter()


@router.get("", response_model=UserListResponse)
def list_users(
    db: Annotated[Session, Depends(get_db)],
    keyword: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> UserListResponse:
    """分页返回用户列表，支持按 user_id 关键字模糊搜索。

    返回总条数 total 用于前端分页组件计算总页数。
    """
    try:
        items, total = get_users(db=db, keyword=keyword, skip=skip, limit=limit)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Failed to query users from database.") from exc

    return UserListResponse(
        items=[UserResponse.model_validate(item) for item in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{user_id}/checkins", response_model=list[CheckinResponse])
def list_user_checkins(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=5000),
) -> list[CheckinResponse]:
    """返回指定用户的签到记录，支持时间范围筛选。

    签到记录与 POI 表 JOIN，同时返回 POI 名称和类别等展示信息。
    user_id 不存在时返回空列表而非 404，以兼容旧前端行为。
    """
    # 参数校验：user_id 不能为空，时间范围不能颠倒
    if not user_id.strip():
        raise HTTPException(status_code=422, detail="user_id cannot be empty.")
    if start_time and end_time and start_time > end_time:
        raise HTTPException(status_code=422, detail="start_time cannot be later than end_time.")

    try:
        # 用户不存在时直接返回空列表，避免无意义的数据库查询
        if not user_exists(db=db, user_id=user_id):
            return []
        rows = get_user_checkins(
            db=db,
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Failed to query check-ins from database.") from exc

    return [CheckinResponse.model_validate(row._mapping) for row in rows]


@router.get("/{user_id}/sessions", response_model=SessionListResponse)
def list_user_sessions(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> SessionListResponse:
    """分页返回指定用户的会话列表，按开始时间倒序排列。

    用户不存在时返回 404，会话数据来自 sessions 表。
    """
    if not user_id.strip():
        raise HTTPException(status_code=422, detail="user_id cannot be empty.")

    try:
        if not user_exists(db=db, user_id=user_id):
            raise HTTPException(status_code=404, detail=f"User '{user_id}' was not found.")
        items, total = get_user_sessions(db=db, user_id=user_id, skip=skip, limit=limit)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Failed to query sessions from database.") from exc

    return SessionListResponse(
        items=[SessionSummaryResponse.model_validate(item) for item in items],
        total=total,
        skip=skip,
        limit=limit,
    )
