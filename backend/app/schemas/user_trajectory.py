"""Pydantic schemas for users, check-ins, sessions, and trajectories.
用户、签到、会话和轨迹相关的 Pydantic 数据模型，定义 API 响应结构。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    """用户响应模型，包含内部 ID 和用户唯一标识。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str


class UserListResponse(BaseModel):
    """用户列表响应模型，支持分页信息返回。"""

    items: list[UserResponse]
    total: int
    skip: int
    limit: int


class CheckinResponse(BaseModel):
    """签到记录响应模型，JOIN POI 表后包含场所展示信息。

    字段同时包含签到元数据（时间、时区偏移）和 POI 详情（名称、类别、坐标），
    供前端同时展示签到时间和地点信息。
    """

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


class SessionListResponse(BaseModel):
    """会话列表响应模型，支持分页。"""

    items: list[SessionSummaryResponse]
    total: int
    skip: int
    limit: int


class TrajectoryPointResponse(BaseModel):
    """轨迹点响应模型，单个签到点在轨迹中的表示。

    包含顺序号、POI 标识和坐标，用于前端 Cesium 地图的时间序列渲染。
    """

    sequence_no: int
    venue_id: str
    display_name: str | None = None
    venue_category: str | None = None
    longitude: float
    latitude: float
    utc_timestamp: datetime


class SessionTrajectoryResponse(BaseModel):
    """会话轨迹响应模型，组合会话摘要和完整轨迹点序列。

    前端获取此数据后可在 Cesium 地图上绘制用户的移动路径和时间轴。
    """

    session: SessionSummaryResponse
    points: list[TrajectoryPointResponse]
