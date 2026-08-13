"""零售选址领域骨架的最小单元测试。"""

from app.site_selection.repositories import SiteSelectionRepository
from app.site_selection.schemas import CandidateArea, MetricResult, SiteSelectionResult
from app.site_selection.services import SiteSelectionService


def test_site_selection_schemas_can_be_created() -> None:
    area = CandidateArea(area_id="shinjuku", display_name="Shinjuku")
    metric = MetricResult(
        metric_id="poi_count",
        value=100.0,
        description="分析区内的历史 POI 数量。",
    )
    result = SiteSelectionResult(area_id=area.area_id, metrics=[metric])

    assert result.area_id == "shinjuku"
    assert result.metrics == [metric]
    assert result.score is None
    assert result.explanation is None


def test_site_selection_service_accepts_repository_dependency() -> None:
    repository = SiteSelectionRepository()

    service = SiteSelectionService(repository=repository)

    assert service.repository is repository
