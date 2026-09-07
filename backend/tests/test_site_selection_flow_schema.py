"""区域行为流向结果 Schema 的契约测试。"""

import pytest
from pydantic import ValidationError

from app.site_selection.schemas import AreaFlowResult


def test_area_flow_result_can_be_created() -> None:
    result = AreaFlowResult(
        source_area="shinjuku",
        target_area="shibuya",
        flow_count=12,
        unique_users=5,
        unique_sessions=8,
    )

    assert result.source_area == "shinjuku"
    assert result.target_area == "shibuya"
    assert result.flow_count == 12
    assert result.unique_users == 5
    assert result.unique_sessions == 8


@pytest.mark.parametrize(
    ("flow_count", "unique_users", "unique_sessions"),
    [
        (0, 1, 1),
        (2, 0, 1),
        (3, 2, 1),
        (2, 1, 3),
    ],
)
def test_area_flow_result_rejects_invalid_counts(
    flow_count: int,
    unique_users: int,
    unique_sessions: int,
) -> None:
    with pytest.raises(ValidationError):
        AreaFlowResult(
            source_area="shinjuku",
            target_area="shibuya",
            flow_count=flow_count,
            unique_users=unique_users,
            unique_sessions=unique_sessions,
        )


@pytest.mark.parametrize(
    ("source_area", "target_area"),
    [("", "shibuya"), ("shinjuku", "   ")],
)
def test_area_flow_result_rejects_blank_area_ids(
    source_area: str,
    target_area: str,
) -> None:
    with pytest.raises(ValidationError):
        AreaFlowResult(
            source_area=source_area,
            target_area=target_area,
            flow_count=1,
            unique_users=1,
            unique_sessions=1,
        )


def test_area_flow_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AreaFlowResult(
            source_area="shinjuku",
            target_area="shibuya",
            flow_count=2,
            unique_users=1,
            unique_sessions=1,
            score=0.5,
        )
