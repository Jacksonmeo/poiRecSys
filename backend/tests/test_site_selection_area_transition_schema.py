"""单次区域相邻迁移事实 Schema 的契约测试。"""

import pytest
from pydantic import ValidationError

from app.site_selection.schemas import AreaTransition


def test_area_transition_can_be_created() -> None:
    transition = AreaTransition(
        source_area="shinjuku",
        target_area="shibuya",
        session_id="TKY_user_1_1",
        user_id="user_1",
    )

    assert transition.source_area == "shinjuku"
    assert transition.target_area == "shibuya"
    assert transition.session_id == "TKY_user_1_1"
    assert transition.user_id == "user_1"


@pytest.mark.parametrize(
    ("source_area", "target_area", "session_id", "user_id"),
    [
        ("", "shibuya", "session_1", "user_1"),
        ("shinjuku", "   ", "session_1", "user_1"),
        ("shinjuku", "shibuya", "", "user_1"),
        ("shinjuku", "shibuya", "session_1", "\t"),
    ],
)
def test_area_transition_rejects_blank_identifiers(
    source_area: str,
    target_area: str,
    session_id: str,
    user_id: str,
) -> None:
    with pytest.raises(ValidationError):
        AreaTransition(
            source_area=source_area,
            target_area=target_area,
            session_id=session_id,
            user_id=user_id,
        )


def test_area_transition_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AreaTransition(
            source_area="shinjuku",
            target_area="shibuya",
            session_id="session_1",
            user_id="user_1",
            flow_count=1,
        )
