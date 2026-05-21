from datetime import UTC, datetime

from business.memory.event_builder import EventBuilder
from business.memory.intelligence_models import ClaimMemory, EntityMemory, EventMemory, EvidenceMemory


def test_event_builder_creates_event_with_links_and_type() -> None:
    evidence = [
        EvidenceMemory(
            evidence_id="ev-1",
            run_id="run-1",
            title="OpenAI released model weights",
            summary="OpenAI released model weights.",
            source_urls=[],
            source_item_ids=[],
            published_at=datetime(2026, 5, 21, tzinfo=UTC),
        )
    ]
    claims = [ClaimMemory(claim_id="claim-1", run_id="run-1", text="OpenAI released model weights", evidence_ids=["ev-1"])]
    entities = [EntityMemory(entity_id="entity-1", entity_type="organization", canonical_name="OpenAI")]

    result = EventBuilder().build_events(
        run_id="run-1",
        topic="AI",
        evidence=evidence,
        claims=claims,
        entities=entities,
    )

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "model_release"
    assert event.claim_ids == ["claim-1"]
    assert event.evidence_ids == ["ev-1"]
    assert event.entity_ids == ["entity-1"]


def test_event_builder_skips_duplicate_event() -> None:
    existing = EventMemory(
        event_id="event-existing",
        event_type="general_news",
        title="Same update",
        summary="Summary",
        run_id="run-0",
        topic="AI",
        detected_at=datetime(2026, 5, 21, tzinfo=UTC),
    )
    evidence = [
        EvidenceMemory(
            evidence_id="ev-1",
            run_id="run-1",
            title="Same update",
            summary="Summary",
            source_urls=[],
            source_item_ids=[],
            published_at=datetime(2026, 5, 21, tzinfo=UTC),
        )
    ]

    result = EventBuilder().build_events(
        run_id="run-1",
        topic="AI",
        evidence=evidence,
        claims=[],
        entities=[],
        existing_events=[existing],
    )

    assert result.events == []
    assert result.duplicate_event_ids == ["event-existing"]
