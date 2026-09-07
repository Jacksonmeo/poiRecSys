"""SiteSelectionArtifact 统一事实结果契约测试。"""

import pytest
from pydantic import ValidationError

from app.site_selection.schemas import (
    AnalysisMetadata,
    AreaFlowResult,
    CandidateArea,
    MetricResult,
    SiteSelectionArtifact,
)


def _metadata() -> AnalysisMetadata:
    return AnalysisMetadata(
        config_version="tokyo_coffee_v1",
        dataset="TSMC2014_TKY",
        observation_period="2012-04-03T18:17:18Z/2013-02-16T02:35:29Z",
    )


def _candidate_area() -> CandidateArea:
    return CandidateArea(area_id="shinjuku", display_name="Shinjuku")


def _metric() -> MetricResult:
    return MetricResult(
        metric_id="poi_count",
        value=120.0,
        description="分析区内的历史 POI 数量。",
    )


def _flow() -> AreaFlowResult:
    return AreaFlowResult(
        source_area="shinjuku",
        target_area="shibuya",
        flow_count=8,
        unique_users=3,
        unique_sessions=5,
    )


def test_site_selection_artifact_can_be_created() -> None:
    artifact = SiteSelectionArtifact(
        analysis_type="site_selection_facts",
        candidate_areas=[_candidate_area()],
        metadata=_metadata(),
        metrics=[_metric()],
        flows=[_flow()],
        summary="该结果仅汇总历史空间与行为事实。",
    )

    assert artifact.candidate_areas[0].area_id == "shinjuku"
    assert artifact.metadata == _metadata()
    assert artifact.metrics == [_metric()]
    assert artifact.flows == [_flow()]
    assert artifact.summary == "该结果仅汇总历史空间与行为事实。"


def test_site_selection_artifact_accepts_empty_metrics() -> None:
    artifact = SiteSelectionArtifact(
        analysis_type="site_selection_facts",
        candidate_areas=[_candidate_area()],
        metadata=_metadata(),
        metrics=[],
        flows=[_flow()],
    )

    assert artifact.metrics == []


def test_site_selection_artifact_accepts_empty_flows() -> None:
    artifact = SiteSelectionArtifact(
        analysis_type="site_selection_facts",
        candidate_areas=[_candidate_area()],
        metadata=_metadata(),
        metrics=[_metric()],
        flows=[],
    )

    assert artifact.flows == []


def test_site_selection_artifact_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SiteSelectionArtifact(
            analysis_type="site_selection_facts",
            candidate_areas=[_candidate_area()],
            metadata=_metadata(),
            metrics=[],
            flows=[],
            score=0.9,
        )


def test_site_selection_artifact_uses_strict_types() -> None:
    with pytest.raises(ValidationError):
        SiteSelectionArtifact(
            analysis_type=1,
            candidate_areas=[_candidate_area()],
            metadata=_metadata(),
            metrics=[],
            flows=[],
        )


def test_analysis_metadata_can_be_created() -> None:
    metadata = _metadata()

    assert metadata.config_version == "tokyo_coffee_v1"
    assert metadata.dataset == "TSMC2014_TKY"
    assert metadata.observation_period is not None


@pytest.mark.parametrize(
    "values",
    [
        {"config_version": " ", "dataset": "TSMC2014_TKY"},
        {"config_version": "tokyo_coffee_v1", "dataset": "\t"},
        {
            "config_version": "tokyo_coffee_v1",
            "dataset": "TSMC2014_TKY",
            "observation_period": "   ",
        },
    ],
)
def test_analysis_metadata_rejects_blank_strings(values: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="metadata string must not be blank"):
        AnalysisMetadata(**values)


def test_analysis_metadata_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisMetadata(
            config_version="tokyo_coffee_v1",
            dataset="TSMC2014_TKY",
            recommendation="shinjuku",
        )


def test_analysis_metadata_uses_strict_types() -> None:
    with pytest.raises(ValidationError):
        AnalysisMetadata(
            config_version=1,
            dataset="TSMC2014_TKY",
        )
