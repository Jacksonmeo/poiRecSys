"""LLM 客户端层单元测试（Stage 4 Step 1 / Step 3）。

MockProvider 不依赖数据库与外部网络，直接单元测试；
Factory 验证按配置返回对应客户端类型；
OpenAICompatClient 通过 monkeypatch 模拟 SDK 响应（不发起真实网络请求）。
"""

import pytest

from app.llm.factory import get_llm_client
from app.llm.providers.mock import MockProvider
from app.llm.providers.openai_compat import OpenAICompatClient
from app.llm.schemas import LLMMessage, LLMResponse, LLMToolCall


def _user_message(content: str) -> list[LLMMessage]:
    return [LLMMessage(role="user", content=content)]


def test_mock_provider_routes_category() -> None:
    """类别关键词 → query_poi 工具调用（带 category 参数）。"""
    response = MockProvider().complete(_user_message("帮我找咖啡店"))
    assert response.tool_calls == [
        LLMToolCall(name="query_poi", arguments={"category": "Coffee Shop"})
    ]


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("找医院", "Medical Center"),
        ("找酒吧", "Bar"),
        ("找运动场", "Athletic & Sport"),
    ],
)
def test_mock_provider_routes_common_poi_categories(message: str, category: str) -> None:
    """常见中文类别也应进入 query_poi，而不是返回能力兜底文案。"""
    response = MockProvider().complete(_user_message(message))
    assert response.tool_calls == [
        LLMToolCall(name="query_poi", arguments={"category": category})
    ]


def test_mock_provider_routes_density() -> None:
    """密度意图 → spatial_density 工具调用（带默认 bbox + grid_size）。"""
    response = MockProvider().complete(_user_message("看看空间密度"))
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "spatial_density"
    assert call.arguments["grid_size"] == 10
    assert set(call.arguments["bbox"]) == {"min_lon", "min_lat", "max_lon", "max_lat"}


def test_mock_provider_fallback_text() -> None:
    """未识别意图 → 直接文本回复（兜底模板），无工具调用。"""
    response = MockProvider().complete(_user_message("你好"))
    assert response.tool_calls == []
    assert "POI" in response.text or "查" in response.text


def test_mock_provider_uses_last_user_message() -> None:
    """多轮历史中取最后一条用户消息路由。"""
    messages = [
        LLMMessage(role="system", content="你是 GeoAgent"),
        LLMMessage(role="user", content="你好"),
        LLMMessage(role="assistant", content="你好，有什么可以帮你？"),
        LLMMessage(role="user", content="给我推荐"),
    ]
    response = MockProvider().complete(messages)
    assert response.tool_calls[0].name == "recommend"


def test_llm_response_defaults() -> None:
    """LLMResponse 默认值：无工具调用、空文本。"""
    response = LLMResponse()
    assert response.text == ""
    assert response.tool_calls == []


def test_factory_returns_mock_by_default() -> None:
    """默认配置（llm_provider=mock）返回 MockProvider。"""
    assert isinstance(get_llm_client(), MockProvider)


# ── OpenAI 兼容客户端（monkeypatch SDK，不联网）──────────────────────


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, name: str, arguments: str, call_id: str | None = None) -> None:
        self.id = call_id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content: str, tool_calls: list[_FakeToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeCompletion:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [_FakeChoice(message)]


class _FakeCompletions:
    """模拟 chat.completions：create() 返回固定 completion。"""

    def __init__(self, completion: _FakeCompletion) -> None:
        self.completion = completion

    def create(self, **kwargs):
        return self.completion


class _FakeChat:
    """模拟 chat 命名空间：completions 属性。"""

    def __init__(self, completion: _FakeCompletion) -> None:
        self.completions = _FakeCompletions(completion)


class _FakeSDK:
    """替换 openai.OpenAI：拦截 chat.completions.create 返回固定 completion。"""

    def __init__(self, completion: _FakeCompletion) -> None:
        self.chat = _FakeChat(completion)


def _compat_client(monkeypatch, completion: _FakeCompletion) -> OpenAICompatClient:
    monkeypatch.setattr(
        "app.llm.providers.openai_compat.OpenAI", lambda **kwargs: _FakeSDK(completion)
    )
    return OpenAICompatClient(base_url="https://example.com/v1", api_key="sk-test", model="gpt-test")


def test_openai_compat_availability() -> None:
    """配置齐全才可用；缺 api_key / model 时不可用（触发降级）。"""
    full = OpenAICompatClient("https://example.com/v1", "sk-test", "gpt-test")
    assert full.is_available()
    no_key = OpenAICompatClient("https://example.com/v1", "", "gpt-test")
    assert not no_key.is_available()
    no_model = OpenAICompatClient("https://example.com/v1", "sk-test", "")
    assert not no_model.is_available()


def test_openai_compat_parses_tool_call(monkeypatch) -> None:
    """tool_calls（arguments JSON 字符串）→ LLMToolCall。"""
    client = _compat_client(
        monkeypatch,
        _FakeCompletion(
            _FakeMessage(
                content="我来查询咖啡店",
                tool_calls=[_FakeToolCall("query_poi", '{"category": "Coffee Shop"}')],
            )
        ),
    )
    response = client.complete([LLMMessage(role="user", content="找咖啡店")], tools=[])
    assert response.text == "我来查询咖啡店"
    assert response.tool_calls == [LLMToolCall(name="query_poi", arguments={"category": "Coffee Shop"})]


def test_openai_compat_parses_text(monkeypatch) -> None:
    """无 tool_calls → 纯文本回复。"""
    client = _compat_client(monkeypatch, _FakeCompletion(_FakeMessage(content="你好，我可以帮你。")))
    response = client.complete([LLMMessage(role="user", content="你好")])
    assert response.tool_calls == []
    assert response.text == "你好，我可以帮你。"


def test_openai_compat_invalid_arguments_raises(monkeypatch) -> None:
    """arguments 非法 JSON → ValueError（路由层会重试并降级）。"""
    client = _compat_client(
        monkeypatch,
        _FakeCompletion(_FakeMessage(content="", tool_calls=[_FakeToolCall("query_poi", "not-json")])),
    )
    with pytest.raises(ValueError):
        client.complete([LLMMessage(role="user", content="找咖啡店")], tools=[])


def test_openai_compat_serializes_tool_result_conversation() -> None:
    """第二轮消息保留 assistant tool_calls 与 tool_call_id。"""
    call = LLMToolCall(
        id="call-1",
        name="query_poi",
        arguments={"category": "Coffee Shop"},
    )
    assistant = OpenAICompatClient._message_payload(
        LLMMessage(role="assistant", tool_calls=[call])
    )
    tool_result = OpenAICompatClient._message_payload(
        LLMMessage(
            role="tool",
            name="query_poi",
            tool_call_id="call-1",
            content='{"count": 1}',
        )
    )

    assert assistant["tool_calls"][0]["id"] == "call-1"
    assert assistant["tool_calls"][0]["function"]["name"] == "query_poi"
    assert tool_result["role"] == "tool"
    assert tool_result["tool_call_id"] == "call-1"
