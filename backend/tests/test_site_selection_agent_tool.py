"""SiteSelection Agent Runtime Adapter 测试。"""

from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.agent.registry import AgentTool
from app.agent.tools.site_selection_agent_tool import SiteSelectionAgentTool
from app.site_selection.schemas import (
    AnalysisMetadata,
    CandidateArea,
    SiteSelectionArtifact,
)
from app.site_selection.tools import SiteSelectionTool


def _artifact() -> SiteSelectionArtifact:
    return SiteSelectionArtifact(
        analysis_type="site_selection",
        candidate_areas=[
            CandidateArea(area_id="shinjuku", display_name="Shinjuku")
        ],
        metadata=AnalysisMetadata(
            config_version="tokyo_coffee_v1",
            dataset="TSMC2014_TKY",
            observation_period="2012-04-03T18:17:18Z/2013-02-16T02:35:29Z",
        ),
        metrics=[],
        flows=[],
        summary=None,
    )


def _adapter(artifact: SiteSelectionArtifact | None = None) -> tuple[
    SiteSelectionAgentTool,
    Mock,
]:
    site_selection_tool = Mock(spec=SiteSelectionTool)
    site_selection_tool.analyze.return_value = artifact or _artifact()
    return SiteSelectionAgentTool(site_selection_tool), site_selection_tool


def test_site_selection_agent_tool_implements_agent_interface() -> None:
    adapter, _ = _adapter()

    assert isinstance(adapter, AgentTool)
    assert adapter.name == "analyze_site_selection"
    assert callable(adapter.run)


def test_run_accepts_db_and_args_and_returns_dict() -> None:
    adapter, site_selection_tool = _adapter()
    db = Mock(spec=Session)

    result = adapter.run(db, {"area_ids": ["shinjuku"]})

    assert isinstance(result, dict)
    site_selection_tool.analyze.assert_called_once_with(["shinjuku"])


def test_run_result_contains_artifact_fields() -> None:
    adapter, _ = _adapter()

    result = adapter.run(Mock(spec=Session), {"area_ids": ["shinjuku"]})

    assert set(result) == {
        "analysis_type",
        "candidate_areas",
        "metadata",
        "metrics",
        "flows",
        "summary",
    }
    assert result["analysis_type"] == "site_selection"
    assert result["candidate_areas"][0]["area_id"] == "shinjuku"
    assert result["metadata"]["config_version"] == "tokyo_coffee_v1"
