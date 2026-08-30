from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from backend.memory.evaluation import MemoryEvaluationRequest, MemoryEvaluator


ConsolidationTaskType = Literal[
    "entity_merge",
    "claim_status_refresh",
    "event_dedupe",
    "timeline_summary",
    "source_reliability_update",
    "memory_noise_cleanup",
]


@dataclass(frozen=True)
class MemoryConsolidationTask:
    task_type: ConsolidationTaskType
    topic: str | None = None
    entity_id: str | None = None
    dry_run: bool = True
    limit: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryConsolidationResult:
    task_type: ConsolidationTaskType
    scanned: int = 0
    changed: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "scanned": self.scanned,
            "changed": self.changed,
            "skipped": self.skipped,
            "warnings": list(self.warnings),
            "changes": [dict(change) for change in self.changes],
        }


class MemoryConsolidationService:
    def __init__(self, repository: Any, evaluator: MemoryEvaluator | None = None) -> None:
        self.repository = repository
        self.evaluator = evaluator or MemoryEvaluator(repository)

    def run_task(self, task: MemoryConsolidationTask) -> MemoryConsolidationResult:
        if task.task_type == "entity_merge":
            return self.merge_entities(task)
        if task.task_type == "claim_status_refresh":
            return self.refresh_claim_status(task)
        if task.task_type == "event_dedupe":
            return self.dedupe_events(task)
        if task.task_type == "timeline_summary":
            return self.summarize_timeline(task)
        if task.task_type == "source_reliability_update":
            return self.update_source_reliability(task)
        if task.task_type == "memory_noise_cleanup":
            return self.cleanup_noise(task)
        raise ValueError(f"unsupported task_type: {task.task_type}")

    def merge_entities(self, task: MemoryConsolidationTask) -> MemoryConsolidationResult:
        if not task.entity_id:
            return MemoryConsolidationResult(task_type=task.task_type, warnings=["entity_id is required"], skipped=1)
        entity = self.repository.get_entity(task.entity_id)
        if entity is None:
            return MemoryConsolidationResult(task_type=task.task_type, warnings=["entity not found"], skipped=1)
        candidates = [
            item
            for item in self.repository.search_entities(query=entity.canonical_name, limit=task.limit)
            if item.entity_id != entity.entity_id and item.normalized_name() == entity.normalized_name()
        ]
        changes = [
            {
                "action": "merge_entity_alias",
                "source_entity_id": candidate.entity_id,
                "target_entity_id": entity.entity_id,
                "canonical_name": entity.canonical_name,
            }
            for candidate in candidates
        ]
        return MemoryConsolidationResult(
            task_type=task.task_type,
            scanned=1 + len(candidates),
            changed=len(changes),
            skipped=0 if changes else 1,
            changes=changes,
        )

    def refresh_claim_status(self, task: MemoryConsolidationTask) -> MemoryConsolidationResult:
        claims = self._claims(task)
        changes = []
        for claim in claims:
            if claim.status != "contradicted" and claim.contradicted_by:
                changes.append(
                    {
                        "action": "update_claim_status",
                        "claim_id": claim.claim_id,
                        "old_status": claim.status,
                        "new_status": "contradicted",
                    }
                )
                if not task.dry_run:
                    self.repository.update_claim_status(
                        claim.claim_id,
                        status="contradicted",
                        reason="contradicted_by_existing_evidence",
                        evidence_id=claim.contradicted_by[-1],
                    )
        return MemoryConsolidationResult(
            task_type=task.task_type,
            scanned=len(claims),
            changed=len(changes),
            skipped=max(0, len(claims) - len(changes)),
            changes=changes,
        )

    def dedupe_events(self, task: MemoryConsolidationTask) -> MemoryConsolidationResult:
        events = self._events(task)
        changes = []
        seen: set[str] = set()
        for event in events:
            if event.event_id in seen:
                continue
            similar = [item for item in self.repository.find_similar_events(event, limit=task.limit) if item.event_id != event.event_id]
            for duplicate in similar:
                seen.add(duplicate.event_id)
                changes.append(
                    {
                        "action": "mark_duplicate_event",
                        "event_id": duplicate.event_id,
                        "duplicate_of": event.event_id,
                    }
                )
                if not task.dry_run and hasattr(self.repository, "upsert_event"):
                    self.repository.upsert_event(
                        replace(
                            duplicate,
                            status="duplicate",
                            metadata={**dict(duplicate.metadata), "duplicate_of": event.event_id},
                        )
                    )
        return MemoryConsolidationResult(
            task_type=task.task_type,
            scanned=len(events),
            changed=len(changes),
            skipped=max(0, len(events) - len(changes)),
            changes=changes,
        )

    def summarize_timeline(self, task: MemoryConsolidationTask) -> MemoryConsolidationResult:
        events = self._events(task)
        if not events:
            return MemoryConsolidationResult(task_type=task.task_type, skipped=1, warnings=["no events to summarize"])
        summary = " | ".join(f"{event.title}: {event.summary}" for event in events[:5])
        return MemoryConsolidationResult(
            task_type=task.task_type,
            scanned=len(events),
            changed=1,
            changes=[{"action": "timeline_summary", "topic": task.topic, "entity_id": task.entity_id, "summary": summary}],
        )

    def update_source_reliability(self, task: MemoryConsolidationTask) -> MemoryConsolidationResult:
        report = self.evaluator.evaluate(MemoryEvaluationRequest(topic=task.topic, entity_id=task.entity_id, limit=task.limit))
        changes = []
        if report.metrics.source_false_positive_rate > 0.25:
            changes.append(
                {
                    "action": "review_source_reliability",
                    "source_false_positive_rate": report.metrics.source_false_positive_rate,
                }
            )
        return MemoryConsolidationResult(
            task_type=task.task_type,
            scanned=report.metrics.metadata.get("evidence_count", 0),
            changed=len(changes),
            skipped=0 if changes else 1,
            warnings=list(report.warnings),
            changes=changes,
        )

    def cleanup_noise(self, task: MemoryConsolidationTask) -> MemoryConsolidationResult:
        evidence = self.repository.search_evidence(query=task.topic or "", topic=task.topic, limit=task.limit)
        noisy = [item for item in evidence if item.confidence < 0.25]
        changes = [
            {"action": "flag_noisy_evidence", "evidence_id": item.evidence_id, "confidence": item.confidence}
            for item in noisy
        ]
        return MemoryConsolidationResult(
            task_type=task.task_type,
            scanned=len(evidence),
            changed=len(changes),
            skipped=max(0, len(evidence) - len(changes)),
            changes=changes,
        )

    def _claims(self, task: MemoryConsolidationTask):
        if task.entity_id:
            return self.repository.list_claims_by_entity(task.entity_id, limit=task.limit)
        if task.topic:
            return self.repository.list_claims_by_topic(task.topic, limit=task.limit)
        return self.repository.search_claims(query="", limit=task.limit)

    def _events(self, task: MemoryConsolidationTask):
        if task.entity_id:
            return self.repository.list_events_by_entity(task.entity_id, limit=task.limit)
        if task.topic:
            return self.repository.list_events_by_topic(task.topic, limit=task.limit)
        return self.repository.search_events(query="", limit=task.limit)


__all__ = [
    "ConsolidationTaskType",
    "MemoryConsolidationResult",
    "MemoryConsolidationService",
    "MemoryConsolidationTask",
]
