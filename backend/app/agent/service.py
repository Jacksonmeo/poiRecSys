"""Agent 编排服务：LLM Function Calling（降级规则路由）闭环（Stage 4）。

流程：用户输入 → LLM 意图识别（LLMIntentRouter，降级时用规则路由）→ 执行 Tool
→ 生成回复 + map_layers。各工具的 parameters 是 JSON Schema，直接作为 LLM 函数声明。
"""

from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agent.graph import AgentLoopResult, AgentRunner
from app.agent.memory import InMemoryConversationMemory
from app.agent.prompts.prompt import REPLY_TEMPLATES
from app.agent.registry import AgentTool, ToolRegistry
from app.agent.router_llm import LLMIntentRouter
from app.agent.schemas import AgentArtifact, ChatResponse, MapLayer, ToolCallInfo
from app.agent.stream import ChatStreamEvent, chunk_text, tool_result_summary
from app.agent.tools.poi_tool import QueryPOITool
from app.agent.tools.recommend_tool import RecommendTool
from app.agent.tools.spatial_tool import SpatialAnalysisTool
from app.agent.tools.track_tool import TrackTool


def build_default_registry(extra_tools: Iterable[AgentTool] = ()) -> ToolRegistry:
    """注册无状态内置工具，并接收由请求依赖在外部构造的有状态工具。"""
    registry = ToolRegistry()
    tools = (QueryPOITool(), SpatialAnalysisTool(), RecommendTool(), TrackTool())
    for tool in (*tools, *extra_tools):
        registry.register(tool)
    return registry


# 模块级单例：对话记忆（内存实现，未来可替换 Redis）
conversation_memory = InMemoryConversationMemory()


def _poi_layer_data(result: dict) -> list[dict]:
    """从 query_poi 结果提取统一地图点位（含 GeoJSON → 点位归一化）。"""
    if result.get("type") == "feature_collection":
        points = []
        for feature in result.get("data", {}).get("features", []):
            props = feature.get("properties", {})
            lon, lat = feature["geometry"]["coordinates"]
            points.append(
                {
                    "venue_id": props.get("venue_id"),
                    "display_name": props.get("name"),
                    "venue_category": props.get("category"),
                    "longitude": lon,
                    "latitude": lat,
                }
            )
        return points
    return result.get("data", [])


def build_map_layers(tool_name: str, result: dict) -> list[MapLayer]:
    """把工具结果转换为前端地图图层描述（map_layers）。"""
    if tool_name == "query_poi":
        data = _poi_layer_data(result)
        return [MapLayer(type="poi", data=data)] if data else []
    if tool_name == "spatial_density":
        cells = result.get("cells", [])
        return [MapLayer(type="heatmap", data=cells)] if cells else []
    if tool_name == "recommend":
        candidates = result.get("candidates", [])
        return [MapLayer(type="poi", data=candidates)] if candidates else []
    if tool_name == "track":
        points = result.get("points", [])
        return [MapLayer(type="trajectory", data=points)] if points else []
    return []


def _names(items: list[dict]) -> str:
    """提取前 3 个名称用于回复（display_name 缺失时用 venue_id 兜底）。"""
    names = "、".join(item.get("display_name") or item.get("venue_id", "") for item in items[:3])
    return f"{names}等" if len(items) > 3 else names


def build_reply(tool_name: str, result: dict) -> str:
    """按工具结果填充回复模板，生成自然语言总结。"""
    template = REPLY_TEMPLATES.get(tool_name)
    if template is None:
        return REPLY_TEMPLATES["fallback"]

    if tool_name == "query_poi":
        pois = _poi_layer_data(result)
        category = result.get("category") or ""
        scope = f"（类别：{category}）" if category else ""
        return template.format(count=len(pois), scope=scope, names=_names(pois))

    if tool_name == "spatial_density":
        cells = result.get("cells", [])
        return template.format(count=result.get("count", 0), cells=len(cells))

    if tool_name == "recommend":
        candidates = result.get("candidates", [])
        reply = template.format(
            top_k=result.get("top_k", len(candidates)),
            session_id=result.get("session_id", ""),
            names=_names(candidates),
        )
        # 附加 Top-1 候选的解释理由（派生字段，供推荐可解释展示）
        if candidates and candidates[0].get("reason"):
            reply += f" 推荐理由：{candidates[0]['reason']}。"
        return reply

    if tool_name == "track":
        points = result.get("points", [])
        return template.format(
            session_id=result.get("session_id", ""),
            count=len(points),
            names=_names(points),
        )

    if tool_name == "analyze_site_selection":
        areas = result.get("candidate_areas", [])
        names = "、".join(
            area.get("display_name") or area.get("area_id", "") for area in areas
        )
        return (
            f"已完成 {len(areas)} 个候选区域的选址事实分析"
            f"（{names}），得到 {len(result.get('metrics', []))} 项指标和 "
            f"{len(result.get('flows', []))} 条区域流向。"
        )

    return REPLY_TEMPLATES["fallback"]


