from __future__ import annotations

from framework.harness import FakeRAGSessionController
from framework.harness.rag.fake import fake_rag_session_spec
from framework.harness.rag import validate_rag_evidence_refs


def test_fake_rag_session_controller_builds_graph_context_pack() -> None:
    controller = FakeRAGSessionController()
    result = controller.run(fake_rag_session_spec())
    assert result.context_pack is not None
    pack = result.context_pack

    assert pack.context_refs == ("paper://sparse-mixture-reader",)
    assert pack.evidence[0].source_refs
    assert validate_rag_evidence_refs(pack).passed is True
