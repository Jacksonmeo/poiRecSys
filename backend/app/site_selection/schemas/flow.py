"""区域行为流向分析的数据契约。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionAreaSequence(BaseModel):
    """一个有效 Session 按签到顺序排列的区域状态序列。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: str = Field(min_length=1, description="Session 的稳定唯一标识。")
    user_id: str = Field(min_length=1, description="Session 所属用户标识。")
    areas: list[str] = Field(
        min_length=1,
        description="按 sequence_no 排列的 CandidateArea 或区域外状态。",
    )

    @field_validator("session_id", "user_id")
    @classmethod
    def validate_identifier_not_blank(cls, value: str) -> str:
        """拒绝只包含空白字符的 Session 或用户标识。"""
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value

    @field_validator("areas")
    @classmethod
    def validate_area_ids_not_blank(cls, values: list[str]) -> list[str]:
        """区域序列中的每个状态都必须具有非空标识。"""
        if any(not value.strip() for value in values):
            raise ValueError("area identifier must not be blank")
        return values


class AreaTransition(BaseModel):
    """同一 Session 中一次相邻区域迁移事实。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    source_area: str = Field(min_length=1, description="相邻迁移的起点区域标识。")
    target_area: str = Field(min_length=1, description="相邻迁移的终点区域标识。")
    session_id: str = Field(min_length=1, description="产生迁移的 Session 标识。")
    user_id: str = Field(min_length=1, description="产生迁移的用户标识。")

    @field_validator("source_area", "target_area", "session_id", "user_id")
    @classmethod
    def validate_identifier_not_blank(cls, value: str) -> str:
        """迁移事实中的所有标识符都必须包含非空白字符。"""
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value


class AreaFlowResult(BaseModel):
    """一个有向候选区域对的历史行为流向聚合结果。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    source_area: str = Field(
        min_length=1,
        description="流向起点的候选区域标识。",
    )
    target_area: str = Field(
        min_length=1,
        description="流向终点的候选区域标识。",
    )
    flow_count: int = Field(
        gt=0,
        description="起点到终点的相邻有向转换总数。",
    )
    unique_users: int = Field(
        ge=1,
        description="产生该流向的去重用户数。",
    )
    unique_sessions: int = Field(
        ge=1,
        description="产生该流向的去重 Session 数。",
    )

    @field_validator("source_area", "target_area")
    @classmethod
    def validate_area_id_not_blank(cls, value: str) -> str:
        """拒绝只包含空白字符的区域标识。"""
        if not value.strip():
            raise ValueError("area identifier must not be blank")
        return value

    @model_validator(mode="after")
    def validate_count_relationship(self) -> "AreaFlowResult":
        """确保用户数、Session 数和流向数保持可解释的包含关系。"""
        if not self.unique_users <= self.unique_sessions <= self.flow_count:
            raise ValueError(
                "counts must satisfy unique_users <= unique_sessions <= flow_count"
            )
        return self
