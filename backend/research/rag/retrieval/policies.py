from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

from framework.rag.core import intent_allowed, intent_budget, position_decay_score

from backend.research.rag.adapters.paper_field_text import FIELD_NAMES
from backend.research.rag.retrieval.policy_config import (
    RetrievalPolicyConfigError,
    load_policy_config_payload,
)
from backend.research.rag.retrieval.scoring import (
    normalized_child_fallback_score_weights,
    normalized_child_final_score_weights,
    normalized_field_score_weights,
    normalized_parent_score_weights,
)

# Default position weight per intent (0 = no position bias)
_DEFAULT_ALPHA: dict[str, float] = {
    "figure_query": 0.0,
    "table_query": 0.0,
    "formula_query": 0.0,
    "contribution": 0.05,
    "concept_method": 0.2,
    "numerical_result": 0.2,
    "comparison": 0.2,
}

DEFAULT_RETRIEVAL_POLICY = "default"
PAPER_VISUAL_RAG_TUNED_POLICY = "paper_visual_rag_tuned"
PAPER_BLIND_SEMANTIC_RAG_V1_POLICY = "paper_blind_semantic_rag_v1"
PAPER_HYBRID_RRF_RAG_V1_POLICY = "paper_hybrid_rrf_rag_v1"
PAPER_FORMULA_RAG_V1_POLICY = "paper_formula_rag_v1"
NEWS_PAPER_RAG_POLICY_ENV = "NEWS_PAPER_RAG_POLICY"
NEWS_PAPER_RAG_POLICY_CONFIG_ENV = "NEWS_PAPER_RAG_POLICY_CONFIG"
HIGH_VALUE_VISUAL_RESULT_INTENTS = ("figure_query", "table_query", "numerical_result", "comparison")
LIGHTWEIGHT_FIELD_RERANK_INTENTS = (*HIGH_VALUE_VISUAL_RESULT_INTENTS, "formula_query")


