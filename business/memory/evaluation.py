from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from business.memory.intelligence_models import ClaimMemory, EventMemory, EvidenceMemory
from business.memory.memory_metrics import MemoryEvaluationMetrics


@dataclass(frozen=True)
class MemoryEvaluationRequest:
    topic: str | None = None
    entity_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "entity_id": self.entity_id,
            "since": _dt(self.since),
            "until": _dt(self.until),
            "limit": self.limit,
        }


@dataclass(frozen=True)
class MemoryEvaluationReport:
    request: MemoryEvaluationRequest
    metrics: MemoryEvaluationMetrics
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "metrics": self.metrics.to_dict(),
            "warnings": list(self.warnings),
            "recommendations": list(self.recommendations),
            "generated_at": _dt(self.generated_at),
        }


class MemoryEvaluator:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def evaluate(self, request: MemoryEvaluationRequest) -> MemoryEvaluationReport:
        claims = self._claims(request)
        events = self._events(request)
        evidence = self._evidence(request, claims)
        metrics = MemoryEvaluationMetrics(
            claim_support_rate=self.compute_claim_support_rate(request, claims),
            claim_contradiction_rate=self.compute_claim_contradiction_rate(request, claims),
            event_duplicate_rate=self.compute_event_duplicate_rate(request, events),
            recall_usefulness_score=self.compute_recall_usefulness_score(request, claims, events, evidence),
            memory_noise_ratio=self.compute_memory_noise_ratio(request, evidence),
            timeline_coverage_score=self.compute_timeline_coverage_score(request, events),
            decision_regret_score=self.compute_decision_regret_score(request),
            source_false_positive_rate=self.compute_source_false_positive_rate(request, evidence),
            metadata={"claim_count": len(claims), "event_count": len(events), "evidence_count": len(evidence)},
        )
        return MemoryEvaluationReport(
            request=request,
            metrics=metrics,
            warnings=self.build_warnings(metrics),
            recommendations=self.build_recommendations(metrics),
        )

    def compute_claim_support_rate(self, request: MemoryEvaluationRequest, claims: list[ClaimMemory] | None = None) -> float:
        claims = claims if claims is not None else self._claims(request)
        if not claims:
            return 1.0
        supported = sum(1 for claim in claims if claim.evidence_ids or self.repository.list_evidence_for_claim(claim.claim_id))
        return supported / len(claims)

    def compute_claim_contradiction_rate(self, request: MemoryEvaluationRequest, claims: list[ClaimMemory] | None = None) -> float:
        claims = claims if claims is not None else self._claims(request)
        if not claims:
            return 0.0
        contradicted = sum(1 for claim in claims if claim.status == "contradicted" or claim.contradicted_by)
        return contradicted / len(claims)

    def compute_event_duplicate_rate(self, request: MemoryEvaluationRequest, events: list[EventMemory] | None = None) -> float:
        events = events if events is not None else self._events(request)
        if not events:
            return 0.0
        duplicates = 0
        for event in events:
            similar = [item for item in self.repository.find_similar_events(event, limit=3) if item.event_id != event.event_id]
            duplicates += 1 if similar else 0
        return duplicates / len(events)

    def compute_recall_usefulness_score(
        self,
        request: MemoryEvaluationRequest,
        claims: list[ClaimMemory] | None = None,
        events: list[EventMemory] | None = None,
        evidence: list[EvidenceMemory] | None = None,
    ) -> float:
        claims = claims if claims is not None else self._claims(request)
        events = events if events is not None else self._events(request)
        evidence = evidence if evidence is not None else self._evidence(request, claims)
        return min(1.0, (len(claims) + len(events) + len(evidence)) / max(1, request.limit))

    def compute_memory_noise_ratio(self, request: MemoryEvaluationRequest, evidence: list[EvidenceMemory] | None = None) -> float:
        evidence = evidence if evidence is not None else self._evidence(request, self._claims(request))
        if not evidence:
            return 0.0
        noisy = sum(1 for item in evidence if item.confidence < 0.25)
        return noisy / len(evidence)

    def compute_timeline_coverage_score(self, request: MemoryEvaluationRequest, events: list[EventMemory] | None = None) -> float:
        events = events if events is not None else self._events(request)
        if not events:
            return 0.0
        covered = sum(1 for event in events if event.claim_ids or event.evidence_ids)
        return covered / len(events)

    def compute_decision_regret_score(self, request: MemoryEvaluationRequest) -> float:
        target_type = "entity" if request.entity_id else "topic"
        target_id = request.entity_id or request.topic or ""
        if not target_id or not hasattr(self.repository, "list_decisions_for_target"):
            return 0.0
        decisions = self.repository.list_decisions_for_target(target_type, target_id, limit=request.limit)
        if not decisions:
            return 0.0
        negative = sum(1 for decision in decisions if not decision.is_positive())
        return negative / len(decisions)

    def compute_source_false_positive_rate(self, request: MemoryEvaluationRequest, evidence: list[EvidenceMemory] | None = None) -> float:
        evidence = evidence if evidence is not None else self._evidence(request, self._claims(request))
        if not evidence:
            return 0.0
        weak = sum(1 for item in evidence if item.confidence < 0.35)
        return weak / len(evidence)

    def build_warnings(self, metrics: MemoryEvaluationMetrics) -> list[str]:
        warnings = []
        if metrics.claim_support_rate < 0.8:
            warnings.append("claim support rate below target")
        if metrics.claim_contradiction_rate > 0.2:
            warnings.append("claim contradiction rate elevated")
        if metrics.event_duplicate_rate > 0.2:
            warnings.append("event duplicate rate elevated")
        if metrics.memory_noise_ratio > 0.2:
            warnings.append("memory noise ratio elevated")
        return warnings

    def build_recommendations(self, metrics: MemoryEvaluationMetrics) -> list[str]:
        recommendations = []
        if metrics.claim_support_rate < 0.8:
            recommendations.append("run claim support consolidation")
        if metrics.event_duplicate_rate > 0.2:
            recommendations.append("run event dedupe consolidation")
        if metrics.memory_noise_ratio > 0.2:
            recommendations.append("review low-confidence sources")
        return recommendations

    def _claims(self, request: MemoryEvaluationRequest) -> list[ClaimMemory]:
        if request.entity_id:
            return list(self.repository.list_claims_by_entity(request.entity_id, limit=request.limit))
        if request.topic:
            return list(self.repository.list_claims_by_topic(request.topic, limit=request.limit))
        return list(self.repository.search_claims(query="", limit=request.limit))

    def _events(self, request: MemoryEvaluationRequest) -> list[EventMemory]:
        if request.entity_id:
            return list(self.repository.list_events_by_entity(request.entity_id, limit=request.limit))
        if request.topic:
            return list(self.repository.list_events_by_topic(request.topic, limit=request.limit))
        return list(self.repository.search_events(query="", limit=request.limit))

    def _evidence(self, request: MemoryEvaluationRequest, claims: list[ClaimMemory]) -> list[EvidenceMemory]:
        by_id: dict[str, EvidenceMemory] = {}
        for claim in claims:
            for item in self.repository.list_evidence_for_claim(claim.claim_id):
                by_id[item.evidence_id] = item
        if not by_id and request.topic:
            for item in self.repository.search_evidence(query=request.topic, topic=request.topic, limit=request.limit):
                by_id[item.evidence_id] = item
        return list(by_id.values())


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


__all__ = ["MemoryEvaluationReport", "MemoryEvaluationRequest", "MemoryEvaluator"]
