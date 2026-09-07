"""Flow Analysis 完整 Service 编排入口测试。"""

from unittest.mock import Mock, call

from app.schemas.site_selection_config import CandidateArea
from app.site_selection.repositories import SiteSelectionFlowRepository
from app.site_selection.schemas import (
    AreaFlowResult,
    AreaTransition,
    SessionAreaSequence,
)
from app.site_selection.services import SiteSelectionFlowService


def _build_service() -> tuple[SiteSelectionFlowService, Mock]:
    repository = Mock(spec=SiteSelectionFlowRepository)
    return SiteSelectionFlowService(repository=repository), repository


def test_analyze_area_flows_runs_complete_pipeline() -> None:
    service, repository = _build_service()
    candidate_areas = [Mock(spec=CandidateArea)]
    repository.get_session_area_sequences.return_value = [
        SessionAreaSequence(
            session_id="session-1",
            user_id="user-1",
            areas=["shinjuku", "shibuya", "ginza"],
        )
    ]

    results = service.analyze_area_flows(candidate_areas)

    assert results == [
        AreaFlowResult(
            source_area="shibuya",
            target_area="ginza",
            flow_count=1,
            unique_users=1,
            unique_sessions=1,
        ),
        AreaFlowResult(
            source_area="shinjuku",
            target_area="shibuya",
            flow_count=1,
            unique_users=1,
            unique_sessions=1,
        ),
    ]
    repository.get_session_area_sequences.assert_called_once_with(candidate_areas)


def test_analyze_area_flows_returns_empty_list_for_empty_data() -> None:
    service, repository = _build_service()
    candidate_areas = [Mock(spec=CandidateArea)]
    repository.get_session_area_sequences.return_value = []

    assert service.analyze_area_flows(candidate_areas) == []


def test_analyze_area_flows_calls_three_stages_in_order() -> None:
    service, _ = _build_service()
    candidate_areas = [Mock(spec=CandidateArea)]
    sequences = [
        SessionAreaSequence(
            session_id="session-1",
            user_id="user-1",
            areas=["shinjuku", "shibuya"],
        )
    ]
    transitions = [
        AreaTransition(
            source_area="shinjuku",
            target_area="shibuya",
            session_id="session-1",
            user_id="user-1",
        )
    ]
    flows = [
        AreaFlowResult(
            source_area="shinjuku",
            target_area="shibuya",
            flow_count=1,
            unique_users=1,
            unique_sessions=1,
        )
    ]
    service.prepare_session_area_sequences = Mock(return_value=sequences)
    service.build_area_transitions = Mock(return_value=transitions)
    service.aggregate_area_flows = Mock(return_value=flows)
    stage_calls = Mock()
    stage_calls.attach_mock(service.prepare_session_area_sequences, "prepare")
    stage_calls.attach_mock(service.build_area_transitions, "build")
    stage_calls.attach_mock(service.aggregate_area_flows, "aggregate")

    results = service.analyze_area_flows(candidate_areas)

    assert results == flows
    assert stage_calls.mock_calls == [
        call.prepare(candidate_areas),
        call.build(sequences),
        call.aggregate(transitions),
    ]
