from __future__ import annotations

from typing import Any, cast

from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_models import (
    ClaimMemory,
    ClaimStatus,
    DecisionMemory,
    EntityMemory,
    EntityType,
    EventMemory,
    EventType,
    EvidenceMemory,
    PreferenceMemory,
)
from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository
from business.memory.quality_memory_checks import QualityMemoryChecker


class DailyMemoryQualityService:
    def evaluate(
        self,
        memory_context: dict[str, Any] | None,
        *,
        repository: IntelligenceMemoryQueryRepository | None = None,
    ) -> dict[str, Any]:
        if not memory_context:
            return {
                "passed": True,
                "issues": [],
                "memory_available": False,
                "metadata": {
                    "reason": "memory_context_missing",
                    "memory_repository_available": repository is not None,
                },
            }

        context = memory_context_from_payload(memory_context)
        checker_repository = repository or ContextMemoryQualityRepository(context)
        result = QualityMemoryChecker(checker_repository).check_report_context(context)
        payload = result.to_dict()
        metadata = dict(payload.get("metadata") or {})
        metadata.update(
            {
                "memory_available": bool(
                    (memory_context.get("metadata") or {}).get("memory_available", True)
                ),
                "memory_repository_available": repository is not None,
                "memory_repository_source": "injected" if repository is not None else "context",
                "claim_count": len(context.claims),
                "event_count": len(context.events),
                "evidence_count": len(context.evidence),
                "conflict_count": len(context.conflicts),
                "critical_issue_count": len(result.critical_issues()),
            }
        )
        payload["metadata"] = metadata
        payload["memory_available"] = metadata["memory_available"]
        return payload


