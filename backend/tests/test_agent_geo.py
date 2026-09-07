"""GeoResolver 与 LLM 地点解析集成测试（Stage 4 Step 4）。

验证：LLM 只输出地点名 → GeoResolver 解析为 bbox → 工具执行参数。
"""

from app.agent.geo.resolver import GeoResolver
from app.agent.router_llm import LLMIntentRouter, _llm_parameters, _tool_schema
from app.agent.service import build_default_registry
from app.agent.tools.poi_tool import QueryPOITool
from app.agent.tools.spatial_tool import SpatialAnalysisTool
from app.llm.client import LLMClient
from app.llm.schemas import LLMResponse, LLMToolCall

resolver = GeoResolver()


def test_resolver_known_place_returns_bbox() -> None:
    """已收录地点（涩谷）→ bbox。"""
    bbox = resolver.resolve("涩谷")
    assert bbox == {"min_lon": 139.695, "min_lat": 35.655, "max_lon": 139.715, "max_lat": 35.665}


def test_resolver_english_alias() -> None:
    """英文别名（shibuya）同样解析。"""
    bbox = resolver.resolve("Shibuya")
    assert bbox is not None
    assert bbox["max_lon"] == 139.715


def test_resolver_tokyo_returns_default_bbox() -> None:
    """东京 → 默认东京中心 bbox。"""
    from app.agent.prompts.prompt import DEFAULT_BBOX

    assert resolver.resolve("东京") == DEFAULT_BBOX
    assert resolver.resolve("东京中心") == DEFAULT_BBOX


def test_resolver_unknown_place_returns_none() -> None:
    """未收录地点 → None（调用方回退默认区域）。"""
    assert resolver.resolve("巴黎") is None
    assert resolver.resolve("") is None
    assert resolver.resolve("   ") is None


class _LocationClient(LLMClient):
    """输出 location 参数的工具调用客户端。"""

    name = "location"

    def __init__(self, tool_name: str, arguments: dict) -> None:
        self._tool = tool_name
        self._args = arguments

    def complete(self, messages, tools=None):
        return LLMResponse(tool_calls=[LLMToolCall(name=self._tool, arguments=self._args)])


def _router_with(client: LLMClient) -> LLMIntentRouter:
    return LLMIntentRouter(build_default_registry(), client=client)


def test_router_resolves_location_to_bbox() -> None:
    """LLM 输出 location=涩谷 → Intent 参数变为涩谷 bbox。"""
    client = _LocationClient("query_poi", {"category": "Coffee Shop", "location": "涩谷"})
    intent = _router_with(client).route("涩谷的咖啡店")
    assert intent.tool == "query_poi"
    assert intent.args["category"] == "Coffee Shop"
    assert intent.args["bbox"] == resolver.resolve("涩谷")
    assert "location" not in intent.args  # location 已被消费


def test_router_density_without_location_uses_default_bbox() -> None:
    """LLM 密度调用未给 location → 默认东京中心 bbox。"""
    client = _LocationClient("spatial_density", {"grid_size": 10})
    intent = _router_with(client).route("看看密度")
    assert intent.tool == "spatial_density"
    assert intent.args["bbox"] is not None
    assert intent.args["bbox"]["min_lon"] == 139.69


def test_router_unknown_location_falls_back_to_default_bbox() -> None:
    """LLM 给未知地点 → 回退默认东京中心，不报错。"""
    client = _LocationClient("query_poi", {"location": "巴黎"})
    intent = _router_with(client).route("巴黎的咖啡店")
    assert intent.tool == "query_poi"
    assert intent.args["bbox"]["min_lon"] == 139.69


def test_llm_schema_hides_bbox_exposes_location() -> None:
    """空间工具对 LLM 的 schema：无 bbox，有 location。"""
    parameters = _llm_parameters(QueryPOITool())
    assert "bbox" not in parameters["properties"]
    assert parameters["properties"]["location"]["type"] == "string"


def test_non_spatial_tool_schema_unchanged() -> None:
    """非空间工具（recommend）schema 保持原样。"""
    from app.agent.tools.recommend_tool import RecommendTool

    parameters = _llm_parameters(RecommendTool())
    assert "user_id" in parameters["properties"]
    assert "location" not in parameters["properties"]


def test_tool_schema_function_format() -> None:
    """函数声明格式：type=function + name/description/parameters。"""
    schema = _tool_schema(SpatialAnalysisTool())
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "spatial_density"
    assert schema["function"]["parameters"]["type"] == "object"
