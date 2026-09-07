"""LangGraph Postgres 持久化与 Redis 热点缓存/分布式锁的生命周期。"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock, RLock
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from app.agent.memory.artifacts import (
    InMemoryArtifactRepository,
    sqlalchemy_artifact_repository,
)
from app.agent.memory.context import ContextCache


class ThreadBusyError(RuntimeError):
    """同一 thread 未能在限定时间内取得执行锁。"""


class ThreadLockManager(Protocol):
    """同一会话串行执行所需的最小锁协议。"""

    def hold(self, thread_id: str) -> AbstractContextManager[None]: ...


class LocalThreadLockManager:
    """测试/单进程降级实现；不提供跨进程互斥。"""

    def __init__(self) -> None:
        self._guard = Lock()
        self._locks: dict[str, RLock] = {}

    @contextmanager
    def hold(self, thread_id: str):
        if not thread_id:
            yield
            return
        with self._guard:
            lock = self._locks.setdefault(thread_id, RLock())
        with lock:
            yield


class RedisContextCache(ContextCache):
    """长期偏好的 Redis JSON 热点缓存。"""

    def __init__(self, client: Any, ttl_seconds: int) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(f"agent:preferences:{key}")
        if raw is None:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._client.setex(
            f"agent:preferences:{key}",
            self._ttl_seconds,
            json.dumps(value, ensure_ascii=False, default=str),
        )


class RedisThreadLockManager:
    """使用 Redis 锁防止同一 LangGraph thread 被并发推进。"""

    def __init__(self, client: Any, timeout_seconds: int, wait_seconds: int) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._wait_seconds = wait_seconds

    @contextmanager
    def hold(self, thread_id: str):
        if not thread_id:
            yield
            return
        lock = self._client.lock(
            f"agent:thread-lock:{thread_id}",
            timeout=self._timeout_seconds,
            blocking_timeout=self._wait_seconds,
            raise_on_release_error=False,
        )
        if not lock.acquire(blocking=True):
            raise ThreadBusyError("当前会话正在处理另一条请求，请稍后重试。")
        try:
            yield
        finally:
            lock.release()


@dataclass
class AgentContextRuntime:
    """图编译和请求执行共享的上下文基础设施。"""

    checkpointer: BaseCheckpointSaver
    store: BaseStore
    cache: ContextCache
    thread_locks: ThreadLockManager
    artifact_repository_factory: Any = sqlalchemy_artifact_repository
    _postgres_pool: Any = None
    _redis_client: Any = None

    @classmethod
    def in_memory(cls) -> "AgentContextRuntime":
        """创建无需 PostgreSQL/Redis 的 mock 运行时。"""
        from app.agent.memory.context import InMemoryContextCache

        artifacts = InMemoryArtifactRepository()
        return cls(
            checkpointer=InMemorySaver(),
            store=InMemoryStore(),
            cache=InMemoryContextCache(),
            thread_locks=LocalThreadLockManager(),
            artifact_repository_factory=lambda _db: artifacts,
        )

    def close(self) -> None:
        """释放外部连接；内存实现无需处理。"""
        if self._redis_client is not None:
            self._redis_client.close()
        if self._postgres_pool is not None:
            self._postgres_pool.close()


def build_agent_context_runtime() -> AgentContextRuntime:
    """按配置构造运行时，并执行 LangGraph 自带表结构初始化。"""
    from app.core.config import settings

    if settings.agent_context_backend == "memory":
        return AgentContextRuntime.in_memory()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required when AGENT_CONTEXT_BACKEND=postgres_redis.")

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        from langgraph.store.postgres import PostgresStore
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        from redis import Redis
    except ImportError as exc:
        raise RuntimeError(
            "Postgres/Redis context dependencies are missing; install requirements.txt."
        ) from exc

    connection_url = _psycopg_url(settings.database_url)
    pool: Any = ConnectionPool(
        conninfo=connection_url,
        min_size=1,
        max_size=settings.agent_context_postgres_pool_size,
        open=True,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    )
    serializer = JsonPlusSerializer(
        allowed_msgpack_modules={
            ("app.agent.graph.state", "ToolExecution"),
            ("app.llm.schemas", "LLMMessage"),
            ("app.llm.schemas", "LLMToolCall"),
        }
    )
    checkpointer = PostgresSaver(pool, serde=serializer)
    store = PostgresStore(pool)
    checkpointer.setup()
    store.setup()

    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    redis_client.ping()
    cache = RedisContextCache(redis_client, settings.agent_context_cache_ttl_seconds)
    locks = RedisThreadLockManager(
        redis_client,
        timeout_seconds=settings.agent_thread_lock_timeout_seconds,
        wait_seconds=settings.agent_thread_lock_wait_seconds,
    )
    return AgentContextRuntime(
        checkpointer=checkpointer,
        store=store,
        cache=cache,
        thread_locks=locks,
        artifact_repository_factory=sqlalchemy_artifact_repository,
        _postgres_pool=pool,
        _redis_client=redis_client,
    )


@lru_cache(maxsize=1)
def get_agent_context_runtime() -> AgentContextRuntime:
    """返回进程级运行时，避免每个请求重复建连接和执行 setup。"""
    return build_agent_context_runtime()


def close_agent_context_runtime() -> None:
    """关闭已经初始化的运行时。"""
    if get_agent_context_runtime.cache_info().currsize:
        get_agent_context_runtime().close()
        get_agent_context_runtime.cache_clear()


def _psycopg_url(sqlalchemy_url: str) -> str:
    """把 SQLAlchemy 驱动 URL 转换为 psycopg 可识别格式。"""
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)
