from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryQuery:
    query: str
    scopes: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 10
    min_score: float | None = None
    max_context_tokens: int | None = None
    time_window: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        text = str(self.query or "").strip()
        object.__setattr__(self, "query", text)
        object.__setattr__(self, "scopes", [str(value) for value in self.scopes])
        object.__setattr__(self, "kinds", [str(value) for value in self.kinds])
        object.__setattr__(self, "filters", dict(self.filters or {}))
        if not text and not self.filters and not self.kinds:
            raise ValueError("query, filters, or kinds are required")
        object.__setattr__(self, "limit", max(1, min(int(self.limit or 10), 100)))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MemoryQuery:
        return cls(
            query=str(payload.get("query") or payload.get("text") or ""),
            scopes=[str(value) for value in payload.get("scopes") or []],
            kinds=[str(value) for value in payload.get("kinds") or []],
            filters=dict(payload.get("filters") or {}),
            limit=int(payload.get("limit") or 10),
            min_score=_optional_float(payload.get("min_score", payload.get("score_threshold"))),
            max_context_tokens=_optional_int(payload.get("max_context_tokens")),
            time_window=dict(payload["time_window"]) if isinstance(payload.get("time_window"), dict) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "scopes": list(self.scopes),
            "kinds": list(self.kinds),
            "filters": dict(self.filters),
            "limit": self.limit,
            "min_score": self.min_score,
            "max_context_tokens": self.max_context_tokens,
            "time_window": dict(self.time_window) if self.time_window is not None else None,
        }


@dataclass(frozen=True)
class MemoryConsolidationRequest:
    memory_ids: list[str] = field(default_factory=list)
    query: MemoryQuery | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    actor: str | None = None
    run_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        memory_ids = [str(memory_id).strip() for memory_id in self.memory_ids if str(memory_id).strip()]
        query = self.query
        if query is not None and not isinstance(query, MemoryQuery):
            query = MemoryQuery.from_dict(dict(query))
        filters = dict(self.filters or {})
        if not memory_ids and query is None and not filters:
            raise ValueError("memory_ids, query, or filters are required")
        object.__setattr__(self, "memory_ids", memory_ids)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "filters", filters)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MemoryConsolidationRequest:
        raw_query = payload.get("query")
        query = MemoryQuery.from_dict(raw_query) if isinstance(raw_query, dict) else None
        return cls(
            memory_ids=[str(value) for value in payload.get("memory_ids") or []],
            query=query,
            filters=dict(payload.get("filters") or {}),
            actor=_optional_str(payload.get("actor")),
            run_id=_optional_str(payload.get("run_id")),
            reason=_optional_str(payload.get("reason")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_ids": list(self.memory_ids),
            "query": self.query.to_dict() if self.query is not None else None,
            "filters": dict(self.filters),
            "actor": self.actor,
            "run_id": self.run_id,
            "reason": self.reason,
        }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


