"""Database-backed query helpers for persisted user sessions.
会话数据库查询服务，封装所有与 sessions 表相关的查询逻辑。
"""

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.models.checkin import Checkin
from app.models.poi import Poi
from app.models.session import UserSession


def get_user_sessions(
    db: Session,
    user_id: str,
    skip: int,
    limit: int,
) -> tuple[list[UserSession], int]:
    """分页查询指定用户的会话列表，按开始时间倒序排列。

    最近的会话排在前面，便于前端展示用户的最新活动。

    Args:
        db: 数据库会话。
        user_id: 用户 ID。
        skip: 分页偏移量。
        limit: 单页最大条数。

    Returns:
        (会话列表, 总记录数) 元组。
    """
    filters = [UserSession.user_id == user_id]

    # 按开始时间倒序，相同时按 session_id 升序保证确定性
    data_stmt = (
        select(UserSession)
        .where(*filters)
        .order_by(UserSession.start_time.desc(), UserSession.session_id.asc())
        .offset(skip)
        .limit(limit)
    )
    count_stmt = select(func.count()).select_from(UserSession).where(*filters)

    return list(db.scalars(data_stmt).all()), db.scalar(count_stmt) or 0


def get_session_by_id(db: Session, session_id: str) -> UserSession | None:
    """根据 session_id 查询单个会话。

    Args:
        db: 数据库会话。
        session_id: 全局唯一的会话 ID。

    Returns:
        UserSession 实例，未找到时返回 None。
    """
    stmt = select(UserSession).where(UserSession.session_id == session_id)
    return db.scalars(stmt).first()


def get_session_points(db: Session, session_id: str) -> list[Row]:
    """查询指定会话的所有轨迹点，JOIN POI 表获取场所信息。

    轨迹点按 sequence_no 升序排列（空值排在最后），同时用时间戳和 id 兜底排序，
    确保即使 sequence_no 缺失也能得到确定性的顺序。

    Args:
        db: 数据库会话。
        session_id: 会话 ID。

    Returns:
        SQLAlchemy Row 列表，每行包含签到顺序号和 POI 展示字段。
    """
    stmt = (
        select(
            # COALESCE 将 null sequence_no 转为 0，空值自然排到最后
            func.coalesce(Checkin.sequence_no, 0).label("sequence_no"),
            Checkin.venue_id,
            Checkin.utc_timestamp,
            Poi.display_name,
            Poi.venue_category,
            Poi.longitude,
            Poi.latitude,
        )
        .join(Poi, Checkin.venue_id == Poi.venue_id)
        .where(Checkin.session_id == session_id)
        .order_by(Checkin.sequence_no.asc().nullslast(), Checkin.utc_timestamp.asc(), Checkin.id.asc())
    )
    return list(db.execute(stmt).all())
