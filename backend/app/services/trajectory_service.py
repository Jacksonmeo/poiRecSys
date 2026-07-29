"""轨迹服务：读取 trajectory.csv 并按用户/会话组装轨迹结构。

此模块从 CSV Mock 数据中加载轨迹信息，供前端轨迹回放功能使用。
后续迁移到数据库后，查询逻辑应改为 SQLAlchemy 查询 sessions 和 checkins 表。
"""

from pathlib import Path

import pandas as pd

# mock 数据目录，轨迹接口从 trajectory.csv 中读取访问序列。
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_trajectories() -> pd.DataFrame:
    """读取轨迹 CSV，并固定关键 ID 字段为字符串类型。

    将 user_id、session_id、poi_id 强制转为字符串，避免 pandas 自动推断类型
    导致后续字符串比较出错。
    """
    return pd.read_csv(DATA_DIR / "trajectory.csv", dtype={"user_id": str, "session_id": str, "poi_id": str})


def _to_session_payload(data: pd.DataFrame, user_id: str, session_id: str) -> dict:
    """将某个会话内的轨迹点按 sequence 排序后包装为响应结构。

    轨迹点按 sequence 字段升序排列，还原用户在会话中的真实访问顺序。
    """
    ordered = data.sort_values("sequence")
    return {
        "user_id": user_id,
        "session_id": session_id,
        "points": ordered.to_dict(orient="records"),
    }


def get_users() -> list[dict]:
    """按用户聚合会话数和轨迹点数量，供页面下拉选择使用。

    统计每个用户的 session 数量和轨迹点总数，用于前端用户选择器的摘要展示。
    """
    trajectories = _load_trajectories()
    return [
        {
            "user_id": user_id,
            "session_count": int(group["session_id"].nunique()),
            "point_count": int(len(group)),
        }
        for user_id, group in trajectories.groupby("user_id")
    ]


def get_user_trajectory(user_id: str) -> dict | None:
    """返回指定用户的所有会话轨迹，不存在时返回 None。

    将用户的所有签到按 session_id 分组，每组包装为一次会话的完整轨迹。
    """
    trajectories = _load_trajectories()
    user_data = trajectories[trajectories["user_id"] == user_id]
    if user_data.empty:
        return None
    return {
        "user_id": user_id,
        "sessions": [
            _to_session_payload(session_data, user_id, session_id)
            for session_id, session_data in user_data.groupby("session_id")
        ],
    }


def get_session(user_id: str, session_id: str) -> dict | None:
    """返回指定用户与会话的单条轨迹，不存在时返回 None。

    同时过滤 user_id 和 session_id 以确保数据隔离，
    防止跨用户读取会话数据。
    """
    trajectories = _load_trajectories()
    session_data = trajectories[
        (trajectories["user_id"] == user_id) & (trajectories["session_id"] == session_id)
    ]
    if session_data.empty:
        return None
    return _to_session_payload(session_data, user_id, session_id)
