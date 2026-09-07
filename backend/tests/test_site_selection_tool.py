"""SiteSelection Tool 适配层测试。"""

from unittest.mock import Mock, call

import pytest

from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.schemas import (
    AnalysisMetadata,
    CandidateArea,
    SiteSelectionArtifact,
)
from app.site_selection.services import SiteSelectionAnalysisService
from app.site_selection.tools import SiteSelectionTool


def _artifact(area_ids: list[str]) -> SiteSelectionArtifact:
    config = load_site_selection_config()
    areas_by_id = {area.area_id: area for area in config.candidate_areas}
    return SiteSelectionArtifact(
        analysis_type="site_selection",
        candidate_areas=[
            CandidateArea(
                area_id=area_id,
                display_name=areas_by_id[area_id].display_name,
            )
            for area_id in area_ids
        ],
        metadata=AnalysisMetadata(
            config_version=config.config_version,
            dataset=config.dataset.name,
            observation_period="2012-04-03T18:17:18Z/2013-02-16T02:35:29Z",
        ),
        metrics=[],
        flows=[],
        summary=None,
    )


def test_site_selection_tool_returns_analysis_artifact() -> None:
    analysis_service = Mock(spec=SiteSelectionAnalysisService)
    expected_artifact = _artifact(["shinjuku", "shibuya"])
    analysis_service.analyze_site_selection.return_value = expected_artifact
    tool = SiteSelectionTool(analysis_service)

    result = tool.analyze(["shinjuku", "shibuya"])

    assert result is expected_artifact
    candidate_areas = analysis_service.analyze_site_selection.call_args.args[0]
    assert [area.area_id for area in candidate_areas] == ["shinjuku", "shibuya"]


def test_site_selection_tool_rejects_unknown_area_id() -> None:
    analysis_service = Mock(spec=SiteSelectionAnalysisService)
    tool = SiteSelectionTool(analysis_service)

    with pytest.raises(ValueError, match="Unknown candidate area_id: unknown_area"):
        tool.analyze(["shinjuku", "unknown_area"])

    analysis_service.analyze_site_selection.assert_not_called()


def test_site_selection_tool_only_delegates_analysis() -> None:
    analysis_service = Mock(spec=SiteSelectionAnalysisService)
    expected_artifact = _artifact(["ginza"])
    analysis_service.analyze_site_selection.return_value = expected_artifact
    tool = SiteSelectionTool(analysis_service)

    result = tool.analyze(["ginza"])

    candidate_areas = analysis_service.analyze_site_selection.call_args.args[0]
    assert result is expected_artifact
    assert analysis_service.mock_calls == [
        call.analyze_site_selection(candidate_areas)
    ]
