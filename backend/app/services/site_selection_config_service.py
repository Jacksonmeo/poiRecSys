"""Read and validate versioned site-selection configuration files only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.site_selection_config import (
    SUPPORTED_CONFIG_VERSION,
    SiteSelectionConfig,
)

CONFIG_DIRECTORY = Path(__file__).resolve().parents[1] / "site_selection" / "config"


class SiteSelectionConfigError(RuntimeError):
    """Base exception for configuration loading failures."""


class UnsupportedConfigVersionError(SiteSelectionConfigError):
    """Raised when a caller or file requests an unknown contract version."""


class InvalidSiteSelectionConfigError(SiteSelectionConfigError):
    """Raised when JSON syntax or the strict Pydantic contract is invalid."""


def _assert_supported_version(config_version: Any) -> str:
    """校验配置版本受支持，未知版本抛 UnsupportedConfigVersionError。"""
    if config_version != SUPPORTED_CONFIG_VERSION:
        raise UnsupportedConfigVersionError(
            f"unsupported site-selection config_version: {config_version!r}; "
            f"supported version: {SUPPORTED_CONFIG_VERSION!r}"
        )
    return config_version


def load_site_selection_config_file(path: str | Path) -> SiteSelectionConfig:
    """Load one JSON file and reject unknown versions without fallback."""

    config_path = Path(path)
    try:
        raw_text = config_path.read_text(encoding="utf-8")
        raw_config = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSiteSelectionConfigError(
            f"unable to read site-selection config {config_path}: {exc}"
        ) from exc

    if not isinstance(raw_config, dict):
        raise InvalidSiteSelectionConfigError(
            "site-selection config root must be a JSON object"
        )
    _assert_supported_version(raw_config.get("config_version"))

    try:
        return SiteSelectionConfig.model_validate_json(raw_text)
    except ValidationError as exc:
        raise InvalidSiteSelectionConfigError(
            f"invalid site-selection config {config_path}: {exc}"
        ) from exc


def load_site_selection_config(
    config_version: str = SUPPORTED_CONFIG_VERSION,
) -> SiteSelectionConfig:
    """Load the exact requested version; an unknown version never falls back."""

    version = _assert_supported_version(config_version)
    return load_site_selection_config_file(CONFIG_DIRECTORY / f"{version}.json")

