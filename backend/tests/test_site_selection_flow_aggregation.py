"""AreaTransition 到 AreaFlowResult 的纯业务聚合测试。"""

from unittest.mock import Mock

from app.site_selection.schemas import AreaTransition
from app.site_selection.services import SiteSelectionFlowService


def _build_service() -> SiteSelectionFlowService:
    return SiteSelectionFlowService(repository=Mock())


def _transition(
    source_area: str,
    target_area: str,
    session_id: str,
    user_id: str,
) -> AreaTransition:
    return AreaTransition(
        source_area=source_area,
        target_area=target_area,
        session_id=session_id,
        user_id=user_id,
    )


def test_aggregate_area_flows_groups_same_area_pair() -> None:
    service = _build_service()
    transitions = [
        _transition("shinjuku", "shibuya", "session-1", "user-1"),
        _transition("shinjuku", "shibuya", "session-1", "user-1"),
        _transition("ginza", "shibuya", "session-2", "user-2"),
    ]

    results = service.aggregate_area_flows(transitions)

    assert [(result.source_area, result.target_area) for result in results] == [
        ("shinjuku", "shibuya"),
        ("ginza", "shibuya"),
    ]
    assert results[0].flow_count == 2
    assert results[0].unique_users == 1
    assert results[0].unique_sessions == 1


def test_aggregate_area_flows_counts_unique_users() -> None:
    service = _build_service()
    transitions = [
        _transition("shinjuku", "ginza", "session-1", "user-1"),
        _transition("shinjuku", "ginza", "session-2", "user-2"),
        _transition("shinjuku", "ginza", "session-3", "user-2"),
    ]

    result = service.aggregate_area_flows(transitions)[0]

    assert result.flow_count == 3
    assert result.unique_users == 2


def test_aggregate_area_flows_counts_unique_sessions() -> None:
    service = _build_service()
    transitions = [
        _transition("ikebukuro", "shinjuku", "session-1", "user-1"),
        _transition("ikebukuro", "shinjuku", "session-2", "user-1"),
        _transition("ikebukuro", "shinjuku", "session-2", "user-1"),
    ]

    result = service.aggregate_area_flows(transitions)[0]

    assert result.flow_count == 3
    assert result.unique_sessions == 2


def test_aggregate_area_flows_returns_empty_list_for_empty_input() -> None:
    service = _build_service()

    assert service.aggregate_area_flows([]) == []


def test_aggregate_area_flows_does_not_modify_input() -> None:
    service = _build_service()
    transitions = [
        _transition("shibuya", "ginza", "session-1", "user-1"),
        _transition("shibuya", "ginza", "session-2", "user-1"),
    ]
    original_values = [transition.model_dump() for transition in transitions]

    service.aggregate_area_flows(transitions)

    assert [transition.model_dump() for transition in transitions] == original_values
