"""推荐结果 API。

列表接口提供分页，详情接口返回轨迹、真实目标和 Top-K 候选。所有数据均
来自离线推理写入的 PostgreSQL 表，请求过程中不会现场运行模型。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.services.recommend_service import get_recommendation, get_recommendations

router = APIRouter()


@router.get("")
def list_recommendations(
    db: Annotated[Session, Depends(get_db)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    user_id: str | None = None,
) -> dict:
    """分页返回当前配置模型已有结果的 session 摘要。

    可选按 user_id 过滤，返回每个 session 的 target_poi_id 和候选数量 top_k。
    数据来源为 recommendation_results 表，按模型名筛选。
    """
    try:
        items, total = get_recommendations(
            db,
            settings.recommendation_model_name,
            user_id=user_id,
            skip=skip,
            limit=limit,
        )
        return {"data": {"items": items, "total": total, "skip": skip, "limit": limit}}
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Failed to query recommendation results.") from exc


@router.get("/{user_id}")
def list_user_recommendations(user_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    """兼容旧调用：返回指定用户前 200 个推荐 session 的摘要列表。

    此接口为前端旧版调用保留，新代码应使用带分页的 GET /api/recommendations。
    """
    try:
        recommendations, _ = get_recommendations(
            db, settings.recommendation_model_name, user_id=user_id, limit=200
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Failed to query recommendation results.") from exc
    if not recommendations:
        raise HTTPException(status_code=404, detail=f"No recommendations for user '{user_id}'.")
    return {"data": recommendations}


@router.get("/{user_id}/{session_id}")
def get_recommendation_detail(
    user_id: str,
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """返回单个 session 的推荐详情：历史轨迹、真实目标 POI 和按名次排序的 Top-K 候选。

    这是前端推荐详情页面的核心接口，组装了以下三部分数据：
    1. 历史轨迹（去掉最后一点以避免与目标重复）
    2. 真实目标 POI 的展示信息
    3. 模型推荐的候选 POI 列表（含排名和分数）
    """
    try:
        result = get_recommendation(db, user_id, session_id, settings.recommendation_model_name)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Failed to query recommendation detail.") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="The requested recommendation result was not found.")
    return {"data": result}
