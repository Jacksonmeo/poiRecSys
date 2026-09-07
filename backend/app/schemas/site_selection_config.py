"""Strict Pydantic contract for versioned retail site-selection configuration."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPPORTED_CONFIG_VERSION = "tokyo_coffee_v1"
REQUIRED_AREA_IDS = frozenset({"shinjuku", "shibuya", "ginza", "ikebukuro"})
MANDATORY_METRIC_IDS = frozenset(
    {
        "poi_count",
        "historical_checkin_count",
        "competitor_count",
        "transport_poi_count",
        "business_mix_diversity",
    }
)
REQUIRED_PROHIBITED_CLAIMS = frozenset(
    {
        "人口",
        "实时客流",
        "销售额",
        "租金",
        "转化率",
        "成功率",
        "population",
        "real-time foot traffic",
        "sales revenue",
        "rent",
        "conversion rate",
        "success rate",
    }
)


class StrictConfigModel(BaseModel):
    """Base model that rejects coercion and undeclared fields."""

    model_config = ConfigDict(extra="forbid", strict=True)


class DatasetInfo(StrictConfigModel):
    """Identity and limitations of the historical source dataset."""

    name: Literal["TSMC2014_TKY"]
    source: Literal["Foursquare"]
    city_subset: Literal["Tokyo"]
    source_artifact: Literal["dataset_TSMC2014_TKY.csv"]
    sample_type: Literal["historical_checkin_sample"]
    sample_description: Literal[
        "Foursquare Tokyo 2012-2013 historical check-in sample"
    ]
    is_historical: Literal[True]
    limitations: list[str] = Field(min_length=1)


class ObservationPeriod(StrictConfigModel):
    """Inclusive temporal coverage recorded by the source sample."""

    start_at: datetime
    end_at: datetime
    timezone: Literal["UTC"]

    @model_validator(mode="after")
    def validate_period(self) -> "ObservationPeriod":
        """校验观测周期：时间必须带时区且 start 早于 end。"""
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("observation_period timestamps must be timezone-aware")
        if self.start_at >= self.end_at:
            raise ValueError("observation_period.start_at must precede end_at")
        return self


class CenterPoint(StrictConfigModel):
    """WGS84 point in explicit longitude/latitude fields."""

    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class PolygonProvenance(StrictConfigModel):
    """Reproducibility metadata for a generated analysis circle."""

    method: Literal["spherical_destination_point"]
    circle_type: Literal["geodesic_circle_approximation"]
    generated_from: Literal["candidate_area.center"]
    coordinate_order: Literal["longitude_latitude"]
    radius_m: Literal[1000]
    segments: int = Field(ge=32)
    earth_radius_m: float = Field(gt=6_000_000, lt=7_000_000)
    generator: Literal["backend/scripts/generate_site_selection_config.py"]


def _orientation(
    point_a: list[float], point_b: list[float], point_c: list[float]
) -> float:
    """计算三点叉积方向（用于线段相交判定）。"""
    return (point_b[0] - point_a[0]) * (point_c[1] - point_a[1]) - (
        point_b[1] - point_a[1]
    ) * (point_c[0] - point_a[0])


def _segments_cross(
    a1: list[float], a2: list[float], b1: list[float], b2: list[float]
) -> bool:
    """判断两条线段是否严格相交（跨立实验）。"""
    epsilon = 1e-14
    o1 = _orientation(a1, a2, b1)
    o2 = _orientation(a1, a2, b2)
    o3 = _orientation(b1, b2, a1)
    o4 = _orientation(b1, b2, a2)
    return (
        ((o1 > epsilon and o2 < -epsilon) or (o1 < -epsilon and o2 > epsilon))
        and ((o3 > epsilon and o4 < -epsilon) or (o3 < -epsilon and o4 > epsilon))
    )


class GeoJSONPolygon(StrictConfigModel):
    """Single-ring RFC 7946 Polygon with longitude/latitude positions."""

    type: Literal["Polygon"]
    coordinates: list[list[list[float]]]

    @model_validator(mode="after")
    def validate_polygon(self) -> "GeoJSONPolygon":
        """校验多边形：单环、闭合、无自交且面积非零。"""
        if len(self.coordinates) != 1:
            raise ValueError("candidate Polygon must contain exactly one exterior ring")

        ring = self.coordinates[0]
        if len(ring) < 4:
            raise ValueError("candidate Polygon ring must contain at least 4 positions")
        for position in ring:
            if len(position) != 2:
                raise ValueError("GeoJSON positions must be [longitude, latitude]")
            longitude, latitude = position
            if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                raise ValueError("GeoJSON position is outside longitude/latitude bounds")

        if ring[0] != ring[-1]:
            raise ValueError("candidate Polygon ring must be closed")
        if len({tuple(position) for position in ring[:-1]}) < 3:
            raise ValueError("candidate Polygon requires at least 3 distinct vertices")

        signed_area = sum(
            ring[index][0] * ring[index + 1][1]
            - ring[index + 1][0] * ring[index][1]
            for index in range(len(ring) - 1)
        )
        if math.isclose(signed_area, 0.0, abs_tol=1e-14):
            raise ValueError("candidate Polygon must have non-zero area")

        segment_count = len(ring) - 1
        for first in range(segment_count):
            for second in range(first + 1, segment_count):
                if second == first + 1:
                    continue
                if first == 0 and second == segment_count - 1:
                    continue
                if _segments_cross(
                    ring[first],
                    ring[first + 1],
                    ring[second],
                    ring[second + 1],
                ):
                    raise ValueError("candidate Polygon ring must not self-intersect")
        return self


def _haversine_distance_m(center: CenterPoint, position: list[float]) -> float:
    """计算中心点与经纬度位置间的球面距离（米）。"""
    earth_radius_m = 6_371_008.8
    longitude, latitude = position
    lat1 = math.radians(center.latitude)
    lat2 = math.radians(latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(longitude - center.longitude)
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(
        lat2
    ) * math.sin(delta_lon / 2) ** 2
    return 2 * earth_radius_m * math.asin(min(1.0, math.sqrt(haversine)))


class CandidateArea(StrictConfigModel):
    """One station-centred, uniformly generated candidate analysis area."""

    area_id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1)
    center_reference: str = Field(min_length=1)
    center: CenterPoint
    analysis_radius_m: Literal[1000]
    polygon: GeoJSONPolygon
    polygon_provenance: PolygonProvenance

    @model_validator(mode="after")
    def validate_generated_circle(self) -> "CandidateArea":
        """校验候选区：半径/段数与来源一致且顶点落在圆上。"""
        ring = self.polygon.coordinates[0]
        if self.polygon_provenance.radius_m != self.analysis_radius_m:
            raise ValueError("polygon provenance radius must match analysis_radius_m")
        if len(ring) - 1 != self.polygon_provenance.segments:
            raise ValueError("polygon vertex count must match provenance segments")

        for position in ring[:-1]:
            distance_m = _haversine_distance_m(self.center, position)
            if not math.isclose(
                distance_m,
                self.analysis_radius_m,
                rel_tol=0.0,
                abs_tol=1.0,
            ):
                raise ValueError(
                    "candidate Polygon vertices must be generated from the center "
                    "and the uniform 1000 metre radius"
                )
        return self


class BusinessMixGroup(StrictConfigModel):
    """Named POI category group reserved for later metric implementation."""

    group_id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    categories: list[str] = Field(min_length=1)


class SiteSelectionConfig(StrictConfigModel):
    """Frozen Sprint 0 configuration contract; no metric computation is included."""

    config_version: Literal["tokyo_coffee_v1"]
    city: Literal["Tokyo"]
    business_type: Literal["coffee_shop"]
    ranking_scope: Literal["relative_to_selected_candidates"]
    dataset: DatasetInfo
    observation_period: ObservationPeriod
    candidate_areas: list[CandidateArea] = Field(min_length=1)
    aliases: dict[str, str]
    competitor_categories: list[str] = Field(min_length=1)
    transport_categories: list[str] = Field(min_length=1)
    business_mix_groups: list[BusinessMixGroup] = Field(min_length=1)
    metric_directions: dict[
        str, Literal["higher_is_better", "lower_is_better"]
    ]
    metric_weights: dict[str, float]
    normalization_method: Literal["min_max_within_selected_candidates"]
    mandatory_disclosures: list[str] = Field(min_length=1)
    prohibited_claims: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> "SiteSelectionConfig":
        """校验整体契约：区域唯一、指标齐备、权重与声明合规。"""
        area_ids = [area.area_id for area in self.candidate_areas]
        if len(area_ids) != len(set(area_ids)):
            raise ValueError("candidate area_id values must be unique")
        if set(area_ids) != REQUIRED_AREA_IDS:
            raise ValueError(
                "candidate_areas must contain exactly shinjuku, shibuya, ginza, "
                "and ikebukuro"
            )

        normalized_aliases = [alias.strip().casefold() for alias in self.aliases]
        if len(normalized_aliases) != len(set(normalized_aliases)):
            raise ValueError("aliases must be unique after case folding")
        unknown_alias_targets = set(self.aliases.values()) - set(area_ids)
        if unknown_alias_targets:
            raise ValueError("every alias must resolve to a configured candidate area")

        group_ids = [group.group_id for group in self.business_mix_groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("business mix group_id values must be unique")

        if not {"Coffee Shop", "Café"}.issubset(self.competitor_categories):
            raise ValueError(
                "competitor_categories must include Coffee Shop and Café"
            )

        if set(self.metric_directions) != MANDATORY_METRIC_IDS:
            raise ValueError("metric_directions must contain every mandatory metric")
        if set(self.metric_weights) != MANDATORY_METRIC_IDS:
            raise ValueError("metric_weights must contain every mandatory metric")
        if any(
            not math.isclose(weight, 0.20, rel_tol=0.0, abs_tol=1e-12)
            for weight in self.metric_weights.values()
        ):
            raise ValueError("tokyo_coffee_v1 metric weights must all equal 0.20")
        if not math.isclose(
            sum(self.metric_weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("metric_weights must sum to 1")

        if not REQUIRED_PROHIBITED_CLAIMS.issubset(self.prohibited_claims):
            raise ValueError("prohibited_claims is missing required prohibited wording")
        return self

