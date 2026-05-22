from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.scoring import FeatureVector


@dataclass(frozen=True)
class BusinessMemoryHit:
    hit_id: str
    score: float
    text: str = ""
    source_name: str | None = None
    source_type: str | None = None
    topic: str | None = None
    evidence_id: str | None = None
    source_item_id: str | None = None
    run_id: str | None = None
    published_at: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "hit_id", str(self.hit_id))
        object.__setattr__(self, "score", _clamp(self.score))
        object.__setattr__(self, "tags", [str(tag) for tag in self.tags])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def from_any(cls, value: Any) -> "BusinessMemoryHit":
        payload = _payload_from_any(value)
        raw_nested_payload = payload.get("payload")
        nested_payload = dict(raw_nested_payload) if isinstance(raw_nested_payload, dict) else {}
        raw_record = payload.get("record")
        record = dict(raw_record) if isinstance(raw_record, dict) else {}
        raw_record_metadata = record.get("metadata")
        record_metadata = dict(raw_record_metadata) if isinstance(raw_record_metadata, dict) else {}
        raw_metadata = payload.get("metadata")
        payload_metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        raw_refs = payload.get("refs")
        refs = dict(raw_refs) if isinstance(raw_refs, dict) else {}
        metadata = {
            **nested_payload,
            **record_metadata,
            **payload_metadata,
        }
        return cls(
            hit_id=str(
                payload.get("document_id")
                or payload.get("memory_id")
                or record.get("memory_id")
                or metadata.get("document_id")
                or "memory-hit"
            ),
            score=float(payload.get("score", payload.get("relevance", 0.0)) or 0.0),
            text=str(payload.get("text") or payload.get("content") or record.get("content") or ""),
            source_name=_optional_str(
                payload.get("source_name")
                or metadata.get("source_name")
                or nested_payload.get("source_name")
            ),
            source_type=_optional_str(payload.get("source_type") or metadata.get("source_type")),
            topic=_optional_str(payload.get("topic") or metadata.get("topic")),
            evidence_id=_optional_str(payload.get("evidence_id") or refs.get("evidence_id")),
            source_item_id=_optional_str(payload.get("source_item_id") or refs.get("source_item_id")),
            run_id=_optional_str(payload.get("run_id") or refs.get("run_id")),
            published_at=_optional_str(payload.get("published_at") or metadata.get("published_at")),
            tags=[str(tag) for tag in payload.get("tags") or record.get("tags") or metadata.get("tags") or []],
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hit_id": self.hit_id,
            "score": self.score,
            "text": self.text,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "topic": self.topic,
            "evidence_id": self.evidence_id,
            "source_item_id": self.source_item_id,
            "run_id": self.run_id,
            "published_at": self.published_at,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BusinessMemoryContext:
    query: str
    hits: list[BusinessMemoryHit] = field(default_factory=list)
    source_reliability_score: float = 0.5
    historical_duplicate_score: float = 0.0
    topic_momentum_score: float = 0.0
    previous_misrank_penalty: float = 0.0
    historical_noise_penalty: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "hits",
            [hit if isinstance(hit, BusinessMemoryHit) else BusinessMemoryHit.from_any(hit) for hit in self.hits],
        )
        for name in (
            "source_reliability_score",
            "historical_duplicate_score",
            "topic_momentum_score",
            "previous_misrank_penalty",
            "historical_noise_penalty",
        ):
            object.__setattr__(self, name, _clamp(getattr(self, name)))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def empty(cls, query: str = "", *, reason: str | None = None) -> "BusinessMemoryContext":
        metadata: dict[str, Any] = {"memory_available": False}
        if reason:
            metadata["reason"] = reason
        return cls(
            query=query,
            hits=[],
            source_reliability_score=0.0,
            historical_duplicate_score=0.0,
            topic_momentum_score=0.0,
            previous_misrank_penalty=0.0,
            historical_noise_penalty=0.0,
            metadata=metadata,
        )

    def to_feature_dict(self) -> dict[str, float]:
        if not self.hits and not self.metadata.get("memory_available"):
            return {
                "source_reliability_memory_score": 0.0,
                "historical_duplicate_score": 0.0,
                "topic_momentum_score": 0.0,
                "previous_misrank_penalty": 0.0,
                "historical_noise_penalty": 0.0,
                "memory_safety_score": 0.0,
                "memory_decision_score": 0.0,
            }
        return {
            "source_reliability_memory_score": self.source_reliability_score,
            "historical_duplicate_score": self.historical_duplicate_score,
            "topic_momentum_score": self.topic_momentum_score,
            "previous_misrank_penalty": self.previous_misrank_penalty,
            "historical_noise_penalty": self.historical_noise_penalty,
            "memory_safety_score": _memory_safety_score(
                duplicate=self.historical_duplicate_score,
                misrank=self.previous_misrank_penalty,
                noise=self.historical_noise_penalty,
            ),
            "memory_decision_score": _memory_decision_score(
                source_reliability=self.source_reliability_score,
                duplicate=self.historical_duplicate_score,
                momentum=self.topic_momentum_score,
                misrank=self.previous_misrank_penalty,
                noise=self.historical_noise_penalty,
            ),
        }

    def to_feature_vector(self) -> FeatureVector:
        return FeatureVector.from_scores(
            self.to_feature_dict(),
            source="business_memory",
            metadata={
                "memory_available": bool(self.hits),
                "memory_hit_count": len(self.hits),
                "memory_query": self.query,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hits": [hit.to_dict() for hit in self.hits],
            "source_reliability_score": self.source_reliability_score,
            "historical_duplicate_score": self.historical_duplicate_score,
            "topic_momentum_score": self.topic_momentum_score,
            "previous_misrank_penalty": self.previous_misrank_penalty,
            "historical_noise_penalty": self.historical_noise_penalty,
            "metadata": dict(self.metadata),
        }


def _payload_from_any(value: Any) -> dict[str, Any]:
    if isinstance(value, BusinessMemoryHit):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        return dict(payload) if isinstance(payload, dict) else {}
    try:
        return {
            name: item
            for name, item in vars(value).items()
            if not name.startswith("_")
        }
    except TypeError:
        return {"document_id": str(value), "text": str(value), "score": 0.0}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _memory_safety_score(*, duplicate: float, misrank: float, noise: float) -> float:
    penalty = duplicate * 0.45 + misrank * 0.35 + noise * 0.20
    return _clamp(1.0 - penalty)


def _memory_decision_score(
    *,
    source_reliability: float,
    duplicate: float,
    momentum: float,
    misrank: float,
    noise: float,
) -> float:
    positive = max(0.0, source_reliability - 0.5) * 0.40 + momentum * 0.25
    penalty = duplicate * 0.25 + misrank * 0.25 + noise * 0.20
    return _clamp(0.55 + positive - penalty)
