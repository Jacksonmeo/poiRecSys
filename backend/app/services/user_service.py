"""Database-backed query helpers for users and user check-ins.
用户和签到数据库查询服务，封装所有与 users 和 checkins 表相关的查询逻辑。
"""

from datetime import datetime

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.models.checkin import Checkin
from app.models.poi import Poi
from app.models.user import User


def get_users(
    db: Session,
    keyword: str | None,
    skip: int,
    limit: int,
) -> tuple[list[User], int]:
    """分页查询用户列表，支持按 user_id 模糊搜索。

    同时执行数据查询和计数查询，一次返回分页数据和总记录数。

    Args:
        db: 数据库会话。
        keyword: 可选，按 user_id 进行 ILIKE 模糊匹配。
        skip: 分页偏移量。
        limit: 单页最大条数。

    Returns:
        (用户列表, 总记录数) 元组。
    """
    filters = []
    # 清理关键字空白，避免纯空格触发无效查询
    normalized_keyword = keyword.strip() if keyword else ""

    if normalized_keyword:
        filters.append(User.user_id.ilike(f"%{normalized_keyword}%"))

    # 数据查询：按 user_id 排序保证分页结果稳定
    data_stmt = (
        select(User)
        .where(*filters)
        .order_by(User.user_id)
        .offset(skip)
        .limit(limit)
    )
    # 计数查询：统计满足条件的总用户数
    count_stmt = select(func.count()).select_from(User).where(*filters)

    return list(db.scalars(data_stmt).all()), db.scalar(count_stmt) or 0


def user_exists(db: Session, user_id: str) -> bool:
    """检查指定 user_id 的用户是否存在。

    只查询 id 列并限制 1 行，避免不必要的数据传输。

    Args:
        db: 数据库会话。
        user_id: 待检查的用户 ID。

    Returns:
        True 表示用户存在，False 表示不存在。
    """
    stmt = select(User.id).where(User.user_id == user_id).limit(1)
    return db.scalar(stmt) is not None


def get_user_checkins(
    db: Session,
    user_id: str,
    start_time: datetime | None,
    end_time: datetime | None,
    limit: int,
) -> list[Row]:
    """查询指定用户的签到记录，JOIN POI 表以获取场所展示信息。

    支持按时间范围筛选，结果按时间升序排列以还原移动轨迹顺序。

    Args:
        db: 数据库会话。
        user_id: 用户 ID。
        start_time: 可选，签到时间下界（含）。
        end_time: 可选，签到时间上界（含）。
        limit: 最大返回条数。

    Returns:
        SQLAlchemy Row 列表，每行包含签到和 POI 的联合字段。
    """
    filters = [Checkin.user_id == user_id]
    if start_time is not None:
        filters.append(Checkin.utc_timestamp >= start_time)
    if end_time is not None:
        filters.append(Checkin.utc_timestamp <= end_time)

    # JOIN poi 表获取 display_name、category 和坐标，供前端直接展示
    stmt = (
        select(
            Checkin.id,
            Checkin.user_id,
            Checkin.venue_id,
            Checkin.timezone_offset,
            Checkin.utc_timestamp,
            Poi.display_name,
            Poi.venue_category_id,
            Poi.venue_category,
            Poi.longitude,
            Poi.latitude,
        )
        .join(Poi, Checkin.venue_id == Poi.venue_id)
        .where(*filters)
        .order_by(Checkin.utc_timestamp.asc(), Checkin.id.asc())
        .limit(limit)
    )
    return list(db.execute(stmt).all())
