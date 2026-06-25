from __future__ import annotations

import json

from business.research.rag.answer_eval import (
    EvidenceAnswerEvalResult,
    EvidenceAnswerSample,
    EvidenceAnswerScores,
)
from business.research.rag.evaluation_report import EvidenceRegressionReport
from business.research.rag.evidence_eval import EvidenceEvalResult, EvidenceQAPair


def test_evidence_regression_report_writes_json_and_markdown(tmp_path) -> None:
    pair = EvidenceQAPair(
        question="What is supported?",
        paper_id="p1",
        qa_type="citation_qa",
        gold_chunk_ids=["para-1"],
    )
    retrieval = EvidenceEvalResult(
        total=1,
        answerable_total=1,
        abstain_total=0,
        ks=(1,),
        hit_at={1: 1},
        evidence_coverage_at={1: [1.0]},
        required_type_coverage_at={1: [0.0]},
        source_locator_coverage_at={1: [0.0]},
        citation_accuracy_at={1: []},
        image_recall_at={1: [0.0]},
        visual_evidence_coverage_at={1: [0.0]},
        over_retrieval_at={1: [0]},
        reciprocal_ranks=[1.0],
        ndcg_at={1: [1.0]},
    )
    answer = EvidenceAnswerEvalResult(scores=[
        EvidenceAnswerScores(
            sample=EvidenceAnswerSample(pair=pair, answer="Supported. [para-1]", cited_chunk_ids=["para-1"]),
            fact_coverage=None,
            citation_grounding=1.0,
            source_locator_grounding=None,
            abstention_correct=None,
            answer_success=True,
        )
    ])
    report = EvidenceRegressionReport(
        retrieval=retrieval,
        answer=answer,
        metadata={"paper_id": "p1"},
    )

    report.write(tmp_path)

    payload = json.loads((tmp_path / "evidence_regression_report.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "evidence_regression_report.md").read_text(encoding="utf-8")
    assert payload["metadata"]["paper_id"] == "p1"
    assert payload["retrieval"]["by_k"]["1"]["hit_rate"] == 1.0
    assert payload["answer"]["success_rate"] == 1.0
    assert "Paper RAG Evidence Regression Report" in markdown
    assert "Evidence Retrieval Eval" in markdown
    assert "Evidence Answer Eval" in markdown