def build_artifacts(tool_name: str, result: dict) -> list[AgentArtifact]:
    """保留需要独立渲染的完整结构化 Tool 结果。"""
    if tool_name == "analyze_site_selection":
        return [AgentArtifact(type="site_selection", data=result)]
    return []


class AgentService:
    """请求级 Agent 编排服务；同步与 SSE 入口共享同一个 AgentLoop。"""

    def __init__(
        self,
        registry: ToolRegistry,
        memory: InMemoryConversationMemory | None = None,
        db: Session | None = None,
        router: LLMIntentRouter | None = None,
        max_steps: int = 3,
    ) -> None:
        """构造请求级编排服务：组合注册表、记忆、路由与 LangGraph 执行器。"""
        self._registry = registry
        self._db = db
        self._router = router or LLMIntentRouter(registry)
        self._memory = memory or conversation_memory
        self._runner = AgentRunner(
            registry=registry,
            router=self._router,
            fallback_reply=build_reply,
            max_steps=max_steps,
        )

    def chat(
        self,
        db: Session | None = None,
        message: str = "",
        session_id: str = "",
    ) -> ChatResponse:
        """执行一次非流式对话：推理 → 组装响应 → 写入会话记忆。"""
        request_db = self._request_db(db)
        history = self._memory.get(session_id) if session_id else None
        try:
            result = self._runner.run(db=request_db, message=message, history=history)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        response = self._build_response(result)
        if session_id:
            self._memory.append(session_id, message, response.reply)
        return response

    def chat_stream(
        self,
        db: Session | None = None,
        message: str = "",
        session_id: str = "",
    ):
        """SSE 编排：逐步转发 Loop 事件，再输出文本增量与终态。

        事件序列：tool_call → tool_result → text（增量）→ done。
        工具校验失败（ValueError）由路由层捕获并转为 error 事件。
        """
        request_db = self._request_db(db)
        history = self._memory.get(session_id) if session_id else None
        iterator = self._runner.iter_run(
            db=request_db,
            message=message,
            history=history,
        )
        while True:
            try:
                event = next(iterator)
            except StopIteration as stop:
                loop_result = stop.value
                break
            if event.kind == "tool_call":
                yield ChatStreamEvent(
                    kind="tool_call",
                    payload={"tool": event.name, "args": event.args},
                )
            else:
                yield ChatStreamEvent(
                    kind="tool_result",
                    payload=tool_result_summary(event.name, event.result or {}),
                )

        response = self._build_response(loop_result)
        for chunk in chunk_text(response.reply):
            yield ChatStreamEvent(kind="text", payload={"content": chunk})
        yield ChatStreamEvent(
            kind="done",
            payload=response.model_dump(mode="json"),
        )

        if session_id:
            self._memory.append(session_id, message, response.reply)

    def _request_db(self, db: Session | None) -> Session:
        """解析请求级数据库会话；两者皆缺时抛 RuntimeError。"""
        request_db = db or self._db
        if request_db is None:
            raise RuntimeError("AgentService requires a request-scoped database session.")
        return request_db

    @staticmethod
    def _build_response(result: AgentLoopResult) -> ChatResponse:
        """把循环终态转换为 ChatResponse（工具记录 + 地图图层 + 产物）。"""
        tool_calls: list[ToolCallInfo] = []
        layers: list[MapLayer] = []
        artifacts: list[AgentArtifact] = []
        for execution in result.executions:
            tool_calls.append(
                ToolCallInfo(tool=execution.name, args=execution.args)
            )
            layers.extend(build_map_layers(execution.name, execution.result))
            artifacts.extend(build_artifacts(execution.name, execution.result))
        return ChatResponse(
            reply=result.reply,
            tool_calls=tool_calls,
            map_layers=layers,
            artifacts=artifacts,
        )
