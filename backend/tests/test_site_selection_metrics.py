"""SiteSelection 第一批 PostGIS 指标的测试。"""

from unittest.mock import Mock

from geoalchemy2 import WKTElement

from app.db.database import SessionLocal
from app.models.poi import Poi
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.repositories import SiteSelectionRepository
from app.site_selection.services import SiteSelectionService


def _get_shinjuku_area():
    config = load_site_selection_config()
    return next(area for area in config.candidate_areas if area.area_id == "shinjuku")


def test_repository_queries_can_execute(seeded: dict[str, object]) -> None:
    area = _get_shinjuku_area()
    with SessionLocal() as db:
        db.add(
            Poi(
                venue_id="site_selection_competitor",
                display_name="Test Coffee",
                venue_category="Coffee Shop",
                latitude=area.center.latitude,
                longitude=area.center.longitude,
                geom=WKTElement(
                    f"POINT({area.center.longitude} {area.center.latitude})",
                    srid=4326,
                ),
            )
        )
        db.commit()
        repository = SiteSelectionRepository(db=db)

        assert repository.get_poi_count(area) == 2
        assert repository.get_competitor_count(
            area, ["Coffee Shop", "Café"]
        ) == 1


def test_service_combines_basic_metric_results() -> None:
    area = _get_shinjuku_area()
    repository = Mock(spec=SiteSelectionRepository)
    repository.get_poi_count.return_value = 3160
    repository.get_competitor_count.return_value = 195
    service = SiteSelectionService(
        repository=repository,
        competitor_categories=["Coffee Shop", "Café"],
    )

    result = service.analyze_basic_metrics(area)

    assert result.area_id == "shinjuku"
    assert [(metric.metric_id, metric.value) for metric in result.metrics] == [
        ("poi_count", 3160.0),
        ("competitor_count", 195.0),
    ]
    assert result.score is None
    assert result.explanation is None
