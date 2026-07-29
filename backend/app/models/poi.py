"""POI ORM 模型：映射数据库 pois 表。

数据库已存在 GIST 空间索引，ORM 中不再重复创建。
geom 字段只在查询中使用，不会直接返回给前端。
"""

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Poi(Base):
    """POI（兴趣点）表，存储东京区域的各类场所。

    空间参考系为 WGS84（SRID 4326），geom 通过 ST_MakePoint(longitude, latitude) 生成。
    每条记录对应 Foursquare 中的一个 venue，包含名称、类别和地理坐标。
    """

    __tablename__ = "pois"

    # 自增主键，用于内部唯一标识
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    # Foursquare venue ID，业务主键，全局唯一
    venue_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    # POI 展示名称，可能为空
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Foursquare 类别 ID
    venue_category_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # 人类可读的类别名称，如 "Ramen Restaurant"，用于前端筛选和展示
    venue_category: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    # 纬度坐标
    latitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # 经度坐标
    longitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # PostGIS 几何字段，用于空间查询（如距离计算、范围筛选）
    # spatial_index=False 因为数据库已有手工创建的 GIST 索引
    geom: Mapped[object] = mapped_column(
        Geometry(
            geometry_type="POINT",
            srid=4326,
            spatial_index=False,  # 数据库已建 GIST 索引，ORM 无需重复
        ),
        nullable=False,
    )

    def __repr__(self) -> str:
        """调试用字符串表示，显示关键标识字段。"""
        return (
            f"<Poi(id={self.id}, venue_id='{self.venue_id}', "
            f"display_name='{self.display_name}', "
            f"venue_category='{self.venue_category}')>"
        )
