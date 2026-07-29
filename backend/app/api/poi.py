"""POI 路由：提供 POI 列表、类别和单个 POI 查询接口。

所有接口通过 get_db 依赖注入获取数据库会话，
查询逻辑委托给 poi_service，保持 Router → Service → ORM 的分层。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.poi import (
    CategoryListResponse,
    PoiDetailResponse,
    PoiListResponse,
    PoiResponse,
)
from app.services.poi_service import get_categories, get_poi_by_venue_id, get_pois

router = APIRouter()


@router.get("", response_model=PoiListResponse)
def list_pois(
    db: Annotated[Session, Depends(get_db)],
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(default=1000, ge=1, le=5000, description="返回记录数上限"),
    category: str | None = Query(default=None, description="按类别精确筛选"),
) -> dict:
    """按可选类别和分页参数返回 POI 列表。

    返回格式与旧 Mock API 兼容：{ "data": [...] }
    支持按 venue_category 精确筛选，适用于前端类别过滤器。
    """
    try:
        pois = get_pois(
            db=db,
            skip=skip,
            limit=limit,
            category=category,
        )
        # 显式构造 dict 以触发 Pydantic 序列化
        return {"data": [PoiResponse.model_validate(p) for p in pois]}
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to query POI data from database",
        ) from exc


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回 POI 数据中包含的所有不重复类别，供前端下拉筛选器使用。"""
    try:
        return {"data": get_categories(db=db)}
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to query POI categories from database",
        ) from exc


@router.get("/{poi_id}", response_model=PoiDetailResponse)
def get_poi(
    poi_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """根据 POI ID（对应数据库 venue_id）返回单个 POI，不存在时返回 404。

    注意：路径参数名保留为 poi_id 以兼容旧前端，实际查询使用 venue_id。
    """
    try:
        poi = get_poi_by_venue_id(db=db, venue_id=poi_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to query POI data from database",
        ) from exc

    if poi is None:
        raise HTTPException(
            status_code=404,
            detail=f"POI '{poi_id}' was not found.",
        )

    return {"data": PoiResponse.model_validate(poi)}
