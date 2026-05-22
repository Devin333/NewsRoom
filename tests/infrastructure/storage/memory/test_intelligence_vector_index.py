from datetime import UTC, datetime

from business.memory.intelligence_models import (
    ClaimMemory,
    DecisionMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    IntelligenceMemoryBundle,
    PreferenceMemory,
)
from infrastructure.storage.memory import IntelligenceVectorIndexAdapter


def test_intelligence_vector_index_writes_all_memory_layers() -> None:
    store = _CapturingVectorStore()
    bundle = IntelligenceMemoryBundle(
        run_id="run-1",
        topic="AI",
        evidence=[
            EvidenceMemory(
                evidence_id="ev-1",
                run_id="run-1",
                title="Evidence title",
                summary="Evidence summary",
                source_urls=["https://example.com/a"],
                source_item_ids=["source-item-1"],
                topic="AI",
                published_at=datetime(2026, 5, 20, tzinfo=UTC),
            )
        ],
        claims=[ClaimMemory(claim_id="claim-1", run_id="run-1", text="OpenAI shipped memory")],
        entities=[EntityMemory(entity_id="entity-openai", entity_type="organization", canonical_name="OpenAI")],
        events=[
            EventMemory(
                event_id="event-1",
                event_type="general_news",
                title="Memory shipped",
                summary="OpenAI shipped memory.",
                run_id="run-1",
                topic="AI",
            )
        ],
        decisions=[
            DecisionMemory(
                decision_id="decision-1",
                decision_type="quality_gate",
                target_type="report",
                target_id="report-1",
                decision="pass",
                run_id="run-1",
            )
        ],
        preferences=[
            PreferenceMemory(
                preference_id="pref-1",
                owner_type="topic",
                owner_id="AI",
                preference_type="tone",
                content="Prefer concise reports.",
            )
        ],
    )

    indexed, collections, document_ids = IntelligenceVectorIndexAdapter(store).index_bundle(bundle)

    assert indexed == 6
    assert collections == ["claims", "decisions", "entities", "events", "evidence_items", "preferences"]
    assert document_ids == ["ev-1", "claim-1", "entity-openai", "event-1", "decision-1", "pref-1"]
    assert [doc.collection for doc in store.documents] == [
        "evidence_items",
        "claims",
        "entities",
        "events",
        "decisions",
        "preferences",
    ]
    claim = store.by_id["claim-1"]
    assert claim.text == "OpenAI shipped memory"
    assert claim.payload["memory_layer"] == "claim"
    assert claim.payload["memory_object_id"] == "claim-1"
    assert claim.payload["run_id"] == "run-1"
    assert claim.payload["topic"] == "AI"
    assert claim.payload["claim_id"] == "claim-1"
    assert claim.payload["refs"]["memory_layer"] == "claim"
    evidence = store.by_id["ev-1"]
    assert evidence.source_type == "intelligence_evidence"
    assert evidence.evidence_id == "ev-1"
    assert evidence.source_item_id == "source-item-1"
    assert "Evidence title" in evidence.text


class _CapturingVectorStore:
    def __init__(self) -> None:
        self.documents = []

    @property
    def by_id(self):
        return {doc.document_id: doc for doc in self.documents}

    def upsert_documents(self, docs):
        self.documents.extend(docs)
