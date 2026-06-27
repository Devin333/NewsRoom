from __future__ import annotations

from typing import Any

from framework.rag.evaluation import MetricValue, RAGEvaluationReport, RAGFailureReason, RAGScorecard

from business.research.rag.answer_eval import EvidenceAnswerEvalResult
from business.research.rag.evidence_eval import EvidenceEvalResult
from business.research.rag.generation_eval import GenerationEvalResult


_FAILURE_REASON_MAP: dict[str, RAGFailureReason] = {
    "missing_gold_in_retrieval": RAGFailureReason.MISSING_GOLD_IN_RETRIEVAL,
    "missing_gold_in_llm_context": RAGFailureReason.CONTEXT_MISSING_GOLD,
    "missing_gold_citation": RAGFailureReason.CITATION_MISSING_SOURCE,
    "fact_match_low": RAGFailureReason.FACT_MATCH_LOW,
    "unexpected_abstention": RAGFailureReason.ABSTENTION_EXPECTED,
    "abstention_mismatch": RAGFailureReason.ABSTENTION_EXPECTED,
    "other": RAGFailureReason.ANSWER_NOT_GROUNDED,
}


def evidence_results_to_rag_report(
    *,
    retrieval: EvidenceEvalResult | None = None,
    answer: EvidenceAnswerEvalResult | None = None,
    generation: GenerationEvalResult | None = None,
    thresholds: dict[str, float] | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str = "paper-rag-evidence-regression",
) -> RAGEvaluationReport:
    return RAGEvaluationReport(
        title="Paper RAG Evidence Regression",
        scorecard=evidence_results_to_rag_scorecard(
            retrieval=retrieval,
            answer=answer,
            generation=generation,
            thresholds=thresholds or {},
            metadata=metadata or {},
            run_id=run_id,
        ),
    )


def evidence_results_to_rag_scorecard(
    *,
    retrieval: EvidenceEvalResult | None = None,
    answer: EvidenceAnswerEvalResult | None = None,
    generation: GenerationEvalResult | None = None,
    thresholds: dict[str, float] | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str = "paper-rag-evidence-regression",
) -> RAGScorecard:
    metrics: list[MetricValue] = []
    if retrieval is not None:
        metrics.extend(_retrieval_metrics(retrieval))
    if answer is not None:
        metrics.extend(_answer_metrics(answer))
    if generation is not None:
        metrics.extend(_generation_metrics(generation))
    scorecard_metadata = {
        **dict(metadata or {}),
        "thresholds": dict(thresholds or {}),
        "paper_specific_metrics": _paper_specific_metrics(retrieval),
        "raw_failure_reason_counts": answer.failure_reason_counts() if answer is not None else {},
    }
    return RAGScorecard(
        run_id=run_id,
        metrics=tuple(metrics),
        failure_reasons=_mapped_failure_reasons(answer),
        metadata=scorecard_metadata,
    )


def _retrieval_metrics(result: EvidenceEvalResult) -> list[MetricValue]:
    metrics = [
        MetricValue("retrieval.mrr", result.mrr()),
        MetricValue("retrieval.total", result.total),
        MetricValue("retrieval.answerable_total", result.answerable_total),
    ]
    for k in result.ks:
        metrics.extend([
            MetricValue(f"retrieval.hit_at_{k}", result.hit_rate(k), {"k": k}),
            MetricValue(f"retrieval.evidence_coverage_at_{k}", result.evidence_coverage(k), {"k": k}),
            MetricValue(f"retrieval.source_locator_coverage_at_{k}", result.source_locator_coverage(k), {"k": k}),
            MetricValue(f"retrieval.ndcg_at_{k}", result.ndcg(k), {"k": k}),
        ])
    return metrics


def _answer_metrics(result: EvidenceAnswerEvalResult) -> list[MetricValue]:
    return [
        MetricValue("answer.fact_coverage", result.answer_fact_coverage()),
        MetricValue("answer.retrieval_context_coverage", result.retrieval_context_coverage_score()),
        MetricValue("answer.citation_grounding", result.citation_grounding_score()),
        MetricValue("answer.citation_gold_coverage", result.citation_gold_coverage_score()),
        MetricValue("answer.source_locator_grounding", result.source_locator_grounding_score()),
        MetricValue("answer.abstention_accuracy", result.abstention_accuracy()),
        MetricValue("answer.success_rate", result.success_rate()),
    ]


def _generation_metrics(result: GenerationEvalResult) -> list[MetricValue]:
    return [
        MetricValue("generation.faithfulness", result.faithfulness_score()),
        MetricValue("generation.answer_relevancy", result.answer_relevancy_score()),
        MetricValue("generation.context_precision", result.context_precision_score()),
    ]


def _paper_specific_metrics(result: EvidenceEvalResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        str(k): {
            "required_type_coverage": result.required_type_coverage(k),
            "image_recall": result.image_recall(k),
            "visual_evidence_coverage": result.visual_evidence_coverage(k),
            "citation_accuracy": result.citation_accuracy(k),
            "overlap_citation_accuracy": result.overlap_citation_accuracy(k),
            "over_retrieval_rate": result.over_retrieval_rate(k),
        }
        for k in result.ks
    }


def _mapped_failure_reasons(result: EvidenceAnswerEvalResult | None) -> tuple[RAGFailureReason, ...]:
    if result is None:
        return ()
    mapped: list[RAGFailureReason] = []
    for reason in result.failure_reason_counts():
        generic_reason = _FAILURE_REASON_MAP.get(reason)
        if generic_reason is not None and generic_reason not in mapped:
            mapped.append(generic_reason)
    return tuple(mapped)


__all__ = [
    "evidence_results_to_rag_report",
    "evidence_results_to_rag_scorecard",
]
