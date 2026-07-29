"""推荐结果查询服务。

本模块只负责数据库查询和前端响应数据的组装：推荐候选来自
``recommendation_results``，POI 展示信息来自 ``pois``，历史轨迹来自
``checkins``。模型推理不应放在 API 请求中，而应由离线脚本预先完成。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.poi import Poi
from app.models.recommendation_result import RecommendationResult
from app.services.session_service import get_session_points


def get_recommendations(
    db: Session,
    model_name: str,
    user_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """分页查询已生成推荐结果的 session 摘要。

    按 user_id + session_id 分组聚合，返回每个 session 的候选数量和真实目标。
    支持可选 user_id 过滤，用于查看特定用户的推荐概况。

    Args:
        db: 数据库会话。
        model_name: 模型名称，用于筛选特定模型的推荐结果。
        user_id: 可选，按用户过滤。
        skip: 分页偏移量。
        limit: 单页最大条数。

    Returns:
        (session 摘要列表, 总 session 数) 元组。
    """
    filters = [RecommendationResult.model_name == model_name]
    if user_id is not None:
        filters.append(RecommendationResult.user_id == user_id)

    # 按 session 分组聚合，计算每个 session 的候选 POI 数量
    stmt = (
        select(
            RecommendationResult.user_id,
            RecommendationResult.session_id,
            RecommendationResult.target_poi_id,
            func.count().label("top_k"),
        )
        .where(*filters)
        .group_by(
            RecommendationResult.user_id,
            RecommendationResult.session_id,
            RecommendationResult.target_poi_id,
        )
        .order_by(RecommendationResult.user_id, RecommendationResult.session_id)
        .offset(skip)
        .limit(limit)
    )
    # 计数查询：统计有推荐结果的不重复 session 总数
    count_stmt = select(
        func.count(func.distinct(RecommendationResult.session_id))
    ).where(*filters)
    return [dict(row._mapping) for row in db.execute(stmt)], db.scalar(count_stmt) or 0


def _poi_payload(poi: Poi) -> dict:
    """同时返回数据库原生字段和现有前端仍在使用的兼容别名。

    将 ORM 对象的字段展开为字典，同时包含新旧两组字段名，
    确保前端无论使用哪套字段名都能正常渲染 POI 信息。
    """
    name = poi.display_name or poi.venue_id
    category = poi.venue_category or "Unknown"
    return {
        "id": poi.id,
        "venue_id": poi.venue_id,
        "display_name": poi.display_name,
        "venue_category_id": poi.venue_category_id,
        "venue_category": poi.venue_category,
        "latitude": poi.latitude,
        "longitude": poi.longitude,
        # 以下为旧前端兼容字段
        "poi_id": poi.venue_id,
        "name": name,
        "category": category,
        "lng": poi.longitude,
        "lat": poi.latitude,
        "address": "",
    }


def get_recommendation(db: Session, user_id: str, session_id: str, model_name: str) -> dict | None:
    """组装一个 session 的历史轨迹、真实目标和按名次排序的候选。

    这是推荐详情页的核心数据组装逻辑，返回结构包含三部分：
    1. history: 历史轨迹点（去掉最后一点避免与目标重复造成信息泄漏）
    2. target_poi: 真实目标 POI 信息
    3. candidates: 模型推荐的候选列表（含排名和分数）

    Args:
        db: 数据库会话。
        user_id: 用户 ID。
        session_id: 会话 ID。
        model_name: 模型名称。

    Returns:
        组装好的推荐详情字典，未找到时返回 None。
    """
    # 查询该 session 的所有推荐候选，按 rank 升序排列
    stmt = (
        select(RecommendationResult)
        .where(
            RecommendationResult.user_id == user_id,
            RecommendationResult.session_id == session_id,
            RecommendationResult.model_name == model_name,
        )
        .order_by(RecommendationResult.rank)
    )
    results = list(db.scalars(stmt).all())
    if not results:
        return None

    # 收集所有涉及的 POI ID（候选 + 目标），批量查询 POI 信息
    poi_ids = {row.poi_id for row in results}
    poi_ids.add(results[0].target_poi_id)
    pois = {
        poi.venue_id: poi
        for poi in db.scalars(select(Poi).where(Poi.venue_id.in_(poi_ids))).all()
    }
    # 查找真实目标 POI，若数据库中没有对应记录则返回 None
    target = pois.get(results[0].target_poi_id)
    if target is None:
        return None

    # 离线推理把最后一个签到作为真实目标，因此历史轨迹必须去掉最后一点，
    # 否则地图会把真实目标同时画进"已知历史"，造成信息泄漏的错觉。
    session_points = get_session_points(db, session_id)
    if session_points and session_points[-1].venue_id == results[0].target_poi_id:
        session_points = session_points[:-1]

    # 组装历史轨迹数组，供前端 Cesium 地图绘制已知访问路径
    history = []
    for index, row in enumerate(session_points, start=1):
        point = row._mapping
        history.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "sequence": point["sequence_no"] or index,
                "poi_id": point["venue_id"],
                "poi_name": point["display_name"] or point["venue_id"],
                "lng": point["longitude"],
                "lat": point["latitude"],
                "visit_time": point["utc_timestamp"],
            }
        )

    # 组装候选列表，将每个候选 rank 的 POI 信息与排名、分数合并
    candidates = []
    for result in results:
        poi = pois.get(result.poi_id)
        if poi is not None:
            candidates.append({**_poi_payload(poi), "rank": result.rank, "score": result.score})

    return {
        "user_id": user_id,
        "session_id": session_id,
        "history": history,
        "target_poi": _poi_payload(target),
        "candidates": candidates,
    }
