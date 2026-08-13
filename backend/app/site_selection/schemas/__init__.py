"""零售选址领域的输入输出数据契约。"""

from app.site_selection.schemas.artifact import AnalysisMetadata, SiteSelectionArtifact
from app.site_selection.schemas.flow import (
    AreaFlowResult,
    AreaTransition,
    SessionAreaSequence,
)
from app.site_selection.schemas.site_selection import (
    CandidateArea,
    MetricResult,
    SiteSelectionAnalyzeRequest,
    SiteSelectionResult,
)

__all__ = [
    "AreaFlowResult",
    "AreaTransition",
    "AnalysisMetadata",
    "CandidateArea",
    "MetricResult",
    "SessionAreaSequence",
    "SiteSelectionAnalyzeRequest",
    "SiteSelectionArtifact",
    "SiteSelectionResult",
]
