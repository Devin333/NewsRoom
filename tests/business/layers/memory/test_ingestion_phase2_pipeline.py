from business.layers.memory.ingestion import MemoryIngestionService
from infrastructure.storage.memory import IntelligenceVectorIndexAdapter


def test_memory_ingestion_phase2_pipeline_saves_and_indexes_structured_memory() -> None:
    legacy_store = _CapturingVectorStore()
    structured_store = _CapturingVectorStore()
    repository = _CapturingRepository()
    service = MemoryIngestionService(
        legacy_store,
        repository=repository,
        vector_index=IntelligenceVectorIndexAdapter(structured_store),
    )

    result = service.ingest_run_output(
        {
            "final_report": {
                "title": "Daily Intelligence: AI",
                "sections": [
                    {
                        "title": "Summary",
                        "content": "OpenAI shipped memory. GitHub repo owner/project is trending.",
                        "sources": ["https://example.com/openai-memory"],
                    }
                ],
                "metadata": {"quality_score": 0.91},
            },
            "evidence_bundle": {
                "bundle_id": "daily",
                "items": [
                    {
                        "evidence_id": "ev-1",
                        "source_url": "https://example.com/openai-memory",
                        "title": "OpenAI shipped memory",
                        "summary": "OpenAI shipped memory for agents.",
                        "confidence": 0.9,
                        "source_id": "source-1",
                        "metadata": {"github_repo": "owner/project"},
                    }
                ],
            },
            "quality_result": {"decision": "pass"},
        },
        run_id="run-1",
        report_id="report-1",
        topic="AI",
    )

    assert result.metadata["claim_consolidation"]
    assert result.metadata["entity_resolution"]
    assert result.metadata["event_build"]
    assert result.counts["evidence"] == 1
    assert result.counts["claims"] > 0
    assert result.counts["entities"] > 0
    assert result.counts["events"] > 0
    assert repository.saved["claims"]
    assert repository.saved["entities"]
    assert repository.saved["events"]
    assert [doc.collection for doc in legacy_store.documents] == ["report_sections", "evidence_items"]
    structured_collections = {doc.collection for doc in structured_store.documents}
    assert {"claims", "entities", "events", "evidence_items"}.issubset(structured_collections)
    assert result.indexed_documents == len(legacy_store.documents) + len(structured_store.documents)
    assert any(doc_id in result.document_ids for doc_id in [doc.document_id for doc in structured_store.documents])


def test_phase2_pipeline_merges_duplicate_claims_across_runs() -> None:
    repository = _CapturingRepository()
    structured_store = _CapturingVectorStore()
    service = MemoryIngestionService(
        repository=repository,
        vector_index=IntelligenceVectorIndexAdapter(structured_store),
    )

    service.ingest_run_output(
        _run_output(
            evidence_id="ev-1",
            title="OpenAI shipped memory",
            summary="OpenAI shipped memory for agents.",
        ),
        run_id="run-1",
        topic="AI",
    )
    result = service.ingest_run_output(
        _run_output(
            evidence_id="ev-2",
            title="OpenAI shipped memory",
            summary="OpenAI shipped memory for agents.",
        ),
        run_id="run-2",
        topic="AI",
    )

    assert result.metadata["claim_consolidation"]["merged"] >= 1
    assert repository.saved["claims"][0].evidence_ids == ["ev-1", "ev-2"]


def test_phase2_pipeline_appends_claim_history_when_status_changes() -> None:
    repository = _CapturingRepository()
    service = MemoryIngestionService(repository=repository)

    service.ingest_run_output(
        _run_output(
            evidence_id="ev-1",
            title="OpenAI released GPT-5",
            summary="OpenAI released GPT-5.",
        ),
        run_id="run-1",
        topic="AI",
    )
    result = service.ingest_run_output(
        _run_output(
            evidence_id="ev-2",
            title="OpenAI not released GPT-5",
            summary="OpenAI not released GPT-5.",
        ),
        run_id="run-2",
        topic="AI",
    )

    assert result.metadata["claim_consolidation"]["contradicted"] >= 1
    assert repository.claim_history
    assert repository.claim_history[-1].old_status == "active"
    assert repository.claim_history[-1].new_status == "contradicted"