@dataclass(frozen=True)
class RetrievalPolicy:
    """Tunable retrieval parameters (position weighting + over-fetch + rerank filter)."""

    name: str = DEFAULT_RETRIEVAL_POLICY
    position_alpha: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_ALPHA))
    default_alpha: float = 0.2
    sigma: float = 3.0
    overfetch_multiplier: int = 3
    element_label_overfetch_multiplier: int = 25
    rerank_score_threshold: float = 0.3
    visual_fusion_text_weight: float = 0.65
    visual_fusion_visual_weight: float = 0.35
    max_table_context_chunks: int = 4
    table_result_context_search_limit: int = 12
    supplemental_table_result_limit: int = 2
    max_figure_context_chunks: int = 2
    max_formula_context_chunks: int = 2
    citation_claim_overfetch_multiplier: int = 15
    citation_claim_boost: float = 0.35
    table_context_rerank_score_threshold: float = 0.0
    max_parent_chunks: int = 3
    max_parent_tokens: int = 1800
    long_parent_token_threshold: int = 900
    parent_snippet_token_window: int = 450
    parent_rerank_score_threshold: float = 0.0
    parent_intent_budgets: dict[str, tuple[int, int]] = field(default_factory=lambda: {
        "table_query": (1, 700),
        "formula_query": (1, 700),
        "numerical_result": (2, 1000),
        "comparison": (2, 1000),
    })
    parent_default_score_weights: dict[str, float] = field(default_factory=lambda: {
        "child": 0.45,
        "parent": 0.35,
        "heading": 0.15,
        "position": 0.05,
    })
    parent_intent_score_weights: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "concept_method": {"child": 0.40, "parent": 0.30, "heading": 0.20, "position": 0.10},
        "contribution": {"child": 0.40, "parent": 0.30, "heading": 0.20, "position": 0.10},
        "numerical_result": {"child": 0.35, "parent": 0.40, "heading": 0.20, "position": 0.05},
        "comparison": {"child": 0.35, "parent": 0.40, "heading": 0.20, "position": 0.05},
        "table_query": {"child": 0.45, "parent": 0.25, "heading": 0.20, "position": 0.10},
        "formula_query": {"child": 0.45, "parent": 0.25, "heading": 0.20, "position": 0.10},
    })
    field_scoring_enabled: bool = True
    child_score_weights: dict[str, float] = field(default_factory=lambda: {
        "semantic": 0.60,
        "field": 0.25,
        "position": 0.10,
        "graph": 0.05,
    })
    child_final_score_weights: dict[str, float] = field(default_factory=lambda: {
        "semantic": 0.45,
        "field_embedding": 0.25,
        "field_rerank": 0.20,
        "position": 0.05,
        "graph": 0.05,
    })
    element_label_boosts: dict[str, float] = field(default_factory=dict)
    field_default_score_weights: dict[str, float] = field(default_factory=lambda: {
        "title": 0.25,
        "abstract": 0.15,
        "caption": 0.15,
        "equation": 0.15,
        "body": 0.30,
    })
    field_intent_score_weights: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "concept_method": {"title": 0.35, "abstract": 0.15, "caption": 0.10, "equation": 0.10, "body": 0.30},
        "citation_query": {"title": 0.05, "abstract": 0.20, "caption": 0.00, "equation": 0.00, "body": 0.75},
        "contribution": {"title": 0.30, "abstract": 0.40, "caption": 0.05, "equation": 0.05, "body": 0.20},
        "figure_query": {"title": 0.10, "abstract": 0.05, "caption": 0.60, "equation": 0.05, "body": 0.20},
        "table_query": {"title": 0.10, "abstract": 0.05, "caption": 0.40, "equation": 0.05, "body": 0.40},
        "formula_query": {"title": 0.10, "abstract": 0.05, "caption": 0.05, "equation": 0.60, "body": 0.20},
        "numerical_result": {"title": 0.20, "abstract": 0.05, "caption": 0.25, "equation": 0.05, "body": 0.45},
        "comparison": {"title": 0.20, "abstract": 0.05, "caption": 0.20, "equation": 0.05, "body": 0.50},
    })
    field_embedding_enabled: bool = True
    field_reranking_enabled: bool = True
    reranking_intents: tuple[str, ...] = ()
    field_reranking_intents: tuple[str, ...] = ()
    sparse_lexical_enabled: bool = False
    hybrid_rrf_enabled: bool = False
    multi_query_enabled: bool = False
    rrf_k: int = 60
    sparse_search_limit_multiplier: int = 3
    field_embedding_search_limit_multiplier: int = 2
    formula_sparse_enabled: bool = False
    formula_sparse_boost: float = 0.0
    field_default_search_fields: tuple[str, ...] = FIELD_NAMES
    field_intent_search_fields: dict[str, tuple[str, ...]] = field(default_factory=lambda: {
        "concept_method": ("title", "abstract", "body", "caption"),
        "citation_query": ("body", "abstract", "title"),
        "contribution": ("abstract", "title", "body"),
        "figure_query": ("caption", "visual_description", "body"),
        "table_query": ("caption", "table_rows", "table_columns", "body"),
        "formula_query": ("equation", "referenced_text", "body"),
        "numerical_result": ("caption", "table_rows", "table_columns", "body", "title"),
        "comparison": ("caption", "table_rows", "table_columns", "body", "title"),
    })

    def alpha_for(self, intent: str) -> float:
        return self.position_alpha.get(intent, self.default_alpha)

    def position_weight(self, intent: str, section_index: int, current: int) -> float:
        return position_decay_score(
            section_index=section_index,
            current_index=current,
            alpha=self.alpha_for(intent),
            sigma=self.sigma,
        )

    def parent_budget_for(self, intent: str) -> tuple[int, int]:
        return intent_budget(
            intent,
            intent_budgets=self.parent_intent_budgets,
            default_budget=(self.max_parent_chunks, self.max_parent_tokens),
            max_chunks=self.max_parent_chunks,
            max_tokens=self.max_parent_tokens,
        )

    def parent_score_weights_for(self, intent: str) -> dict[str, float]:
        weights = dict(self.parent_default_score_weights)
        weights.update(self.parent_intent_score_weights.get(intent, {}))
        return normalized_parent_score_weights(weights)

    def field_score_weights_for(self, intent: str) -> dict[str, float]:
        weights = dict(self.field_default_score_weights)
        weights.update(self.field_intent_score_weights.get(intent, {}))
        return normalized_field_score_weights(weights)

    def normalized_child_score_weights(self) -> dict[str, float]:
        return normalized_child_fallback_score_weights(self.child_score_weights)

    def normalized_child_final_score_weights(self) -> dict[str, float]:
        return normalized_child_final_score_weights(self.child_final_score_weights)

    def field_search_fields_for(self, intent: str) -> tuple[str, ...]:
        fields = self.field_intent_search_fields.get(intent, self.field_default_search_fields)
        seen: set[str] = set()
        out: list[str] = []
        for field_name in fields:
            normalized = str(field_name).casefold()
            if normalized in FIELD_NAMES and normalized not in seen:
                out.append(normalized)
                seen.add(normalized)
        return tuple(out) if out else tuple(FIELD_NAMES)

    def reranker_enabled_for(self, intent: str) -> bool:
        return intent_allowed(intent, self.reranking_intents)

    def field_reranker_enabled_for(self, intent: str) -> bool:
        return self.field_reranking_enabled and intent_allowed(intent, self.field_reranking_intents)


