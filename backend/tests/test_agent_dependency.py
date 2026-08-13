"""AgentService 请求级依赖工厂测试。"""

from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.agent.service import AgentService
from app.agent.tools.site_selection_agent_tool import SiteSelectionAgentTool
from app.api.dependencies.agent import get_agent_service
from app.api.dependencies.site_selection import (
    get_site_selection_analysis_service,
)
from app.site_selection.services import SiteSelectionAnalysisService


def _analysis_service(db: Session) -> SiteSelectionAnalysisService:
    return get_site_selection_analysis_service(db)


def test_dependency_returns_distinct_agent_service_instances() -> None:
    analysis_service = _analysis_service(Mock(spec=Session))

    service = get_agent_service(analysis_service)
    another_service = get_agent_service(analysis_service)

    assert isinstance(service, AgentService)
    assert service is not another_service


def test_dependency_registry_contains_all_tools() -> None:
    service = get_agent_service(_analysis_service(Mock(spec=Session)))

    assert {tool.name for tool in service._registry.all()} == {
        "query_poi",
        "spatial_density",
        "recommend",
        "track",
        "analyze_site_selection",
    }
    assert isinstance(
        service._registry.get("analyze_site_selection"),
        SiteSelectionAgentTool,
    )


def test_site_selection_tool_receives_request_analysis_service() -> None:
    db = Mock(spec=Session)
    analysis_service = _analysis_service(db)

    service = get_agent_service(analysis_service)
    agent_tool = service._registry.get("analyze_site_selection")

    assert isinstance(agent_tool, SiteSelectionAgentTool)
    assert agent_tool.site_selection_tool.analysis_service is analysis_service
    assert analysis_service.site_selection_service.repository.db is db
    assert analysis_service.flow_service.repository.db is db
