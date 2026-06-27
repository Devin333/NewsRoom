from __future__ import annotations

from framework.harness import ContextCacheScope, ContextSegmentType, FakeRAGSessionController, RAGContextPackAssembler
from framework.harness.context.fake import FakeContextAssembler
from framework.harness.rag.fake import fake_rag_session_spec
from framework.harness.rag.models import EvidenceCandidate
from framework.harness.rag.policy import RAGExecutionPolicy


def test_context_pack_assembler_routes_rag_payload_through_context_assembler() -> None:
    spec = fake_rag_session_spec()
    assembler = RAGContextPackAssembler(FakeContextAssembler())
    evidence = (
        EvidenceCandidate(
            evidence_id="evidence:method",
            title="Method paragraph",
            summary="The reader repair retrieves method spans with preserved lineage.",
            source_ref="source://paper#method",
            span_refs=("source://paper#method:p3",),
            evidence_type="method",
            confidence=0.9,
            freshness="static-fixture",
            lineage=("retrieval.fake", "source.read"),
            artifact_refs=("artifact://paper/method-image",),
        ),
    )

    pack = assembler.assemble(
        spec=spec,
        accepted_evidence=evidence,
        artifact_refs=("artifact://retrieval/request-1",),
        budget_snapshot=None,
        policy=RAGExecutionPolicy.from_session_spec(spec),
    )

    envelope = assembler.envelopes[0]
    assert pack.metadata["context_snapshot_ref"]
    assert pack.artifact_refs == ("artifact://paper/method-image", "artifact://retrieval/request-1")
    assert pack.evidence_trace == (
        {
            "status": "accepted",
            "evidence_id": "evidence:method",
            "evidence_type": "method",
            "source_ref": "source://paper#method",
            "span_refs": ["source://paper#method:p3"],
            "artifact_refs": ["artifact://paper/method-image"],
            "lineage": ["retrieval.fake", "source.read"],
            "confidence": 0.9,
            "score_breakdown": {},
        },
    )
    assert envelope.stable_prefix[ContextSegmentType.GLOBAL_POLICY.value]
    assert envelope.artifact_refs == pack.artifact_refs
    assert envelope.metadata["evidence_trace"] == [dict(pack.evidence_trace[0])]
    assert ContextSegmentType.EVIDENCE_MEMORY.value in envelope.dynamic_tail
    assert all(segment.cache_scope == ContextCacheScope.STABLE_PREFIX for segment in envelope.segments[:3])
    assert all(segment.cache_scope == ContextCacheScope.DYNAMIC_TAIL for segment in envelope.segments[3:])


def test_fake_runtime_context_pack_keeps_dynamic_results_out_of_stable_prefix() -> None:
    controller = FakeRAGSessionController()
    result = controller.run_fake_session()

    envelope = controller.context_pack_assembler.envelopes[0]

    assert result.context_pack is not None
    assert result.context_pack.metadata["stable_prefix_contains_dynamic_rag"] is False
    assert "accepted_evidence" not in envelope.stable_prefix.get(ContextSegmentType.GLOBAL_POLICY.value, {})
    assert ContextSegmentType.EVIDENCE_MEMORY.value in envelope.dynamic_tail
