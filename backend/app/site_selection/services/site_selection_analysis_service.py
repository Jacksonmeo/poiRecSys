"""完整零售选址事实分析的应用编排服务。"""

from app.schemas.site_selection_config import BusinessMixGroup
from app.schemas.site_selection_config import CandidateArea as ConfigCandidateArea
from app.site_selection.schemas import CandidateArea as ArtifactCandidateArea
from app.site_selection.schemas import (
    AnalysisMetadata,
    MetricResult,
    SiteSelectionArtifact,
)
from app.site_selection.services.site_selection_flow_service import (
    SiteSelectionFlowService,
)
from app.site_selection.services.site_selection_service import SiteSelectionService


class SiteSelectionAnalysisService:
    """组合既有指标与流向能力，不承担数据查询或评分职责。"""

    def __init__(
        self,
        site_selection_service: SiteSelectionService,
        flow_service: SiteSelectionFlowService,
        metadata: AnalysisMetadata,
        transport_categories: list[str],
        business_mix_groups: list[BusinessMixGroup],
    ) -> None:
        """注入指标/流向服务与配置元信息（配置由边界注入，不自行读取）。"""
        self.site_selection_service = site_selection_service
        self.flow_service = flow_service
        # 元信息由配置边界注入，编排层不自行读取配置或硬编码数据口径。
        self.metadata = metadata
        self.transport_categories = list(transport_categories)
        self.business_mix_groups = list(business_mix_groups)

    def analyze_site_selection(
        self,
        candidate_areas: list[ConfigCandidateArea],
    ) -> SiteSelectionArtifact:
        """逐区获取既有指标，并在完整候选区上下文中分析流向。"""
        metrics: list[MetricResult] = []
        for candidate_area in candidate_areas:
            basic_result = self.site_selection_service.analyze_basic_metrics(
                candidate_area
            )
            transport_metric = (
                self.site_selection_service.analyze_transport_poi_count(
                    candidate_area,
                    self.transport_categories,
                )
            )
            business_mix_metric = (
                self.site_selection_service.analyze_business_mix_diversity(
                    candidate_area,
                    self.business_mix_groups,
                )
            )
            behavior_result = self.site_selection_service.analyze_behavior_metrics(
                candidate_area
            )
            metrics.extend(basic_result.metrics)
            metrics.extend([transport_metric, business_mix_metric])
            metrics.extend(behavior_result.metrics)

        flows = self.flow_service.analyze_area_flows(candidate_areas)
        artifact_areas = [
            ArtifactCandidateArea(
                area_id=candidate_area.area_id,
                display_name=candidate_area.display_name,
            )
            for candidate_area in candidate_areas
        ]
        return SiteSelectionArtifact(
            analysis_type="site_selection",
            candidate_areas=artifact_areas,
            metadata=self.metadata,
            metrics=metrics,
            flows=flows,
            summary=None,
        )
