from __future__ import annotations

from framework.harness import FakeRAGSessionController, RAGSessionRequest
from framework.harness.rag import ensure_jsonable_rag_model
from framework.harness.rag.fake import fake_reader_repair_memory, fake_research_evidence_packs


def test_fake_rag_runtime_returns_serializable_context_pack() -> None:
    result = FakeRAGSessionController().run_fake_session()

    assert result.context_pack is not None
    ensure_jsonable_rag_model(result.context_pack)
    assert result.context_pack.accepted_evidence[0].source_ref.startswith("source://paper/")
    assert result.context_pack.memory_context


def test_fake_rag_controller_preserves_legacy_request_entrypoint() -> None:
    pack = FakeRAGSessionController().build_context_pack(
        RAGSessionRequest(
            query="How should reader repair recover missing method evidence?",
            context_refs=("paper://sparse-mixture-reader",),
            metadata={
                "session_id": "legacy-rag-test",
                "allowed_corpora": ("research-papers",),
                "allowed_memory_namespaces": ("research.reader_repair",),
                "allowed_tools": ("retrieval.read_source",),
                "required_evidence_types": ("method",),
            },
        )
    )

    assert pack.pack_id == "rag-context://legacy-rag-test"
    assert pack.metadata["context_snapshot_ref"]


def test_fake_rag_fixtures_use_research_shaped_data() -> None:
    evidence = fake_research_evidence_packs()
    memory = fake_reader_repair_memory()

    assert any("method" in ref for pack in evidence for ref in pack.source_refs)
    assert {item["case_type"] for item in memory} == {
        "successful_repair_case",
        "failed_repair_case",
        "procedural_strategy",
    }
    assert all(item["namespace"] == "research.reader_repair" for item in memory)
