"""POI 服务：通过 SQLAlchemy 从 PostgreSQL 查询 POI 数据。

迁移说明：
- 原实现读取 app/data/poi.csv（pandas）
- get_pois / get_categories / get_poi_by_venue_id 现在查询 PostgreSQL
- get_poi_by_id 保留 CSV 读取，供 recommend_service 等尚未迁移的模块使用
"""

from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.poi import Poi

# mock 数据目录，供尚未迁移的模块回退使用。
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# 单次查询最大返回条数，防止一次性加载全部数据导致内存溢出。
_MAX_LIMIT = 5000


# ── 数据库查询（POI 模块已迁移） ─────────────────────────────────


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


# ── CSV 回退函数（供 recommend / trajectory 等尚未迁移的模块使用） ──


def _load_pois_csv() -> pd.DataFrame:
    """读取 POI CSV（仅用于尚未迁移的模块的向后兼容）。

    将 poi_id 列强制转为字符串类型，避免数值型 ID 被 pandas 解析为整数。
    """
    return pd.read_csv(DATA_DIR / "poi.csv", dtype={"poi_id": str})


def get_poi_by_id(poi_id: str) -> dict | None:
    """根据 poi_id 查询单条 POI（CSV 回退，供 recommend_service 等使用）。

    此函数保留 CSV 读取逻辑，为尚未迁移的模块提供向后兼容。
    后续推荐模块迁移到数据库后，此函数应被移除。

    Args:
        poi_id: CSV 中的 poi_id。

    Returns:
        POI 字典，未找到时返回 None。
    """
    poi = _load_pois_csv().loc[lambda frame: frame["poi_id"] == poi_id]
    return None if poi.empty else poi.iloc[0].to_dict()
