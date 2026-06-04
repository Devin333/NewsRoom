from __future__ import annotations

from framework.harness import FakeRAGSessionController, RAGSessionRequest
from framework.harness.rag import validate_rag_evidence_refs


def test_fake_rag_session_controller_builds_context_pack_from_retrieval_port() -> None:
    controller = FakeRAGSessionController()
    pack = controller.build_context_pack(RAGSessionRequest(query="reader repair", context_refs=("context://stable",)))

    assert pack.context_refs == ("context://stable",)
    assert pack.evidence[0].source_refs
    assert validate_rag_evidence_refs(pack).passed is True
