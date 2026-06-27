from __future__ import annotations

from enum import StrEnum


class RAGFailureReason(StrEnum):
    MISSING_GOLD_IN_RETRIEVAL = "missing_gold_in_retrieval"
    LOW_RANK_GOLD = "low_rank_gold"
    CONTEXT_MISSING_GOLD = "context_missing_gold"
    CITATION_MISSING_SOURCE = "citation_missing_source"
    FACT_MATCH_LOW = "fact_match_low"
    ANSWER_NOT_GROUNDED = "answer_not_grounded"
    ABSTENTION_EXPECTED = "abstention_expected"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RERANKER_UNAVAILABLE = "reranker_unavailable"


__all__ = ["RAGFailureReason"]
