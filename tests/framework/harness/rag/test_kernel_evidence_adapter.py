from __future__ import annotations

from framework.harness.rag.kernel_evidence_adapter import evidence_candidate_from_rag_evidence
from framework.rag.core import RAGEvidence, RAGScoreBreakdown, SourceLocator


def test_kernel_rag_evidence_converts_to_harness_evidence_candidate():
    evidence = RAGEvidence(
        evidence_id="ev-1",
        chunk_id="chunk-1",
        document_id="doc-1",
        text="A grounded evidence summary.",
        score=0.85,
        score_breakdown=RAGScoreBreakdown(child_similarity=0.8, final_score=0.85),
        source_locator=SourceLocator(
            source_id="source://doc-1/chunk-1",
            raw_locator="source://doc-1/chunk-1",
        ),
        metadata={"section_title": "Results", "artifact_refs": ["artifact://visual/1"]},
    )

    candidate = evidence_candidate_from_rag_evidence(evidence, evidence_type="experiment_result")

    assert candidate.evidence_id == "ev-1"
    assert candidate.title == "Results"
    assert candidate.summary == "A grounded evidence summary."
    assert candidate.source_ref == "source://doc-1/chunk-1"
    assert candidate.span_refs == ("source://doc-1/chunk-1",)
    assert candidate.evidence_type == "experiment_result"
    assert candidate.confidence == 0.85
    assert candidate.lineage == ("doc-1",)
    assert candidate.artifact_refs == ("artifact://visual/1",)
    assert candidate.metadata["rag_score"] == 0.85
    assert candidate.metadata["rag_score_breakdown"] == {
        "child_similarity": 0.8,
        "final_score": 0.85,
    }
