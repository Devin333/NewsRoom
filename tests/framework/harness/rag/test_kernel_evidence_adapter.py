from __future__ import annotations

from framework.harness.rag.kernel_evidence_adapter import evidence_candidate_from_rag_evidence
from framework.harness.rag.kernel_evidence_adapter import KernelRAGRetrieverHarnessAdapter
from framework.harness.retrieval.request import RetrievalRequest
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


def test_kernel_rag_retriever_adapter_returns_harness_evidence_pack_collection():
    retriever = _FakeKernelRetriever((
        RAGEvidence(
            evidence_id="ev-2",
            chunk_id="chunk-2",
            document_id="doc-1",
            text="A second grounded evidence summary.",
            score=0.67,
            score_breakdown=RAGScoreBreakdown(field_score=0.5, final_score=0.67),
            source_locator=SourceLocator(source_id="source://doc-1/chunk-2"),
            metadata={"title": "Ablation"},
        ),
    ))
    adapter = KernelRAGRetrieverHarnessAdapter(
        retriever,
        default_intent="experiment_result",
        default_evidence_type="result",
    )

    collection = adapter.retrieve(RetrievalRequest(
        query="What do the results show?",
        scope="paper-corpus",
        filters={"paper_id": "doc-1"},
        limit=3,
        context_refs=("source://doc-1",),
        metadata={"preferred_fields": ("caption", "body")},
    ))

    assert retriever.queries[0].intent == "experiment_result"
    assert retriever.queries[0].filters["paper_id"] == "doc-1"
    assert retriever.queries[0].filters["context_refs"] == ["source://doc-1"]
    assert retriever.queries[0].preferred_fields == ("caption", "body")
    assert collection.request_ref == "rag-kernel://retrieval/experiment_result/what-do-the-results-show?"
    assert collection.metadata["adapter"] == "kernel_rag_retriever_harness_adapter"
    assert collection.packs[0].evidence_id == "ev-2"
    assert collection.packs[0].metadata["evidence_type"] == "result"
    assert collection.packs[0].metadata["rag_score_breakdown"] == {
        "field_score": 0.5,
        "final_score": 0.67,
    }


class _FakeKernelRetriever:
    def __init__(self, evidence: tuple[RAGEvidence, ...]) -> None:
        self.evidence = evidence
        self.queries = []

    def retrieve(self, query):
        self.queries.append(query)
        return self.evidence
