"""Pydantic schemas for users, check-ins, sessions, and trajectories.
用户、签到、会话和轨迹相关的 Pydantic 数据模型，定义 ApiResponse.data 的内层结构。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    """用户响应模型，包含内部 ID 和用户唯一标识。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str


class CheckinResponse(BaseModel):
    """签到记录响应模型，JOIN POI 表后包含场所展示信息。"""

    id: int
    user_id: str
    venue_id: str
    display_name: str | None = None
    venue_category_id: str | None = None
    venue_category: str | None = None
    longitude: float
    latitude: float
    timezone_offset: int | None = None
    utc_timestamp: datetime


class SessionSummaryResponse(BaseModel):
    """会话摘要响应模型，包含会话基本信息和签到统计。"""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    user_id: str
    start_time: datetime
    end_time: datetime
    checkin_count: int
    dataset: str = "TKY"


class TrajectoryPointResponse(BaseModel):
    """轨迹点响应模型，单个签到点在轨迹中的表示。"""

    sequence_no: int
    venue_id: str
    display_name: str | None = None
    venue_category: str | None = None
    longitude: float
    latitude: float
    utc_timestamp: datetime


class SessionTrajectoryResponse(BaseModel):
    """会话轨迹响应模型，组合会话摘要和完整轨迹点序列。"""

    session: SessionSummaryResponse
    points: list[TrajectoryPointResponse]
