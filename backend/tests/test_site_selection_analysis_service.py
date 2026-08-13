"""SiteSelectionArtifact 应用编排服务测试。"""

from unittest.mock import Mock

from app.schemas.site_selection_config import CandidateArea
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.schemas import (
    AnalysisMetadata,
    AreaFlowResult,
    MetricResult,
    SiteSelectionResult,
)
from app.site_selection.services import (
    SiteSelectionAnalysisService,
    SiteSelectionFlowService,
    SiteSelectionService,
)


def _candidate_areas(count: int = 1) -> list[CandidateArea]:
    return load_site_selection_config().candidate_areas[:count]


def _metadata() -> AnalysisMetadata:
    return AnalysisMetadata(
        config_version="tokyo_coffee_v1",
        dataset="TSMC2014_TKY",
        observation_period="2012-04-03T18:17:18Z/2013-02-16T02:35:29Z",
    )


def _build_service() -> tuple[SiteSelectionAnalysisService, Mock, Mock]:
    config = load_site_selection_config()
    metrics_service = Mock(spec=SiteSelectionService)
    metrics_service.analyze_basic_metrics.return_value = SiteSelectionResult(
        area_id="default",
        metrics=[],
    )
    metrics_service.analyze_behavior_metrics.return_value = SiteSelectionResult(
        area_id="default",
        metrics=[],
    )
    metrics_service.analyze_transport_poi_count.return_value = _metric(
        "transport_poi_count",
        0.0,
    )
    metrics_service.analyze_business_mix_diversity.return_value = _metric(
        "business_mix_diversity",
        0.0,
    )
    flow_service = Mock(spec=SiteSelectionFlowService)
    flow_service.analyze_area_flows.return_value = []
    service = SiteSelectionAnalysisService(
        metrics_service,
        flow_service,
        metadata=_metadata(),
        transport_categories=config.transport_categories,
        business_mix_groups=config.business_mix_groups,
    )
    return service, metrics_service, flow_service


def _metric(metric_id: str, value: float) -> MetricResult:
    return MetricResult(
        metric_id=metric_id,
        value=value,
        description=f"{metric_id} 的历史事实结果。",
    )


def test_analyze_site_selection_builds_complete_artifact() -> None:
    areas = _candidate_areas()
    area = areas[0]
    service, metrics_service, flow_service = _build_service()
    poi_metric = _metric("poi_count", 120.0)
    competitor_metric = _metric("competitor_count", 8.0)
    transport_metric = _metric("transport_poi_count", 12.0)
    business_mix_metric = _metric("business_mix_diversity", 4.0)
    checkin_metric = _metric("historical_checkin_count", 480.0)
    user_metric = _metric("unique_user_count", 90.0)
    flow = AreaFlowResult(
        source_area=area.area_id,
        target_area="shibuya",
        flow_count=6,
        unique_users=2,
        unique_sessions=4,
    )
    metrics_service.analyze_basic_metrics.return_value = SiteSelectionResult(
        area_id=area.area_id,
        metrics=[poi_metric, competitor_metric],
    )
    metrics_service.analyze_transport_poi_count.return_value = transport_metric
    metrics_service.analyze_business_mix_diversity.return_value = business_mix_metric
    metrics_service.analyze_behavior_metrics.return_value = SiteSelectionResult(
        area_id=area.area_id,
        metrics=[checkin_metric, user_metric],
    )
    flow_service.analyze_area_flows.return_value = [flow]

    artifact = service.analyze_site_selection(areas)

    assert artifact.analysis_type == "site_selection"
    assert artifact.candidate_areas[0].area_id == area.area_id
    assert artifact.candidate_areas[0].display_name == area.display_name
    assert artifact.metadata == _metadata()
    assert artifact.metrics == [
        poi_metric,
        competitor_metric,
        transport_metric,
        business_mix_metric,
        checkin_metric,
        user_metric,
    ]
    assert artifact.flows == [flow]
    assert artifact.summary is None
    metrics_service.analyze_basic_metrics.assert_called_once_with(area)
    metrics_service.analyze_transport_poi_count.assert_called_once_with(
        area,
        service.transport_categories,
    )
    metrics_service.analyze_business_mix_diversity.assert_called_once_with(
        area,
        service.business_mix_groups,
    )
    metrics_service.analyze_behavior_metrics.assert_called_once_with(area)
    flow_service.analyze_area_flows.assert_called_once_with(areas)


def test_analyze_site_selection_accepts_empty_flows() -> None:
    areas = _candidate_areas()
    service, _, flow_service = _build_service()
    flow_service.analyze_area_flows.return_value = []

    artifact = service.analyze_site_selection(areas)

    assert artifact.flows == []


