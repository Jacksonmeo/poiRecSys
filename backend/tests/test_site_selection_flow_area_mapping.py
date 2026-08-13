"""POI 到 CandidateArea 空间归属的 PostgreSQL/PostGIS 集成测试。"""

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.poi import Poi
from app.schemas.site_selection_config import CandidateArea
from app.site_selection.repositories import SiteSelectionFlowRepository
from app.site_selection.services import SiteSelectionFlowService
from scripts.generate_site_selection_config import (
    ANALYSIS_RADIUS_M,
    EARTH_RADIUS_M,
    POLYGON_SEGMENTS,
    make_polygon,
)


def _make_candidate_area(
    area_id: str,
    longitude: float,
    latitude: float,
) -> CandidateArea:
    center = {"longitude": longitude, "latitude": latitude}
    return CandidateArea.model_validate(
        {
            "area_id": area_id,
            "display_name": area_id,
            "center_reference": f"{area_id} test center",
            "center": center,
            "analysis_radius_m": ANALYSIS_RADIUS_M,
            "polygon": make_polygon(center),
            "polygon_provenance": {
                "method": "spherical_destination_point",
                "circle_type": "geodesic_circle_approximation",
                "generated_from": "candidate_area.center",
                "coordinate_order": "longitude_latitude",
                "radius_m": ANALYSIS_RADIUS_M,
                "segments": POLYGON_SEGMENTS,
                "earth_radius_m": EARTH_RADIUS_M,
                "generator": "backend/scripts/generate_site_selection_config.py",
            },
        }
    )


def _add_poi(
    db: Session,
    venue_id: str,
    longitude: float,
    latitude: float,
) -> None:
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


def _prepare_mapping(
    db: Session,
    candidate_areas: list[CandidateArea],
) -> dict[str, str]:
    repository = SiteSelectionFlowRepository(db=db)
    service = SiteSelectionFlowService(repository=repository)
    return service.prepare_area_mapping(candidate_areas)


def test_inside_boundary_and_outside_pois_are_mapped() -> None:
    area = _make_candidate_area("alpha", 139.7000, 35.6900)
    boundary_longitude, boundary_latitude = area.polygon.coordinates[0][0]
    with SessionLocal() as db:
        _add_poi(db, "inside", area.center.longitude, area.center.latitude)
        _add_poi(db, "boundary", boundary_longitude, boundary_latitude)
        _add_poi(db, "outside", 139.7500, 35.7500)
        db.commit()

        mapping = _prepare_mapping(db, [area])

        assert mapping == {
            "boundary": "alpha",
            "inside": "alpha",
            "outside": "outside_candidate_area",
        }


def test_overlapping_polygons_choose_nearest_center() -> None:
    west = _make_candidate_area("west", 139.7000, 35.6900)
    east = _make_candidate_area("east", 139.7050, 35.6900)
    with SessionLocal() as db:
        _add_poi(db, "overlap_near_east", east.center.longitude, east.center.latitude)
        db.commit()

        mapping = _prepare_mapping(db, [west, east])

        assert mapping["overlap_near_east"] == "east"


def test_equal_distance_overlap_uses_ascii_area_id_order() -> None:
    alpha = _make_candidate_area("alpha", 139.7000, 35.6900)
    zeta = _make_candidate_area("zeta", 139.7000, 35.6900)
    with SessionLocal() as db:
        _add_poi(db, "overlap_tie", alpha.center.longitude, alpha.center.latitude)
        db.commit()

        mapping = _prepare_mapping(db, [zeta, alpha])

        assert mapping["overlap_tie"] == "alpha"
