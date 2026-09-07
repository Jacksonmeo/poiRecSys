"""SiteSelection 分析 API 测试。"""

from collections.abc import Iterator
from unittest.mock import Mock

import pytest

from app.api.dependencies.site_selection import (
    get_site_selection_analysis_service,
)
from app.main import app
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.schemas import (
    AnalysisMetadata,
    AreaFlowResult,
    CandidateArea,
    SiteSelectionArtifact,
)
from app.site_selection.services import SiteSelectionAnalysisService
from tests.conftest import client


def _artifact(
    area_ids: list[str],
    flows: list[AreaFlowResult] | None = None,
) -> SiteSelectionArtifact:
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
        flows=flows or [],
        summary=None,
    )


@pytest.fixture
def analysis_service() -> Iterator[Mock]:
    service = Mock(spec=SiteSelectionAnalysisService)

    def override_service() -> Mock:
        return service

    app.dependency_overrides[get_site_selection_analysis_service] = override_service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(get_site_selection_analysis_service, None)


def test_analyze_site_selection_returns_artifact(analysis_service: Mock) -> None:
    analysis_service.analyze_site_selection.return_value = _artifact(["shinjuku"])

    response = client.post(
        "/api/site-selection/analyze",
        json={"area_ids": ["shinjuku"]},
    )

    assert response.status_code == 200
    assert response.json()["data"]["candidate_areas"][0]["area_id"] == "shinjuku"
    candidate_areas = analysis_service.analyze_site_selection.call_args.args[0]
    assert [area.area_id for area in candidate_areas] == ["shinjuku"]


def test_analyze_site_selection_unknown_area_returns_404(
    analysis_service: Mock,
) -> None:
    response = client.post(
        "/api/site-selection/analyze",
        json={"area_ids": ["unknown_area"]},
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "message": "Candidate area 'unknown_area' was not found.",
        "data": None,
    }
    analysis_service.analyze_site_selection.assert_not_called()


def test_analyze_site_selection_uses_api_response_envelope(
    analysis_service: Mock,
) -> None:
    analysis_service.analyze_site_selection.return_value = _artifact(["shibuya"])

    response = client.post(
        "/api/site-selection/analyze",
        json={"area_ids": ["shibuya"]},
    )

    assert response.status_code == 200
    assert set(response.json()) == {"code", "message", "data"}
    assert response.json()["code"] == 0
    assert response.json()["message"] == "success"


def test_analyze_site_selection_returns_multi_area_flow(
    analysis_service: Mock,
) -> None:
    flow = AreaFlowResult(
        source_area="shinjuku",
        target_area="shibuya",
        flow_count=5,
        unique_users=2,
        unique_sessions=3,
    )
    analysis_service.analyze_site_selection.return_value = _artifact(
        ["shinjuku", "shibuya"],
        flows=[flow],
    )

    response = client.post(
        "/api/site-selection/analyze",
        json={"area_ids": ["shinjuku", "shibuya"]},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [area["area_id"] for area in data["candidate_areas"]] == [
        "shinjuku",
        "shibuya",
    ]
    assert data["flows"] == [flow.model_dump()]


@pytest.mark.parametrize(
    "payload",
    [
        {"area_ids": []},
        {"area_ids": ["   "]},
        {"area_ids": ["shinjuku"], "score": 1.0},
    ],
)
def test_analyze_site_selection_rejects_invalid_request(
    analysis_service: Mock,
    payload: dict[str, object],
) -> None:
    response = client.post("/api/site-selection/analyze", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == 422
    analysis_service.analyze_site_selection.assert_not_called()
