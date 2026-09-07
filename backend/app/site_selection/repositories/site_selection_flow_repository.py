"""区域行为流向分析的数据访问边界。"""

import json

from geoalchemy2 import Geography
from sqlalchemy import and_, cast, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session

from app.models.checkin import Checkin
from app.models.poi import Poi
from app.models.session import UserSession
from app.schemas.site_selection_config import CandidateArea
from app.site_selection.schemas import AreaFlowResult, SessionAreaSequence

OUTSIDE_AREA_ID = "outside_candidate_area"
_SRID = 4326


def _candidate_area_row(area: CandidateArea):
    """把一个已校验候选区转换为查询内的区域记录。"""
    polygon_geojson = json.dumps(
        area.polygon.model_dump(mode="json"),
        ensure_ascii=False,
    )
    polygon = func.ST_SetSRID(func.ST_GeomFromGeoJSON(polygon_geojson), _SRID)
    center = func.ST_SetSRID(
        func.ST_MakePoint(area.center.longitude, area.center.latitude),
        _SRID,
    )
    return select(
        literal(area.area_id).label("area_id"),
        polygon.label("polygon"),
        center.label("center"),
    )


def _candidate_areas_cte(candidate_areas: list[CandidateArea]):
    """构造只在当前查询生命周期存在的候选区 CTE。"""
    area_rows = [_candidate_area_row(area) for area in candidate_areas]
    area_query = area_rows[0] if len(area_rows) == 1 else union_all(*area_rows)
    return area_query.cte("candidate_areas")


def _poi_area_mapping_cte(candidate_areas: list[CandidateArea]):
    """构造唯一 POI 区域归属，供映射和 Session 序列查询复用。"""
    if not candidate_areas:
        return select(
            Poi.venue_id.label("venue_id"),
            literal(OUTSIDE_AREA_ID).label("area_id"),
        ).cte("poi_area_mapping")

    areas = _candidate_areas_cte(candidate_areas)
    poi_geography = cast(Poi.geom, Geography(geometry_type="POINT", srid=_SRID))
    center_geography = cast(
        areas.c.center,
        Geography(geometry_type="POINT", srid=_SRID),
    )
    distance = func.ST_Distance(poi_geography, center_geography, True)
    matches = (
        select(
            Poi.venue_id.label("venue_id"),
            areas.c.area_id.label("area_id"),
            func.row_number()
            .over(
                partition_by=Poi.venue_id,
                order_by=(distance.asc(), areas.c.area_id.collate("C").asc()),
            )
            .label("area_rank"),
        )
        .select_from(Poi)
        .join(areas, func.ST_Covers(areas.c.polygon, Poi.geom))
        .cte("ranked_area_matches")
    )
    assigned_area = func.coalesce(
        matches.c.area_id,
        literal(OUTSIDE_AREA_ID),
    ).label("area_id")
    return (
        select(Poi.venue_id.label("venue_id"), assigned_area)
        .outerjoin(
            matches,
            and_(matches.c.venue_id == Poi.venue_id, matches.c.area_rank == 1),
        )
        .cte("poi_area_mapping")
    )


def _ordered_session_checkins_cte():
    """保留原始 Session Checkin，并计算时间顺序校验所需前值。"""
    previous_timestamp = func.lag(Checkin.utc_timestamp).over(
        partition_by=Checkin.session_id,
        order_by=(Checkin.sequence_no.asc().nullslast(), Checkin.id.asc()),
    )
    return (
        select(
            Checkin.id,
            Checkin.session_id,
            Checkin.user_id,
            Checkin.venue_id,
            Checkin.utc_timestamp,
            Checkin.sequence_no,
            previous_timestamp.label("previous_timestamp"),
        )
        .where(Checkin.session_id.isnot(None))
        .cte("ordered_session_checkins")
    )


def _valid_sessions_cte(checkins, poi_mapping):
    """筛选数量、用户、序号、时间和 POI 关联均完整的 TKY Session。"""
    row_count = func.count(checkins.c.id)
    user_matches = and_(
        checkins.c.user_id == UserSession.user_id,
        func.btrim(checkins.c.user_id) != "",
        func.btrim(checkins.c.venue_id) != "",
    )
    time_is_ordered = or_(
        checkins.c.previous_timestamp.is_(None),
        checkins.c.utc_timestamp >= checkins.c.previous_timestamp,
    )
    return (
        select(UserSession.session_id, UserSession.user_id)
        .join(checkins, checkins.c.session_id == UserSession.session_id)
        .outerjoin(poi_mapping, poi_mapping.c.venue_id == checkins.c.venue_id)
        .where(
            UserSession.dataset == "TKY",
            func.btrim(UserSession.session_id) != "",
            func.btrim(UserSession.user_id) != "",
        )
        .group_by(
            UserSession.session_id,
            UserSession.user_id,
            UserSession.checkin_count,
        )
        .having(
            row_count == UserSession.checkin_count,
            func.count(checkins.c.sequence_no) == row_count,
            func.min(checkins.c.sequence_no) == 1,
            func.max(checkins.c.sequence_no) == row_count,
            func.count(func.distinct(checkins.c.sequence_no)) == row_count,
            func.bool_and(user_matches),
            func.count(poi_mapping.c.venue_id) == row_count,
            func.bool_and(time_is_ordered),
        )
        .cte("valid_sessions")
    )


class SiteSelectionFlowRepository:
    """保存数据库会话，并为后续流向查询提供稳定接口。"""

    def __init__(self, db: Session) -> None:
        """绑定数据库会话（生命周期由调用方管理）。"""
        # 数据库会话由调用方管理，Repository 不创建连接或控制其生命周期。
        self.db = db

    def get_area_flows(self) -> list[AreaFlowResult]:
        """返回区域流向结果；真实数据库查询将在后续阶段实现。"""
        return []

    def get_poi_area_mapping(
        self,
        candidate_areas: list[CandidateArea],
    ) -> list[tuple[str, str]]:
        """返回全部 POI 的唯一候选区归属，未命中项归为区域外。"""
        mapping = _poi_area_mapping_cte(candidate_areas)
        statement = select(mapping.c.venue_id, mapping.c.area_id).order_by(
            mapping.c.venue_id
        )
        return [(row.venue_id, row.area_id) for row in self.db.execute(statement)]

    def get_session_area_sequences(
        self,
        candidate_areas: list[CandidateArea],
    ) -> list[SessionAreaSequence]:
        """返回有效 TKY Session 按原始序号排列的完整区域状态序列。"""
        mapping = _poi_area_mapping_cte(candidate_areas)
        checkins = _ordered_session_checkins_cte()
        valid_sessions = _valid_sessions_cte(checkins, mapping)
        areas = func.array_agg(
            aggregate_order_by(
                mapping.c.area_id,
                checkins.c.sequence_no.asc(),
                checkins.c.id.asc(),
            )
        ).label("areas")
        statement = (
            select(valid_sessions.c.session_id, valid_sessions.c.user_id, areas)
            .join(checkins, checkins.c.session_id == valid_sessions.c.session_id)
            .join(mapping, mapping.c.venue_id == checkins.c.venue_id)
            .group_by(valid_sessions.c.session_id, valid_sessions.c.user_id)
            .order_by(valid_sessions.c.session_id.collate("C"))
        )
        return [
            SessionAreaSequence(
                session_id=row.session_id,
                user_id=row.user_id,
                areas=list(row.areas),
            )
            for row in self.db.execute(statement)
        ]
