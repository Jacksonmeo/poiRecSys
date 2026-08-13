"""SiteSelection FastAPI 依赖工厂测试。"""

from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.api.dependencies.site_selection import (
    get_site_selection_analysis_service,
)
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.services import SiteSelectionAnalysisService


def test_dependency_creates_analysis_service() -> None:
    db = Mock(spec=Session)

    service = get_site_selection_analysis_service(db)
    another_service = get_site_selection_analysis_service(db)

    assert isinstance(service, SiteSelectionAnalysisService)
    assert service is not another_service


def test_dependency_repositories_share_request_session() -> None:
    db = Mock(spec=Session)

    service = get_site_selection_analysis_service(db)

    assert service.site_selection_service.repository.db is db
    assert service.flow_service.repository.db is db


def test_dependency_injects_metadata_from_config() -> None:
    db = Mock(spec=Session)
    config = load_site_selection_config()

    service = get_site_selection_analysis_service(db)

    assert service.metadata.config_version == config.config_version
    assert service.metadata.dataset == config.dataset.name
    assert service.metadata.observation_period == (
        "2012-04-03T18:17:18Z/2013-02-16T02:35:29Z"
    )
    assert (
        service.site_selection_service.competitor_categories
        == config.competitor_categories
    )
    assert service.transport_categories == config.transport_categories
    assert service.business_mix_groups == config.business_mix_groups
