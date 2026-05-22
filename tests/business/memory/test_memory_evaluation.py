from datetime import UTC, datetime

from business.memory.evaluation import MemoryEvaluationRequest, MemoryEvaluator
from business.memory.intelligence_models import ClaimMemory, DecisionMemory, EventMemory, EvidenceMemory


def test_memory_evaluator_computes_report_metrics_and_recommendations() -> None:
    evaluator = MemoryEvaluator(_EvaluationRepository())

    report = evaluator.evaluate(MemoryEvaluationRequest(topic="AI", limit=10))

    assert report.metrics.claim_support_rate == 0.5
    assert report.metrics.claim_contradiction_rate == 0.5
    assert report.metrics.event_duplicate_rate == 0.5
    assert "claim support rate below target" in report.warnings
    assert report.to_dict()["metrics"]["overall_score"] >= 0.0


def test_memory_evaluator_applies_since_until_time_window() -> None:
    evaluator = MemoryEvaluator(_TimedEvaluationRepository())

    report = evaluator.evaluate(
        MemoryEvaluationRequest(
            topic="AI",
            since=datetime(2026, 1, 2, tzinfo=UTC),
            until=datetime(2026, 1, 3, tzinfo=UTC),
            limit=10,
        )
    )

    assert report.metrics.metadata["claim_count"] == 1
    assert report.metrics.metadata["event_count"] == 1
    assert report.metrics.metadata["evidence_count"] == 1
    assert report.metrics.claim_support_rate == 1.0


class _EvaluationRepository:
    claims = [
        ClaimMemory(claim_id="claim-1", run_id="run-1", text="Supported", evidence_ids=["ev-1"]),
        ClaimMemory(claim_id="claim-2", run_id="run-1", text="Contradicted", status="contradicted"),
    ]
    events = [
        EventMemory(
            event_id="event-1",
            event_type="general_news",
            title="Event",
            summary="Summary",
            run_id="run-1",
            topic="AI",
            claim_ids=["claim-1"],
            evidence_ids=["ev-1"],
        ),
        EventMemory(event_id="event-2", event_type="general_news", title="Event", summary="Summary", run_id="run-2", topic="AI"),
    ]
    evidence = [
        EvidenceMemory(
            evidence_id="ev-1",
            run_id="run-1",
            title="Evidence",
            summary="Summary",
            source_urls=["https://example.com"],
            source_item_ids=["item-1"],
            confidence=0.9,
            topic="AI",
        )
    ]

    def list_claims_by_topic(self, topic, *, limit=20):
        return self.claims

    def list_claims_by_entity(self, entity_id, *, limit=20):
        return []

    def search_claims(self, *, query, topic=None, limit=8):
        return self.claims

    def list_events_by_topic(self, topic, *, limit=20):
        return self.events

    def list_events_by_entity(self, entity_id, *, limit=20):
        return []

    def search_events(self, *, query, topic=None, limit=8):
        return self.events

    def find_similar_events(self, event, *, limit=3):
        return [self.events[1]] if event.event_id == "event-1" else []

    def list_evidence_for_claim(self, claim_id):
        return self.evidence if claim_id == "claim-1" else []

    def search_evidence(self, *, query, topic=None, limit=8):
        return self.evidence

    def list_decisions_for_target(self, target_type, target_id, *, limit=20):
        return [
            DecisionMemory(
                decision_id="decision-1",
                decision_type="quality_gate",
                target_type=target_type,
                target_id=target_id,
                decision="reject",
                run_id="run-1",
            )
        ]


class _TimedEvaluationRepository(_EvaluationRepository):
    claims = [
        ClaimMemory(
            claim_id="claim-old",
            run_id="run-1",
            text="Old",
            first_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
            last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        ClaimMemory(
            claim_id="claim-current",
            run_id="run-1",
            text="Current",
            evidence_ids=["ev-current"],
            first_seen_at=datetime(2026, 1, 2, tzinfo=UTC),
            last_seen_at=datetime(2026, 1, 2, tzinfo=UTC),
        ),
        ClaimMemory(
            claim_id="claim-future",
            run_id="run-1",
            text="Future",
            first_seen_at=datetime(2026, 1, 4, tzinfo=UTC),
            last_seen_at=datetime(2026, 1, 4, tzinfo=UTC),
        ),
    ]
    events = [
        EventMemory(
            event_id="event-old",
            event_type="general_news",
            title="Old",
            summary="Old",
            run_id="run-1",
            topic="AI",
            detected_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        EventMemory(
            event_id="event-current",
            event_type="general_news",
            title="Current",
            summary="Current",
            run_id="run-1",
            topic="AI",
            detected_at=datetime(2026, 1, 2, tzinfo=UTC),
            claim_ids=["claim-current"],
            evidence_ids=["ev-current"],
        ),
        EventMemory(
            event_id="event-future",
            event_type="general_news",
            title="Future",
            summary="Future",
            run_id="run-1",
            topic="AI",
            detected_at=datetime(2026, 1, 4, tzinfo=UTC),
        ),
    ]
    evidence = [
        EvidenceMemory(
            evidence_id="ev-current",
            run_id="run-1",
            title="Current evidence",
            summary="Current",
            source_urls=["https://example.com/current"],
            source_item_ids=["item-current"],
            topic="AI",
            fetched_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    ]
