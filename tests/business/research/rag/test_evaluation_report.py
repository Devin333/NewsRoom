from __future__ import annotations

import json

from business.research.rag.evaluation.paper_answer_eval import (
    EvidenceAnswerEvalResult,
    EvidenceAnswerSample,
    EvidenceAnswerScores,
)
from business.research.rag.evaluation.paper_evaluation_report import EvidenceRegressionReport
from business.research.rag.evaluation.paper_evidence_eval import EvidenceEvalResult, EvidenceQAPair
from business.research.rag.evaluation.paper_generation_eval import GenerationEvalResult, GenerationScores


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
    generation = GenerationEvalResult(per_sample=[
        GenerationScores(
            faithfulness=1.0,
            answer_relevancy=0.9,
            context_precision=0.8,
        )
    ])
    report = EvidenceRegressionReport(
        retrieval=retrieval,
        answer=answer,
        generation=generation,
        thresholds={
            "retrieval.evidence_coverage": 0.5,
            "answer.success_rate": 0.9,
            "generation.faithfulness": 0.9,
        },
        metadata={"paper_id": "p1"},
    )

    report.write(tmp_path)

    payload = json.loads((tmp_path / "evidence_regression_report.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "evidence_regression_report.md").read_text(encoding="utf-8")
    assert payload["metadata"]["paper_id"] == "p1"
    assert payload["passed"] is True
    assert payload["retrieval"]["by_k"]["1"]["hit_rate"] == 1.0
    assert payload["answer"]["success_rate"] == 1.0
    assert payload["generation"]["faithfulness"] == 1.0
    scorecard = payload["rag_evaluation_report"]["scorecard"]
    metrics = {metric["name"]: metric["value"] for metric in scorecard["metrics"]}
    assert metrics["retrieval.mrr"] == 1.0
    assert metrics["retrieval.hit_at_1"] == 1.0
    assert metrics["answer.success_rate"] == 1.0
    assert metrics["generation.faithfulness"] == 1.0
    assert "Paper RAG Evidence Regression Report" in markdown
    assert "RAG Scorecard" in markdown
    assert "Evidence Retrieval Eval" in markdown
    assert "Evidence Answer Eval" in markdown
    assert "Generation" in markdown


def test_evidence_regression_report_records_threshold_failures() -> None:
    retrieval = EvidenceEvalResult(
        total=1,
        answerable_total=1,
        abstain_total=0,
        ks=(1,),
        hit_at={1: 0},
        evidence_coverage_at={1: [0.0]},
        required_type_coverage_at={1: [0.0]},
        source_locator_coverage_at={1: [0.0]},
        citation_accuracy_at={1: []},
        image_recall_at={1: [0.0]},
        visual_evidence_coverage_at={1: [0.0]},
        over_retrieval_at={1: [1]},
        reciprocal_ranks=[0.0],
        ndcg_at={1: [0.0]},
    )
    report = EvidenceRegressionReport(
        retrieval=retrieval,
        thresholds={"retrieval.evidence_coverage": 0.8},
    )

    assert report.passed() is False
    assert report.issues() == ["retrieval.evidence_coverage=0.000 is below threshold 0.800"]
    assert "**Status:** FAIL" in report.to_markdown()


def test_evidence_regression_report_maps_answer_failures_to_rag_scorecard() -> None:
    pair = EvidenceQAPair(
        question="What is missing?",
        paper_id="p1",
        qa_type="table_qa",
        gold_chunk_ids=["tbl-1"],
    )
    answer = EvidenceAnswerEvalResult(scores=[
        EvidenceAnswerScores(
            sample=EvidenceAnswerSample(pair=pair, answer="The answer missed the table."),
            fact_coverage=1.0,
            citation_grounding=0.0,
            source_locator_grounding=None,
            abstention_correct=None,
            answer_success=False,
            retrieval_context_coverage=0.0,
            citation_gold_coverage=0.0,
            failure_reason="missing_gold_in_llm_context",
        )
    ])
    report = EvidenceRegressionReport(answer=answer, metadata={"split": "test"})

    scorecard = report.to_dict()["rag_evaluation_report"]["scorecard"]

    assert scorecard["failure_reasons"] == ["context_missing_gold"]
    assert scorecard["metadata"]["raw_failure_reason_counts"] == {"missing_gold_in_llm_context": 1}
    assert scorecard["metadata"]["split"] == "test"