def build_retrieval_policy(policy_name: str | None = None) -> RetrievalPolicy:
    """Build a named retrieval policy without changing the default behavior."""

    normalized = (policy_name or DEFAULT_RETRIEVAL_POLICY).strip().casefold()
    if not normalized or normalized == DEFAULT_RETRIEVAL_POLICY:
        return RetrievalPolicy()
    if normalized not in {
        PAPER_VISUAL_RAG_TUNED_POLICY,
        PAPER_BLIND_SEMANTIC_RAG_V1_POLICY,
        PAPER_HYBRID_RRF_RAG_V1_POLICY,
        PAPER_FORMULA_RAG_V1_POLICY,
    }:
        raise ValueError(
            f"unknown retrieval policy {policy_name!r}; expected "
            f"{DEFAULT_RETRIEVAL_POLICY!r}, {PAPER_VISUAL_RAG_TUNED_POLICY!r}, "
            f"{PAPER_BLIND_SEMANTIC_RAG_V1_POLICY!r}, {PAPER_HYBRID_RRF_RAG_V1_POLICY!r}, "
            f"or {PAPER_FORMULA_RAG_V1_POLICY!r}"
        )

    defaults = RetrievalPolicy()
    field_intent_score_weights = {
        intent: dict(weights)
        for intent, weights in defaults.field_intent_score_weights.items()
    }
    field_intent_score_weights["figure_query"] = {
        "title": 0.05,
        "abstract": 0.00,
        "caption": 0.75,
        "equation": 0.00,
        "body": 0.20,
    }
    field_intent_score_weights["table_query"] = {
        "title": 0.05,
        "abstract": 0.00,
        "caption": 0.45,
        "equation": 0.00,
        "body": 0.50,
    }
    child_final_score_weights = dict(defaults.child_final_score_weights)
    if normalized in {PAPER_BLIND_SEMANTIC_RAG_V1_POLICY, PAPER_HYBRID_RRF_RAG_V1_POLICY, PAPER_FORMULA_RAG_V1_POLICY}:
        child_final_score_weights = {
            "semantic": 0.35,
            "field_embedding": 0.25,
            "field_rerank": 0.30,
            "position": 0.00,
            "graph": 0.10,
        }
    if normalized == PAPER_FORMULA_RAG_V1_POLICY:
        field_intent_score_weights["formula_query"] = {
            "title": 0.05,
            "abstract": 0.00,
            "caption": 0.00,
            "equation": 0.75,
            "body": 0.20,
        }
    return RetrievalPolicy(
        name=normalized,
        overfetch_multiplier=5,
        visual_fusion_text_weight=0.85,
        visual_fusion_visual_weight=0.15,
        reranking_intents=HIGH_VALUE_VISUAL_RESULT_INTENTS,
        field_reranking_intents=LIGHTWEIGHT_FIELD_RERANK_INTENTS,
        element_label_boosts={
            "formula_query": 0.18,
            "table_query": 0.18,
            "figure_query": 0.12,
            "numerical_result": 0.12,
        },
        child_score_weights={
            "semantic": 0.45,
            "field": 0.40,
            "position": 0.05,
            "graph": 0.10,
        },
        child_final_score_weights=child_final_score_weights,
        field_intent_score_weights=field_intent_score_weights,
        sparse_lexical_enabled=normalized in {PAPER_HYBRID_RRF_RAG_V1_POLICY, PAPER_FORMULA_RAG_V1_POLICY},
        hybrid_rrf_enabled=normalized in {PAPER_HYBRID_RRF_RAG_V1_POLICY, PAPER_FORMULA_RAG_V1_POLICY},
        multi_query_enabled=normalized in {PAPER_HYBRID_RRF_RAG_V1_POLICY, PAPER_FORMULA_RAG_V1_POLICY},
        rrf_k=60,
        sparse_search_limit_multiplier=5 if normalized == PAPER_FORMULA_RAG_V1_POLICY else (
            4 if normalized == PAPER_HYBRID_RRF_RAG_V1_POLICY else 3
        ),
        formula_sparse_enabled=normalized == PAPER_FORMULA_RAG_V1_POLICY,
        formula_sparse_boost=0.20 if normalized == PAPER_FORMULA_RAG_V1_POLICY else 0.0,
        max_formula_context_chunks=4 if normalized == PAPER_FORMULA_RAG_V1_POLICY else defaults.max_formula_context_chunks,
    )


