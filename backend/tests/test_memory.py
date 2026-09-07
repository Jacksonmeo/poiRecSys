"""三层上下文单元测试；不连接 PostgreSQL、Redis 或外部 LLM。"""

import json
from unittest.mock import Mock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.memory import InMemoryStore
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.agent.graph.runner import AgentRunner
from app.agent.memory.artifacts import (
    InMemoryArtifactRepository,
    SqlAlchemyArtifactRepository,
)
from app.agent.memory.context import (
    ContextBuilder,
    ContextPolicy,
    InMemoryContextCache,
    LongTermMemory,
    scoped_identifier,
)
from app.agent.memory.runtime import RedisContextCache, RedisThreadLockManager
from app.agent.registry import AgentTool, ToolRegistry
from app.agent.router_llm import LLMIntentRouter
from app.llm.client import LLMClient
from app.llm.schemas import LLMMessage, LLMResponse, LLMToolCall


class _LargePoiTool(AgentTool):
    name = "query_poi"
    description = "mock POI query"
    parameters = {
        "type": "object",
        "properties": {"category": {"type": "string"}},
    }

    def run(self, db: Session, args: dict) -> dict:
        return {
            "type": "poi_list",
            "category": args.get("category"),
            "data": [
                {
                    "venue_id": f"poi_{index}",
                    "display_name": f"Coffee {index}",
                    "latitude": 35.0 + index / 1000,
                    "longitude": 139.0 + index / 1000,
                }
                for index in range(200)
            ],
        }


class _ContextAwareClient(LLMClient):
    name = "context_aware"

    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []

    def complete(self, messages, tools=None):
        self.calls.append([message.model_copy(deep=True) for message in messages])
        if messages[-1].role == "tool":
            return LLMResponse(text="已完成咖啡店查询。")
        latest_user = next(message.content for message in reversed(messages) if message.role == "user")
        if "咖啡" in latest_user:
            return LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="call-poi",
                        name="query_poi",
                        arguments={"category": "Coffee Shop", "location": "东京"},
                    )
                ]
            )
        return LLMResponse(text="已读取上一次任务上下文。")


def _runner(client: LLMClient, saver=None, store=None):
    registry = ToolRegistry()
    registry.register(_LargePoiTool())
    artifacts = InMemoryArtifactRepository()
    runner = AgentRunner(
        registry=registry,
        router=LLMIntentRouter(registry, client=client),
        fallback_reply=lambda _name, _result: "fallback",
        checkpointer=saver or _strict_saver(),
        store=store or InMemoryStore(),
        context_cache=InMemoryContextCache(),
        artifact_repository_factory=lambda _db: artifacts,
    )
    return runner, artifacts


def _strict_saver() -> InMemorySaver:
    """使用与生产 PostgresSaver 相同的反序列化白名单。"""
    serializer = JsonPlusSerializer(
        allowed_msgpack_modules={
            ("app.agent.graph.state", "ToolExecution"),
            ("app.llm.schemas", "LLMMessage"),
            ("app.llm.schemas", "LLMToolCall"),
        }
    )
    return InMemorySaver(serde=serializer)


def test_checkpointer_restores_structured_state_between_turns() -> None:
    client = _ContextAwareClient()
    runner, _artifacts = _runner(client)

    first = runner.run(
        Mock(spec=Session),
        "分析东京的咖啡店",
        session_id="session-a",
        user_id="user-a",
    )
    second = runner.run(
        Mock(spec=Session),
        "沿用刚才的任务上下文",
        session_id="session-a",
        user_id="user-a",
    )

    snapshot = runner.get_state("session-a", "user-a")
    assert first.reply == "已完成咖啡店查询。"
    assert second.reply == "已读取上一次任务上下文。"
    assert snapshot.values["task_context"]["city"] == "东京"
    assert snapshot.values["task_context"]["business_type"] == "Coffee Shop"
    assert snapshot.values["context_version"] == 1
    assert len(snapshot.values["artifact_refs"]) == 1
    assert [message.role for message in snapshot.values["messages"]].count("user") == 2
    assert snapshot.values["summary"]["completed_actions"]


def test_full_tool_result_bypasses_checkpoint_and_model_context() -> None:
    client = _ContextAwareClient()
    runner, artifacts = _runner(client)

    result = runner.run(
        Mock(spec=Session),
        "分析东京的咖啡店",
        session_id="session-large-result",
        user_id="user-a",
    )

    assert len(result.executions[0].result["data"]) == 200
    model_payload = json.loads(client.calls[1][-1].content)
    assert model_payload["count"] == 200
    assert "data" not in model_payload
    assert "latitude" not in client.calls[1][-1].content

    snapshot = runner.get_state("session-large-result", "user-a")
    checkpoint_payload = snapshot.values["executions"][0].result
    assert "data" not in checkpoint_payload
    artifact_id = result.executions[0].artifact_id
    thread_id = scoped_identifier("user-a", "session-large-result")
    assert len(artifacts.get(artifact_id, thread_id)["data"]) == 200


def test_same_session_is_isolated_by_user_id() -> None:
    client = _ContextAwareClient()
    runner, _artifacts = _runner(client)
    runner.run(Mock(spec=Session), "分析东京的咖啡店", "shared", "user-a")

    assert runner.get_state("shared", "user-a").values["messages"]
    assert runner.get_state("shared", "user-b").values == {}


