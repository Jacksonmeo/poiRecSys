"""ORM mapping for raw check-in records.
签到记录 ORM 模型，映射原始 Foursquare 签到数据。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Checkin(Base):
    """签到记录表，存储用户的每次签到行为。

    每条记录包含用户、地点、时间信息，并通过 session_id 关联到所属会话。
    签到按时间排序后可构建用户的移动轨迹序列。
    """

    __tablename__ = "checkins"

    # 自增主键
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 签到用户 ID
    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    # 签到场所的 venue_id
    venue_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    # UTC 时区偏移量（分钟），可空
    timezone_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    # 签到 UTC 时间戳，带时区信息
    utc_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    # 所属会话 ID，由 build_sessions 脚本分配
    session_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        index=True,
    )
    # 在会话内的顺序号，从 1 开始递增
    sequence_no: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
