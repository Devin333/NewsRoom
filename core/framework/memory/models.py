from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar
from uuid import uuid4


class MemoryScope(str, Enum):
    WORKING = "working"
    SESSION = "session"
    AGENT = "agent"
    WORKFLOW = "workflow"
    USER = "user"
    GLOBAL = "global"


class MemoryKind(str, Enum):
    WORKING = "working"
    SESSION = "session"
    CORE = "core"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATION = "relation"
    REFLECTIVE = "reflective"
    PROCEDURAL = "procedural"
    ARTIFACT = "artifact"
    OBSERVATION = "observation"


class MemoryWriteMode(str, Enum):
    APPEND = "append"
    UPSERT = "upsert"
    REPLACE = "replace"


@dataclass(frozen=True)
class TimeWindow:
    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        start = _optional_datetime(self.start)
        end = _optional_datetime(self.end)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        if start is not None and end is not None and start > end:
            raise ValueError("time_window start must be before end")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TimeWindow":
        return cls(
            start=_optional_datetime(payload.get("start")),
            end=_optional_datetime(payload.get("end")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": _datetime_to_json(self.start),
            "end": _datetime_to_json(self.end),
        }


@dataclass(frozen=True)
class MemoryRecord:
    content: str
    kind: MemoryKind = MemoryKind.SEMANTIC
    scope: MemoryScope = MemoryScope.SESSION
    memory_id: str = field(default_factory=lambda: uuid4().hex)
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    confidence: float | None = None
    importance: float | None = None
    actor: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        content = str(self.content or "").strip()
        if not content:
            raise ValueError("memory content is required")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "kind", _coerce_enum(MemoryKind, self.kind))
        object.__setattr__(self, "scope", _coerce_enum(MemoryScope, self.scope))
        object.__setattr__(self, "memory_id", str(self.memory_id or uuid4().hex))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "refs", dict(self.refs or {}))
        _validate_no_sensitive_keys(self.metadata, field_name="metadata")
        _validate_no_sensitive_keys(self.refs, field_name="refs")
        object.__setattr__(self, "tags", [str(tag) for tag in (self.tags or [])])
        object.__setattr__(
            self,
            "created_at",
            _optional_datetime(self.created_at) or datetime.now(UTC),
        )
        if self.updated_at is not None:
            object.__setattr__(self, "updated_at", _coerce_datetime(self.updated_at))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _coerce_datetime(self.expires_at))
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        _validate_optional_score("confidence", self.confidence)
        _validate_optional_score("importance", self.importance)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryRecord":
        refs = dict(payload.get("refs") or {})
        for key in ("run_id", "report_id", "evidence_id", "source_item_id", "section_id"):
            value = payload.get(key)
            if value is not None:
                refs.setdefault(key, value)
        metadata = dict(payload.get("metadata") or {})
        extra_payload = payload.get("payload")
        if isinstance(extra_payload, dict):
            metadata.setdefault("payload", dict(extra_payload))
        return cls(
            memory_id=str(payload.get("memory_id") or payload.get("document_id") or uuid4().hex),
            kind=payload.get("kind") or payload.get("source_type") or MemoryKind.SEMANTIC,
            scope=payload.get("scope") or MemoryScope.SESSION,
            content=str(payload.get("content") or payload.get("text") or ""),
            summary=_optional_str(payload.get("summary")),
            metadata=metadata,
            refs=refs,
            tags=[str(item) for item in payload.get("tags") or []],
            confidence=_optional_float(payload.get("confidence")),
            importance=_optional_float(payload.get("importance")),
            actor=_optional_str(payload.get("actor")),
            created_at=_optional_datetime(payload.get("created_at")) or datetime.now(UTC),
            updated_at=_optional_datetime(payload.get("updated_at")),
            expires_at=_optional_datetime(payload.get("expires_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "kind": self.kind.value,
            "scope": self.scope.value,
            "summary": self.summary,
            "content": self.content,
            "metadata": dict(self.metadata),
            "refs": dict(self.refs),
            "tags": list(self.tags),
            "confidence": self.confidence,
            "importance": self.importance,
            "actor": self.actor,
            "created_at": _datetime_to_json(self.created_at),
            "updated_at": _datetime_to_json(self.updated_at),
            "expires_at": _datetime_to_json(self.expires_at),
        }


@dataclass(frozen=True)
class MemoryQuery:
    query: str
    scopes: list[MemoryScope] = field(default_factory=list)
    kinds: list[MemoryKind] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 10
    min_score: float | None = None
    max_context_tokens: int | None = None
    time_window: TimeWindow | None = None

    def __post_init__(self) -> None:
        text = str(self.query or "").strip()
        object.__setattr__(self, "query", text)
        object.__setattr__(self, "scopes", _coerce_enum_list(MemoryScope, self.scopes))
        object.__setattr__(self, "kinds", _coerce_enum_list(MemoryKind, self.kinds))
        object.__setattr__(self, "filters", dict(self.filters or {}))
        if not text and not self.filters and not self.kinds:
            raise ValueError("query, filters, or kinds are required")
        object.__setattr__(self, "limit", max(1, min(int(self.limit or 10), 100)))
        if self.min_score is not None:
            _validate_optional_score("min_score", self.min_score)
            object.__setattr__(self, "min_score", float(self.min_score))
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
            limit=int(payload.get("limit") or 10),
            min_score=_optional_float(payload.get("min_score", payload.get("score_threshold"))),
            max_context_tokens=_optional_int(payload.get("max_context_tokens")),
            time_window=TimeWindow.from_dict(raw_time_window) if isinstance(raw_time_window, dict) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "scopes": [scope.value for scope in self.scopes],
            "kinds": [kind.value for kind in self.kinds],
            "filters": dict(self.filters),
            "limit": self.limit,
            "min_score": self.min_score,
            "max_context_tokens": self.max_context_tokens,
            "time_window": self.time_window.to_dict() if self.time_window is not None else None,
        }


@dataclass(frozen=True)
class MemorySearchResult:
    record: MemoryRecord
    score: float = 0.0
    match_reasons: list[str] = field(default_factory=list)

    @property
    def memory_id(self) -> str:
        return self.record.memory_id

    def to_dict(self) -> dict[str, Any]:
        refs = dict(self.record.refs)
        payload = {
            "memory_id": self.record.memory_id,
            "document_id": self.record.memory_id,
            "kind": self.record.kind.value,
            "scope": self.record.scope.value,
            "summary": self.record.summary,
            "content": self.record.content,
            "text": self.record.content,
            "score": self.score,
            "refs": refs,
            "metadata": dict(self.record.metadata),
            "match_reasons": list(self.match_reasons),
        }
        for key in ("run_id", "report_id", "evidence_id", "source_item_id", "section_id"):
            value = refs.get(key) or self.record.metadata.get(key)
            if value is not None:
                payload[key] = value
        payload["record"] = self.record.to_dict()
        return payload


@dataclass(frozen=True)
class MemoryContextBlock:
    content: str
    token_estimate: int
    memory_ids: list[str] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "MemoryContextBlock":
        return cls(content="", token_estimate=0, memory_ids=[])

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "token_estimate": self.token_estimate,
            "memory_ids": list(self.memory_ids),
        }


