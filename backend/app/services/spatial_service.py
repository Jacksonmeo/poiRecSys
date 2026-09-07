"""空间分析服务：业务编排层（Stage 2 PostGIS）。

职责边界：
- 只负责参数校验 → 调用 repository 空间查询 → 组装响应模型。
- 本层不出现任何 SQL / PostGIS 函数，所有空间查询在 repositories/poi_repository.py。
- 校验失败抛 HTTPException，由 main.py 全局异常处理器统一转换。
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.repositories.poi_repository import query_by_bbox, query_by_radius, query_density_grid
from app.schemas.spatial import (
    DensityCellResponse,
    FeatureCollection,
    GeoPoint,
    NearbyPoi,
    PoiFeature,
    PoiFeatureProperties,
)

# 空间查询默认返回条数上限
DEFAULT_BBOX_LIMIT = 2000
DEFAULT_NEARBY_LIMIT = 50


def validate_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> None:
    """校验包围盒合法性：min 必须严格小于 max，否则 422。"""
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(
            status_code=422,
            detail="bbox 参数非法：min_lon < max_lon 且 min_lat < max_lat 必须同时成立。",
        )


def get_pois_in_bbox(
    db: Session,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    category: str | None = None,
    limit: int = DEFAULT_BBOX_LIMIT,
) -> FeatureCollection:
    """按包围盒查询 POI 并组装为 GeoJSON FeatureCollection。"""
    validate_bbox(min_lon, min_lat, max_lon, max_lat)
    pois = query_by_bbox(
        db=db,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        category=category,
        limit=limit,
    )
    features = [
        PoiFeature(
            geometry=GeoPoint(coordinates=(poi.longitude, poi.latitude)),
            properties=PoiFeatureProperties(
                venue_id=poi.venue_id,
                category=poi.venue_category,
                name=poi.display_name,
            ),
        )
        for poi in pois
    ]
    return FeatureCollection(features=features)


def get_nearby_pois(
    db: Session,
    longitude: float,
    latitude: float,
    radius_meter: float,
    category: str | None = None,
    limit: int = DEFAULT_NEARBY_LIMIT,
) -> list[NearbyPoi]:
    """按中心点 + 半径查询附近 POI，附带距离（米），按距离升序。"""
    rows = query_by_radius(
        db=db,
        longitude=longitude,
        latitude=latitude,
        radius_meter=radius_meter,
        category=category,
        limit=limit,
    )
    return [
        NearbyPoi(
            venue_id=poi.venue_id,
            display_name=poi.display_name,
            venue_category=poi.venue_category,
            latitude=poi.latitude,
            longitude=poi.longitude,
            distance_m=round(distance, 1),
        )
        for poi, distance in rows
    ]


def get_density_grid(
    db: Session,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    grid_size: int,
) -> list[DensityCellResponse]:
    """统计 bbox 内 grid_size×grid_size 格网的 POI 密度，供 Mapbox heatmap 使用。"""
    validate_bbox(min_lon, min_lat, max_lon, max_lat)
    cells = query_density_grid(
        db=db,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        grid_size=grid_size,
    )
    return [
        DensityCellResponse(lat=cell.lat, lon=cell.lon, count=cell.count)
        for cell in cells
    ]
