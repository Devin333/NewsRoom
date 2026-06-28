from __future__ import annotations

from framework.rag.evaluation.answer_metrics import (
    AnswerMetricCase,
    AnswerMetricScore,
    evaluate_answer_case,
    score_answer_case,
)
from framework.rag.evaluation.failure_reason import RAGFailureReason, normalize_failure_reason
from framework.rag.evaluation.report import MetricValue, RAGEvaluationReport, RAGScorecard
from framework.rag.evaluation.retrieval_metrics import (
    RetrievalMetricCase,
    evaluate_retrieval_case,
    evidence_coverage,
    hit_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    reciprocal_rank,
    source_locator_coverage,
)

__all__ = [
    "AnswerMetricCase",
    "AnswerMetricScore",
    "MetricValue",
    "RAGEvaluationReport",
    "RAGFailureReason",
    "RAGScorecard",
    "RetrievalMetricCase",
    "evaluate_answer_case",
    "evaluate_retrieval_case",
    "evidence_coverage",
    "hit_at_k",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "reciprocal_rank",
    "source_locator_coverage",
    "score_answer_case",
    "normalize_failure_reason",
]
