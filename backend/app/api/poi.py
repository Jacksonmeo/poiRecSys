"""POI 路由：提供 POI 列表、类别和单个 POI 查询接口。

所有接口通过 get_db 依赖注入获取数据库会话，
查询逻辑委托给 poi_service，保持 Router → Service → ORM 的分层。
异常由 main.py 中的全局异常处理器统一转换为标准响应格式。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.response import ApiResponse
from app.db.database import get_db
from app.schemas.poi import PoiResponse
from app.schemas.spatial import FeatureCollection, NearbyPoi
from app.services.poi_service import get_categories, get_poi_by_venue_id, get_pois
from app.services.spatial_service import get_nearby_pois, get_pois_in_bbox

router = APIRouter()


@router.get("", response_model=ApiResponse[list[PoiResponse]])
def list_pois(
    db: Annotated[Session, Depends(get_db)],
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(default=1000, ge=1, le=5000, description="返回记录数上限"),
    category: str | None = Query(default=None, description="按类别精确筛选"),
) -> ApiResponse[list[PoiResponse]]:
    """按可选类别和分页参数返回 POI 列表。

    支持按 venue_category 精确筛选，适用于前端类别过滤器。
    """
    pois = get_pois(
        db=db,
        skip=skip,
        limit=limit,
        category=category,
    )
    return ApiResponse(data=[PoiResponse.model_validate(p) for p in pois])


@router.get("/categories", response_model=ApiResponse[list[str]])
def list_categories(
    db: Annotated[Session, Depends(get_db)],
) -> ApiResponse[list[str]]:
    """返回 POI 数据中包含的所有不重复类别，供前端下拉筛选器使用。"""
    return ApiResponse(data=get_categories(db=db))


@router.get("/spatial", response_model=ApiResponse[FeatureCollection])
def query_pois_by_bbox(
    db: Annotated[Session, Depends(get_db)],
    min_lon: float = Query(..., ge=-180, le=180, description="包围盒最小经度"),
    min_lat: float = Query(..., ge=-90, le=90, description="包围盒最小纬度"),
    max_lon: float = Query(..., ge=-180, le=180, description="包围盒最大经度"),
    max_lat: float = Query(..., ge=-90, le=90, description="包围盒最大纬度"),
    category: str | None = Query(default=None, description="可选：按类别精确筛选"),
    limit: int = Query(default=2000, ge=1, le=5000, description="返回条数上限"),
) -> ApiResponse[FeatureCollection]:
    """按空间包围盒查询 POI，返回 GeoJSON FeatureCollection（ST_Intersects + ST_MakeEnvelope）。

    参数必须满足 min_lon < max_lon 且 min_lat < max_lat，否则返回统一 422 格式。
    返回的 geometry.coordinates 为 [longitude, latitude]（WGS84），
    可直接作为 Mapbox geojson source / Agent 空间查询工具的输入。
    """
    fc = get_pois_in_bbox(
        db=db,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        category=category,
        limit=limit,
    )
    return ApiResponse(data=fc)


@router.get("/nearby", response_model=ApiResponse[list[NearbyPoi]])
def query_pois_by_radius(
    db: Annotated[Session, Depends(get_db)],
    longitude: float = Query(..., ge=-180, le=180, description="中心点经度"),
    latitude: float = Query(..., ge=-90, le=90, description="中心点纬度"),
    radius_meter: float = Query(..., gt=0, le=100_000, description="查询半径（米）"),
    category: str | None = Query(default=None, description="可选：按类别精确筛选"),
    limit: int = Query(default=50, ge=1, le=200, description="返回条数上限"),
) -> ApiResponse[list[NearbyPoi]]:
    """按中心点 + 半径（米）查询附近 POI（ST_DWithin，geography 语义保证单位为米）。

    结果按距离升序排列，每项附带 distance_m（米）。
    """
    pois = get_nearby_pois(
        db=db,
        longitude=longitude,
        latitude=latitude,
        radius_meter=radius_meter,
        category=category,
        limit=limit,
    )
    return ApiResponse(data=pois)


@router.get("/{poi_id}", response_model=ApiResponse[PoiResponse])
def get_poi(
    poi_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ApiResponse[PoiResponse]:
    """根据 POI ID（对应数据库 venue_id）返回单个 POI，不存在时返回 404。

    注意：路径参数名保留为 poi_id 以兼容旧调用，实际查询使用 venue_id。
    """
    poi = get_poi_by_venue_id(db=db, venue_id=poi_id)
    if poi is None:
        raise HTTPException(
            status_code=404,
            detail=f"POI '{poi_id}' was not found.",
        )
    return ApiResponse(data=PoiResponse.model_validate(poi))
