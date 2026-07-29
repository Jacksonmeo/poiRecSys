"""轨迹路由：提供用户列表、用户全量轨迹和单个会话轨迹接口。

这些接口从 Mock 数据（trajectory.csv）中读取，用于前端轨迹回放功能。
后续迁移到数据库后，查询逻辑应委托给对应的 service 模块。
"""

from fastapi import APIRouter, HTTPException

from app.services.trajectory_service import get_session, get_user_trajectory, get_users

router = APIRouter()


@router.get("/users")
def list_users() -> dict:
    """返回 mock 数据中所有用户及其会话/轨迹点统计。

    用于前端用户选择下拉框，显示每个用户的会话数和轨迹点总数。
    """
    return {"data": get_users()}


@router.get("/users/{user_id}")
def get_user(user_id: str) -> dict:
    """返回指定用户的所有会话轨迹，不存在时返回 404。

    每个会话包含按 sequence 排序的轨迹点列表，供前端 Cesium 时间轴播放。
    """
    trajectory = get_user_trajectory(user_id)
    if trajectory is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' was not found.")
    return {"data": trajectory}


@router.get("/users/{user_id}/sessions/{session_id}")
def get_user_session(user_id: str, session_id: str) -> dict:
    """返回指定用户在指定会话中的轨迹点序列，不存在时返回 404。

    用于前端查看单次会话的详细访问路径和停留时间。
    """
    session = get_session(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="The requested user session was not found.")
    return {"data": session}
