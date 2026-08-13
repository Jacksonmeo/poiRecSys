"""一次完整零售选址事实分析的统一结果契约。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.site_selection.schemas.flow import AreaFlowResult
from app.site_selection.schemas.site_selection import CandidateArea, MetricResult


class AnalysisMetadata(BaseModel):
    """标识事实分析所使用的配置与历史数据时间范围。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    config_version: str = Field(
        min_length=1,
        description="生成分析结果所使用的版本化配置标识。",
    )
    dataset: str = Field(
        min_length=1,
        description="生成分析结果所使用的数据集标识。",
    )
    observation_period: str | None = Field(
        default=None,
        description="历史数据的可选观测时间范围。",
    )

    @field_validator("config_version", "dataset", "observation_period")
    @classmethod
    def validate_string_not_blank(cls, value: str | None) -> str | None:
        """允许观测期缺省，但拒绝所有只包含空白字符的字符串。"""
        if value is not None and not value.strip():
            raise ValueError("metadata string must not be blank")
        return value


class SiteSelectionArtifact(BaseModel):
    """承载候选区集合的事实分析结果，不表达评分、排名或最终推荐。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    analysis_type: str = Field(
        min_length=1,
        description="本次事实分析的稳定类型标识。",
    )
    candidate_areas: list[CandidateArea] = Field(
        description="本次分析包含的候选分析区。",
    )
    metadata: AnalysisMetadata = Field(
        description="本次分析使用的配置版本、数据集和观测周期。",
    )
    metrics: list[MetricResult] = Field(
        description="各候选分析区的事实指标结果；无指标时为空列表。",
    )
    flows: list[AreaFlowResult] = Field(
        description="候选分析区之间的事实流向结果；无流向时为空列表。",
    )
    summary: str | None = Field(
        default=None,
        description="可选的事实结果摘要，不承载推荐结论。",
    )
