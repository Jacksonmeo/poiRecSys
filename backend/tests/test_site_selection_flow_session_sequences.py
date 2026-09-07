"""Session 内 POI 区域序列的 PostgreSQL/PostGIS 集成测试。"""

from datetime import datetime, timedelta, timezone

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.checkin import Checkin
from app.models.poi import Poi
from app.models.session import UserSession
from app.models.user import User
from app.schemas.site_selection_config import CandidateArea
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.repositories import SiteSelectionFlowRepository
from app.site_selection.services import SiteSelectionFlowService


def _get_candidate_areas() -> list[CandidateArea]:
    return load_site_selection_config().candidate_areas


def _add_reference_pois(db: Session, areas: list[CandidateArea]) -> None:
    area_by_id = {area.area_id: area for area in areas}
    poi_specs = [
        ("poi_shinjuku", area_by_id["shinjuku"].center.longitude,
         area_by_id["shinjuku"].center.latitude),
        ("poi_shibuya", area_by_id["shibuya"].center.longitude,
         area_by_id["shibuya"].center.latitude),
        ("poi_outside", 139.7500, 35.7500),
    ]
    for venue_id, longitude, latitude in poi_specs:
        db.add(
            Poi(
                venue_id=venue_id,
                display_name=venue_id,
                venue_category="Test",
                longitude=longitude,
                latitude=latitude,
                geom=WKTElement(f"POINT({longitude} {latitude})", srid=4326),
            )
        )


def _add_session(
    db: Session,
    session_id: str,
    user_id: str,
    venue_sequence: list[tuple[str, int | None]],
    dataset: str = "TKY",
    declared_count: int | None = None,
) -> None:
    start_time = datetime(2012, 4, 4, 1, 0, tzinfo=timezone.utc)
    db.add(
        UserSession(
            session_id=session_id,
            user_id=user_id,
            start_time=start_time,
            end_time=start_time + timedelta(hours=1),
            checkin_count=declared_count or len(venue_sequence),
            dataset=dataset,
        )
    )
    for index, (venue_id, sequence_no) in enumerate(venue_sequence, start=1):
        time_order = sequence_no if sequence_no is not None else index
        db.add(
            Checkin(
                user_id=user_id,
                venue_id=venue_id,
                timezone_offset=540,
                utc_timestamp=start_time + timedelta(minutes=10 * time_order),
                session_id=session_id,
                sequence_no=sequence_no,
            )
        )


def _prepare_sequences(db: Session, areas: list[CandidateArea]):
    repository = SiteSelectionFlowRepository(db=db)
    service = SiteSelectionFlowService(repository=repository)
    return service.prepare_session_area_sequences(areas)


def test_session_area_sequence_preserves_sequence_number_order() -> None:
    areas = _get_candidate_areas()
    with SessionLocal() as db:
        db.add(User(user_id="user_order"))
        _add_reference_pois(db, areas)
        _add_session(
            db,
            "session_order",
            "user_order",
            [("poi_shibuya", 2), ("poi_shinjuku", 1), ("poi_shinjuku", 3)],
        )
        db.commit()

        sequences = _prepare_sequences(db, areas)

        assert sequences[0].areas == ["shinjuku", "shibuya", "shinjuku"]


def test_session_area_sequence_preserves_outside_state() -> None:
    areas = _get_candidate_areas()
    with SessionLocal() as db:
        db.add(User(user_id="user_outside"))
        _add_reference_pois(db, areas)
        _add_session(
            db,
            "session_outside",
            "user_outside",
            [("poi_shinjuku", 1), ("poi_outside", 2), ("poi_shibuya", 3)],
        )
        db.commit()

        sequences = _prepare_sequences(db, areas)

        assert sequences[0].areas == [
            "shinjuku",
            "outside_candidate_area",
            "shibuya",
        ]


def test_different_sessions_remain_separate() -> None:
    areas = _get_candidate_areas()
    with SessionLocal() as db:
        db.add_all([User(user_id="user_a"), User(user_id="user_b")])
        _add_reference_pois(db, areas)
        _add_session(
            db, "session_a", "user_a", [("poi_shinjuku", 1), ("poi_shibuya", 2)]
        )
        _add_session(
            db, "session_b", "user_b", [("poi_shibuya", 1), ("poi_shinjuku", 2)]
        )
        db.commit()

        sequences = _prepare_sequences(db, areas)

        assert [(item.session_id, item.user_id, item.areas) for item in sequences] == [
            ("session_a", "user_a", ["shinjuku", "shibuya"]),
            ("session_b", "user_b", ["shibuya", "shinjuku"]),
        ]


def test_invalid_sessions_are_filtered_as_whole_sessions() -> None:
    areas = _get_candidate_areas()
    with SessionLocal() as db:
        user_ids = ["user_valid", "user_dataset", "user_null", "user_count"]
        db.add_all([User(user_id=user_id) for user_id in user_ids])
        _add_reference_pois(db, areas)
        _add_session(
            db, "session_valid", "user_valid",
            [("poi_shinjuku", 1), ("poi_shibuya", 2)]
        )
        _add_session(
            db, "session_wrong_dataset", "user_dataset",
            [("poi_shinjuku", 1), ("poi_shibuya", 2)], dataset="OSA"
        )
        _add_session(
            db, "session_null_sequence", "user_null",
            [("poi_shinjuku", 1), ("poi_shibuya", None)]
        )
        _add_session(
            db, "session_count_mismatch", "user_count",
            [("poi_shinjuku", 1), ("poi_shibuya", 2)], declared_count=3
        )
        db.commit()

        sequences = _prepare_sequences(db, areas)

        assert [item.session_id for item in sequences] == ["session_valid"]
