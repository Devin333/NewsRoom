from datetime import UTC, datetime, timedelta

from backend.memory.intelligence_models import (
    ClaimMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    IntelligenceMemoryBundle,
    PreferenceMemory,
)


def test_evidence_memory_primary_url_normalizes_urls() -> None:
    memory = EvidenceMemory(
        evidence_id="ev-1",
        run_id="run-1",
        title="Title",
        summary="Summary",
        source_urls=[" https://b.example ", "https://a.example", "https://a.example"],
        source_item_ids=[],
    )

    assert memory.normalized_source_urls() == ["https://a.example", "https://b.example"]
    assert memory.primary_url() == "https://a.example"
    assert memory.to_payload()["source_urls"] == ["https://a.example", "https://b.example"]


def test_claim_memory_helpers_are_immutable() -> None:
    claim = ClaimMemory(claim_id="claim-1", run_id="run-1", text="  OpenAI   Released Model  ")

    assert claim.normalized_text() == "openai released model"
    assert claim.is_active()
    with_evidence = claim.with_evidence("ev-1")
    contradicted = with_evidence.mark_contradicted("ev-2", reason="new source")

    assert claim.evidence_ids == []
    assert with_evidence.evidence_ids == ["ev-1"]
    assert contradicted.status == "contradicted"
    assert contradicted.contradicted_by == ["ev-2"]
    assert contradicted.metadata["contradiction_reason"] == "new source"


def test_entity_event_preference_and_bundle_helpers() -> None:
    entity = EntityMemory(entity_id="ent-1", entity_type="topic", canonical_name="AI", aliases=["ai"])
    updated = entity.with_alias("Artificial Intelligence")
    event = EventMemory(
        event_id="event-1",
        event_type="general_news",
        title="Update",
        summary="Summary",
        run_id="run-1",
        entity_ids=["ent-1", "ent-1"],
        evidence_ids=["ev-1", "ev-2", "ev-2"],
    )
    expired = PreferenceMemory(
        preference_id="pref-1",
        owner_type="project",
        owner_id="newsroom",
        preference_type="topic",
        content="AI",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    bundle = IntelligenceMemoryBundle(run_id="run-1", entities=[updated], events=[event], preferences=[expired])

    assert updated.all_names() == ["AI", "Artificial Intelligence"]
    assert event.entity_count() == 1
    assert event.evidence_count() == 2
    assert expired.is_expired()
    assert bundle.counts() == {
        "evidence": 0,
        "claims": 0,
        "entities": 1,
        "events": 1,
        "decisions": 0,
        "preferences": 1,
    }
    assert len(bundle.all_indexable_items()) == 3
