from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from framework.memory.models.kind import MemoryKind
from framework.memory.models.record import MemoryRecord
from framework.memory.models.scope import MemoryScope
from framework.memory.models.time_window import TimeWindow


@dataclass(frozen=True)
class MemoryQuery:
    query: str
    scopes: list[MemoryScope] = field(default_factory=list)
    kinds: list[MemoryKind] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    namespace: str | None = None
    tenant_id: str | None = None
    limit: int = 10
    min_score: float | None = None
    max_context_tokens: int | None = None
    time_window: TimeWindow | None = None
    include_invalidated: bool = False
    include_expired: bool = False

    def __post_init__(self) -> None:
        text = str(self.query or "").strip()
        object.__setattr__(self, "query", text)
        object.__setattr__(self, "scopes", [_scope(scope) for scope in self.scopes])
        object.__setattr__(self, "kinds", [_kind(kind) for kind in self.kinds])
        object.__setattr__(self, "filters", dict(self.filters or {}))
        object.__setattr__(self, "tags", [str(tag) for tag in (self.tags or [])])
        object.__setattr__(self, "namespace", _optional_str(self.namespace))
        object.__setattr__(self, "tenant_id", _optional_str(self.tenant_id))
        if not text and not self.filters and not self.kinds and not self.tags:
            raise ValueError("query, filters, or kinds are required")
        object.__setattr__(self, "limit", max(1, min(int(self.limit or 10), 100)))
        if self.min_score is not None:
            score = float(self.min_score)
            if score < 0.0 or score > 1.0:
                raise ValueError("min_score must be between 0 and 1")
            object.__setattr__(self, "min_score", score)
        if self.max_context_tokens is not None:
            object.__setattr__(self, "max_context_tokens", max(1, int(self.max_context_tokens)))
        if self.time_window is not None and not isinstance(self.time_window, TimeWindow):
            object.__setattr__(self, "time_window", TimeWindow.from_dict(dict(self.time_window)))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryQuery":
        raw_time_window = payload.get("time_window")
        return cls(
            query=str(payload.get("query") or payload.get("text") or ""),
            scopes=list(payload.get("scopes") or []),
            kinds=list(payload.get("kinds") or []),
            filters=dict(payload.get("filters") or {}),
            tags=[str(item) for item in payload.get("tags") or []],
            namespace=_optional_str(payload.get("namespace")),
            tenant_id=_optional_str(payload.get("tenant_id")),
            limit=int(payload.get("limit") or 10),
            min_score=_optional_float(payload.get("min_score", payload.get("score_threshold"))),
            max_context_tokens=_optional_int(payload.get("max_context_tokens")),
            time_window=TimeWindow.from_dict(raw_time_window) if isinstance(raw_time_window, dict) else None,
            include_invalidated=bool(payload.get("include_invalidated", False)),
            include_expired=bool(payload.get("include_expired", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "scopes": [scope.value for scope in self.scopes],
            "kinds": [kind.value for kind in self.kinds],
            "filters": dict(self.filters),
            "tags": list(self.tags),
            "namespace": self.namespace,
            "tenant_id": self.tenant_id,
            "limit": self.limit,
            "min_score": self.min_score,
            "max_context_tokens": self.max_context_tokens,
            "time_window": self.time_window.to_dict() if self.time_window is not None else None,
            "include_invalidated": self.include_invalidated,
            "include_expired": self.include_expired,
        }

    def effective_limit(self, max_limit: int) -> int:
        return min(self.limit, max(1, int(max_limit)))

    def with_filters(self, **filters: Any) -> "MemoryQuery":
        return replace(self, filters={**self.filters, **filters})

    def matches_metadata(self, record: MemoryRecord) -> bool:
        for key, value in self.filters.items():
            if key == "collection":
                continue
            actual = _record_filter_value(record, key)
            if actual != value:
                return False
        return True


def _record_filter_value(record: MemoryRecord, key: str) -> Any:
    refs = record.refs if isinstance(record.refs, dict) else {}
    if key == "memory_id":
        return record.memory_id
    if key == "scope":
        return record.scope.value
    if key == "kind":
        return record.kind.value
    if key in refs:
        return refs[key]
    if key in record.metadata:
        return record.metadata[key]
    return getattr(record, key, None)


def _scope(value: Any) -> MemoryScope:
    return value if isinstance(value, MemoryScope) else MemoryScope(str(value))


def _kind(value: Any) -> MemoryKind:
    return value if isinstance(value, MemoryKind) else MemoryKind(str(value))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
