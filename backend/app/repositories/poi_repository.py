"""POI 空间查询 Repository 层。

职责边界：
- 本层是唯一接触 PostGIS 空间函数（ST_*）的地方，所有 SQL 集中于此。
- Service 层只做业务编排与响应组装，不出现 SQL；Router 层更不允许直接写 SQL。
- 本层只做查询，返回数据库原生数据（ORM 对象或数据类），不包含业务判断。

Stage 2 新增：bbox 范围查询 / 半径查询 / 格网密度统计。
"""

from dataclasses import dataclass

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.models.poi import Poi

# 单次空间查询最大返回条数，防止大范围 bbox 一次性加载过多记录。
MAX_SPATIAL_LIMIT = 2000

# 4326 是 WGS84 经纬度坐标系，POI 表几何列使用该 SRID。
_SRID = 4326


@dataclass(frozen=True)
class DensityCell:
    """密度格网单元：格点中心坐标（WGS84）+ 该格内的 POI 数量。"""

    lon: float
    lat: float
    count: int


def _to_geography(geometry):
    """把 geometry 表达式转为 geography，使 ST_DWithin/ST_Distance 以米为单位计算。"""
    return cast(geometry, Geography(geometry_type="POINT", srid=_SRID))


def query_by_bbox(
    db: Session,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    category: str | None = None,
    limit: int = MAX_SPATIAL_LIMIT,
) -> list[Poi]:
    """按包围盒查询 POI：ST_Intersects(geom, ST_MakeEnvelope(...))。

    Args:
        db: 数据库会话。
        min_lon/min_lat/max_lon/max_lat: WGS84 包围盒边界。
        category: 可选，按 venue_category 精确筛选。
        limit: 返回条数上限。

    Returns:
        POI ORM 实例列表（按 ID 升序，保证结果稳定）。
    """
    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, _SRID)
    stmt = select(Poi).where(func.ST_Intersects(Poi.geom, envelope))
    if category:
        stmt = stmt.where(Poi.venue_category == category)
    stmt = stmt.order_by(Poi.id).limit(limit)
    return list(db.scalars(stmt).all())


def query_by_radius(
    db: Session,
    longitude: float,
    latitude: float,
    radius_meter: float,
    category: str | None = None,
    limit: int = 200,
) -> list[tuple[Poi, float]]:
    """按中心点 + 半径（米）查询 POI：ST_DWithin + ST_Distance。

    使用 geography 语义，保证距离单位是米（geometry 4326 的 ST_DWithin 以度为单位）。
    返回 (POI, 距中心点的米数) 列表，按距离升序。

    Args:
        db: 数据库会话。
        longitude/latitude: 中心点 WGS84 坐标。
        radius_meter: 查询半径，单位米。
        category: 可选，按 venue_category 精确筛选。
        limit: 返回条数上限。

    Returns:
        (Poi, distance_m) 元组列表，已按距离从近到远排序。
    """
    center = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), _SRID)
    center_geog = _to_geography(center)
    poi_geog = _to_geography(Poi.geom)
    distance = func.ST_Distance(poi_geog, center_geog).label("distance_m")

    stmt = select(Poi, distance).where(func.ST_DWithin(poi_geog, center_geog, radius_meter))
    if category:
        stmt = stmt.where(Poi.venue_category == category)
    stmt = stmt.order_by(distance).limit(limit)

    return [(poi, dist) for poi, dist in db.execute(stmt).all()]


def query_density_grid(
    db: Session,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    grid_size: int,
) -> list[DensityCell]:
    """把 bbox 切成 grid_size × grid_size 格网，统计每个格内的 POI 数量。

    实现：ST_SnapToGrid(geom, 单元格宽, 单元格高) + COUNT + GROUP BY。
    格网边长由 bbox 跨度除以 grid_size 得出，使结果近似规则 N×N 网格，
    可直接作为 Mapbox heatmap 的输入（每个格点输出为一个密度点）。

    Args:
        db: 数据库会话。
        min_lon/min_lat/max_lon/max_lat: WGS84 包围盒边界。
        grid_size: 单边格网数（如 10 表示 10×10）。

    Returns:
        密度格网列表，按 count 降序（高密度格在前）。
    """
    cell_width = (max_lon - min_lon) / grid_size
    cell_height = (max_lat - min_lat) / grid_size
    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, _SRID)
    grid_cell = func.ST_SnapToGrid(Poi.geom, cell_width, cell_height)

    stmt = (
        select(
            func.ST_X(grid_cell).label("lon"),
            func.ST_Y(grid_cell).label("lat"),
            func.count().label("count"),
        )
        .where(func.ST_Intersects(Poi.geom, envelope))
        .group_by(grid_cell)
        .order_by(func.count().desc())
    )
    return [DensityCell(lon=lon, lat=lat, count=count) for lon, lat, count in db.execute(stmt).all()]
