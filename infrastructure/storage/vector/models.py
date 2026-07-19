from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone as _tz
from typing import Any

UTC = _tz.utc


@dataclass(frozen=True)
class VectorDocument:
    document_id: str
    collection: str
    text: str
    payload: dict[str, Any]
    source_type: str
    vector: list[float] | None = None
    run_id: str | None = None
    report_id: str | None = None
    evidence_id: str | None = None
    source_item_id: str | None = None
    topic: str | None = None
    section_id: str | None = None
    published_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def with_vector(self, vector: list[float]) -> "VectorDocument":
        return replace(self, vector=list(vector))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "collection": self.collection,
            "text": self.text,
            "source_type": self.source_type,
            "run_id": self.run_id,
            "report_id": self.report_id,
            "evidence_id": self.evidence_id,
            "source_item_id": self.source_item_id,
            "topic": self.topic,
            "section_id": self.section_id,
            "published_at": self.published_at.isoformat().replace("+00:00", "Z") if self.published_at else None,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
        }

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.payload)
        payload.update(
            {key: value for key, value in self.canonical_payload().items() if value is not None}
        )
        return payload


@dataclass(frozen=True)
class VectorSearchQuery:
    collection: str
    text: str
    vector: list[float] | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 10
    offset: int = 0
    score_threshold: float | None = None


@dataclass(frozen=True)
class VectorSearchResult:
    document_id: str
    score: float
    text: str
    source_type: str
    payload: dict[str, Any]
    run_id: str | None = None
    report_id: str | None = None
    evidence_id: str | None = None
    source_item_id: str | None = None
    topic: str | None = None
    section_id: str | None = None
    published_at: str | None = None

    @classmethod
    def from_payload(cls, *, score: float, payload: dict[str, Any]) -> "VectorSearchResult":
        return cls(
            document_id=str(payload["document_id"]),
            score=float(score),
            text=str(payload.get("text") or ""),
            source_type=str(payload.get("source_type") or ""),
            payload=dict(payload),
            run_id=payload.get("run_id"),
            report_id=payload.get("report_id"),
            evidence_id=payload.get("evidence_id"),
            source_item_id=payload.get("source_item_id"),
            topic=payload.get("topic"),
            section_id=payload.get("section_id"),
            published_at=payload.get("published_at"),
        )

    def refs(self) -> dict[str, str]:
        raw_refs = self.payload.get("refs")
        refs: dict[str, str] = {
            str(key): str(value)
            for key, value in (raw_refs.items() if isinstance(raw_refs, dict) else [])
            if value is not None
        }
        if self.run_id:
            refs["run_id"] = self.run_id
        if self.report_id:
            refs["report_id"] = self.report_id
        if self.evidence_id:
            refs["evidence_id"] = self.evidence_id
        if self.source_item_id:
            refs["source_item_id"] = self.source_item_id
        if self.section_id:
            refs["section_id"] = self.section_id
        source_item_ids = self.payload.get("source_item_ids")
        if isinstance(source_item_ids, list) and source_item_ids:
            refs["source_item_ids"] = ",".join(str(value) for value in source_item_ids)
        return refs

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "score": self.score,
            "text": self.text,
            "source_type": self.source_type,
            "payload": dict(self.payload),
            "run_id": self.run_id,
            "report_id": self.report_id,
            "evidence_id": self.evidence_id,
            "source_item_id": self.source_item_id,
            "topic": self.topic,
            "section_id": self.section_id,
            "published_at": self.published_at,
            "refs": self.refs(),
        }


@dataclass(frozen=True)
class VectorCollectionStatus:
    collection: str
    vector_size: int
    existed_before: bool
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "vector_size": self.vector_size,
            "existed_before": self.existed_before,
            "created": self.created,
        }


@dataclass(frozen=True)
class VectorPayloadIndexStatus:
    collection: str
    field_name: str
    field_schema: str
    existed_before: bool
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "field_name": self.field_name,
            "field_schema": self.field_schema,
            "existed_before": self.existed_before,
            "created": self.created,
        }
