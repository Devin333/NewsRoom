from business.layers.output.memory_ingestion import MemoryIngestionService
from core.framework.memory import InMemoryMemoryStore, MemoryKind, MemoryRuntime, MemoryScope


def test_memory_ingestion_builds_report_section_documents() -> None:
    store = _CapturingVectorStore()
    service = MemoryIngestionService(store)
    report = {
        "title": "Daily Intelligence: AI",
        "sections": [
            {
                "title": "Summary",
                "content": "Agent runtime updates accelerated.",
                "sources": ["https://example.com/a"],
            },
            {
                "title": "Outlook",
                "content": "Memory retrieval remains important.",
            },
        ],
        "source_urls": ["https://example.com/a", "https://example.com/b"],
        "metadata": {"quality_score": 0.88},
    }

    result = service.ingest_report(report, run_id="run-1", report_id="report-1", topic="AI")

    assert result.documents_indexed == 2
    assert result.collections == ["report_sections"]
    assert result.document_ids == ["run-1:report_section:0", "run-1:report_section:1"]
    first = store.documents[0]
    assert first.collection == "report_sections"
    assert first.source_type == "report_section"
    assert first.run_id == "run-1"
    assert first.report_id == "report-1"
    assert first.payload["section_index"] == 0
    assert first.payload["topic"] == "AI"
    assert first.payload["source_urls"] == ["https://example.com/a"]
    assert first.payload["refs"] == {
        "run_id": "run-1",
        "report_id": "report-1",
        "section_id": "section_1",
    }
    assert first.payload["section_id"] == "section_1"
    assert first.section_id == "section_1"
    assert "Summary" in first.text
    assert "Agent runtime" in first.text
    assert result.to_dict()["memories_written"] == 0
    assert result.to_dict()["memory_ids"] == []


def test_memory_ingestion_builds_evidence_documents() -> None:
    store = _CapturingVectorStore()
    service = MemoryIngestionService(store)
    bundle = {
        "bundle_id": "daily",
        "items": [
            {
                "evidence_id": "evidence-1",
                "source_url": "https://example.com/a",
                "title": "Agent runtime update",
                "summary": "A runtime added vector memory.",
                "confidence": 0.91,
                "source_id": "source-1",
            }
        ],
    }

    result = service.ingest_evidence_bundle(bundle, run_id="run-1", topic="AI")

    assert result.documents_indexed == 1
    assert result.collections == ["evidence_items"]
    doc = store.documents[0]
    assert doc.document_id == "run-1:evidence:evidence-1"
    assert doc.collection == "evidence_items"
    assert doc.evidence_id == "evidence-1"
    assert doc.source_item_id == "source-1"
    assert doc.payload["source_url"] == "https://example.com/a"
    assert doc.payload["source_urls"] == ["https://example.com/a"]
    assert doc.payload["source_item_ids"] == []
    assert doc.payload["refs"] == {
        "run_id": "run-1",
        "evidence_id": "evidence-1",
        "source_item_id": "source-1",
    }
    assert doc.payload["confidence"] == 0.91
    assert doc.payload["topic"] == "AI"


def test_memory_ingestion_indexes_run_output_report_and_evidence() -> None:
    store = _CapturingVectorStore()
    service = MemoryIngestionService(store)
    report = {
        "title": "Daily Intelligence: AI",
        "sections": [{"title": "Summary", "content": "Agent runtime update."}],
        "source_urls": ["https://example.com/a"],
    }
    bundle = {
        "bundle_id": "daily",
        "items": [
            {
                "evidence_id": "evidence-1",
                "source_url": "https://example.com/a",
                "title": "Agent runtime update",
                "summary": "A runtime added vector memory.",
                "confidence": 0.91,
                "source_id": "source-1",
            }
        ],
    }

    result = service.ingest_run_output(
        {"final_report": report, "evidence_bundle": bundle},
        run_id="run-1",
        topic="AI",
    )

    assert result.documents_indexed == 2
    assert result.collections == ["evidence_items", "report_sections"]
    assert [doc.collection for doc in store.documents] == ["report_sections", "evidence_items"]


def test_memory_ingestion_writes_memory_records_through_runtime() -> None:
    memory_store = InMemoryMemoryStore()
    runtime = MemoryRuntime(memory_store)
    service = MemoryIngestionService(memory_runtime=runtime)

    result = service.ingest_run_output(
        {
            "final_report": {
                "title": "Daily Intelligence: AI",
                "sections": [
                    {
                        "title": "Summary",
                        "content": "Agent runtime memory indexing shipped.",
                    }
                ],
            },
            "evidence_bundle": {
                "bundle_id": "bundle-1",
                "items": [
                    {
                        "evidence_id": "ev-1",
                        "source_url": "https://example.com/source",
                        "title": "Memory indexing",
                        "summary": "Vector memory indexing now runs through the runtime.",
                        "confidence": 0.9,
                        "source_id": "source-1",
                    }
                ],
            },
        },
        run_id="run-1",
        report_id="report-1",
        topic="AI",
    )

    assert result.documents_indexed == 2
    assert result.memories_written == 2
    assert result.memory_ids == ["run-1:report_section:0", "run-1:evidence:ev-1"]
    report_memory = memory_store.get("run-1:report_section:0")
    evidence_memory = memory_store.get("run-1:evidence:ev-1")
    assert report_memory is not None
    assert report_memory.kind == MemoryKind.ARTIFACT
    assert report_memory.scope == MemoryScope.SESSION
    assert report_memory.refs == {
        "run_id": "run-1",
        "report_id": "report-1",
        "section_id": "section_1",
    }
    assert report_memory.metadata["collection"] == "report_sections"
    assert report_memory.metadata["topic"] == "AI"
    assert evidence_memory is not None
    assert evidence_memory.refs["evidence_id"] == "ev-1"
    assert evidence_memory.confidence == 0.9


class _CapturingVectorStore:
    def __init__(self) -> None:
        self.documents = []

    def upsert_documents(self, docs):
        self.documents.extend(docs)
