from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from backend.memory.graph_models import GraphExpansion
from backend.memory.intelligence_context import IntelligenceMemoryContext
from backend.memory.intelligence_models import ClaimMemory, EntityMemory, EventMemory, EventType, EvidenceMemory


@dataclass(frozen=True)
class HistoricalContextRequest:
    topic: str | None = None
    entity_id: str | None = None
    event_id: str | None = None
    claim_text: str | None = None
    limit: int = 10
    include_graph: bool = True
    include_conflicts: bool = True


@dataclass(frozen=True)
class HistoricalContext:
    query: str
    topic: str | None = None
    entity: EntityMemory | None = None
    recent_events: list[EventMemory] = field(default_factory=list)
    known_claims: list[ClaimMemory] = field(default_factory=list)
    supporting_evidence: list[EvidenceMemory] = field(default_factory=list)
    repeated_claims: list[ClaimMemory] = field(default_factory=list)
    contradictions: list[ClaimMemory] = field(default_factory=list)
    graph_expansion: GraphExpansion | None = None
    timeline_summary: str | None = None
    unresolved_questions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (
            self.entity
            or self.recent_events
            or self.known_claims
            or self.supporting_evidence
            or self.repeated_claims
            or self.contradictions
            or self.graph_expansion
        )

    def to_prompt_context(self, *, limit: int = 10) -> str:
        parts: list[str] = []
        if self.timeline_summary:
            parts.append(f"Timeline summary: {self.timeline_summary}")
        if self.recent_events:
            parts.append("Recent events:")
            parts.extend(f"- {event.title}: {event.summary}" for event in self.recent_events[:limit])
        if self.known_claims:
            parts.append("Known claims:")
            parts.extend(f"- {claim.text}" for claim in self.known_claims[:limit])
        if self.contradictions:
            parts.append("Contradictions:")
            parts.extend(f"- {claim.text}" for claim in self.contradictions[:limit])
        if self.unresolved_questions:
            parts.append("Unresolved questions:")
            parts.extend(f"- {item}" for item in self.unresolved_questions[:limit])
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "topic": self.topic,
            "entity": self.entity.to_payload() if self.entity is not None else None,
            "recent_events": [event.to_payload() for event in self.recent_events],
            "known_claims": [claim.to_payload() for claim in self.known_claims],
            "supporting_evidence": [item.to_payload() for item in self.supporting_evidence],
            "repeated_claims": [claim.to_payload() for claim in self.repeated_claims],
            "contradictions": [claim.to_payload() for claim in self.contradictions],
            "graph_expansion": self.graph_expansion.to_dict() if self.graph_expansion is not None else None,
            "timeline_summary": self.timeline_summary,
            "unresolved_questions": list(self.unresolved_questions),
            "metadata": dict(self.metadata),
        }


