"""SiteSelection Tool 的 LLM Function Calling 描述契约。"""

from typing import ClassVar


class SiteSelectionToolSchema:
    """集中声明 Agent Registry 与 LLM 所需的静态工具元数据。"""

    name: ClassVar[str] = "analyze_site_selection"
    description: ClassVar[str] = (
        "分析一个或多个候选区域的空间指标、用户行为指标和区域流向。"
    )
    parameters: ClassVar[dict[str, object]] = {
        "type": "object",
        "properties": {
            "area_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "需要分析的 canonical 候选区域 ID 列表。",
            }
        },
        "required": ["area_ids"],
        "additionalProperties": False,
    }
