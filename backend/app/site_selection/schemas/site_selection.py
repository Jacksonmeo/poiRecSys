"""零售选址领域的最小 Pydantic 数据契约。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SiteSelectionSchema(BaseModel):
    """拒绝未声明字段，避免领域边界被调用方隐式扩张。"""

    model_config = ConfigDict(extra="forbid")


class SiteSelectionAnalyzeRequest(SiteSelectionSchema):
    """按 canonical area_id 发起多候选区域事实分析。"""

    area_ids: list[str] = Field(
        min_length=1,
        description="需要纳入同一次分析的候选区域标识。",
    )

    @field_validator("area_ids")
    @classmethod
    def validate_area_ids_not_blank(cls, values: list[str]) -> list[str]:
        """拒绝空字符串或只包含空白字符的候选区域标识。"""
        if any(not value.strip() for value in values):
            raise ValueError("area_id must not be blank")
        return values


class CandidateArea(SiteSelectionSchema):
    """参与相对比较的候选分析区。"""

    area_id: str = Field(
        min_length=1,
        description="候选分析区的稳定唯一标识。",
    )
    display_name: str = Field(
        min_length=1,
        description="面向用户展示的候选分析区名称。",
    )


class MetricResult(SiteSelectionSchema):
    """某候选分析区的一项指标结果。"""

    metric_id: str = Field(
        min_length=1,
        description="指标的稳定唯一标识。",
    )
    value: float = Field(description="指标的数值结果。")
    description: str = Field(
        min_length=1,
        description="指标口径及结果含义的简要说明。",
    )


class SiteSelectionResult(SiteSelectionSchema):
    """单个候选分析区的选址分析结果。"""

    area_id: str = Field(
        min_length=1,
        description="该结果对应的候选分析区标识。",
    )
    metrics: list[MetricResult] = Field(
        description="该候选分析区已计算的指标结果。",
    )
    score: float | None = Field(
        default=None,
        description="预留的综合分数；评分能力实现前保持为空。",
    )
    explanation: str | None = Field(
        default=None,
        description="预留的结果解释；解释能力实现前保持为空。",
    )
