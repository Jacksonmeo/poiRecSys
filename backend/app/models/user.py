"""ORM mapping for the existing users table.
用户表 ORM 模型，存储系统中的所有用户标识。
"""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class User(Base):
    """用户表，每条记录对应一个独立用户。

    目前仅存储 user_id，后续可扩展用户名、注册时间等字段。
    """

    __tablename__ = "users"

    # 自增主键
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # 用户唯一标识，来自原始签到数据
    user_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
