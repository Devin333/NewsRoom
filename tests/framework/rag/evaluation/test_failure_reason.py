from __future__ import annotations

from framework.rag.evaluation import RAGFailureReason, normalize_failure_reason


def test_normalize_failure_reason_maps_legacy_answer_eval_reasons() -> None:
    assert normalize_failure_reason("missing_gold_in_llm_context") == RAGFailureReason.CONTEXT_MISSING_GOLD
    assert normalize_failure_reason("missing_gold_citation") == RAGFailureReason.CITATION_MISSING_SOURCE
    assert normalize_failure_reason("unexpected_abstention") == RAGFailureReason.ABSTENTION_EXPECTED
    assert normalize_failure_reason("abstention_mismatch") == RAGFailureReason.ABSTENTION_EXPECTED


def test_normalize_failure_reason_keeps_known_generic_reason() -> None:
    assert normalize_failure_reason(RAGFailureReason.LOW_RANK_GOLD) == RAGFailureReason.LOW_RANK_GOLD
    assert normalize_failure_reason("low_rank_gold") == RAGFailureReason.LOW_RANK_GOLD


def test_normalize_failure_reason_uses_grounding_default_for_unknown_values() -> None:
    assert normalize_failure_reason("provider_specific_failure") == RAGFailureReason.ANSWER_NOT_GROUNDED
