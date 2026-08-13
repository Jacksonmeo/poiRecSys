"""SiteSelection Agent Tool：连接 canonical 区域输入与分析服务。"""

from pydantic import ValidationError

from app.services.site_selection_config_service import load_site_selection_config
from app.site_selection.schemas import SiteSelectionAnalyzeRequest, SiteSelectionArtifact
from app.site_selection.services import SiteSelectionAnalysisService
from app.site_selection.tools.site_selection_tool_schema import SiteSelectionToolSchema


class SiteSelectionTool(SiteSelectionToolSchema):
    """只解析候选区并委托领域 Service，不承担数据查询或指标计算。"""

    def __init__(self, analysis_service: SiteSelectionAnalysisService) -> None:
        """绑定选址分析服务（数据查询封装在领域服务内）。"""
        self.analysis_service = analysis_service

    def run(self, arguments: dict[str, object]) -> SiteSelectionArtifact:
        """校验 Function Calling 参数并委托既有分析入口。"""
        try:
            request = SiteSelectionAnalyzeRequest.model_validate(arguments)
        except ValidationError as error:
            raise ValueError(
                f"Invalid SiteSelectionTool arguments: {error}"
            ) from error
        return self.analyze(request.area_ids)

    def analyze(self, area_ids: list[str]) -> SiteSelectionArtifact:
        """按输入顺序解析 canonical area_id 并执行多区域分析。"""
        config = load_site_selection_config()
        areas_by_id = {area.area_id: area for area in config.candidate_areas}
        unknown_area_id = next(
            (area_id for area_id in area_ids if area_id not in areas_by_id),
            None,
        )
        if unknown_area_id is not None:
            raise ValueError(f"Unknown candidate area_id: {unknown_area_id}")
        candidate_areas = [areas_by_id[area_id] for area_id in area_ids]
        return self.analysis_service.analyze_site_selection(candidate_areas)
