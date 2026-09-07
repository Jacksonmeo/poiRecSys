"""交通设施与商业业态覆盖指标的 PostGIS 集成测试。"""

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.poi import Poi
from app.schemas.site_selection_config import CandidateArea, SiteSelectionConfig
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.repositories import SiteSelectionRepository
from app.site_selection.services import SiteSelectionService


def _get_config_and_shinjuku_area() -> tuple[SiteSelectionConfig, CandidateArea]:
    config = load_site_selection_config()
    area = next(
        candidate
        for candidate in config.candidate_areas
        if candidate.area_id == "shinjuku"
    )
    return config, area


def _add_area_poi(
    db: Session,
    area: CandidateArea,
    venue_id: str,
    category: str,
) -> None:
    db.add(
        Poi(
            venue_id=venue_id,
            display_name=f"Test {category}",
            venue_category=category,
            latitude=area.center.latitude,
            longitude=area.center.longitude,
            geom=WKTElement(
                f"POINT({area.center.longitude} {area.center.latitude})",
                srid=4326,
            ),
        )
    )


def test_transport_poi_query_uses_configured_categories(
    seeded: dict[str, object],
) -> None:
    config, area = _get_config_and_shinjuku_area()
    with SessionLocal() as db:
        _add_area_poi(db, area, "site_selection_station", "Train Station")
        _add_area_poi(db, area, "site_selection_non_transport", "Bakery")
        db.commit()
        repository = SiteSelectionRepository(db=db)
        service = SiteSelectionService(repository=repository)

        metric = service.analyze_transport_poi_count(
            area,
            config.transport_categories,
        )

        assert repository.get_transport_poi_count(
            area, config.transport_categories
        ) == 1
        assert (metric.metric_id, metric.value) == ("transport_poi_count", 1.0)


def test_business_mix_queries_presence_and_service_sums_covered_groups(
    seeded: dict[str, object],
) -> None:
    config, area = _get_config_and_shinjuku_area()
    with SessionLocal() as db:
        _add_area_poi(db, area, "site_selection_bakery", "Bakery")
        _add_area_poi(db, area, "site_selection_mall", "Shopping Mall")
        db.commit()
        repository = SiteSelectionRepository(db=db)
        service = SiteSelectionService(repository=repository)

        group_presence = repository.get_business_mix_group_presence(
            area,
            config.business_mix_groups,
        )
        metric = service.analyze_business_mix_diversity(
            area,
            config.business_mix_groups,
        )

        assert group_presence == {
            "food_and_dining": True,
            "retail": True,
            "leisure_and_culture": False,
            "nightlife": False,
        }
        assert (metric.metric_id, metric.value) == (
            "business_mix_diversity",
            2.0,
        )
