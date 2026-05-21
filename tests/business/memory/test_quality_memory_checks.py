from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_models import ClaimMemory, EventMemory, EvidenceMemory
from business.memory.quality_memory_checks import QualityMemoryChecker


def test_claim_without_evidence_is_critical_issue() -> None:
    result = QualityMemoryChecker(_QualityRepository()).check_claims(
        [ClaimMemory(claim_id="claim-1", run_id="run-1", text="Unsupported")]
    )

    assert not result.passed
    assert result.critical_issues()[0].issue_type == "unsupported_claim"


def test_contradicted_claim_is_high_issue() -> None:
    result = QualityMemoryChecker(_QualityRepository()).check_claims(
        [
            ClaimMemory(
                claim_id="claim-1",
                run_id="run-1",
                text="Contradicted",
                status="contradicted",
                evidence_ids=["ev-1"],
                contradicted_by=["ev-2"],
            )
        ]
    )

    assert not result.passed
    assert result.issues[0].issue_type == "contradicted_claim"


def test_duplicate_event_is_issue_but_not_critical() -> None:
    event = EventMemory(
        event_id="event-1",
        event_type="general_news",
        title="Update",
        summary="Summary",
        run_id="run-1",
    )

    duplicate = EventMemory(
        event_id="event-2",
        event_type="general_news",
        title="Update",
        summary="Summary",
        run_id="run-2",
    )

    result = QualityMemoryChecker(_QualityRepository(similar_events=[duplicate])).check_events([event])

    assert result.passed
    assert result.issues[0].issue_type == "duplicate_event"


def test_report_context_conflict_fails() -> None:
    context = IntelligenceMemoryContext(
        query="AI",
        conflicts=[{"issue_type": "claim_conflict", "message": "Conflict"}],
    )

    result = QualityMemoryChecker(_QualityRepository()).check_report_context(context)

    assert not result.passed
    assert result.issues[0].issue_type == "claim_conflict"


def test_low_confidence_evidence_marks_noisy_source() -> None:
    evidence = EvidenceMemory(
        evidence_id="ev-1",
        run_id="run-1",
        title="Low confidence",
        summary="Summary",
        source_urls=[],
        source_item_ids=[],
        confidence=0.1,
    )

    issue = QualityMemoryChecker(_QualityRepository()).check_source_not_noisy(evidence)

    assert issue is not None
    assert issue.issue_type == "noisy_source"


class _QualityRepository:
    def __init__(self, similar_events=None) -> None:
        self.similar_events = similar_events or []

    def list_evidence_for_claim(self, claim_id):
        return []

    def find_similar_events(self, event, *, limit=3):
        return self.similar_events[:limit]