def test_phase2_pipeline_skips_duplicate_events() -> None:
    repository = _CapturingRepository()
    service = MemoryIngestionService(repository=repository)

    service.ingest_run_output(
        _run_output(
            evidence_id="ev-1",
            title="OpenAI shipped memory",
            summary="OpenAI shipped memory for agents.",
        ),
        run_id="run-1",
        topic="AI",
    )
    result = service.ingest_run_output(
        _run_output(
            evidence_id="ev-2",
            title="OpenAI shipped memory",
            summary="OpenAI shipped memory for agents.",
        ),
        run_id="run-2",
        topic="AI",
    )

    assert result.metadata["event_build"]["duplicates"] >= 1
    assert result.metadata["event_build"]["skipped"] >= 1


class _CapturingVectorStore:
    def __init__(self) -> None:
        self.documents = []

    def upsert_documents(self, docs):
        self.documents.extend(docs)


class _CapturingRepository:
    def __init__(self) -> None:
        self.saved = {
            "evidence": [],
            "claims": [],
            "entities": [],
            "events": [],
            "decisions": [],
            "preferences": [],
        }
        self.claim_history = []

    def save_evidence(self, items):
        _upsert(self.saved["evidence"], items, "evidence_id")

    def save_claims(self, claims):
        _upsert(self.saved["claims"], claims, "claim_id")

    def save_entities(self, entities):
        _upsert(self.saved["entities"], entities, "entity_id")

    def save_events(self, events):
        _upsert(self.saved["events"], events, "event_id")

    def save_decisions(self, decisions):
        _upsert(self.saved["decisions"], decisions, "decision_id")

    def save_preferences(self, preferences):
        _upsert(self.saved["preferences"], preferences, "preference_id")

    def list_claims_by_topic(self, topic: str, *, limit: int = 20):
        del topic
        return list(self.saved["claims"])[:limit]

    def find_similar_claims(self, claim, *, limit: int = 10):
        return [
            existing
            for existing in self.saved["claims"]
            if existing.claim_id != claim.claim_id
            and (
                existing.normalized_text() == claim.normalized_text()
                or ("not " in existing.normalized_text()) != ("not " in claim.normalized_text())
            )
        ][:limit]

    def list_events_by_topic(self, topic: str, *, limit: int = 20):
        return [event for event in self.saved["events"] if event.topic == topic][:limit]

    def find_similar_events(self, event, *, limit: int = 10):
        return [
            existing
            for existing in self.saved["events"]
            if existing.event_id != event.event_id
            and existing.topic == event.topic
            and existing.event_type == event.event_type
            and existing.title == event.title
        ][:limit]

    def append_claim_history(self, history):
        self.claim_history.append(history)


def _run_output(*, evidence_id: str, title: str, summary: str) -> dict:
    return {
        "evidence_bundle": {
            "bundle_id": "daily",
            "items": [
                {
                    "evidence_id": evidence_id,
                    "source_url": f"https://example.com/{evidence_id}",
                    "source_urls": [f"https://example.com/{evidence_id}"],
                    "title": title,
                    "summary": summary,
                    "confidence": 0.8,
                    "source_id": "source-1",
                }
            ],
        },
        "quality_result": {"decision": "pass", "reason": "supported"},
    }


def _upsert(target, items, key: str) -> None:
    by_id = {getattr(item, key): index for index, item in enumerate(target)}
    for item in items:
        item_id = getattr(item, key)
        if item_id in by_id:
            target[by_id[item_id]] = item
        else:
            by_id[item_id] = len(target)
            target.append(item)
