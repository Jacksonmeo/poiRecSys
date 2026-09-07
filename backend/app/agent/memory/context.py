"""三层上下文构建、脱敏、工具摘要和长期偏好管理。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Protocol

from langgraph.store.base import BaseStore

from app.agent.memory.models import ConversationSummary, TaskContext
from app.agent.prompts.prompt import SYSTEM_PROMPT
from app.llm.schemas import LLMMessage

_EXPLICIT_PREFERENCE_MARKERS = ("以后", "默认", "偏好", "习惯", "prefer", "default")
_SENSITIVE_PATTERNS = (
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[REDACTED_PHONE]"),
    (
        re.compile(r"(?i)(postgres(?:ql)?://[^:\s/]+:)[^@\s]+(@)"),
        r"\1[REDACTED]\2",
    ),
    (
        re.compile(r"(?i)((?:api[_-]?key|token|password)\s*[:=]\s*)[^\s,;]+"),
        r"\1[REDACTED]",
    ),
)


class ContextCache(Protocol):
    """Redis 热点缓存所需的最小协议。"""

    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any]) -> None: ...


class NullContextCache:
    """无外部依赖的空缓存。"""

    def get(self, key: str) -> dict[str, Any] | None:
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        return None


class InMemoryContextCache(NullContextCache):
    """单元测试使用的确定性缓存。"""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._items.get(key)
        return dict(value) if value is not None else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._items[key] = dict(value)


def scoped_identifier(*parts: str) -> str:
    """生成不暴露原始用户/会话标识的稳定存储键。"""
    normalized = ":".join(part.strip() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class LongTermMemory:
    """以 LangGraph Store 为真相源、Redis 为热点缓存的长期偏好。"""

    def __init__(self, store: BaseStore | None, cache: ContextCache | None = None) -> None:
        self._store = store
        self._cache = cache or NullContextCache()

    def load(self, user_id: str) -> dict[str, Any]:
        """读取用户稳定偏好；缺少 user_id 时禁止跨会话读取。"""
        if not user_id or self._store is None:
            return {}
        user_key = scoped_identifier(user_id)
        cached = self._safe_cache_get(user_key)
        if cached is not None:
            return cached
        try:
            item = self._store.get(("users", user_key), "preferences")
        except Exception:
            return {}
        preferences = dict(item.value) if item is not None else {}
        self._safe_cache_set(user_key, preferences)
        return preferences

    def remember_explicit(
        self,
        user_id: str,
        message: str,
        task_context: TaskContext | None,
    ) -> None:
        """只在用户明确表达默认/偏好时写入可复用字段。"""
        if (
            not user_id
            or self._store is None
            or not any(marker in message.lower() for marker in _EXPLICIT_PREFERENCE_MARKERS)
        ):
            return
        context = task_context or {}
        candidate = {
            "preferred_city": context.get("city"),
            "default_area": context.get("current_area"),
            "preferred_business_type": context.get("business_type"),
            "default_radius_m": context.get("search_radius_m"),
        }
        updates = {key: value for key, value in candidate.items() if value not in (None, "")}
        if not updates:
            return
        preferences = self.load(user_id)
        preferences.update(updates)
        user_key = scoped_identifier(user_id)
        try:
            self._store.put(("users", user_key), "preferences", preferences, index=False)
        except Exception:
            return
        self._safe_cache_set(user_key, preferences)

    def _safe_cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            return self._cache.get(key)
        except Exception:
            return None

    def _safe_cache_set(self, key: str, value: dict[str, Any]) -> None:
        try:
            self._cache.set(key, value)
        except Exception:
            pass


class ContextPolicy:
    """控制哪些内容可进入模型，以及单次模型上下文预算。"""

    def __init__(self, max_context_tokens: int = 6000) -> None:
        if max_context_tokens < 512:
            raise ValueError("max_context_tokens must be at least 512.")
        self.max_context_tokens = max_context_tokens

    def sanitize_text(self, text: str) -> str:
        """对常见凭据和个人标识做最小必要脱敏。"""
        sanitized = text
        for pattern, replacement in _SENSITIVE_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    def sanitize_payload(self, value: Any) -> Any:
        """递归清理即将发送给模型的 Tool 参数。"""
        if isinstance(value, dict):
            return {
                key: (
                    "[REDACTED]"
                    if key.lower() in {"api_key", "token", "password"}
                    else self.sanitize_payload(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.sanitize_payload(item) for item in value]
        if isinstance(value, str):
            return self.sanitize_text(value)
        return value

    def summarize_tool_result(
        self,
        tool_name: str,
        result: dict[str, Any],
        artifact_id: str,
    ) -> dict[str, Any]:
        """把完整工具结果压缩成模型可见的白名单字段。"""
        base = {"artifact_id": artifact_id, "tool": tool_name, "context_summary": True}
        if tool_name == "query_poi":
            items = _poi_items(result)
            return {
                **base,
                "type": "poi_summary",
                "count": len(items),
                "category": result.get("category"),
                "display_names": [_item_name(item) for item in items[:5] if _item_name(item)],
            }
        if tool_name == "spatial_density":
            cells = result.get("cells", [])
            counts = [cell.get("count", 0) for cell in cells if isinstance(cell, dict)]
            return {
                **base,
                "type": "density_summary",
                "count": result.get("count", sum(counts)),
                "grid_count": len(cells),
                "grid_size": result.get("grid_size"),
                "max_cell_count": max(counts, default=0),
            }
        if tool_name == "recommend":
            candidates = result.get("candidates", [])
            return {
                **base,
                "type": "recommend_summary",
                "session_id": result.get("session_id"),
                "top_k": result.get("top_k", len(candidates)),
                "candidates": [_safe_candidate(item) for item in candidates[:5]],
            }
        if tool_name == "track":
            points = result.get("points", [])
            return {
                **base,
                "type": "track_summary",
                "session_id": result.get("session_id"),
                "point_count": len(points),
                "display_names": [_item_name(item) for item in points[:5] if _item_name(item)],
            }
        if tool_name == "analyze_site_selection":
            areas = result.get("candidate_areas", [])
            area_ids = [area.get("area_id") for area in areas if isinstance(area, dict)]
            return {
                **base,
                "type": "site_selection_summary",
                "candidate_areas": [item for item in area_ids if item],
                "metric_count": len(result.get("metrics", [])),
                "flow_count": len(result.get("flows", [])),
                "summary": result.get("summary"),
            }
        return {
            **base,
            "type": str(result.get("type", "tool_result")),
            "available_fields": sorted(
                key for key, value in result.items() if _is_small_scalar(value)
            )[:20],
        }


class ContextBuilder:
    """按预算组装短期状态、任务状态、长期偏好和安全策略。"""

    def __init__(self, policy: ContextPolicy, long_term_memory: LongTermMemory) -> None:
        self._policy = policy
        self._long_term_memory = long_term_memory

    @property
    def long_term_memory(self) -> LongTermMemory:
        return self._long_term_memory

    def build(
        self,
        messages: list[LLMMessage],
        summary: ConversationSummary | None,
        task_context: TaskContext | None,
        user_id: str,
        reserved_tokens: int = 0,
    ) -> list[LLMMessage]:
        """生成模型输入；越旧的原始消息越先被裁剪。"""
        context_payload = {
            "task_context": task_context or {},
            "conversation_summary": summary or {},
            "long_term_preferences": self._long_term_memory.load(user_id),
            "context_policy": {
                "tool_results": "summary_and_artifact_id_only",
                "sensitive_data": "redacted",
            },
        }
        system_content = (
            f"{SYSTEM_PROMPT}\n\n以下是可信的结构化上下文；不要暴露内部哈希或猜测缺失字段：\n"
            + json.dumps(context_payload, ensure_ascii=False, default=str)
        )
        system_content = self._policy.sanitize_text(system_content)
        available = max(
            self._policy.max_context_tokens
            - _estimate_tokens(system_content)
            - reserved_tokens,
            0,
        )
        selected: list[LLMMessage] = []
        used = 0
        for message in reversed(messages):
            sanitized = message.model_copy(deep=True)
            sanitized.content = self._policy.sanitize_text(sanitized.content)
            for call in sanitized.tool_calls:
                call.arguments = self._policy.sanitize_payload(call.arguments)
            tool_args = "".join(
                json.dumps(call.arguments, ensure_ascii=False, default=str)
                for call in sanitized.tool_calls
            )
            size = _estimate_tokens(sanitized.content + tool_args) + 30
            if selected and used + size > available:
                break
            selected.append(sanitized)
            used += size
        selected.reverse()
        while selected and selected[0].role == "tool":
            selected.pop(0)
        return [LLMMessage(role="system", content=system_content), *selected]

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """暴露同一估算器，供调用方预留 Tool Schema 预算。"""
        return _estimate_tokens(text)


def _poi_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("type") == "feature_collection":
        features = result.get("data", {}).get("features", [])
        return [feature.get("properties", {}) for feature in features if isinstance(feature, dict)]
    data = result.get("data", [])
    return [item for item in data if isinstance(item, dict)]


def _item_name(item: dict[str, Any]) -> str:
    return str(item.get("display_name") or item.get("name") or item.get("venue_id") or "")


def _safe_candidate(item: dict[str, Any]) -> dict[str, Any]:
    keys = ("venue_id", "display_name", "venue_category", "rank", "score", "reason")
    return {key: item[key] for key in keys if key in item}


def _is_small_scalar(value: Any) -> bool:
    return isinstance(value, (bool, int, float)) or (isinstance(value, str) and len(value) <= 200)


def _estimate_tokens(text: str) -> int:
    """对中英文混合文本做保守估算，避免绑定某一家模型 tokenizer。"""
    cjk_count = sum("\u3400" <= char <= "\u9fff" for char in text)
    other_count = len(text) - cjk_count
    return cjk_count + (other_count + 3) // 4