def build_retrieval_policy_from_config_file(
    path: str | os.PathLike[str],
    *,
    base_policy_name: str | None = None,
) -> RetrievalPolicy:
    payload = load_policy_config_payload(Path(path))
    return build_retrieval_policy_from_config(payload, base_policy_name=base_policy_name)


def build_retrieval_policy_from_config(
    payload: Mapping[str, Any],
    *,
    base_policy_name: str | None = None,
) -> RetrievalPolicy:
    allowed_root_keys = {"base_policy", "overrides"}
    unknown_root_keys = sorted(set(payload) - allowed_root_keys)
    if unknown_root_keys:
        raise RetrievalPolicyConfigError(
            "unknown retrieval policy config key(s): " + ", ".join(unknown_root_keys)
        )
    base_name = payload.get("base_policy") or base_policy_name
    if base_name is not None and not isinstance(base_name, str):
        raise RetrievalPolicyConfigError("retrieval policy config base_policy must be a string")
    base_policy = build_retrieval_policy(base_name)
    overrides = payload.get("overrides") or {}
    if not isinstance(overrides, Mapping):
        raise RetrievalPolicyConfigError("retrieval policy config overrides must be an object")
    if not overrides:
        return base_policy
    field_names = {item.name for item in fields(RetrievalPolicy)}
    unknown_fields = sorted(str(key) for key in overrides if str(key) not in field_names)
    if unknown_fields:
        raise RetrievalPolicyConfigError(
            "unknown retrieval policy override field(s): " + ", ".join(unknown_fields)
        )
    values = {item.name: getattr(base_policy, item.name) for item in fields(RetrievalPolicy)}
    for key, value in overrides.items():
        field_name = str(key)
        values[field_name] = _coerce_policy_override(field_name, value, values[field_name])
    return RetrievalPolicy(**values)


def _coerce_policy_override(field_name: str, value: Any, current_value: Any) -> Any:
    if isinstance(current_value, bool):
        if not isinstance(value, bool):
            raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be a boolean")
        return value
    if isinstance(current_value, int) and not isinstance(current_value, bool):
        if not isinstance(value, int) or isinstance(value, bool):
            raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be an integer")
        return value
    if isinstance(current_value, float):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be numeric")
        return float(value)
    if isinstance(current_value, str):
        if not isinstance(value, str):
            raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be a string")
        return value
    if isinstance(current_value, tuple):
        return _coerce_tuple_field(field_name, value, current_value)
    if isinstance(current_value, dict):
        return _coerce_dict_field(field_name, value, current_value)
    return value


