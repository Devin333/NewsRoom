from __future__ import annotations

from business.research.rag.retrieval.paper_retriever import (
    PAPER_HYBRID_RRF_RAG_V1_POLICY,
    build_retrieval_policy,
)
from business.research.rag.retrieval.policy_config import policy_config_hash, stable_policy_config


def test_policy_config_hash_is_stable_for_same_named_policy() -> None:
    left = build_retrieval_policy(PAPER_HYBRID_RRF_RAG_V1_POLICY)
    right = build_retrieval_policy(PAPER_HYBRID_RRF_RAG_V1_POLICY)

    assert stable_policy_config(left) == stable_policy_config(right)
    assert policy_config_hash(left) == policy_config_hash(right)
    assert len(policy_config_hash(left)) == 16


def test_policy_config_hash_changes_when_tuned_value_changes() -> None:
    base = build_retrieval_policy(PAPER_HYBRID_RRF_RAG_V1_POLICY)
    tuned = build_retrieval_policy(PAPER_HYBRID_RRF_RAG_V1_POLICY)
    tuned = tuned.__class__(**{**stable_policy_config(tuned), "rrf_k": tuned.rrf_k + 1})

    assert policy_config_hash(base) != policy_config_hash(tuned)
