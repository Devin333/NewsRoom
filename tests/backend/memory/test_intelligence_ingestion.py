from backend.memory.intelligence_ingestion import (
    IntelligenceMemoryIngestionResult,
    IntelligenceMemoryIngestionService,
)
from backend.memory.intelligence_models import ClaimMemory


def test_ingestion_without_repository_returns_counts() -> None:
    service = IntelligenceMemoryIngestionService()

    result = service.ingest_run_output(
        {"evidence_bundle": {"items": [{"evidence_id": "ev-1", "title": "Title", "summary": "Summary"}]}},
        run_id="run-1",
        topic="AI",
    )

    assert result.counts["evidence"] == 1
    assert result.counts["claims"] == 1
    assert result.documents_indexed == 0


def test_ingestion_saves_layers_in_order() -> None:
    repository = _RecordingRepository()
    service = IntelligenceMemoryIngestionService(repository=repository)

    service.ingest_run_output(
        {
            "evidence_bundle": {
                "items": [{"evidence_id": "ev-1", "title": "Title", "summary": "Summary"}]
            },
            "quality_result": {"decision": "pass"},
        },
        run_id="run-1",
        topic="AI",
    )

    assert repository.calls == [
        "save_evidence",
        "save_claims",
        "save_entities",
        "save_events",
        "save_decisions",
        "save_preferences",
    ]
    assert repository.sizes["save_evidence"] == 1
    assert repository.sizes["save_claims"] == 1
    assert repository.sizes["save_events"] == 1
    assert repository.sizes["save_decisions"] == 1


def test_ingestion_appends_claim_history_for_consolidated_claims() -> None:
    repository = _RecordingRepository()
    existing = ClaimMemory(
        claim_id="claim-1",
        run_id="old-run",
        text="OpenAI released a model",
        subject_entity_id="entity-openai",
        predicate="released",
        confidence=0.8,
        evidence_ids=["ev-old"],
    )
    query_repository = _QueryRepository(existing_claims=[existing])
    service = IntelligenceMemoryIngestionService(repository=repository, query_repository=query_repository)

    service.ingest_run_output(
        {
            "evidence_bundle": {
                "items": [
                    {
                        "evidence_id": "ev-new",
                        "title": "OpenAI did not release a model",
                        "summary": "OpenAI did not release a model",
                    }
                ]
            }
        },
        run_id="run-1",
        topic="AI",
    )

    assert len(repository.claim_history) == 1
    assert repository.claim_history[0].claim_id == "claim-1"
    assert repository.claim_history[0].new_status == "contradicted"


def test_ingestion_result_keeps_legacy_fields() -> None:
    result = IntelligenceMemoryIngestionResult(
        run_id="run-1",
        topic="AI",
        counts={"evidence": 1},
        documents_indexed=3,
        collections=["evidence_items"],
        document_ids=["doc-1"],
        memories_written=1,
        memory_ids=["memory-1"],
    )

    assert result.indexed_documents == 3
    assert result.documents_indexed == 3
    payload = result.to_dict()
    assert payload["run_id"] == "run-1"
    assert payload["topic"] == "AI"
    assert payload["counts"] == {"evidence": 1}
    assert payload["indexed_documents"] == 3
    assert payload["documents_indexed"] == 3
    assert payload["collections"] == ["evidence_items"]
    assert payload["document_ids"] == ["doc-1"]
    assert payload["memories_written"] == 1
    assert payload["memory_ids"] == ["memory-1"]
    assert payload["metadata"] == {}


class _RecordingRepository:
    def __init__(self) -> None:
        self.calls = []
        self.sizes = {}
        self.claim_history = []

    def _record(self, name, items) -> None:
        self.calls.append(name)
        self.sizes[name] = len(items)

    def save_evidence(self, items) -> None:
        self._record("save_evidence", items)

    def save_claims(self, claims) -> None:
        self._record("save_claims", claims)

    def save_entities(self, entities) -> None:
        self._record("save_entities", entities)

    def save_events(self, events) -> None:
        self._record("save_events", events)

    def save_decisions(self, decisions) -> None:
        self._record("save_decisions", decisions)

    def save_preferences(self, preferences) -> None:
        self._record("save_preferences", preferences)

    def append_claim_history(self, history) -> None:
        self.claim_history.append(history)


class _QueryRepository:
    def __init__(self, existing_claims=None, existing_events=None) -> None:
        self.existing_claims = existing_claims or []
        self.existing_events = existing_events or []

    def list_claims_by_topic(self, topic, *, limit=50):
        return self.existing_claims[:limit]

    def find_similar_claims(self, claim, *, limit=10):
        return self.existing_claims[:limit]

    def list_events_by_topic(self, topic, *, limit=50):
        return self.existing_events[:limit]