class ContextMemoryQualityRepository:
    def __init__(self, context: IntelligenceMemoryContext) -> None:
        self.context = context

    def search_evidence(
        self,
        *,
        query: str,
        topic: str | None = None,
        limit: int = 8,
    ) -> list[EvidenceMemory]:
        return _take(
            [
                item
                for item in self.context.evidence
                if _matches_text(query, item.title, item.summary, *item.source_urls)
                and _matches_topic(topic, item.topic)
            ],
            limit,
        )

    def search_claims(
        self,
        *,
        query: str,
        topic: str | None = None,
        limit: int = 8,
    ) -> list[ClaimMemory]:
        return _take(
            [
                item
                for item in self.context.claims
                if _matches_text(query, item.text) and _matches_topic(topic, item.metadata.get("topic"))
            ],
            limit,
        )

    def search_entities(
        self,
        *,
        query: str,
        topic: str | None = None,
        limit: int = 8,
    ) -> list[EntityMemory]:
        _ = topic
        return _take(
            [
                item
                for item in self.context.entities
                if _matches_text(query, item.canonical_name, *item.aliases)
            ],
            limit,
        )

    def search_events(
        self,
        *,
        query: str,
        topic: str | None = None,
        limit: int = 8,
    ) -> list[EventMemory]:
        return _take(
            [
                item
                for item in self.context.events
                if _matches_text(query, item.title, item.summary) and _matches_topic(topic, item.topic)
            ],
            limit,
        )

    def search_decisions(
        self,
        *,
        query: str,
        topic: str | None = None,
        limit: int = 8,
    ) -> list[DecisionMemory]:
        _ = topic
        return _take(
            [
                item
                for item in self.context.decisions
                if _matches_text(query, item.decision_type, item.decision, item.reason)
            ],
            limit,
        )

    def search_preferences(
        self,
        *,
        query: str,
        topic: str | None = None,
        limit: int = 8,
    ) -> list[PreferenceMemory]:
        _ = topic
        return _take(
            [
                item
                for item in self.context.preferences
                if _matches_text(query, item.preference_type, item.content)
            ],
            limit,
        )

    def get_entity(self, entity_id: str) -> EntityMemory | None:
        return next((item for item in self.context.entities if item.entity_id == entity_id), None)

    def find_entity_by_name(self, name: str) -> EntityMemory | None:
        normalized = _normalize(name)
        return next(
            (
                item
                for item in self.context.entities
                if normalized in {_normalize(item.canonical_name), *[_normalize(alias) for alias in item.aliases]}
            ),
            None,
        )

    def list_entities_by_type(
        self,
        entity_type: str,
        *,
        limit: int = 20,
    ) -> list[EntityMemory]:
        return _take([item for item in self.context.entities if item.entity_type == entity_type], limit)

    def get_claim(self, claim_id: str) -> ClaimMemory | None:
        return next((item for item in self.context.claims if item.claim_id == claim_id), None)

    def find_similar_claims(
        self,
        claim: ClaimMemory,
        *,
        limit: int = 10,
    ) -> list[ClaimMemory]:
        normalized = claim.normalized_text()
        return _take(
            [
                item
                for item in self.context.claims
                if item.claim_id != claim.claim_id and item.normalized_text() == normalized
            ],
            limit,
        )

    def list_claims_by_entity(
        self,
        entity_id: str,
        *,
        limit: int = 20,
    ) -> list[ClaimMemory]:
        return _take(
            [
                item
                for item in self.context.claims
                if item.subject_entity_id == entity_id or item.object_entity_id == entity_id
            ],
            limit,
        )

    def list_claims_by_topic(
        self,
        topic: str,
        *,
        limit: int = 20,
    ) -> list[ClaimMemory]:
        return self.search_claims(query=topic, topic=topic, limit=limit)

    def list_evidence_for_claim(self, claim_id: str) -> list[EvidenceMemory]:
        claim = self.get_claim(claim_id)
        if claim is None:
            return []
        evidence_ids = set(claim.evidence_ids)
        return [item for item in self.context.evidence if item.evidence_id in evidence_ids]

    def get_event(self, event_id: str) -> EventMemory | None:
        return next((item for item in self.context.events if item.event_id == event_id), None)

    def find_similar_events(
        self,
        event: EventMemory,
        *,
        limit: int = 10,
    ) -> list[EventMemory]:
        title = _normalize(event.title)
        summary = _normalize(event.summary)
        return _take(
            [
                item
                for item in self.context.events
                if item.event_id != event.event_id
                and (_normalize(item.title) == title or _normalize(item.summary) == summary)
            ],
            limit,
        )

    def list_events_by_entity(
        self,
        entity_id: str,
        *,
        limit: int = 20,
    ) -> list[EventMemory]:
        return _take([item for item in self.context.events if entity_id in item.entity_ids], limit)

    def list_events_by_topic(
        self,
        topic: str,
        *,
        limit: int = 20,
    ) -> list[EventMemory]:
        return self.search_events(query=topic, topic=topic, limit=limit)

    def list_decisions_for_target(
        self,
        target_type: str,
        target_id: str,
        *,
        limit: int = 20,
    ) -> list[DecisionMemory]:
        return _take(
            [
                item
                for item in self.context.decisions
                if item.target_type == target_type and item.target_id == target_id
            ],
            limit,
        )

    def list_preferences(
        self,
        *,
        owner_type: str,
        owner_id: str,
        preference_type: str | None = None,
        limit: int = 20,
    ) -> list[PreferenceMemory]:
        return _take(
            [
                item
                for item in self.context.preferences
                if item.owner_type == owner_type
                and item.owner_id == owner_id
                and (preference_type is None or item.preference_type == preference_type)
            ],
            limit,
        )


def memory_context_from_payload(payload: dict[str, Any]) -> IntelligenceMemoryContext:
    query = str(payload.get("query") or payload.get("topic") or "")
    return IntelligenceMemoryContext(
        query=query,
        topic=str(payload["topic"]) if payload.get("topic") else None,
        evidence=[_evidence_from_payload(item) for item in _dict_items(payload.get("evidence"))],
        claims=[_claim_from_payload(item) for item in _dict_items(payload.get("claims"))],
        entities=[_entity_from_payload(item) for item in _dict_items(payload.get("entities"))],
        events=[_event_from_payload(item) for item in _dict_items(payload.get("events"))],
        decisions=[_decision_from_payload(item) for item in _dict_items(payload.get("decisions"))],
        preferences=[_preference_from_payload(item) for item in _dict_items(payload.get("preferences"))],
        conflicts=[dict(item) for item in _dict_items(payload.get("conflicts"))],
        metadata=dict(payload.get("metadata") or {}),
    )


def has_critical_memory_quality_issue(memory_quality_result: dict[str, Any]) -> bool:
    return any(
        isinstance(issue, dict) and issue.get("severity") == "critical"
        for issue in memory_quality_result.get("issues") or []
    )


