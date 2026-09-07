"""Stage 4 Agent LLM 测试：LLMIntentRouter 工具 schema / 降级 / 文本意图。

端到端对话路径由 test_agent_api.py 覆盖（默认 provider=mock，
已自动改走 LLMIntentRouter → MockProvider 链路）。
"""

from app.agent.router_llm import LLMIntentRouter
from app.agent.service import build_default_registry
from app.llm.client import LLMClient
from app.llm.schemas import LLMResponse, LLMToolCall


class _UnknownToolClient(LLMClient):
    """输出未注册工具名：验证重试后降级规则路由。"""

    name = "unknown_tool"

    def complete(self, messages, tools=None):
        return LLMResponse(tool_calls=[LLMToolCall(name="not_exist", arguments={})])


class _UnavailableClient(LLMClient):
    """不可用客户端：验证直接走规则路由，不调用 LLM。"""

    name = "unavailable"

    def is_available(self):
        return False

    def complete(self, messages, tools=None):
        raise AssertionError("不可用客户端不应被调用")


class _TextClient(LLMClient):
    """直接文本回复的客户端。"""

    name = "text"

    def complete(self, messages, tools=None):
        return LLMResponse(text="你好！我可以帮你做空间分析。")


def _router(client: LLMClient) -> LLMIntentRouter:
    return LLMIntentRouter(build_default_registry(), client=client)


def test_router_unknown_tool_falls_back_to_rules():
    """非法工具名 → 重试后降级规则路由（仍能正确路由）。"""
    intent = _router(_UnknownToolClient()).route("帮我找咖啡店")
    assert intent.tool == "query_poi"
    assert intent.args["category"] == "Coffee Shop"


def test_router_unavailable_client_uses_rules():
    """LLM 不可用 → 规则路由，不调用 complete。"""
    intent = _router(_UnavailableClient()).route("查看轨迹")
    assert intent.tool == "track"


def test_router_no_tool_returns_text_intent():
    """LLM 直接文本回复（无工具调用）→ 文本 Intent（service 用作兜底回复）。"""
    intent = _router(_TextClient()).route("你好")
    assert intent.tool == ""
    assert intent.text == "你好！我可以帮你做空间分析。"


def test_router_tools_schema_is_function_format():
    """LLM 收到的 tools 为 OpenAI 函数声明格式，包含全部 4 个工具。"""
    captured = {}

    class _CaptureClient(LLMClient):
        name = "capture"

        def complete(self, messages, tools=None):
            captured["tools"] = tools
            return LLMResponse(
                tool_calls=[LLMToolCall(name="query_poi", arguments={"category": "Coffee Shop"})]
            )

    intent = _router(_CaptureClient()).route("帮我找咖啡店")
    assert intent.tool == "query_poi"
    tools = captured["tools"]
    assert len(tools) == 4
    assert all(t["type"] == "function" for t in tools)
    assert {t["function"]["name"] for t in tools} == {
        "query_poi",
        "spatial_density",
        "recommend",
        "track",
    }
    # 参数保持 JSON Schema 结构
    assert tools[0]["function"]["parameters"]["type"] == "object"


def test_router_builds_system_and_user_messages():
    """LLM 输入：system prompt 在前，用户消息在最后。"""
    captured = {}

    class _CaptureClient(LLMClient):
        name = "capture2"

        def complete(self, messages, tools=None):
            captured["messages"] = messages
            return LLMResponse()

    _router(_CaptureClient()).route("你好")
    assert captured["messages"][0].role == "system"
    assert captured["messages"][-1].role == "user"
    assert captured["messages"][-1].content == "你好"


# ── Step 5：推荐解释字段（feature / reason）────────────────────────

from tests.conftest import client  # noqa: E402


def test_agent_recommend_has_explanation_fields(seeded):
    """推荐候选含派生解释字段 feature/reason，回复含推荐理由。"""
    resp = client.post("/api/agent/chat", json={"message": "给我推荐"})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["tool_calls"][0]["tool"] == "recommend"
    poi_layer = next(layer for layer in data["map_layers"] if layer["type"] == "poi")
    candidates = poi_layer["data"]
    assert len(candidates) == 3
    for candidate in candidates:
        assert candidate["feature"]["rank"] == candidate["rank"]
        assert candidate["feature"]["score"] == candidate["score"]
        assert candidate["reason"]
    assert "推荐理由" in data["reply"]


def test_agent_recommend_top1_reason_mentions_score(seeded):
    """Top-1 候选理由引用真实分数（可解释性）。"""
    resp = client.post("/api/agent/chat", json={"message": "给我推荐"})
    candidates = resp.json()["data"]["map_layers"][0]["data"]
    assert candidates[0]["feature"]["rank"] == 1
    assert "0.95" in candidates[0]["reason"]


# ── Step 6：SSE 流式（/api/agent/chat/stream）───────────────────────

import json  # noqa: E402


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """解析 SSE 响应文本 → [(event, data)] 列表。"""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        kind, data = "", {}
        for line in block.splitlines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if kind:
            events.append((kind, data))
    return events


def test_agent_chat_stream_tool_flow(seeded):
    """SSE 事件序列：tool_call → tool_result → text → done（含终态）。"""
    resp = client.post("/api/agent/chat/stream", json={"message": "帮我找咖啡店"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "tool_call"
    assert "tool_result" in kinds
    assert "text" in kinds
    assert kinds[-1] == "done"

    tool_call = events[0][1]
    assert tool_call["tool"] == "query_poi"
    assert tool_call["args"]["category"] == "Coffee Shop"

    done = events[-1][1]
    assert done["reply"]
    assert done["tool_calls"][0]["tool"] == "query_poi"
    assert any(layer["type"] == "poi" for layer in done["map_layers"])


def test_agent_chat_stream_text_increments(seeded):
    """text 事件的增量拼接等于终态 reply（打字机完整性）。"""
    resp = client.post("/api/agent/chat/stream", json={"message": "查看轨迹"})
    events = _parse_sse(resp.text)
    chunks = "".join(data["content"] for kind, data in events if kind == "text")
    assert chunks == events[-1][1]["reply"]
    assert len(events[-1][1]["map_layers"]) == 1  # trajectory 图层


def test_agent_chat_stream_greeting_no_tool(seeded):
    """无工具调用 → 直接 text + done，无 tool_call / tool_result。"""
    resp = client.post("/api/agent/chat/stream", json={"message": "你好"})
    events = _parse_sse(resp.text)
    kinds = [kind for kind, _ in events]
    assert "tool_call" not in kinds
    assert "tool_result" not in kinds
    assert events[-1][0] == "done"
    assert events[-1][1]["tool_calls"] == []
    assert events[-1][1]["map_layers"] == []


def test_agent_chat_stream_empty_message_422():
    """空白消息 → 统一 422（流式端点同样校验）。"""
    resp = client.post("/api/agent/chat/stream", json={"message": "   "})
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


def test_agent_chat_stream_site_selection_done_contains_artifact(seeded):
    """SSE done 与同步响应一样保留 SiteSelection Artifact。"""
    resp = client.post(
        "/api/agent/chat/stream",
        json={"message": "比较新宿和涩谷的选址"},
    )
    events = _parse_sse(resp.text)
    done = events[-1][1]

    assert events[0][1]["tool"] == "analyze_site_selection"
    assert done["artifacts"][0]["type"] == "site_selection"
    assert done["artifacts"][0]["data"]["analysis_type"] == "site_selection"
