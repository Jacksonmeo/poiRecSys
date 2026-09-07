"""Generate the committed Tokyo coffee site-selection v1 configuration.

The script uses the same spherical destination-point calculation and 1,000 metre
radius for every candidate. It performs no database access and computes no site
selection metrics or scores.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

EARTH_RADIUS_M = 6_371_008.8
ANALYSIS_RADIUS_M = 1000
POLYGON_SEGMENTS = 64
BACKEND_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = (
    BACKEND_ROOT
    / "app"
    / "site_selection"
    / "config"
    / "tokyo_coffee_v1.json"
)

CANDIDATES = (
    {
        "area_id": "shinjuku",
        "display_name": "Shinjuku 站点周边 1 km 分析区",
        "center_reference": "Shinjuku Station reference point",
        "center": {"longitude": 139.700464, "latitude": 35.689729},
    },
    {
        "area_id": "shibuya",
        "display_name": "Shibuya 站点周边 1 km 分析区",
        "center_reference": "Shibuya Station reference point",
        "center": {"longitude": 139.701636, "latitude": 35.658034},
    },
    {
        "area_id": "ginza",
        "display_name": "Ginza 站点周边 1 km 分析区",
        "center_reference": "Ginza Station reference point",
        "center": {"longitude": 139.765, "latitude": 35.6717},
    },
    {
        "area_id": "ikebukuro",
        "display_name": "Ikebukuro 站点周边 1 km 分析区",
        "center_reference": "Ikebukuro Station reference point",
        "center": {"longitude": 139.7109, "latitude": 35.729503},
    },
)


def destination_point(
    longitude: float,
    latitude: float,
    bearing_degrees: float,
    distance_m: float,
) -> list[float]:
    """Return [longitude, latitude] after a great-circle displacement."""

    angular_distance = distance_m / EARTH_RADIUS_M
    bearing = math.radians(bearing_degrees)
    latitude_1 = math.radians(latitude)
    longitude_1 = math.radians(longitude)

    latitude_2 = math.asin(
        math.sin(latitude_1) * math.cos(angular_distance)
        + math.cos(latitude_1)
        * math.sin(angular_distance)
        * math.cos(bearing)
    )
    longitude_2 = longitude_1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(latitude_1),
        math.cos(angular_distance) - math.sin(latitude_1) * math.sin(latitude_2),
    )
    normalized_longitude = (
        math.degrees(longitude_2) + 540
    ) % 360 - 180
    return [round(normalized_longitude, 7), round(math.degrees(latitude_2), 7)]


def make_polygon(center: dict[str, float]) -> dict[str, object]:
    """Create a closed 64-segment GeoJSON Polygon in lon/lat order."""

    ring = [
        destination_point(
            longitude=center["longitude"],
            latitude=center["latitude"],
            bearing_degrees=index * 360 / POLYGON_SEGMENTS,
            distance_m=ANALYSIS_RADIUS_M,
        )
        for index in range(POLYGON_SEGMENTS)
    ]
    ring.append(ring[0].copy())
    return {"type": "Polygon", "coordinates": [ring]}


def build_config() -> dict[str, object]:
    """Build the frozen v1 contract payload."""
    return {
        "config_version": "tokyo_coffee_v1",
        "city": "Tokyo",
        "business_type": "coffee_shop",
        "ranking_scope": "relative_to_selected_candidates",
        "dataset": _build_dataset(),
        "observation_period": _build_observation_period(),
        "candidate_areas": _build_candidate_areas(),
        "aliases": _build_aliases(),
        "competitor_categories": ["Coffee Shop", "Café"],
        "transport_categories": [
            "Train Station",
            "Subway",
            "Bus Station",
            "Light Rail",
        ],
        "business_mix_groups": _build_business_mix_groups(),
        "metric_directions": _build_metric_directions(),
        "metric_weights": _build_metric_weights(),
        "normalization_method": "min_max_within_selected_candidates",
        "mandatory_disclosures": _build_disclosures(),
        "prohibited_claims": _build_prohibited_claims(),
    }


def _build_dataset() -> dict[str, object]:
    """Build the historical dataset identity and limitation block."""
    return {
        "name": "TSMC2014_TKY",
        "source": "Foursquare",
        "city_subset": "Tokyo",
        "source_artifact": "dataset_TSMC2014_TKY.csv",
        "sample_type": "historical_checkin_sample",
        "sample_description": "Foursquare Tokyo 2012-2013 historical check-in sample",
        "is_historical": True,
        "limitations": [
            "The dataset is a historical opt-in check-in sample and is not a census.",
            "Observed check-ins reflect platform and user self-selection during 2012-2013.",
        ],
    }


def _build_observation_period() -> dict[str, object]:
    """Build the inclusive UTC observation period block."""
    return {
        "start_at": "2012-04-03T18:17:18Z",
        "end_at": "2013-02-16T02:35:29Z",
        "timezone": "UTC",
    }


def _build_candidate_areas() -> list[dict[str, object]]:
    """Build one analysis area entry per candidate with uniform polygon."""
    candidate_areas = []
    for candidate in CANDIDATES:
        center = candidate["center"]
        candidate_areas.append(
            {
                **candidate,
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
    return candidate_areas


def _build_aliases() -> dict[str, str]:
    """Build the alias table resolving user wording to candidate area ids."""
    return {
        "shinjuku": "shinjuku",
        "新宿": "shinjuku",
        "新宿站": "shinjuku",
        "shibuya": "shibuya",
        "涩谷": "shibuya",
        "渋谷": "shibuya",
        "ginza": "ginza",
        "银座": "ginza",
        "銀座": "ginza",
        "ikebukuro": "ikebukuro",
        "池袋": "ikebukuro",
        "池袋站": "ikebukuro",
    }


def _build_business_mix_groups() -> list[dict[str, object]]:
    """Build the named POI category groups used by later metrics."""
    return [
        {
            "group_id": "food_and_dining",
            "categories": [
                "Restaurant",
                "Japanese Restaurant",
                "Ramen / Noodle House",
                "Bakery",
            ],
        },
        {
            "group_id": "retail",
            "categories": [
                "Department Store",
                "Shopping Mall",
                "Convenience Store",
                "Clothing Store",
            ],
        },
        {
            "group_id": "leisure_and_culture",
            "categories": ["Park", "Museum", "Theater", "Bookstore"],
        },
        {
            "group_id": "nightlife",
            "categories": ["Bar", "Pub", "Nightclub", "Lounge"],
        },
    ]


def _build_metric_directions() -> dict[str, str]:
    """Build the direction of every mandatory metric."""
    return {
        "poi_count": "higher_is_better",
        "historical_checkin_count": "higher_is_better",
        "competitor_count": "lower_is_better",
        "transport_poi_count": "higher_is_better",
        "business_mix_diversity": "higher_is_better",
    }


def _build_metric_weights() -> dict[str, float]:
    """Build the equal 0.20 weight of every mandatory metric."""
    return {
        "poi_count": 0.20,
        "historical_checkin_count": 0.20,
        "competitor_count": 0.20,
        "transport_poi_count": 0.20,
        "business_mix_diversity": 0.20,
    }


def _build_disclosures() -> list[str]:
    """Build the mandatory methodological disclosure statements."""
    return [
        "结果仅用于四个已选候选分析区之间的相对比较。",
        "tokyo_coffee_v1 的相对比较母集固定为配置内四个候选分析区。",
        "候选区统一定义为站点中心周边 1 km 分析区，不代表官方商圈边界。",
        "依据为 Foursquare Tokyo 2012-2013 历史签到样本，不代表当前状态。",
        "POI 类别与历史签到仅是样本内的比较信号，不支持因果或经营结果承诺。",
    ]


def _build_prohibited_claims() -> list[str]:
    """Build the wording that must never be used in generated reports."""
    return [
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
    ]


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(build_config(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
