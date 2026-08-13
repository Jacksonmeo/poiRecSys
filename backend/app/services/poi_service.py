"""POI 服务：通过 SQLAlchemy 从 PostgreSQL 查询 POI 数据。

第一阶段治理后已移除全部 CSV 回退逻辑（get_poi_by_id / _load_pois_csv），
所有查询统一走数据库。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.poi import Poi

# 单次查询最大返回条数，防止一次性加载全部数据导致内存溢出。
_MAX_LIMIT = 5000


def get_pois(
    db: Session,
    skip: int = 0,
    limit: int = 1000,
    category: str | None = None,
) -> list[Poi]:
    """返回 POI 列表，支持分页和可选类别筛选。

    按 ID 升序排列以保证分页结果稳定，类别筛选为精确匹配。

    Args:
        db: 数据库会话。
        skip: 跳过的记录数（用于分页）。
        limit: 返回记录数上限（1-5000）。
        category: 可选，按 venue_category 精确筛选。

    Returns:
        POI ORM 实例列表。
    """
    # 限制 limit 范围，防止单次查询数据量过大
    limit = max(1, min(limit, _MAX_LIMIT))

    stmt = select(Poi)

    if category:
        stmt = stmt.where(Poi.venue_category == category)

    stmt = stmt.order_by(Poi.id).offset(skip).limit(limit)

    return list(db.scalars(stmt).all())


def get_categories(db: Session) -> list[str]:
    """返回所有不重复的 POI 类别，按字母排序供前端筛选器使用。

    自动过滤空值类别，结果按字母升序排列。

    Args:
        db: 数据库会话。

    Returns:
        去重排序后的类别名称列表。
    """
    stmt = (
        select(Poi.venue_category)
        .where(Poi.venue_category.isnot(None))
        .distinct()
        .order_by(Poi.venue_category)
    )
    return list(db.scalars(stmt).all())


def get_poi_by_venue_id(db: Session, venue_id: str) -> Poi | None:
    """根据 venue_id 查询单条 POI（数据库）。

    用于 POI 详情页和推荐结果中候选 POI 的信息填充。

    Args:
        db: 数据库会话。
        venue_id: POI 的 venue_id（Foursquare 风格 ID）。

    Returns:
        Poi 实例，未找到时返回 None。
    """
    stmt = select(Poi).where(Poi.venue_id == venue_id)
    return db.scalars(stmt).first()
