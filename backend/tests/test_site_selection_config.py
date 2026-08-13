"""Contract tests for the frozen Tokyo coffee site-selection configuration."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.site_selection_config_service import (
    CONFIG_DIRECTORY,
    InvalidSiteSelectionConfigError,
    UnsupportedConfigVersionError,
    load_site_selection_config,
    load_site_selection_config_file,
)

CONFIG_PATH = CONFIG_DIRECTORY / "tokyo_coffee_v1.json"
EXPECTED_AREA_IDS = {"shinjuku", "shibuya", "ginza", "ikebukuro"}


@pytest.fixture
def raw_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write_config(tmp_path: Path, payload: dict) -> Path:
    config_path = tmp_path / "site_selection_config.json"
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return config_path


def test_config_loads_successfully() -> None:
    config = load_site_selection_config()

    assert config.config_version == "tokyo_coffee_v1"
    assert config.ranking_scope == "relative_to_selected_candidates"


def test_weight_sum_other_than_one_fails(tmp_path: Path, raw_config: dict) -> None:
    payload = deepcopy(raw_config)
    payload["metric_weights"]["poi_count"] = 0.21

    with pytest.raises(InvalidSiteSelectionConfigError, match="metric weights"):
        load_site_selection_config_file(write_config(tmp_path, payload))


def test_unclosed_polygon_fails(tmp_path: Path, raw_config: dict) -> None:
    payload = deepcopy(raw_config)
    payload["candidate_areas"][0]["polygon"]["coordinates"][0][-1] = [0.0, 0.0]

    with pytest.raises(InvalidSiteSelectionConfigError, match="closed"):
        load_site_selection_config_file(write_config(tmp_path, payload))


def test_duplicate_area_id_fails(tmp_path: Path, raw_config: dict) -> None:
    payload = deepcopy(raw_config)
    payload["candidate_areas"][1]["area_id"] = payload["candidate_areas"][0][
        "area_id"
    ]

    with pytest.raises(InvalidSiteSelectionConfigError, match="unique"):
        load_site_selection_config_file(write_config(tmp_path, payload))


def test_unknown_config_version_fails(tmp_path: Path, raw_config: dict) -> None:
    payload = deepcopy(raw_config)
    payload["config_version"] = "tokyo_coffee_v2"

    with pytest.raises(UnsupportedConfigVersionError, match="unsupported"):
        load_site_selection_config_file(write_config(tmp_path, payload))


def test_all_four_candidate_areas_exist() -> None:
    config = load_site_selection_config()

    assert {area.area_id for area in config.candidate_areas} == EXPECTED_AREA_IDS


def test_all_candidate_areas_use_1000_metre_radius() -> None:
    config = load_site_selection_config()

    assert all(area.analysis_radius_m == 1000 for area in config.candidate_areas)
    assert all(
        area.polygon_provenance.radius_m == 1000 for area in config.candidate_areas
    )


def test_prohibited_wording_list_exists() -> None:
    config = load_site_selection_config()

    assert config.prohibited_claims
    assert {"人口", "实时客流", "销售额", "租金", "转化率", "成功率"}.issubset(
        config.prohibited_claims
    )

