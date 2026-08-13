"""SiteSelection 事实分析 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies.site_selection import (
    get_site_selection_analysis_service,
)
from app.core.response import ApiResponse
from app.schemas.site_selection_config import (
    CandidateArea as ConfigCandidateArea,
)
from app.schemas.site_selection_config import SiteSelectionConfig
from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.schemas import (
    SiteSelectionAnalyzeRequest,
    SiteSelectionArtifact,
)
from app.site_selection.services import SiteSelectionAnalysisService

router = APIRouter()


def _resolve_candidate_areas(
    area_ids: list[str],
    config: SiteSelectionConfig,
) -> list[ConfigCandidateArea]:
    """按请求顺序解析 canonical CandidateArea，未知标识统一返回 404。"""
    areas_by_id = {area.area_id: area for area in config.candidate_areas}
    unknown_area_id = next(
        (area_id for area_id in area_ids if area_id not in areas_by_id),
        None,
    )
    if unknown_area_id is not None:
        raise HTTPException(
            status_code=404,
            detail=f"Candidate area '{unknown_area_id}' was not found.",
        )
    return [areas_by_id[area_id] for area_id in area_ids]


@router.post("/analyze", response_model=ApiResponse[SiteSelectionArtifact])
def analyze_site_selection(
    request: SiteSelectionAnalyzeRequest,
    service: Annotated[
        SiteSelectionAnalysisService,
        Depends(get_site_selection_analysis_service),
    ],
) -> ApiResponse[SiteSelectionArtifact]:
    """解析版本化候选区并返回一次多区域事实分析结果。"""
    config = load_site_selection_config()
    candidate_areas = _resolve_candidate_areas(request.area_ids, config)
    return ApiResponse(data=service.analyze_site_selection(candidate_areas))
