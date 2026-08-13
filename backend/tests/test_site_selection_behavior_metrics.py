"""历史签到规模指标的 PostgreSQL/PostGIS 集成测试。"""

from datetime import datetime, timezone

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.checkin import Checkin
from app.models.poi import Poi
from app.schemas.site_selection_config import CandidateArea
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.repositories import SiteSelectionRepository
from app.site_selection.services import SiteSelectionService


def _get_shinjuku_area() -> CandidateArea:
    config = load_site_selection_config()
    return next(area for area in config.candidate_areas if area.area_id == "shinjuku")


def _add_behavior_records(db: Session, area: CandidateArea) -> None:
    venue_id = "site_selection_behavior_poi"
    db.add(
        Poi(
            venue_id=venue_id,
            display_name="Behavior Test POI",
            venue_category="Bakery",
            latitude=area.center.latitude,
            longitude=area.center.longitude,
            geom=WKTElement(
                f"POINT({area.center.longitude} {area.center.latitude})",
                srid=4326,
            ),
        )
    )
    db.add_all(
        [
            Checkin(
                user_id=user_id,
                venue_id=venue_id,
                timezone_offset=540,
                utc_timestamp=datetime(2026, 1, 2, hour, tzinfo=timezone.utc),
            )
            for hour, user_id in [(10, "user_1"), (11, "user_1"), (12, "user_2")]
        ]
    )
    db.commit()


def test_historical_checkin_count_uses_poi_spatial_join(
    seeded: dict[str, object],
) -> None:
    area = _get_shinjuku_area()
    with SessionLocal() as db:
        _add_behavior_records(db, area)
        repository = SiteSelectionRepository(db=db)

        assert repository.get_historical_checkin_count(area) == 4


def test_unique_user_count_and_service_result(
    seeded: dict[str, object],
) -> None:
    area = _get_shinjuku_area()
    with SessionLocal() as db:
        _add_behavior_records(db, area)
        repository = SiteSelectionRepository(db=db)
        service = SiteSelectionService(repository=repository)

        assert repository.get_unique_user_count(area) == 2

        result = service.analyze_behavior_metrics(area)
        assert [(metric.metric_id, metric.value) for metric in result.metrics] == [
            ("historical_checkin_count", 4.0),
            ("unique_user_count", 2.0),
        ]
        assert result.score is None
        assert result.explanation is None
