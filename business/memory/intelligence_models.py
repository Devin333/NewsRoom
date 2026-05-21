from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal


MemoryLayer = Literal[
    "working",
    "evidence",
    "claim",
    "entity",
    "event",
    "decision",
    "preference",
]

ClaimStatus = Literal[
    "active",
    "uncertain",
    "duplicated",
    "contradicted",
    "outdated",
    "rejected",
]

EntityType = Literal[
    "organization",
    "product",
    "model",
    "paper",
    "repository",
    "person",
    "topic",
    "source",
    "policy",
    "unknown",
]

EventType = Literal[
    "product_release",
    "model_release",
    "paper_release",
    "funding",
    "acquisition",
    "policy_update",
    "github_trending",
    "community_discussion",
    "benchmark_update",
    "security_issue",
    "engineering_practice",
    "general_news",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class EvidenceMemory:
    evidence_id: str
    run_id: str
    title: str
    summary: str
    source_urls: list[str]
    source_item_ids: list[str]
    confidence: float = 0.5
    category: str = "news"
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    topic: str | None = None
    source_name: str | None = None
    source_id: str | None = None
    content_hash: str | None = None
    raw_artifact_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_source_urls(self) -> list[str]:
        return sorted({str(url).strip() for url in self.source_urls if str(url).strip()})

    def primary_url(self) -> str | None:
        urls = self.normalized_source_urls()
        return urls[0] if urls else None

    def to_index_text(self) -> str:
        return f"{self.title}\n{self.summary}".strip()

    def to_payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "run_id": self.run_id,
            "title": self.title,
            "summary": self.summary,
            "source_urls": self.normalized_source_urls(),
            "source_item_ids": list(self.source_item_ids),
            "confidence": self.confidence,
            "category": self.category,
            "published_at": _dt(self.published_at),
            "fetched_at": _dt(self.fetched_at),
            "topic": self.topic,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "content_hash": self.content_hash,
            "raw_artifact_ref": self.raw_artifact_ref,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ClaimMemory:
    claim_id: str
    run_id: str
    text: str
    status: ClaimStatus = "active"
    confidence: float = 0.5
    subject_entity_id: str | None = None
    predicate: str | None = None
    object_entity_id: str | None = None
    value: dict[str, Any] = field(default_factory=dict)
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    first_seen_at: datetime = field(default_factory=utc_now)
    last_seen_at: datetime = field(default_factory=utc_now)
    evidence_ids: list[str] = field(default_factory=list)
    contradicted_by: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_text(self) -> str:
        return " ".join(self.text.casefold().split())

    def is_active(self) -> bool:
        return self.status == "active"

    def with_evidence(self, evidence_id: str) -> "ClaimMemory":
        evidence_ids = sorted({*self.evidence_ids, evidence_id})
        return replace(self, evidence_ids=evidence_ids, last_seen_at=utc_now())

    def mark_contradicted(self, evidence_id: str, *, reason: str | None = None) -> "ClaimMemory":
        metadata = dict(self.metadata)
        if reason:
            metadata["contradiction_reason"] = reason
        return replace(
            self,
            status="contradicted",
            contradicted_by=sorted({*self.contradicted_by, evidence_id}),
            invalid_at=utc_now(),
            metadata=metadata,
        )

    def to_index_text(self) -> str:
        return self.text.strip()

    def to_payload(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "run_id": self.run_id,
            "text": self.text,
            "status": self.status,
            "confidence": self.confidence,
            "subject_entity_id": self.subject_entity_id,
            "predicate": self.predicate,
            "object_entity_id": self.object_entity_id,
            "value": dict(self.value),
            "valid_at": _dt(self.valid_at),
            "invalid_at": _dt(self.invalid_at),
            "first_seen_at": _dt(self.first_seen_at),
            "last_seen_at": _dt(self.last_seen_at),
            "evidence_ids": list(self.evidence_ids),
            "contradicted_by": list(self.contradicted_by),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EntityMemory:
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    summary: str | None = None
    first_seen_at: datetime = field(default_factory=utc_now)
    last_seen_at: datetime = field(default_factory=utc_now)
    importance_score: float = 0.0
    trend_score: float = 0.0
    external_refs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def all_names(self) -> list[str]:
        names = [self.canonical_name, *self.aliases]
        seen: set[str] = set()
        result: list[str] = []
        for name in names:
            text = str(name).strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                result.append(text)
        return result

    def normalized_name(self) -> str:
        return " ".join(self.canonical_name.casefold().split())

    def with_alias(self, alias: str) -> "EntityMemory":
        text = str(alias).strip()
        if not text:
            return self
        aliases = [
            name
            for name in self.all_names()
            if name.casefold() != self.canonical_name.casefold()
        ]
        if text.casefold() != self.canonical_name.casefold() and text.casefold() not in {
            item.casefold() for item in aliases
        }:
            aliases.append(text)
        return replace(self, aliases=aliases, last_seen_at=utc_now())

    def to_index_text(self) -> str:
        parts = [self.canonical_name, *(self.aliases or [])]
        if self.summary:
            parts.append(self.summary)
        return "\n".join(str(part) for part in parts if str(part).strip())

    def to_payload(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "summary": self.summary,
            "first_seen_at": _dt(self.first_seen_at),
            "last_seen_at": _dt(self.last_seen_at),
            "importance_score": self.importance_score,
            "trend_score": self.trend_score,
            "external_refs": dict(self.external_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EventMemory:
    event_id: str
    event_type: EventType
    title: str
    summary: str
    run_id: str
    event_time: datetime | None = None
    detected_at: datetime = field(default_factory=utc_now)
    topic: str | None = None
    entity_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    impact_score: float = 0.0
    novelty_score: float = 0.0
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_index_text(self) -> str:
        return f"{self.title}\n{self.summary}".strip()

    def entity_count(self) -> int:
        return len(set(self.entity_ids))

    def evidence_count(self) -> int:
        return len(set(self.evidence_ids))

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "title": self.title,
            "summary": self.summary,
            "run_id": self.run_id,
            "event_time": _dt(self.event_time),
            "detected_at": _dt(self.detected_at),
            "topic": self.topic,
            "entity_ids": list(self.entity_ids),
            "claim_ids": list(self.claim_ids),
            "evidence_ids": list(self.evidence_ids),
            "impact_score": self.impact_score,
            "novelty_score": self.novelty_score,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DecisionMemory:
    decision_id: str
    decision_type: str
    target_type: str
    target_id: str
    decision: str
    run_id: str
    reason: str | None = None
    agent_id: str | None = None
    workflow_id: str | None = None
    input_features: dict[str, Any] = field(default_factory=dict)
    output_scores: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_positive(self) -> bool:
        return self.decision.casefold() in {"pass", "passed", "allow", "approved", "accept", "accepted", "final"}

    def to_index_text(self) -> str:
        parts = [self.decision_type, self.decision]
        if self.reason:
            parts.append(self.reason)
        return "\n".join(part for part in parts if part)

    def to_payload(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "decision": self.decision,
            "run_id": self.run_id,
            "reason": self.reason,
            "agent_id": self.agent_id,
            "workflow_id": self.workflow_id,
            "input_features": dict(self.input_features),
            "output_scores": dict(self.output_scores),
            "created_at": _dt(self.created_at),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PreferenceMemory:
    preference_id: str
    owner_type: str
    owner_id: str
    preference_type: str
    content: str
    weight: float = 1.0
    source: str = "system"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = _ensure_utc(now or utc_now())
        return self.expires_at <= current

    def to_index_text(self) -> str:
        return f"{self.preference_type}\n{self.content}".strip()

    def to_payload(self) -> dict[str, Any]:
        return {
            "preference_id": self.preference_id,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "preference_type": self.preference_type,
            "content": self.content,
            "weight": self.weight,
            "source": self.source,
            "created_at": _dt(self.created_at),
            "updated_at": _dt(self.updated_at),
            "expires_at": _dt(self.expires_at),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ClaimHistoryRecord:
    history_id: str
    claim_id: str
    old_status: str | None
    new_status: ClaimStatus | str
    old_confidence: float | None
    new_confidence: float | None
    reason: str | None = None
    evidence_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "history_id": self.history_id,
            "claim_id": self.claim_id,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "old_confidence": self.old_confidence,
            "new_confidence": self.new_confidence,
            "reason": self.reason,
            "evidence_id": self.evidence_id,
            "created_at": _dt(self.created_at),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class IntelligenceMemoryBundle:
    run_id: str
    topic: str | None = None
    evidence: list[EvidenceMemory] = field(default_factory=list)
    claims: list[ClaimMemory] = field(default_factory=list)
    entities: list[EntityMemory] = field(default_factory=list)
    events: list[EventMemory] = field(default_factory=list)
    decisions: list[DecisionMemory] = field(default_factory=list)
    preferences: list[PreferenceMemory] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "evidence": len(self.evidence),
            "claims": len(self.claims),
            "entities": len(self.entities),
            "events": len(self.events),
            "decisions": len(self.decisions),
            "preferences": len(self.preferences),
        }

    def is_empty(self) -> bool:
        return not any(self.counts().values())

    def all_indexable_items(self) -> list[object]:
        return [
            *self.evidence,
            *self.claims,
            *self.entities,
            *self.events,
            *self.decisions,
            *self.preferences,
        ]

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "topic": self.topic,
            "counts": self.counts(),
            "is_empty": self.is_empty(),
        }


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "ClaimHistoryRecord",
    "ClaimMemory",
    "ClaimStatus",
    "DecisionMemory",
    "EntityMemory",
    "EntityType",
    "EventMemory",
    "EventType",
    "EvidenceMemory",
    "IntelligenceMemoryBundle",
    "MemoryLayer",
    "PreferenceMemory",
    "utc_now",
]