class HistoricalContextService:
    def __init__(
        self,
        *,
        recall_service: Any,
        timeline_service: Any | None = None,
        graph_service: Any | None = None,
    ) -> None:
        self.recall_service = recall_service
        self.timeline_service = timeline_service
        self.graph_service = graph_service

    def build_context(self, request: HistoricalContextRequest) -> HistoricalContext:
        if request.entity_id:
            return self.build_entity_context(request.entity_id, limit=request.limit, include_graph=request.include_graph)
        if request.topic:
            return self.build_topic_context(request.topic, limit=request.limit, include_conflicts=request.include_conflicts)
        if request.claim_text:
            return self.build_claim_context(request.claim_text, limit=request.limit)
        return HistoricalContext(query="")

    def build_topic_context(
        self,
        topic: str,
        *,
        limit: int = 10,
        include_conflicts: bool = True,
    ) -> HistoricalContext:
        memory_context = self.recall_service.recall_for_topic(topic, limit=limit)
        timeline_summary = ""
        if self.timeline_service is not None:
            timeline = self.timeline_service.get_topic_timeline(topic, limit=limit)
            timeline_summary = timeline.to_prompt_context(limit=limit)
        contradictions = [claim for claim in memory_context.claims if claim.status == "contradicted"]
        if include_conflicts:
            contradictions = _dedupe_claims([*contradictions, *_claims_from_conflicts(memory_context)])
        return HistoricalContext(
            query=topic,
            topic=topic,
            recent_events=list(memory_context.events),
            known_claims=list(memory_context.claims),
            supporting_evidence=list(memory_context.evidence),
            repeated_claims=_repeated_claims(memory_context.claims),
            contradictions=contradictions,
            timeline_summary=timeline_summary,
            unresolved_questions=_unresolved_questions(memory_context),
            metadata={"source": "topic", "memory_available": memory_context.metadata.get("memory_available", True)},
        )

    def build_entity_context(
        self,
        entity_id: str,
        *,
        limit: int = 10,
        include_graph: bool = True,
    ) -> HistoricalContext:
        timeline_summary = ""
        recent_events: list[EventMemory] = []
        if self.timeline_service is not None:
            timeline = self.timeline_service.get_entity_timeline(entity_id, limit=limit)
            timeline_summary = timeline.to_prompt_context(limit=limit)
            recent_events = [_event_from_timeline_item(item) for item in timeline.items]
        graph = None
        entity = None
        if include_graph and self.graph_service is not None:
            graph = self.graph_service.expand_entity(entity_id, depth=2, limit=limit)
            entity = _entity_from_graph(graph)
        return HistoricalContext(
            query=entity_id,
            entity=entity,
            recent_events=recent_events,
            graph_expansion=graph,
            timeline_summary=timeline_summary,
            metadata={"source": "entity"},
        )

    def build_claim_context(self, claim_text: str, *, limit: int = 10) -> HistoricalContext:
        if hasattr(self.recall_service, "recall_query"):
            memory_context = self.recall_service.recall_query(claim_text, claim_text=claim_text)
        else:
            memory_context = IntelligenceMemoryContext(query=claim_text)
        return HistoricalContext(
            query=claim_text,
            known_claims=list(memory_context.claims)[:limit],
            supporting_evidence=list(memory_context.evidence)[:limit],
            repeated_claims=_repeated_claims(memory_context.claims),
            contradictions=[claim for claim in memory_context.claims if claim.status == "contradicted"],
            unresolved_questions=_unresolved_questions(memory_context),
            metadata={"source": "claim"},
        )


def _repeated_claims(claims: list[ClaimMemory]) -> list[ClaimMemory]:
    seen: set[str] = set()
    repeated: list[ClaimMemory] = []
    for claim in claims:
        key = claim.normalized_text()
        if key in seen:
            repeated.append(claim)
        seen.add(key)
    return repeated


def _claims_from_conflicts(context: IntelligenceMemoryContext) -> list[ClaimMemory]:
    conflict_ids = {
        str(value)
        for conflict in context.conflicts
        for value in ([conflict.get("claim_id")] if conflict.get("claim_id") else conflict.get("claim_ids") or [])
        if value
    }
    return [claim for claim in context.claims if claim.claim_id in conflict_ids]


def _dedupe_claims(claims: list[ClaimMemory]) -> list[ClaimMemory]:
    by_id = {}
    for claim in claims:
        by_id[claim.claim_id] = claim
    return list(by_id.values())


def _unresolved_questions(context: IntelligenceMemoryContext) -> list[str]:
    questions = []
    if context.conflicts:
        questions.append("Resolve historical claim conflicts before treating this as settled.")
    if not context.evidence and context.claims:
        questions.append("Find supporting evidence for recalled claims.")
    return questions


def _event_from_timeline_item(item: Any) -> EventMemory:
    return EventMemory(
        event_id=str(item.event_id),
        event_type=cast(EventType, str(item.event_type)),
        title=str(item.title),
        summary=str(item.summary),
        run_id="timeline",
        event_time=item.event_time,
        detected_at=item.detected_at,
        topic=item.topic,
        entity_ids=list(item.entity_ids),
        claim_ids=list(item.claim_ids),
        evidence_ids=list(item.evidence_ids),
        impact_score=float(item.impact_score),
        novelty_score=float(item.novelty_score),
    )


def _entity_from_graph(graph: GraphExpansion) -> EntityMemory | None:
    root = graph.root
    if root.node_type != "entity":
        return None
    return EntityMemory(
        entity_id=root.node_id,
        entity_type=str(root.metadata.get("entity_type") or "organization"),  # type: ignore[arg-type]
        canonical_name=root.label,
        summary=root.summary,
        importance_score=root.score,
        metadata=dict(root.metadata),
    )


__all__ = ["HistoricalContext", "HistoricalContextRequest", "HistoricalContextService"]
