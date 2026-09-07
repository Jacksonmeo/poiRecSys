"""零售选址数据访问边界。"""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.checkin import Checkin
from app.models.poi import Poi
from app.schemas.site_selection_config import BusinessMixGroup, CandidateArea
from app.site_selection.schemas import MetricResult


def _area_contains_poi(area: CandidateArea):
    """构造候选分析区包含 POI 点的 PostGIS 条件。"""
    polygon_geojson = json.dumps(
        area.polygon.model_dump(mode="json"),
        ensure_ascii=False,
    )
    polygon = func.ST_SetSRID(func.ST_GeomFromGeoJSON(polygon_geojson), 4326)
    # ST_Covers 与 Sprint 0 审计口径一致，边界上的 POI 也计入结果。
    return func.ST_Covers(polygon, Poi.geom)


class SiteSelectionRepository:
    """使用调用方注入的数据库会话执行选址数据查询。"""

    def __init__(self, db: Session | None = None) -> None:
        """绑定数据库会话；无参初始化兼容领域骨架，查询前需显式注入。"""
        # 保留无参初始化兼容领域骨架；真实查询必须显式注入现有会话。
        self.db = db

    def _require_db(self) -> Session:
        """返回已注入的会话；缺失时抛 RuntimeError。"""
        if self.db is None:
            raise RuntimeError("SiteSelectionRepository 查询需要数据库 Session")
        return self.db

    def get_poi_count(self, area: CandidateArea) -> int:
        """返回候选分析区内的 POI 总数。"""
        statement = select(func.count(Poi.id)).where(_area_contains_poi(area))
        return int(self._require_db().scalar(statement) or 0)

    def get_competitor_count(
        self,
        area: CandidateArea,
        categories: list[str],
    ) -> int:
        """返回候选分析区内属于指定竞争类别的 POI 数量。"""
        statement = select(func.count(Poi.id)).where(
            _area_contains_poi(area),
            Poi.venue_category.in_(categories),
        )
        return int(self._require_db().scalar(statement) or 0)

    def get_transport_poi_count(
        self,
        area: CandidateArea,
        categories: list[str],
    ) -> int:
        """返回候选分析区内属于指定交通类别的 POI 数量。"""
        statement = select(func.count(Poi.id)).where(
            _area_contains_poi(area),
            Poi.venue_category.in_(categories),
        )
        return int(self._require_db().scalar(statement) or 0)

    def get_business_mix_group_presence(
        self,
        area: CandidateArea,
        groups: list[BusinessMixGroup],
    ) -> dict[str, bool]:
        """查询候选分析区内每个商业业态组是否至少存在一个 POI。"""
        db = self._require_db()
        group_presence: dict[str, bool] = {}
        for group in groups:
            matching_poi = select(Poi.id).where(
                _area_contains_poi(area),
                Poi.venue_category.in_(group.categories),
            )
            group_presence[group.group_id] = bool(
                db.scalar(select(matching_poi.exists()))
            )
        return group_presence

    def get_historical_checkin_count(self, area: CandidateArea) -> int:
        """返回候选分析区内 POI 关联的历史签到记录总数。"""
        statement = (
            select(func.count(Checkin.id))
            .select_from(Checkin)
            .join(Poi, Checkin.venue_id == Poi.venue_id)
            .where(_area_contains_poi(area))
        )
        return int(self._require_db().scalar(statement) or 0)

    def get_unique_user_count(self, area: CandidateArea) -> int:
        """返回候选分析区内历史签到用户的去重数量。"""
        statement = (
            select(func.count(func.distinct(Checkin.user_id)))
            .select_from(Checkin)
            .join(Poi, Checkin.venue_id == Poi.venue_id)
            .where(_area_contains_poi(area))
        )
        return int(self._require_db().scalar(statement) or 0)

    def get_candidate_area_metrics(self, area_id: str) -> list[MetricResult]:
        """读取指定候选分析区的指标结果。"""
        # 当前只冻结分层边界，避免在指标口径确定前写入临时 SQL。
        raise NotImplementedError(
            "SiteSelectionRepository.get_candidate_area_metrics 尚未实现"
        )
