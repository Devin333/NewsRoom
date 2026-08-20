from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from framework.memory.models.kind import MemoryKind
from framework.memory.models.reference import (
    MemoryReference,
    legacy_refs_from_references,
    references_from_legacy_refs,
)
from framework.memory.models.scope import MemoryScope
from framework.memory.models.score import MemoryScore
from framework.shared.hashing import short_hash
from framework.shared.time import format_datetime, parse_datetime, utc_now


@dataclass(frozen=True)
class MemoryRecord:
    content: str
    kind: MemoryKind = MemoryKind.SEMANTIC
    scope: MemoryScope = MemoryScope.SESSION
    memory_id: str = field(default_factory=lambda: uuid4().hex)
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] | list[MemoryReference | dict[str, Any]] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    confidence: float | None = None
    importance: float | None = None
    score: MemoryScore | None = None
    embedding: list[float] | None = None
    actor: str | None = None
    namespace: str | None = None
    tenant_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        content = str(self.content or "").strip()
        if not content:
            raise ValueError("memory content is required")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "kind", _memory_kind(self.kind))
        object.__setattr__(self, "scope", _memory_scope(self.scope))
        object.__setattr__(self, "memory_id", str(self.memory_id or uuid4().hex))
        metadata = dict(self.metadata or {})
        refs = _normalize_refs(self.refs)
        _validate_no_sensitive_keys(metadata, field_name="metadata")
        _validate_no_sensitive_keys(refs, field_name="refs")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "refs", refs)
        object.__setattr__(self, "tags", [str(tag) for tag in (self.tags or [])])
        object.__setattr__(self, "confidence", _optional_score("confidence", self.confidence))
        object.__setattr__(self, "importance", _optional_score("importance", self.importance))
        if self.score is not None and not isinstance(self.score, MemoryScore):
            object.__setattr__(self, "score", MemoryScore.from_dict(dict(self.score)))
        if self.embedding is not None:
            object.__setattr__(self, "embedding", [float(value) for value in self.embedding])
        object.__setattr__(self, "actor", _optional_str(self.actor))
        object.__setattr__(self, "namespace", _optional_str(self.namespace))
        object.__setattr__(self, "tenant_id", _optional_str(self.tenant_id))
        created_at = parse_datetime(self.created_at) or utc_now()
        updated_at = parse_datetime(self.updated_at)
        expires_at = parse_datetime(self.expires_at)
        invalidated_at = parse_datetime(self.invalidated_at)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "invalidated_at", invalidated_at)
        if expires_at is not None and expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")
        object.__setattr__(self, "version", max(1, int(self.version or 1)))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryRecord":
        refs = _normalize_refs(payload.get("refs") or payload.get("references") or {})
        for key in _GENERIC_REF_KEYS:
            value = payload.get(key)
            if value is not None:
                refs.setdefault(key, value)
        metadata = dict(payload.get("metadata") or {})
        extra_payload = payload.get("payload")
        if isinstance(extra_payload, dict):
            metadata.setdefault("payload", dict(extra_payload))
        return cls(
            memory_id=str(payload.get("memory_id") or payload.get("document_id") or uuid4().hex),
            kind=_kind_from_payload(payload),
            scope=payload.get("scope") or MemoryScope.SESSION,
            content=str(payload.get("content") or payload.get("text") or ""),
            summary=_optional_str(payload.get("summary")),
            metadata=metadata,
            refs=refs,
            tags=[str(item) for item in payload.get("tags") or []],
            confidence=_optional_float(payload.get("confidence")),
            importance=_optional_float(payload.get("importance")),
            score=MemoryScore.from_dict(payload["score"]) if isinstance(payload.get("score"), dict) else None,
            embedding=_optional_float_list(payload.get("embedding")),
            actor=_optional_str(payload.get("actor")),
            namespace=_optional_str(payload.get("namespace")),
            tenant_id=_optional_str(payload.get("tenant_id")),
            created_at=parse_datetime(payload.get("created_at")) or utc_now(),
            updated_at=parse_datetime(payload.get("updated_at")),
            expires_at=parse_datetime(payload.get("expires_at")),
            invalidated_at=parse_datetime(payload.get("invalidated_at")),
            invalidation_reason=_optional_str(payload.get("invalidation_reason")),
            version=int(payload.get("version") or 1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "kind": self.kind.value,
            "scope": self.scope.value,
            "summary": self.summary,
            "content": self.content,
            "metadata": dict(self.metadata),
            "refs": dict(_normalize_refs(self.refs)),
            "tags": list(self.tags),
            "confidence": self.confidence,
            "importance": self.importance,
            "score": self.score.to_dict() if self.score is not None else None,
            "embedding": list(self.embedding) if self.embedding is not None else None,
            "actor": self.actor,
            "namespace": self.namespace,
            "tenant_id": self.tenant_id,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
            "expires_at": format_datetime(self.expires_at),
            "invalidated_at": format_datetime(self.invalidated_at),
            "invalidation_reason": self.invalidation_reason,
            "version": self.version,
        }

    def references(self) -> list[MemoryReference]:
        return references_from_legacy_refs(_normalize_refs(self.refs))

    def with_metadata(self, **metadata: Any) -> "MemoryRecord":
        return replace(self, metadata={**self.metadata, **metadata})

    def with_refs(self, refs: list[MemoryReference] | dict[str, Any]) -> "MemoryRecord":
        merged = {**_normalize_refs(self.refs), **_normalize_refs(refs)}
        return replace(self, refs=merged)

    def with_embedding(self, embedding: list[float]) -> "MemoryRecord":
        return replace(self, embedding=[float(value) for value in embedding])

    def mark_invalidated(self, reason: str, *, at: datetime | None = None) -> "MemoryRecord":
        return replace(
            self,
            invalidated_at=parse_datetime(at) or utc_now(),
            invalidation_reason=str(reason or "").strip() or None,
            metadata={**self.metadata, "invalidated": True},
        )

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        actual_now = parse_datetime(now) or utc_now()
        return self.expires_at <= actual_now

    def is_invalidated(self) -> bool:
        return self.invalidated_at is not None or self.metadata.get("invalidated") is True

    def is_recallable(self, *, now: datetime | None = None) -> bool:
        return not self.is_expired(now=now) and not self.is_invalidated()

    def stable_hash(self) -> str:
        return short_hash(
            {
                "content": self.content,
                "kind": self.kind.value,
                "scope": self.scope.value,
                "summary": self.summary,
                "metadata": self.metadata,
                "refs": self.refs,
                "tags": self.tags,
            },
            length=16,
        )


def generate_memory_id() -> str:
    return uuid4().hex


def coerce_memory_record(value: MemoryRecord | dict[str, Any]) -> MemoryRecord:
    if isinstance(value, MemoryRecord):
        return value
    if isinstance(value, dict):
        return MemoryRecord.from_dict(value)
    raise TypeError("memory record must be a MemoryRecord or object")


def _normalize_refs(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return legacy_refs_from_references(value)
    return dict(value)


def _memory_kind(value: Any) -> MemoryKind:
    if isinstance(value, MemoryKind):
        return value
    return MemoryKind(str(value))


def _memory_scope(value: Any) -> MemoryScope:
    if isinstance(value, MemoryScope):
        return value
    return MemoryScope(str(value))


def _kind_from_payload(payload: dict[str, Any]) -> MemoryKind:
    raw = payload.get("kind") or payload.get("source_type") or MemoryKind.SEMANTIC
    try:
        return _memory_kind(raw)
    except ValueError:
        return MemoryKind.ARTIFACT


def _optional_score(name: str, value: Any) -> float | None:
    numeric = _optional_float(value)
    if numeric is None:
        return None
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return numeric


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_float_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    return [float(item) for item in value]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_no_sensitive_keys(payload: dict[str, Any], *, field_name: str) -> None:
    for key, value in payload.items():
        normalized = str(key).lower()
        if any(token in normalized for token in _SENSITIVE_KEY_TOKENS):
            raise ValueError(f"memory {field_name} contains sensitive key: {key}")
        if isinstance(value, dict):
            _validate_no_sensitive_keys(value, field_name=field_name)


_GENERIC_REF_KEYS = (
    "artifact_id",
    "record_id",
    "reference_id",
    "reference_ids",
    "run_id",
    "source_memory_ids",
    "graph_id",
    "graph_version",
    "graph_ref",
    "graph_checksum",
    "node_instance_id",
    "stage_id",
)

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
