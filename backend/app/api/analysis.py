"""空间分析路由：提供 PostGIS 空间分析接口（Stage 2）。

当前只有一个密度分析接口（Mapbox heatmap 数据源），后续空间聚类等
分析能力将在此路由组扩展。查询委托给 spatial_service，本层不写 SQL。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.response import ApiResponse
from app.db.database import get_db
from app.schemas.spatial import DensityCellResponse
from app.services.spatial_service import get_density_grid

router = APIRouter()


@router.get("/density", response_model=ApiResponse[list[DensityCellResponse]])
def query_density(
    db: Annotated[Session, Depends(get_db)],
    min_lon: float = Query(..., ge=-180, le=180, description="包围盒最小经度"),
    min_lat: float = Query(..., ge=-90, le=90, description="包围盒最小纬度"),
    max_lon: float = Query(..., ge=-180, le=180, description="包围盒最大经度"),
    max_lat: float = Query(..., ge=-90, le=90, description="包围盒最大纬度"),
    grid_size: int = Query(default=10, ge=2, le=100, description="单边格网数（如 10 表示 10×10）"),
) -> ApiResponse[list[DensityCellResponse]]:
    """统计 bbox 内 grid_size×grid_size 格网的 POI 密度（ST_SnapToGrid + COUNT + GROUP BY）。

    返回 [{lat, lon, count}] 列表（按 count 降序），每个元素是一个格点的中心坐标，
    可直接作为 Mapbox heatmap 图层的数据源。
    """
    cells = get_density_grid(
        db=db,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        grid_size=grid_size,
    )
    return ApiResponse(data=cells)
