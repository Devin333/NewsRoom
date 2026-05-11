from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any


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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def with_vector(self, vector: list[float]) -> "VectorDocument":
        return replace(self, vector=list(vector))

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.payload)
        payload.update(
            {
                "document_id": self.document_id,
                "collection": self.collection,
                "text": self.text,
                "source_type": self.source_type,
                "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            }
        )
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.report_id:
            payload["report_id"] = self.report_id
        if self.evidence_id:
            payload["evidence_id"] = self.evidence_id
        if self.source_item_id:
            payload["source_item_id"] = self.source_item_id
        return payload


@dataclass(frozen=True)
class VectorSearchQuery:
    collection: str
    text: str
    vector: list[float] | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 10
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
        )

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
