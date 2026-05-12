import json

from storage.hybrid_search import HybridSearchQuery, HybridSearchService
from storage.local_json import LocalJsonRepository
from storage.vector import InMemoryVectorStore, VectorDocument


def test_hybrid_search_merges_report_keyword_and_vector_results(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "workflow_id": "daily",
                "profile": "live",
                "status": "succeeded",
                "finished_at": "2026-05-11T00:00:00Z",
                "quality_score": 0.9,
                "artifacts": {"report_json": "report.json"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps({"title": "Agent Runtime Report", "sections": []}),
        encoding="utf-8",
    )
    vector_store = InMemoryVectorStore()
    vector_store.upsert_documents(
        [
            VectorDocument(
                document_id="run-1:report_section:0",
                collection="report_sections",
                text="Agent runtime memory improved.",
                payload={"section_title": "Summary"},
                source_type="report_section",
                run_id="run-1",
                report_id="run-1:final",
            )
        ]
    )

    results = HybridSearchService(
        report_repository=LocalJsonRepository(tmp_path),
        vector_store=vector_store,
    ).search(HybridSearchQuery(query="agent runtime", limit=5))

    assert {result.result_type for result in results} == {"report", "section"}
    assert results[0].score >= results[1].score
    assert any(result.keyword_score == 1.0 for result in results)
    assert any(result.semantic_score is not None for result in results)


def test_hybrid_search_validates_limit() -> None:
    service = HybridSearchService()

    try:
        service.search(HybridSearchQuery(query="ai", limit=0))
    except ValueError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("expected ValueError")
