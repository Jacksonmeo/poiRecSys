"""ORM mapping for persisted 24-hour user sessions.
用户会话 ORM 模型，存储以 24 小时为间隔切分的签到会话。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UserSession(Base):
    """会话表，每条记录代表用户在 24 小时内的一组连续签到。

    会话由 build_sessions.py 脚本根据签到时间间隔自动切分：
    相邻签到间隔超过 24 小时则切分为新会话，单次签到会话被丢弃。
    """

    __tablename__ = "sessions"

    # 自增主键
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 全局唯一的会话 ID，格式为 {dataset}_{user_id}_{index}
    session_id: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        nullable=False,
        index=True,
    )
    # 所属用户 ID
    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    # 会话起始时间（第一次签到）
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    # 会话结束时间（最后一次签到）
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    # 会话内的签到次数
    checkin_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    # 数据集标签，默认 "TKY"（东京）
    dataset: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="TKY",
    )
