"""零售选址业务编排边界。"""

from collections.abc import Sequence

from app.schemas.site_selection_config import BusinessMixGroup, CandidateArea
from app.site_selection.repositories import SiteSelectionRepository
from app.site_selection.schemas import MetricResult, SiteSelectionResult

DEFAULT_COMPETITOR_CATEGORIES = ("Coffee Shop", "Café")


class SiteSelectionService:
    """编排选址用例，不直接承担数据库访问职责。"""

    def __init__(
        self,
        repository: SiteSelectionRepository,
        competitor_categories: Sequence[str] = DEFAULT_COMPETITOR_CATEGORIES,
    ) -> None:
        """注入数据访问依赖与竞争类别口径。"""
        # 由调用方注入数据访问依赖，便于替换实现并保持职责分离。
        self.repository = repository
        self.competitor_categories = list(competitor_categories)

    def analyze_basic_metrics(self, area: CandidateArea) -> SiteSelectionResult:
        """查询并组装 POI 总量与竞争门店数量，不进行评分。"""
        poi_count = self.repository.get_poi_count(area)
        competitor_count = self.repository.get_competitor_count(
            area,
            self.competitor_categories,
        )
        metrics = [
            MetricResult(
                metric_id="poi_count",
                value=float(poi_count),
                description="分析区内的 POI 总数。",
            ),
            MetricResult(
                metric_id="competitor_count",
                value=float(competitor_count),
                description="分析区内属于指定竞争类别的 POI 数量。",
            ),
        ]
        return SiteSelectionResult(area_id=area.area_id, metrics=metrics)

    def analyze_transport_poi_count(
        self,
        area: CandidateArea,
        categories: list[str],
    ) -> MetricResult:
        """查询交通设施 POI 数量并转换为领域指标。"""
        transport_poi_count = self.repository.get_transport_poi_count(
            area,
            categories,
        )
        return MetricResult(
            metric_id="transport_poi_count",
            value=float(transport_poi_count),
            description="分析区内属于配置交通类别的 POI 数量。",
        )

    def analyze_business_mix_diversity(
        self,
        area: CandidateArea,
        groups: list[BusinessMixGroup],
    ) -> MetricResult:
        """汇总分析区内至少存在一个 POI 的商业业态组数量。"""
        group_presence = self.repository.get_business_mix_group_presence(
            area,
            groups,
        )
        covered_group_count = sum(group_presence.values())
        return MetricResult(
            metric_id="business_mix_diversity",
            value=float(covered_group_count),
            description="分析区内至少存在一个 POI 的商业业态组数量。",
        )

    def analyze_behavior_metrics(self, area: CandidateArea) -> SiteSelectionResult:
        """查询并组装区域历史签到规模，不分析轨迹或会话。"""
        historical_checkin_count = self.repository.get_historical_checkin_count(
            area
        )
        unique_user_count = self.repository.get_unique_user_count(area)
        metrics = [
            MetricResult(
                metric_id="historical_checkin_count",
                value=float(historical_checkin_count),
                description="分析区内 POI 关联的历史签到记录总数。",
            ),
            MetricResult(
                metric_id="unique_user_count",
                value=float(unique_user_count),
                description="分析区内产生历史签到的去重用户数量。",
            ),
        ]
        return SiteSelectionResult(area_id=area.area_id, metrics=metrics)

    def get_candidate_area_metrics(self, area_id: str) -> list[MetricResult]:
        """将候选分析区指标读取委托给数据访问层。"""
        return self.repository.get_candidate_area_metrics(area_id)
