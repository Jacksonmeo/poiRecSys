"""AgentService 的 FastAPI 请求级依赖组合。"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.agent.service import AgentService, build_default_registry
from app.agent.tools.site_selection_agent_tool import SiteSelectionAgentTool
from app.api.dependencies.site_selection import (
    get_site_selection_analysis_service,
)
from app.db.database import get_db
from app.site_selection.services import SiteSelectionAnalysisService
from app.site_selection.tools import SiteSelectionTool


def get_agent_service(
    analysis_service: Annotated[
        SiteSelectionAnalysisService,
        Depends(get_site_selection_analysis_service),
    ],
    db: Annotated[Session, Depends(get_db)] = None,
) -> AgentService:
    """为当前请求组合完整 Registry，不缓存数据库会话或 AgentService。"""
    site_selection_tool = SiteSelectionTool(analysis_service=analysis_service)
    site_selection_agent_tool = SiteSelectionAgentTool(site_selection_tool)
    registry = build_default_registry(extra_tools=[site_selection_agent_tool])
    if db is None:
        # 兼容直接调用依赖工厂的单元测试；FastAPI 请求中始终由 get_db 注入。
        db = analysis_service.site_selection_service.repository.db
    return AgentService(registry=registry, db=db)
