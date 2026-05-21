from __future__ import annotations

from typing import Any

from business.memory.claim_consolidation import ClaimConsolidator
from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_models import (
    ClaimMemory,
    DecisionMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    PreferenceMemory,
)
from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository
from business.memory.intelligence_reranker import IntelligenceMemoryReranker
from business.memory.recall_planner import RecallPlan, RecallPlanner
from business.memory.timeline_service import TimelineService


class IntelligenceMemoryRecallService:
    def __init__(
        self,
        repository: IntelligenceMemoryQueryRepository | None = None,
        *,
        planner: RecallPlanner | None = None,
        timeline_service: TimelineService | None = None,
        reranker: IntelligenceMemoryReranker | None = None,
    ) -> None:
        self.repository = repository
        self.planner = planner or RecallPlanner()
        self.timeline_service = timeline_service or (TimelineService(repository) if repository is not None else None)
        self.reranker = reranker or IntelligenceMemoryReranker()
        self.consolidator = ClaimConsolidator()

    def recall_query(
        self,
        query: str,
        *,
        topic: str | None = None,
        entity_id: str | None = None,
        claim_text: str | None = None,
        source_id: str | None = None,
    ) -> IntelligenceMemoryContext:
        plan = self.planner.plan(
            query,
            topic=topic,
            entity_id=entity_id,
            claim_text=claim_text,
            source_id=source_id,
        )
        return self.recall(plan)

    def recall(self, plan: RecallPlan) -> IntelligenceMemoryContext:
        if self.repository is None:
            return IntelligenceMemoryContext(
                query=plan.query,
                topic=plan.topic,
                metadata={
                    "memory_available": False,
                    "reason": "memory_query_repository_missing",
                    "intent": plan.intent,
                },
            )
        evidence = self._recall_evidence(plan) if plan.include_evidence else []
        claims = self._recall_claims(plan) if plan.include_claims else []
        entities = self._recall_entities(plan) if plan.include_entities else []
        events = self._recall_events(plan) if plan.include_events else []
        decisions = self._recall_decisions(plan) if plan.include_decisions else []
        preferences = self._recall_preferences(plan) if plan.include_preferences else []
        conflicts = self._detect_conflicts(claims) if plan.include_conflicts else []
        return IntelligenceMemoryContext(
            query=plan.query,
            topic=plan.topic,
            evidence=evidence,
            claims=claims,
            entities=entities,
            events=events,
            decisions=decisions,
            preferences=preferences,
            conflicts=conflicts,
            metadata={
                "memory_available": True,
                "entity_id": plan.entity_id,
                "intent": plan.intent,
                "conflict_count": len(conflicts),
            },
        )

    def recall_for_topic(self, topic: str, *, limit: int = 8) -> IntelligenceMemoryContext:
        return self.recall(RecallPlan(query=topic, intent="topic_overview", topic=topic, limit_per_layer=limit))

    def recall_for_entity(self, entity_id: str, *, limit: int = 8) -> IntelligenceMemoryContext:
        return self.recall(RecallPlan(query=entity_id, intent="entity_history", entity_id=entity_id, limit_per_layer=limit))

    def _recall_evidence(self, plan: RecallPlan) -> list[EvidenceMemory]:
        if plan.claim_text:
            claims = self.repository.search_claims(query=plan.claim_text, topic=plan.topic, limit=plan.limit_per_layer)
            evidence: list[EvidenceMemory] = []
            for claim in claims:
                evidence.extend(_call_or_empty(self.repository, "list_evidence_for_claim", claim.claim_id))
            if evidence:
                return evidence[: plan.limit_per_layer]
        return self.repository.search_evidence(query=plan.query, topic=plan.topic, limit=plan.limit_per_layer)

    def _recall_claims(self, plan: RecallPlan) -> list[ClaimMemory]:
        if plan.entity_id and _has_method(self.repository, "list_claims_by_entity"):
            return self.repository.list_claims_by_entity(plan.entity_id, limit=plan.limit_per_layer)
        if plan.topic and _has_method(self.repository, "list_claims_by_topic"):
            return self.repository.list_claims_by_topic(plan.topic, limit=plan.limit_per_layer)
        if plan.claim_text:
            probe = ClaimMemory(claim_id="probe", run_id="recall", text=plan.claim_text)
            similar = _call_or_empty(self.repository, "find_similar_claims", probe, limit=plan.limit_per_layer)
            if similar:
                return similar
        return self.repository.search_claims(query=plan.claim_text or plan.query, topic=plan.topic, limit=plan.limit_per_layer)

    def _recall_entities(self, plan: RecallPlan) -> list[EntityMemory]:
        if plan.entity_id and _has_method(self.repository, "get_entity"):
            entity = self.repository.get_entity(plan.entity_id)
            return [entity] if entity is not None else []
        found = _call_or_none(self.repository, "find_entity_by_name", plan.query)
        if found is not None:
            return [found]
        return self.repository.search_entities(query=plan.query, topic=plan.topic, limit=plan.limit_per_layer)

    def _recall_events(self, plan: RecallPlan) -> list[EventMemory]:
        if plan.entity_id and _has_method(self.repository, "list_events_by_entity"):
            return self.repository.list_events_by_entity(plan.entity_id, limit=plan.limit_per_layer)
        if plan.topic and _has_method(self.repository, "list_events_by_topic"):
            return self.repository.list_events_by_topic(plan.topic, limit=plan.limit_per_layer)
        return self.repository.search_events(query=plan.query, topic=plan.topic, limit=plan.limit_per_layer)

    def _recall_decisions(self, plan: RecallPlan) -> list[DecisionMemory]:
        if plan.target_type and plan.target_id and _has_method(self.repository, "list_decisions_for_target"):
            return self.repository.list_decisions_for_target(
                plan.target_type,
                plan.target_id,
                limit=plan.limit_per_layer,
            )
        return self.repository.search_decisions(query=plan.query, topic=plan.topic, limit=plan.limit_per_layer)

    def _recall_preferences(self, plan: RecallPlan) -> list[PreferenceMemory]:
        if plan.target_type and plan.target_id and _has_method(self.repository, "list_preferences"):
            return self.repository.list_preferences(
                owner_type=plan.target_type,
                owner_id=plan.target_id,
                limit=plan.limit_per_layer,
            )
        return self.repository.search_preferences(query=plan.query, topic=plan.topic, limit=plan.limit_per_layer)

    def _detect_conflicts(self, claims: list[ClaimMemory]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        for index, left in enumerate(claims):
            if left.status == "contradicted":
                conflicts.append(
                    {
                        "issue_type": "contradicted_claim",
                        "claim_id": left.claim_id,
                        "message": f"Claim is contradicted: {left.text}",
                    }
                )
            for right in claims[index + 1 :]:
                if self.consolidator.is_contradiction(left, right):
                    conflicts.append(
                        {
                            "issue_type": "claim_conflict",
                            "claim_ids": [left.claim_id, right.claim_id],
                            "message": f"Conflicting claims: {left.text} / {right.text}",
                        }
                    )
        return conflicts


def _has_method(repository: object, name: str) -> bool:
    return callable(getattr(repository, name, None))


def _call_or_empty(repository: object, name: str, *args: Any, **kwargs: Any) -> list[Any]:
    method = getattr(repository, name, None)
    if not callable(method):
        return []
    result = method(*args, **kwargs)
    return list(result or [])


def _call_or_none(repository: object, name: str, *args: Any, **kwargs: Any) -> Any | None:
    method = getattr(repository, name, None)
    if not callable(method):
        return None
    return method(*args, **kwargs)


__all__ = ["IntelligenceMemoryRecallService", "RecallPlan"]