def test_analyze_site_selection_merges_metrics_in_analysis_order() -> None:
    areas = _candidate_areas()
    area = areas[0]
    service, metrics_service, _ = _build_service()
    basic_metrics = [_metric("poi_count", 10.0), _metric("competitor_count", 2.0)]
    behavior_metrics = [
        _metric("historical_checkin_count", 30.0),
        _metric("unique_user_count", 8.0),
    ]
    transport_metric = _metric("transport_poi_count", 5.0)
    business_mix_metric = _metric("business_mix_diversity", 4.0)
    metrics_service.analyze_basic_metrics.return_value = SiteSelectionResult(
        area_id=area.area_id,
        metrics=basic_metrics,
    )
    metrics_service.analyze_behavior_metrics.return_value = SiteSelectionResult(
        area_id=area.area_id,
        metrics=behavior_metrics,
    )
    metrics_service.analyze_transport_poi_count.return_value = transport_metric
    metrics_service.analyze_business_mix_diversity.return_value = business_mix_metric

    artifact = service.analyze_site_selection(areas)

    assert artifact.metrics == [
        *basic_metrics,
        transport_metric,
        business_mix_metric,
        *behavior_metrics,
    ]


def test_analyze_site_selection_does_not_modify_input() -> None:
    areas = _candidate_areas(2)
    service, _, _ = _build_service()
    original_areas = [area.model_dump(mode="json") for area in areas]

    service.analyze_site_selection(areas)

    assert [area.model_dump(mode="json") for area in areas] == original_areas


def test_analyze_site_selection_passes_two_areas_to_flow_context() -> None:
    areas = _candidate_areas(2)
    service, _, flow_service = _build_service()
    flow = AreaFlowResult(
        source_area=areas[0].area_id,
        target_area=areas[1].area_id,
        flow_count=3,
        unique_users=2,
        unique_sessions=2,
    )
    flow_service.analyze_area_flows.return_value = [flow]

    artifact = service.analyze_site_selection(areas)

    assert [area.area_id for area in artifact.candidate_areas] == [
        area.area_id for area in areas
    ]
    assert artifact.flows == [flow]
    flow_service.analyze_area_flows.assert_called_once_with(areas)


def test_analyze_site_selection_merges_metrics_for_multiple_areas() -> None:
    areas = _candidate_areas(2)
    service, metrics_service, _ = _build_service()
    basic_by_area = {
        area.area_id: [_metric(f"{area.area_id}_basic", 1.0)] for area in areas
    }
    behavior_by_area = {
        area.area_id: [_metric(f"{area.area_id}_behavior", 2.0)] for area in areas
    }
    transport_by_area = {
        area.area_id: _metric(f"{area.area_id}_transport", 3.0) for area in areas
    }
    business_mix_by_area = {
        area.area_id: _metric(f"{area.area_id}_business_mix", 4.0) for area in areas
    }
    metrics_service.analyze_basic_metrics.side_effect = lambda area: (
        SiteSelectionResult(area_id=area.area_id, metrics=basic_by_area[area.area_id])
    )
    metrics_service.analyze_behavior_metrics.side_effect = lambda area: (
        SiteSelectionResult(
            area_id=area.area_id,
            metrics=behavior_by_area[area.area_id],
        )
    )
    metrics_service.analyze_transport_poi_count.side_effect = (
        lambda area, categories: transport_by_area[area.area_id]
    )
    metrics_service.analyze_business_mix_diversity.side_effect = (
        lambda area, groups: business_mix_by_area[area.area_id]
    )

    artifact = service.analyze_site_selection(areas)

    expected_metrics = []
    for area in areas:
        expected_metrics.extend(basic_by_area[area.area_id])
        expected_metrics.append(transport_by_area[area.area_id])
        expected_metrics.append(business_mix_by_area[area.area_id])
        expected_metrics.extend(behavior_by_area[area.area_id])
    assert artifact.metrics == expected_metrics


def test_analyze_site_selection_includes_transport_metric() -> None:
    areas = _candidate_areas()
    service, metrics_service, _ = _build_service()
    transport_metric = _metric("transport_poi_count", 7.0)
    metrics_service.analyze_transport_poi_count.return_value = transport_metric

    artifact = service.analyze_site_selection(areas)

    assert transport_metric in artifact.metrics


def test_analyze_site_selection_includes_business_mix_metric() -> None:
    areas = _candidate_areas()
    service, metrics_service, _ = _build_service()
    business_mix_metric = _metric("business_mix_diversity", 4.0)
    metrics_service.analyze_business_mix_diversity.return_value = business_mix_metric

    artifact = service.analyze_site_selection(areas)

    assert business_mix_metric in artifact.metrics
