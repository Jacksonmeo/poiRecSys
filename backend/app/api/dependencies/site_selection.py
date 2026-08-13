"""SiteSelection 分析能力的 FastAPI 请求级依赖组合。"""

from datetime import timezone
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.site_selection_config import SiteSelectionConfig
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.repositories import (
    SiteSelectionFlowRepository,
    SiteSelectionRepository,
)
from app.site_selection.schemas import AnalysisMetadata
from app.site_selection.services import (
    SiteSelectionAnalysisService,
    SiteSelectionFlowService,
    SiteSelectionService,
)


def _build_analysis_metadata(config: SiteSelectionConfig) -> AnalysisMetadata:
    """从已校验配置生成稳定的 UTC 数据上下文，不自行补造口径。"""
    period = config.observation_period
    observation_period = "/".join(
        timestamp.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
        for timestamp in (period.start_at, period.end_at)
    )
    return AnalysisMetadata(
        config_version=config.config_version,
        dataset=config.dataset.name,
        observation_period=observation_period,
    )


def get_site_selection_analysis_service(
    db: Annotated[Session, Depends(get_db)],
) -> SiteSelectionAnalysisService:
    """使用同一请求级 Session 组合 SiteSelection 分析依赖。"""
    config = load_site_selection_config()
    site_selection_repository = SiteSelectionRepository(db=db)
    flow_repository = SiteSelectionFlowRepository(db=db)
    site_selection_service = SiteSelectionService(
        repository=site_selection_repository,
        competitor_categories=config.competitor_categories,
    )
    flow_service = SiteSelectionFlowService(repository=flow_repository)
    return SiteSelectionAnalysisService(
        site_selection_service=site_selection_service,
        flow_service=flow_service,
        metadata=_build_analysis_metadata(config),
        transport_categories=config.transport_categories,
        business_mix_groups=config.business_mix_groups,
    )
