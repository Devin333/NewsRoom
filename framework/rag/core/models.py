from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from framework.shared.json import to_jsonable


def _require_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _as_text_tuple(values: tuple[str, ...] | list[str] | object) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (tuple, list)):
        return tuple(str(value) for value in values if str(value).strip())
    text = str(values).strip()
    return (text,) if text else ()


@dataclass(frozen=True)
class SourceLocator:
    source_id: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    section_path: tuple[str, ...] = ()
    span_start: int | None = None
    span_end: int | None = None
    raw_locator: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _require_text(self.source_id, "source_id"))
        if self.page is not None and self.page < 0:
            raise ValueError("page must be greater than or equal to zero")
        if self.bbox is not None:
            if len(self.bbox) != 4:
                raise ValueError("bbox must have four coordinates")
            object.__setattr__(self, "bbox", tuple(float(value) for value in self.bbox))
        if self.span_start is not None and self.span_start < 0:
            raise ValueError("span_start must be greater than or equal to zero")
        if self.span_end is not None and self.span_end < 0:
            raise ValueError("span_end must be greater than or equal to zero")
        if self.span_start is not None and self.span_end is not None and self.span_end < self.span_start:
            raise ValueError("span_end must be greater than or equal to span_start")
        object.__setattr__(self, "section_path", _as_text_tuple(self.section_path))
        object.__setattr__(self, "raw_locator", str(self.raw_locator or ""))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "page": self.page,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "section_path": list(self.section_path),
            "span_start": self.span_start,
            "span_end": self.span_end,
            "raw_locator": self.raw_locator,
            "metadata": to_jsonable(dict(self.metadata)),
        }


@dataclass(frozen=True)
class RAGScoreBreakdown:
    child_similarity: float | None = None
    parent_relevance: float | None = None
    field_score: float | None = None
    section_heading_score: float | None = None
    position_bonus: float | None = None
    rerank_score: float | None = None
    final_score: float | None = None
    extra: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "child_similarity",
            "parent_relevance",
            "field_score",
            "section_heading_score",
            "position_bonus",
            "rerank_score",
            "final_score",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, float(value))
        object.__setattr__(
            self,
            "extra",
            {str(key): float(value) for key, value in dict(self.extra).items()},
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "RAGScoreBreakdown":
        known = {
            "child_similarity",
            "parent_relevance",
            "field_score",
            "section_heading_score",
            "position_bonus",
            "rerank_score",
            "final_score",
        }
        kwargs: dict[str, float] = {}
        extra: dict[str, float] = {}
        for key, value in values.items():
            number = _as_optional_float(value)
            if number is None:
                continue
            if key in known:
                kwargs[key] = number
            else:
                extra[str(key)] = number
        return cls(**kwargs, extra=extra)

    def to_dict(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for name in (
            "child_similarity",
            "parent_relevance",
            "field_score",
            "section_heading_score",
            "position_bonus",
            "rerank_score",
            "final_score",
        ):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        out.update(dict(self.extra))
        return out


@dataclass(frozen=True)
class RAGChunk:
    chunk_id: str
    document_id: str
    text: str
    chunk_type: str
    fields: Mapping[str, str] = field(default_factory=dict)
    source_locator: SourceLocator | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_id", _require_text(self.chunk_id, "chunk_id"))
        object.__setattr__(self, "document_id", _require_text(self.document_id, "document_id"))
        object.__setattr__(self, "text", _require_text(self.text, "text"))
        object.__setattr__(self, "chunk_type", _require_text(self.chunk_type, "chunk_type"))
        object.__setattr__(self, "fields", {str(key): str(value) for key, value in dict(self.fields).items()})
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "chunk_type": self.chunk_type,
            "fields": dict(self.fields),
            "source_locator": self.source_locator.to_dict() if self.source_locator else None,
            "metadata": to_jsonable(dict(self.metadata)),
        }


@dataclass(frozen=True)
class RAGQuery:
    query: str
    intent: str = "general"
    required_chunk_types: tuple[str, ...] = ()
    preferred_fields: tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 10
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", _require_text(self.query, "query"))
        object.__setattr__(self, "intent", _require_text(self.intent, "intent"))
        if self.limit <= 0:
            raise ValueError("limit must be greater than zero")
        object.__setattr__(self, "required_chunk_types", _as_text_tuple(self.required_chunk_types))
        object.__setattr__(self, "preferred_fields", _as_text_tuple(self.preferred_fields))
        object.__setattr__(self, "filters", dict(self.filters))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "intent": self.intent,
            "required_chunk_types": list(self.required_chunk_types),
            "preferred_fields": list(self.preferred_fields),
            "filters": to_jsonable(dict(self.filters)),
            "limit": self.limit,
            "metadata": to_jsonable(dict(self.metadata)),
        }


@dataclass(frozen=True)
class RAGEvidence:
    evidence_id: str
    chunk_id: str
    document_id: str
    text: str
    score: float = 0.0
    score_breakdown: RAGScoreBreakdown = field(default_factory=RAGScoreBreakdown)
    source_locator: SourceLocator | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _require_text(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "chunk_id", _require_text(self.chunk_id, "chunk_id"))
        object.__setattr__(self, "document_id", _require_text(self.document_id, "document_id"))
        object.__setattr__(self, "text", _require_text(self.text, "text"))
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "score": self.score,
            "score_breakdown": self.score_breakdown.to_dict(),
            "source_locator": self.source_locator.to_dict() if self.source_locator else None,
            "metadata": to_jsonable(dict(self.metadata)),
        }


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "RAGChunk",
    "RAGEvidence",
    "RAGQuery",
    "RAGScoreBreakdown",
    "SourceLocator",
]
