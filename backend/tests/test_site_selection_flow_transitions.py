"""Session 区域序列到相邻迁移事实的纯业务逻辑测试。"""

from unittest.mock import Mock

from app.site_selection.repositories import SiteSelectionFlowRepository
from app.site_selection.schemas import AreaTransition, SessionAreaSequence
from app.site_selection.services import SiteSelectionFlowService


def _build_service() -> SiteSelectionFlowService:
    repository = Mock(spec=SiteSelectionFlowRepository)
    return SiteSelectionFlowService(repository=repository)


def _transition_values(
    transitions: list[AreaTransition],
) -> list[tuple[str, str, str, str]]:
    return [
        (
            transition.source_area,
            transition.target_area,
            transition.session_id,
            transition.user_id,
        )
        for transition in transitions
    ]


def test_build_area_transitions_creates_adjacent_pairs_without_mutation() -> None:
    sequence = SessionAreaSequence(
        session_id="session_1",
        user_id="user_1",
        areas=["area_a", "area_b", "area_c"],
    )
    original_areas = sequence.areas.copy()

    transitions = _build_service().build_area_transitions([sequence])

    assert _transition_values(transitions) == [
        ("area_a", "area_b", "session_1", "user_1"),
        ("area_b", "area_c", "session_1", "user_1"),
    ]
    assert sequence.areas == original_areas


def test_build_area_transitions_filters_same_area_pairs() -> None:
    sequence = SessionAreaSequence(
        session_id="session_same",
        user_id="user_same",
        areas=["area_a", "area_a", "area_b", "area_b", "area_c"],
    )

    transitions = _build_service().build_area_transitions([sequence])

    assert _transition_values(transitions) == [
        ("area_a", "area_b", "session_same", "user_same"),
        ("area_b", "area_c", "session_same", "user_same"),
    ]


def test_build_area_transitions_filters_outside_endpoints() -> None:
    sequence = SessionAreaSequence(
        session_id="session_outside",
        user_id="user_outside",
        areas=[
            "area_a",
            "outside_candidate_area",
            "area_b",
            "area_c",
            "outside_candidate_area",
            "area_d",
        ],
    )

    transitions = _build_service().build_area_transitions([sequence])

    assert _transition_values(transitions) == [
        ("area_b", "area_c", "session_outside", "user_outside")
    ]


def test_build_area_transitions_does_not_mix_sessions() -> None:
    sequences = [
        SessionAreaSequence(
            session_id="session_a",
            user_id="user_a",
            areas=["area_a", "area_b"],
        ),
        SessionAreaSequence(
            session_id="session_b",
            user_id="user_b",
            areas=["area_c", "area_d"],
        ),
    ]

    transitions = _build_service().build_area_transitions(sequences)

    assert _transition_values(transitions) == [
        ("area_a", "area_b", "session_a", "user_a"),
        ("area_c", "area_d", "session_b", "user_b"),
    ]


def test_build_area_transitions_handles_empty_areas() -> None:
    empty_sequence = SessionAreaSequence.model_construct(
        session_id="session_empty",
        user_id="user_empty",
        areas=[],
    )

    transitions = _build_service().build_area_transitions([empty_sequence])

    assert transitions == []
