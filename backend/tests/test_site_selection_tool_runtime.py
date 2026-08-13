"""SiteSelection Tool 的 Function Calling Runtime 适配测试。"""

from unittest.mock import Mock, patch

import pytest

from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.schemas import (
    AnalysisMetadata,
    CandidateArea,
    SiteSelectionArtifact,
)
from app.site_selection.services import SiteSelectionAnalysisService
from app.site_selection.tools import SiteSelectionTool


def _artifact(area_id: str = "shinjuku") -> SiteSelectionArtifact:
    config = load_site_selection_config()
    area = next(area for area in config.candidate_areas if area.area_id == area_id)
    return SiteSelectionArtifact(
        analysis_type="site_selection",
        candidate_areas=[
            CandidateArea(area_id=area.area_id, display_name=area.display_name)
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


def test_run_executes_existing_analyze_method() -> None:
    tool = SiteSelectionTool(Mock(spec=SiteSelectionAnalysisService))
    expected_artifact = _artifact()

    with patch.object(tool, "analyze", return_value=expected_artifact) as analyze:
        result = tool.run({"area_ids": ["shinjuku"]})

    assert result is expected_artifact
    analyze.assert_called_once_with(["shinjuku"])


def test_run_rejects_missing_area_ids() -> None:
    tool = SiteSelectionTool(Mock(spec=SiteSelectionAnalysisService))

    with pytest.raises(ValueError, match="Invalid SiteSelectionTool arguments"):
        tool.run({})


def test_run_rejects_invalid_area_ids_type() -> None:
    tool = SiteSelectionTool(Mock(spec=SiteSelectionAnalysisService))

    with pytest.raises(ValueError, match="Invalid SiteSelectionTool arguments"):
        tool.run({"area_ids": "shinjuku"})


def test_run_returns_site_selection_artifact() -> None:
    analysis_service = Mock(spec=SiteSelectionAnalysisService)
    analysis_service.analyze_site_selection.return_value = _artifact()
    tool = SiteSelectionTool(analysis_service)

    result = tool.run({"area_ids": ["shinjuku"]})

    assert isinstance(result, SiteSelectionArtifact)
