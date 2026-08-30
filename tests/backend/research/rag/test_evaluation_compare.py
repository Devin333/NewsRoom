from __future__ import annotations

from backend.research.document.models import PaperChunk
from backend.research.rag.evaluation.paper_evaluation_compare import EvidenceABComparator, compare_evidence_results
from backend.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair, EvidenceRetrievalEvaluator
from backend.research.rag.retrieval.paper_retriever import RetrievalResult


def _chunk(chunk_id: str, *, chunk_type: str = "paragraph") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="nougat",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Results",
        section_role=["experiment"],  # type: ignore[list-item]
        section_index=4,
        has_table=chunk_type == "table",
        content=f"Content for {chunk_id}.",
        metadata={"source_ref": f"arxiv://p1/{chunk_id}"},
    )


class _FakeRetriever:
    def __init__(self, result: RetrievalResult) -> None:
        self.result = result

    def retrieve(self, request) -> RetrievalResult:
        return self.result


def test_compare_evidence_results_reports_metric_deltas() -> None:
    pair = EvidenceQAPair(
        question="What do the results show?",
        paper_id="p1",
        qa_type="table_qa",
        gold_chunk_ids=["tbl-1", "para-result"],
        required_evidence_types=["table", "paragraph"],
    )
    baseline = EvidenceRetrievalEvaluator(_FakeRetriever(RetrievalResult(
        child_chunks=[_chunk("tbl-1", chunk_type="table")],
        ref_chunks=[],
        parent_chunks=[],
        intent="table_query",
    ))).evaluate([pair], ks=(1, 2))
    candidate = EvidenceRetrievalEvaluator(_FakeRetriever(RetrievalResult(
        child_chunks=[_chunk("tbl-1", chunk_type="table")],
        ref_chunks=[_chunk("para-result")],
        parent_chunks=[],
        intent="table_query",
    ))).evaluate([pair], ks=(1, 2))

    result = compare_evidence_results(
        baseline,
        candidate,
        ks=(1, 2),
        baseline_name="fixed-window",
        candidate_name="semantic",
    )

    assert result.baseline_name == "fixed-window"
    assert result.candidate_name == "semantic"
    assert result.metric_delta("EvidenceCoverage", 2) == 0.5
    assert result.metric_delta("RequiredTypeCoverage", 2) == 0.5
    assert "fixed-window -> semantic" in result.report()


def test_ab_comparator_runs_same_pairs_against_two_retrievers() -> None:
    pair = EvidenceQAPair(
        question="What do the results show?",
        paper_id="p1",
        qa_type="table_qa",
        gold_chunk_ids=["tbl-1", "para-result"],
        required_evidence_types=["table", "paragraph"],
    )
    baseline = _FakeRetriever(RetrievalResult(
        child_chunks=[_chunk("tbl-1", chunk_type="table")],
        ref_chunks=[],
        parent_chunks=[],
        intent="table_query",
    ))
    candidate = _FakeRetriever(RetrievalResult(
        child_chunks=[_chunk("tbl-1", chunk_type="table")],
        ref_chunks=[_chunk("para-result")],
        parent_chunks=[],
        intent="table_query",
    ))

    result = EvidenceABComparator(
        baseline=baseline,
        candidate=candidate,
        baseline_name="fixed-window",
        candidate_name="semantic",
    ).compare([pair], ks=(2,))

    assert result.metric_delta("EvidenceCoverage", 2) == 0.5
    assert result.candidate.evidence_coverage(2) == 1.0
