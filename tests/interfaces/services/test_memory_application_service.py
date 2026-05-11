from interfaces.services.memory_service import MemoryApplicationService
from storage.vector import InMemoryVectorStore, VectorCollectionStatus, VectorSearchResult
import json


def test_memory_application_service_searches_vector_store() -> None:
    store = _FakeVectorStore()
    service = MemoryApplicationService(vector_store=store)

    result = service.search(
        text="agent runtime",
        collection="report_sections",
        limit=2,
        filters={"topic": "AI"},
    )

    query = store.queries[0]
    assert query.text == "agent runtime"
    assert query.collection == "report_sections"
    assert query.limit == 2
    assert query.filters == {"topic": "AI"}
    assert result.to_dict()["result_count"] == 1
    assert result.to_dict()["results"][0]["document_id"] == "doc-1"


def test_memory_application_service_reindexes_run_from_real_artifacts(tmp_path) -> None:
    _write_run_artifacts(
        tmp_path,
        "run-1",
        request={"topic": "AI policy"},
        report={
            "title": "Daily Intelligence",
            "sections": [
                {
                    "title": "Summary",
                    "content": "Agent runtime memory improved.",
                    "sources": ["https://example.com/a"],
                },
                {
                    "title": "Outlook",
                    "content": "Vector recall remains useful.",
                    "sources": ["https://example.com/b"],
                },
            ],
            "source_urls": ["https://example.com/a", "https://example.com/b"],
        },
        evidence_bundle={
            "bundle_id": "daily",
            "items": [
                {
                    "evidence_id": "ev-1",
                    "source_url": "https://example.com/a",
                    "source_id": "source-1",
                    "title": "Agent runtime memory",
                    "summary": "A runtime improved memory recall.",
                    "confidence": 0.9,
                }
            ],
        },
    )
    store = InMemoryVectorStore()
    service = MemoryApplicationService(vector_store=store, artifact_root=tmp_path)

    result = service.reindex_run("run-1")
    search = service.search(
        text="Agent runtime memory",
        collection="report_sections",
        filters={"topic": "AI policy"},
    )

    payload = result.to_dict()
    assert payload["run_id"] == "run-1"
    assert payload["topic"] == "AI policy"
    assert payload["documents_indexed"] == 3
    assert payload["collections"] == ["evidence_items", "report_sections"]
    assert "run-1:report_section:0" in payload["document_ids"]
    assert "run-1:evidence:ev-1" in payload["document_ids"]
    assert search.to_dict()["result_count"] == 2


def test_memory_application_service_reindex_topic_override(tmp_path) -> None:
    _write_run_artifacts(
        tmp_path,
        "run-1",
        request={"topic": "AI policy"},
        report={"title": "Daily", "sections": [{"title": "Summary", "content": "Memory."}]},
        evidence_bundle={"bundle_id": "daily", "items": []},
    )
    service = MemoryApplicationService(vector_store=InMemoryVectorStore(), artifact_root=tmp_path)

    result = service.reindex_run("run-1", topic="Override")

    assert result.to_dict()["topic"] == "Override"


def test_memory_application_service_bootstraps_default_collections() -> None:
    store = _FakeBootstrapVectorStore()
    service = MemoryApplicationService(vector_store=store)

    result = service.bootstrap_collections()

    assert store.bootstrap_calls == [["report_sections", "evidence_items"]]
    assert result.to_dict() == {
        "collection_count": 2,
        "created_count": 1,
        "existing_count": 1,
        "created_collections": ["evidence_items"],
        "existing_collections": ["report_sections"],
        "collections": [
            {
                "collection": "report_sections",
                "vector_size": 64,
                "existed_before": True,
                "created": False,
            },
            {
                "collection": "evidence_items",
                "vector_size": 64,
                "existed_before": False,
                "created": True,
            },
        ],
    }


def test_memory_application_service_bootstrap_deduplicates_custom_collections() -> None:
    store = _FakeBootstrapVectorStore()
    service = MemoryApplicationService(vector_store=store)

    service.bootstrap_collections(["custom", "custom"])

    assert store.bootstrap_calls == [["custom"]]


class _FakeVectorStore:
    def __init__(self) -> None:
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return [
            VectorSearchResult(
                document_id="doc-1",
                score=0.9,
                text="Agent runtime memory",
                source_type="report_section",
                payload={"document_id": "doc-1"},
            )
        ]


class _FakeBootstrapVectorStore(_FakeVectorStore):
    def __init__(self) -> None:
        super().__init__()
        self.bootstrap_calls = []

    def ensure_collections(self, collections):
        self.bootstrap_calls.append(list(collections))
        return [
            VectorCollectionStatus(
                collection="report_sections",
                vector_size=64,
                existed_before=True,
                created=False,
            ),
            VectorCollectionStatus(
                collection="evidence_items",
                vector_size=64,
                existed_before=False,
                created=True,
            ),
        ][: len(collections)]


def _write_run_artifacts(root, run_id, *, request, report, evidence_bundle) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    manifest = {
        "run_id": run_id,
        "status": "succeeded",
        "artifacts": {
            "request": "request.json",
            "report_json": "report.json",
            "evidence_bundle": "evidence_bundle.json",
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (run_dir / "evidence_bundle.json").write_text(json.dumps(evidence_bundle), encoding="utf-8")
