from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.research.rag.retrieval.paper_retriever import (
    NEWS_PAPER_RAG_POLICY_CONFIG_ENV,
    NEWS_PAPER_RAG_POLICY_ENV,
    PAPER_FORMULA_RAG_V1_POLICY,
    PAPER_HYBRID_RRF_RAG_V1_POLICY,
    build_retrieval_policy,
    build_retrieval_policy_from_config_file,
    build_retrieval_policy_from_env,
)
from backend.research.rag.retrieval.policy_config import (
    RetrievalPolicyConfigError,
    policy_config_hash,
    stable_policy_config,
)


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


def test_build_retrieval_policy_from_yaml_config_overrides_named_base(tmp_path: Path) -> None:
    config_path = tmp_path / "retrieval-policy.yaml"
    config_path.write_text(
        """
base_policy: paper_hybrid_rrf_rag_v1
overrides:
  name: enterprise_hybrid_v1
  overfetch_multiplier: 8
  sparse_search_limit_multiplier: 6
  field_reranking_intents:
    - formula_query
  field_intent_search_fields:
    formula_query:
      - equation
      - body
  parent_intent_budgets:
    table_query:
      - 2
      - 900
  element_label_boosts:
    formula_query: 0.4
""",
        encoding="utf-8",
    )

    policy = build_retrieval_policy_from_config_file(config_path)

    assert policy.name == "enterprise_hybrid_v1"
    assert policy.hybrid_rrf_enabled is True
    assert policy.sparse_lexical_enabled is True
    assert policy.overfetch_multiplier == 8
    assert policy.sparse_search_limit_multiplier == 6
    assert policy.field_reranking_intents == ("formula_query",)
    assert policy.field_intent_search_fields["formula_query"] == ("equation", "body")
    assert policy.parent_intent_budgets["table_query"] == (2, 900)
    assert policy.element_label_boosts["formula_query"] == pytest.approx(0.4)


def test_build_retrieval_policy_from_json_config_uses_env_base_when_file_omits_base(tmp_path: Path) -> None:
    config_path = tmp_path / "retrieval-policy.json"
    config_path.write_text(
        json.dumps({
            "overrides": {
                "name": "formula_from_file",
                "max_formula_context_chunks": 6,
            }
        }),
        encoding="utf-8",
    )

    policy = build_retrieval_policy_from_env({
        NEWS_PAPER_RAG_POLICY_ENV: PAPER_FORMULA_RAG_V1_POLICY,
        NEWS_PAPER_RAG_POLICY_CONFIG_ENV: str(config_path),
    })

    assert policy.name == "formula_from_file"
    assert policy.formula_sparse_enabled is True
    assert policy.max_formula_context_chunks == 6


def test_build_retrieval_policy_from_env_preserves_named_policy_without_config() -> None:
    policy = build_retrieval_policy_from_env({
        NEWS_PAPER_RAG_POLICY_ENV: PAPER_HYBRID_RRF_RAG_V1_POLICY,
    })

    assert policy.name == PAPER_HYBRID_RRF_RAG_V1_POLICY
    assert policy.hybrid_rrf_enabled is True


def test_retrieval_policy_config_rejects_unknown_override(tmp_path: Path) -> None:
    config_path = tmp_path / "retrieval-policy.yaml"
    config_path.write_text(
        """
overrides:
  made_up_weight: 0.4
""",
        encoding="utf-8",
    )

    with pytest.raises(RetrievalPolicyConfigError, match="made_up_weight"):
        build_retrieval_policy_from_config_file(config_path)


def test_retrieval_policy_config_rejects_invalid_root_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "retrieval-policy.yaml"
    config_path.write_text(
        """
- not
- an
- object
""",
        encoding="utf-8",
    )

    with pytest.raises(RetrievalPolicyConfigError, match="root must be an object"):
        build_retrieval_policy_from_config_file(config_path)


def test_policy_config_hash_changes_for_configured_override(tmp_path: Path) -> None:
    config_path = tmp_path / "retrieval-policy.yaml"
    config_path.write_text(
        """
base_policy: paper_hybrid_rrf_rag_v1
overrides:
  rrf_k: 61
""",
        encoding="utf-8",
    )
    base = build_retrieval_policy(PAPER_HYBRID_RRF_RAG_V1_POLICY)
    configured = build_retrieval_policy_from_config_file(config_path)

    assert configured.rrf_k == 61
    assert policy_config_hash(configured) != policy_config_hash(base)
