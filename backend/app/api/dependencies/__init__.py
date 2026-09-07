"""FastAPI 请求级依赖工厂。"""

from app.api.dependencies.agent import get_agent_service
from app.api.dependencies.site_selection import (
    get_site_selection_analysis_service,
)

__all__ = ["get_agent_service", "get_site_selection_analysis_service"]