@dataclass(frozen=True)
class MemoryRecallResult:
    query: MemoryQuery
    results: list[MemorySearchResult] = field(default_factory=list)
    context_block: MemoryContextBlock = field(default_factory=MemoryContextBlock.empty)

    @property
    def result_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.query,
            "scopes": [scope.value for scope in self.query.scopes],
            "kinds": [kind.value for kind in self.query.kinds],
            "filters": dict(self.query.filters),
            "limit": self.query.limit,
            "result_count": self.result_count,
            "results": [result.to_dict() for result in self.results],
            "context_block": self.context_block.to_dict(),
        }


@dataclass(frozen=True)
class MemoryWriteRequest:
    records: list[MemoryRecord]
    mode: MemoryWriteMode = MemoryWriteMode.APPEND
    actor: str | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", [coerce_memory_record(record) for record in self.records])
        object.__setattr__(self, "mode", _coerce_enum(MemoryWriteMode, self.mode))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryWriteRequest":
        return cls(
            records=[coerce_memory_record(record) for record in payload.get("records") or []],
            mode=payload.get("mode") or MemoryWriteMode.APPEND,
            actor=_optional_str(payload.get("actor")),
            run_id=_optional_str(payload.get("run_id")),
        )


@dataclass(frozen=True)
class MemoryWriteResult:
    accepted_count: int = 0
    written_count: int = 0
    memory_ids: list[str] = field(default_factory=list)
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "accepted_count": self.accepted_count,
            "written_count": self.written_count,
            "memory_ids": list(self.memory_ids),
            "skipped_count": self.skipped_count,
            "errors": list(self.errors),
        }


def coerce_memory_record(value: MemoryRecord | dict[str, Any]) -> MemoryRecord:
    if isinstance(value, MemoryRecord):
        return value
    if isinstance(value, dict):
        return MemoryRecord.from_dict(value)
    raise TypeError("memory record must be a MemoryRecord or object")


def estimate_tokens(text: str) -> int:
    normalized = str(text or "")
    if not normalized:
        return 0
    return max(1, len(normalized) // 4)


EnumT = TypeVar("EnumT", bound=Enum)


def _coerce_enum(enum_type: type[EnumT], value: Any) -> EnumT:
    if isinstance(value, enum_type):
        return value
    return enum_type(str(value))


def _coerce_enum_list(enum_type: type[EnumT], values: list[Any]) -> list[EnumT]:
    return [_coerce_enum(enum_type, value) for value in values]


def _coerce_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return _coerce_datetime(value) if isinstance(value, datetime) else None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return _coerce_datetime(datetime.fromisoformat(text))


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _coerce_datetime(value).isoformat().replace("+00:00", "Z")


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


def _validate_optional_score(name: str, value: float | None) -> None:
    if value is None:
        return
    numeric = float(value)
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


_SENSITIVE_KEY_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


def _validate_no_sensitive_keys(value: dict[str, Any], *, field_name: str) -> None:
    for key in value:
        normalized = str(key).casefold()
        if any(token in normalized for token in _SENSITIVE_KEY_TOKENS):
            raise ValueError(f"memory {field_name} contains sensitive key: {key}")