def _coerce_tuple_field(field_name: str, value: Any, current_value: tuple[Any, ...]) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be a list")
    sample = next((item for item in current_value if item is not None), "")
    return tuple(_coerce_scalar(f"{field_name}[]", item, sample) for item in value)


def _coerce_dict_field(field_name: str, value: Any, current_value: dict[Any, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be an object")
    sample_value = next(iter(current_value.values()), None)
    if sample_value is None:
        sample_value = {
            "element_label_boosts": 0.0,
        }.get(field_name)
    return {
        str(key): _coerce_dict_value(f"{field_name}.{key}", item, sample_value)
        for key, item in value.items()
    }


def _coerce_dict_value(field_name: str, value: Any, sample_value: Any) -> Any:
    if isinstance(sample_value, tuple):
        return _coerce_tuple_field(field_name, value, sample_value)
    if isinstance(sample_value, Mapping):
        if not isinstance(value, Mapping):
            raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be an object")
        inner_sample = next(iter(sample_value.values()), 0.0)
        return {
            str(key): _coerce_scalar(f"{field_name}.{key}", item, inner_sample)
            for key, item in value.items()
        }
    if sample_value is not None:
        return _coerce_scalar(field_name, value, sample_value)
    return value


def _coerce_scalar(field_name: str, value: Any, sample_value: Any) -> Any:
    if isinstance(sample_value, bool):
        if not isinstance(value, bool):
            raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be a boolean")
        return value
    if isinstance(sample_value, int) and not isinstance(sample_value, bool):
        if not isinstance(value, int) or isinstance(value, bool):
            raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be an integer")
        return value
    if isinstance(sample_value, float):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be numeric")
        return float(value)
    if not isinstance(value, str):
        raise RetrievalPolicyConfigError(f"retrieval policy field {field_name!r} must be a string")
    return value


def retrieval_policy_enables_lightweight_reranker(policy_name: str | None) -> bool:
    return build_retrieval_policy(policy_name).name in {
        PAPER_BLIND_SEMANTIC_RAG_V1_POLICY,
        PAPER_HYBRID_RRF_RAG_V1_POLICY,
        PAPER_FORMULA_RAG_V1_POLICY,
    }


def build_retrieval_policy_from_env(
    env: Mapping[str, str] | None = None,
) -> RetrievalPolicy:
    values = env if env is not None else os.environ
    config_path = values.get(NEWS_PAPER_RAG_POLICY_CONFIG_ENV)
    if config_path:
        return build_retrieval_policy_from_config_file(
            config_path,
            base_policy_name=values.get(NEWS_PAPER_RAG_POLICY_ENV),
        )
    return build_retrieval_policy(values.get(NEWS_PAPER_RAG_POLICY_ENV))


__all__ = [
    "DEFAULT_RETRIEVAL_POLICY",
    "HIGH_VALUE_VISUAL_RESULT_INTENTS",
    "LIGHTWEIGHT_FIELD_RERANK_INTENTS",
    "NEWS_PAPER_RAG_POLICY_CONFIG_ENV",
    "NEWS_PAPER_RAG_POLICY_ENV",
    "PAPER_BLIND_SEMANTIC_RAG_V1_POLICY",
    "PAPER_FORMULA_RAG_V1_POLICY",
    "PAPER_HYBRID_RRF_RAG_V1_POLICY",
    "PAPER_VISUAL_RAG_TUNED_POLICY",
    "RetrievalPolicy",
    "build_retrieval_policy",
    "build_retrieval_policy_from_config",
    "build_retrieval_policy_from_config_file",
    "build_retrieval_policy_from_env",
    "retrieval_policy_enables_lightweight_reranker",
]