def _evidence_from_payload(payload: dict[str, Any]) -> EvidenceMemory:
    source_urls = [str(item) for item in payload.get("source_urls") or [] if item is not None]
    source_url = payload.get("source_url")
    if source_url and str(source_url) not in source_urls:
        source_urls.insert(0, str(source_url))
    return EvidenceMemory(
        evidence_id=str(payload.get("evidence_id") or payload.get("id") or "memory-evidence"),
        run_id=str(payload.get("run_id") or "memory-context"),
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        source_urls=source_urls,
        source_item_ids=[str(item) for item in payload.get("source_item_ids") or [] if item is not None],
        confidence=float(payload.get("confidence") or 0.5),
        topic=str(payload["topic"]) if payload.get("topic") else None,
        source_name=str(payload["source_name"]) if payload.get("source_name") else None,
        source_id=str(payload["source_id"]) if payload.get("source_id") else None,
        metadata=dict(payload.get("metadata") or {}),
    )


def _claim_from_payload(payload: dict[str, Any]) -> ClaimMemory:
    return ClaimMemory(
        claim_id=str(payload.get("claim_id") or payload.get("id") or "memory-claim"),
        run_id=str(payload.get("run_id") or "memory-context"),
        text=str(payload.get("text") or payload.get("claim") or ""),
        status=cast(ClaimStatus, str(payload.get("status") or "active")),
        confidence=float(payload.get("confidence") or 0.5),
        evidence_ids=[str(item) for item in payload.get("evidence_ids") or [] if item is not None],
        contradicted_by=[str(item) for item in payload.get("contradicted_by") or [] if item is not None],
        metadata=dict(payload.get("metadata") or {}),
    )


def _entity_from_payload(payload: dict[str, Any]) -> EntityMemory:
    return EntityMemory(
        entity_id=str(payload.get("entity_id") or payload.get("id") or "memory-entity"),
        entity_type=cast(EntityType, str(payload.get("entity_type") or "unknown")),
        canonical_name=str(payload.get("canonical_name") or payload.get("name") or ""),
        aliases=[str(item) for item in payload.get("aliases") or [] if item is not None],
        summary=str(payload["summary"]) if payload.get("summary") else None,
        metadata=dict(payload.get("metadata") or {}),
    )


def _event_from_payload(payload: dict[str, Any]) -> EventMemory:
    return EventMemory(
        event_id=str(payload.get("event_id") or payload.get("id") or "memory-event"),
        event_type=cast(EventType, str(payload.get("event_type") or "general_news")),
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        run_id=str(payload.get("run_id") or "memory-context"),
        topic=str(payload["topic"]) if payload.get("topic") else None,
        entity_ids=[str(item) for item in payload.get("entity_ids") or [] if item is not None],
        claim_ids=[str(item) for item in payload.get("claim_ids") or [] if item is not None],
        evidence_ids=[str(item) for item in payload.get("evidence_ids") or [] if item is not None],
        metadata=dict(payload.get("metadata") or {}),
    )


def _decision_from_payload(payload: dict[str, Any]) -> DecisionMemory:
    return DecisionMemory(
        decision_id=str(payload.get("decision_id") or payload.get("id") or "memory-decision"),
        decision_type=str(payload.get("decision_type") or "quality_gate"),
        target_type=str(payload.get("target_type") or "report"),
        target_id=str(payload.get("target_id") or "memory-context"),
        decision=str(payload.get("decision") or ""),
        run_id=str(payload.get("run_id") or "memory-context"),
        reason=str(payload["reason"]) if payload.get("reason") else None,
        metadata=dict(payload.get("metadata") or {}),
    )


def _preference_from_payload(payload: dict[str, Any]) -> PreferenceMemory:
    return PreferenceMemory(
        preference_id=str(payload.get("preference_id") or payload.get("id") or "memory-preference"),
        owner_type=str(payload.get("owner_type") or "system"),
        owner_id=str(payload.get("owner_id") or "daily-intelligence"),
        preference_type=str(payload.get("preference_type") or "quality"),
        content=str(payload.get("content") or ""),
        weight=float(payload.get("weight") or 1.0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _matches_text(query: str, *values: Any) -> bool:
    text = _normalize(query)
    if not text:
        return True
    haystack = _normalize(" ".join(str(value) for value in values if value is not None))
    return text in haystack


def _matches_topic(topic: str | None, item_topic: Any) -> bool:
    return topic is None or _normalize(topic) == _normalize(item_topic)


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _take(items: list[Any], limit: int) -> list[Any]:
    return items[: max(0, int(limit))]


__all__ = [
    "ContextMemoryQualityRepository",
    "DailyMemoryQualityService",
    "has_critical_memory_quality_issue",
    "memory_context_from_payload",
]
