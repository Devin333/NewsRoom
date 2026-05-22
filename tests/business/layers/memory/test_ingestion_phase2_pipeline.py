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

    def save_evidence(self, items):
        self.saved["evidence"].extend(items)

    def save_claims(self, claims):
        self.saved["claims"].extend(claims)

    def save_entities(self, entities):
        self.saved["entities"].extend(entities)

    def save_events(self, events):
        self.saved["events"].extend(events)

    def save_decisions(self, decisions):
        self.saved["decisions"].extend(decisions)

    def save_preferences(self, preferences):
        self.saved["preferences"].extend(preferences)