def test_long_term_memory_only_saves_explicit_preferences() -> None:
    store = InMemoryStore()
    cache = InMemoryContextCache()
    memory = LongTermMemory(store, cache)
    context = {
        "city": "东京",
        "current_area": "新宿",
        "business_type": "Coffee Shop",
        "search_radius_m": 1500,
    }

    memory.remember_explicit("user-a", "查询一次", context)
    assert memory.load("user-a") == {}

    memory.remember_explicit("user-a", "以后默认按这个范围分析", context)
    assert memory.load("user-a") == {
        "preferred_city": "东京",
        "default_area": "新宿",
        "preferred_business_type": "Coffee Shop",
        "default_radius_m": 1500,
    }
    model_context = ContextBuilder(ContextPolicy(), memory).build(
        [LLMMessage(role="user", content="继续")],
        None,
        {},
        "user-a",
    )
    assert '"default_area": "新宿"' in model_context[0].content


def test_context_builder_redacts_secrets_and_respects_budget() -> None:
    policy = ContextPolicy(max_context_tokens=512)
    builder = ContextBuilder(policy, LongTermMemory(InMemoryStore()))
    messages = [
        LLMMessage(role="user", content="旧消息" * 600),
        LLMMessage(
            role="user",
            content="邮箱 test@example.com，api_key=secret-value，请继续分析",
        ),
    ]

    result = builder.build(messages, None, {"city": "东京"}, "")
    rendered = "\n".join(message.content for message in result)

    assert result[0].role == "system"
    assert "test@example.com" not in rendered
    assert "secret-value" not in rendered
    assert "[REDACTED_EMAIL]" in rendered
    assert "[REDACTED]" in rendered
    assert "旧消息" * 600 not in rendered
    assert policy.sanitize_payload({"token": "secret", "note": "test@example.com"}) == {
        "token": "[REDACTED]",
        "note": "[REDACTED_EMAIL]",
    }


def test_resume_restarts_from_failed_tool_checkpoint() -> None:
    class _FlakyTool(_LargePoiTool):
        def __init__(self) -> None:
            self.calls = 0

        def run(self, db: Session, args: dict) -> dict:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary tool failure")
            return super().run(db, args)

    tool = _FlakyTool()
    registry = ToolRegistry()
    registry.register(tool)
    client = _ContextAwareClient()
    artifacts = InMemoryArtifactRepository()
    runner = AgentRunner(
        registry=registry,
        router=LLMIntentRouter(registry, client=client),
        fallback_reply=lambda _name, _result: "fallback",
        checkpointer=_strict_saver(),
        store=InMemoryStore(),
        artifact_repository_factory=lambda _db: artifacts,
    )

    with pytest.raises(RuntimeError, match="temporary tool failure"):
        runner.run(Mock(spec=Session), "分析东京的咖啡店", "resume-me", "user-a")
    assert len(client.calls) == 1

    result = runner.resume(Mock(spec=Session), "resume-me", "user-a")

    assert result.reply == "已完成咖啡店查询。"
    assert tool.calls == 2
    assert len(client.calls) == 2


def test_redis_adapters_apply_ttl_and_thread_lock() -> None:
    class _FakeLock:
        def __init__(self) -> None:
            self.acquired = False
            self.released = False

        def acquire(self, blocking=True):
            self.acquired = blocking
            return True

        def release(self):
            self.released = True

    class _FakeRedis:
        def __init__(self) -> None:
            self.items = {}
            self.ttls = {}
            self.created_lock = _FakeLock()

        def get(self, key):
            return self.items.get(key)

        def setex(self, key, ttl, value):
            self.items[key] = value
            self.ttls[key] = ttl

        def lock(self, name, **kwargs):
            self.lock_name = name
            self.lock_options = kwargs
            return self.created_lock

    client = _FakeRedis()
    cache = RedisContextCache(client, ttl_seconds=60)
    cache.set("user-hash", {"preferred_city": "东京"})

    assert cache.get("user-hash") == {"preferred_city": "东京"}
    assert client.ttls["agent:preferences:user-hash"] == 60

    locks = RedisThreadLockManager(client, timeout_seconds=120, wait_seconds=5)
    with locks.hold("thread-hash"):
        assert client.created_lock.acquired
    assert client.created_lock.released
    assert client.lock_name == "agent:thread-lock:thread-hash"


def test_sqlalchemy_artifact_repository_with_in_memory_sqlite() -> None:
    """验证生产仓储读写契约，不连接项目 PostgreSQL。"""
    from app.models.agent_artifact import AgentToolArtifact

    engine = create_engine("sqlite+pysqlite:///:memory:")
    AgentToolArtifact.__table__.create(engine)
    local_session = sessionmaker(bind=engine)()
    repository = SqlAlchemyArtifactRepository(local_session)

    artifact_id = repository.save(
        thread_id="thread-hash",
        user_id_hash="user-hash",
        tool_name="spatial_density",
        payload={"cells": [{"count": 3}]},
    )

    assert repository.get(artifact_id, "thread-hash") == {"cells": [{"count": 3}]}
    assert repository.get(artifact_id, "another-thread") is None
    local_session.close()
    engine.dispose()
