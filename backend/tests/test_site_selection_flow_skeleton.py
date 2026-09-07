"""区域行为流向 Repository 与 Service 骨架测试。"""

from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.site_selection.repositories import SiteSelectionFlowRepository
from app.site_selection.services import SiteSelectionFlowService


def test_flow_repository_accepts_database_session() -> None:
    db = Mock(spec=Session)

    repository = SiteSelectionFlowRepository(db=db)

    assert repository.db is db
    assert repository.get_area_flows() == []


def test_flow_service_calls_repository_for_session_sequences() -> None:
    repository = Mock(spec=SiteSelectionFlowRepository)
    repository.get_session_area_sequences.return_value = []
    service = SiteSelectionFlowService(repository=repository)

    results = service.analyze_area_flows([])

    assert results == []
    repository.get_session_area_sequences.assert_called_once_with([])
