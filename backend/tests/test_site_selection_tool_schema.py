"""SiteSelection Tool 的 LLM Function Calling 描述契约测试。"""

from app.site_selection.tools import SiteSelectionToolSchema


def test_site_selection_tool_schema_structure() -> None:
    schema = SiteSelectionToolSchema()

    assert isinstance(schema.description, str)
    assert schema.description
    assert "空间指标" in schema.description
    assert "用户行为指标" in schema.description
    assert "区域流向" in schema.description
    assert set(schema.parameters) == {
        "type",
        "properties",
        "required",
        "additionalProperties",
    }


def test_site_selection_tool_schema_name() -> None:
    schema = SiteSelectionToolSchema()

    assert schema.name == "analyze_site_selection"


def test_site_selection_tool_parameters_are_valid_json_schema_shape() -> None:
    parameters = SiteSelectionToolSchema.parameters

    assert parameters["type"] == "object"
    assert parameters["required"] == ["area_ids"]
    assert parameters["additionalProperties"] is False
    assert parameters["properties"] == {
        "area_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "需要分析的 canonical 候选区域 ID 列表。",
        }
    }
