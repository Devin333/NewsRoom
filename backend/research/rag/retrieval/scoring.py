from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from framework.rag.retrieval import normalize_score_weights, weighted_component_score

from backend.research.document.models import PaperChunk
from backend.research.rag.adapters.paper_field_text import CORE_FIELD_NAMES, FIELD_NAMES, extract_field_texts
from backend.research.rag.retrieval.channels.sparse_lexical import FormulaSparseScores, formula_sparse_scores

_PARENT_SCORE_KEYS = ("child", "parent", "heading", "position")
_FIELD_SCORE_KEYS = CORE_FIELD_NAMES
_CHILD_FALLBACK_SCORE_KEYS = ("semantic", "field", "position", "graph")
_CHILD_FINAL_SCORE_KEYS = ("semantic", "field_embedding", "field_rerank", "position", "graph")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_RESULT_CONTEXT_KEYWORDS = (
    "sample quality",
    "result",
    "results",
    "experiment",
    "experiments",
    "evaluation",
    "ablation",
    "analysis",
    "conclusion",
    "benchmark",
    "quality",
    "accuracy",
    "fid",
    "inception score",
    "likelihood",
    "codelength",
    "bits/dim",
    "score",
)


@dataclass(frozen=True)
class _FieldScores:
    title_score: float
    abstract_score: float
    caption_score: float
    equation_score: float
    body_score: float
    field_score: float
    weights: dict[str, float]
    strategy: str = "lexical_overlap"


@dataclass(frozen=True)
class _FieldEmbeddingSummary:
    scores: dict[str, float]
    best_field: str = ""
    best_score: float = 0.0
    hits: tuple[dict[str, Any], ...] = ()


class ChildCandidateScorer:
    def __init__(self, policy: Any) -> None:
        self._policy = policy

    def score(
        self,
        chunk: PaperChunk,
        request: Any,
        route: Any,
        *,
        semantic_score: float,
        field_rerank_score: float | None = None,
    ) -> tuple[PaperChunk, float]:
        semantic = clamp_score(semantic_score)
        position_score = _child_position_score(
            self._policy,
            route.intent,
            chunk.section_index,
            request.current_section_index,
        )
        field_scores = _field_scores_for_chunk(
            request.question,
            chunk,
            self._policy.field_score_weights_for(route.intent),
            enabled=self._policy.field_scoring_enabled,
        )
        field_summary = _field_embedding_summary_from_metadata(chunk.metadata)
        field_rerank = clamp_score(field_rerank_score) if field_rerank_score is not None else 0.0
        graph_score = _child_graph_score(chunk)
        route_match_score = _route_match_score(route, chunk)
        claim_index_score = _metadata_float(chunk.metadata, "claim_index_score", 0.0)
        formula_scores = (
            formula_sparse_scores(request.question, chunk)
            if self._policy.formula_sparse_enabled and route.intent == "formula_query"
            else FormulaSparseScores()
        )
        if route.intent == "citation_query":
            graph_score = max(graph_score, claim_index_score)
        element_label_score = _element_label_match_score(request.question, route.intent, chunk)
        graph_score = max(graph_score, element_label_score, formula_scores.label_score)
        element_label_boost = clamp_score(
            element_label_score * max(0.0, self._policy.element_label_boosts.get(route.intent, 0.0))
        )
        citation_claim_score = max(
            _citation_claim_match_score(request.question, chunk),
            claim_index_score,
        )
        citation_claim_boost = (
            clamp_score(citation_claim_score * max(0.0, self._policy.citation_claim_boost))
            if route.intent == "citation_query"
            else 0.0
        )
        formula_sparse_boost = (
            clamp_score(formula_scores.sparse_score * max(0.0, self._policy.formula_sparse_boost))
            if route.intent == "formula_query"
            else 0.0
        )
        has_field_semantic = field_summary.best_score > 0.0 or field_rerank_score is not None
        if has_field_semantic:
            child_weights = self._policy.normalized_child_final_score_weights()
            final_score = weighted_component_score(
                {
                    "semantic": semantic,
                    "field_embedding": field_summary.best_score,
                    "field_rerank": field_rerank,
                    "position": position_score,
                    "graph": graph_score,
                },
                child_weights,
            )
            score_strategy = "semantic_field_embedding_rerank_fusion"
        else:
            child_weights = self._policy.normalized_child_score_weights()
            final_score = weighted_component_score(
                {
                    "semantic": semantic,
                    "field": field_scores.field_score,
                    "position": position_score,
                    "graph": graph_score,
                },
                child_weights,
            )
            score_strategy = "semantic_lexical_field_fallback"
        final_score = clamp_score(final_score + element_label_boost + citation_claim_boost + formula_sparse_boost)
        field_texts = extract_field_texts(chunk)
        best_matching_field = _best_matching_field(field_summary, field_scores)
        metadata = dict(chunk.metadata)
        metadata.update({
            "title_score": field_scores.title_score,
            "abstract_score": field_scores.abstract_score,
            "caption_score": field_scores.caption_score,
            "equation_score": field_scores.equation_score,
            "body_score": field_scores.body_score,
            "field_score": field_scores.field_score,
            "field_score_weights": dict(field_scores.weights),
            "field_score_strategy": field_scores.strategy,
            "title_embedding_score": field_summary.scores.get("title", 0.0),
            "abstract_embedding_score": field_summary.scores.get("abstract", 0.0),
            "caption_embedding_score": field_summary.scores.get("caption", 0.0),
            "equation_embedding_score": field_summary.scores.get("equation", 0.0),
            "body_embedding_score": field_summary.scores.get("body", 0.0),
            "field_embedding_score": round_score(field_summary.best_score),
            "best_embedding_field": field_summary.best_field,
            "field_embedding_hits": list(field_summary.hits),
            "field_embedding_strategy": "field_vector_search" if field_summary.best_score > 0.0 else "",
            "field_rerank_score": round_score(field_rerank) if field_rerank_score is not None else None,
            "field_rerank_strategy": "cross_encoder_structured_fields" if field_rerank_score is not None else "",
            "best_matching_field": best_matching_field,
            "element_label_score": round_score(element_label_score),
            "element_label_match": element_label_score > 0.0,
            "element_label_boost": round_score(element_label_boost),
            "citation_claim_score": round_score(citation_claim_score),
            "citation_claim_boost": round_score(citation_claim_boost),
            "formula_sparse_boost": round_score(formula_sparse_boost),
            "graph_score": round_score(graph_score),
            "route_match_score": round_score(route_match_score),
            "matched_recall_routes": list(_matched_recall_routes(route, chunk)),
            "child_score_strategy": score_strategy,
            "child_score_components": {
                "semantic": round_score(semantic),
                "deterministic_field": field_scores.field_score,
                "field_embedding": round_score(field_summary.best_score),
                "field_rerank": round_score(field_rerank) if field_rerank_score is not None else None,
                "position": round_score(position_score),
                "graph": round_score(graph_score),
                "route_match": round_score(route_match_score),
                "element_label": round_score(element_label_score),
                "element_label_boost": round_score(element_label_boost),
                "claim_index": round_score(claim_index_score),
                "citation_claim": round_score(citation_claim_score),
                "citation_claim_boost": round_score(citation_claim_boost),
                "formula_sparse": round_score(formula_scores.sparse_score),
                "formula_sparse_boost": round_score(formula_sparse_boost),
            },
            "child_semantic_score": round_score(semantic),
            "child_position_score": round_score(position_score),
            "child_final_score": round_score(final_score),
            "child_score_weights": dict(child_weights),
            "field_text_available_fields": field_texts.available_fields(),
            "field_text_sources": {
                field_name: field_texts.sources_for(field_name)
                for field_name in field_texts.available_fields()
            },
        })
        if self._policy.formula_sparse_enabled and route.intent == "formula_query":
            metadata.update(formula_scores.as_metadata())
            metadata["formula_sparse_hit"] = formula_scores.sparse_score > 0.0
        return chunk.model_copy(update={"metadata": metadata}), round_score(final_score)


def normalized_field_score_weights(weights: dict[str, float]) -> dict[str, float]:
    return _normalized_score_weights(weights, _FIELD_SCORE_KEYS, {
        "title": 0.25,
        "abstract": 0.15,
        "caption": 0.15,
        "equation": 0.15,
        "body": 0.30,
    })


def normalized_child_fallback_score_weights(weights: dict[str, float]) -> dict[str, float]:
    return _normalized_score_weights(weights, _CHILD_FALLBACK_SCORE_KEYS, {
        "semantic": 0.60,
        "field": 0.25,
        "position": 0.10,
        "graph": 0.05,
    })


def normalized_child_final_score_weights(weights: dict[str, float]) -> dict[str, float]:
    return _normalized_score_weights(weights, _CHILD_FINAL_SCORE_KEYS, {
        "semantic": 0.45,
        "field_embedding": 0.25,
        "field_rerank": 0.20,
        "position": 0.05,
        "graph": 0.05,
    })


def normalized_parent_score_weights(weights: dict[str, float]) -> dict[str, float]:
    return _normalized_score_weights(weights, _PARENT_SCORE_KEYS, {
        "child": 0.45,
        "parent": 0.35,
        "heading": 0.15,
        "position": 0.05,
    })


def claim_from_citation_question(question: str) -> str:
    match = re.search(r"supports\s+the\s+claim:\s*(.+)", str(question or ""), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return " ".join(match.group(1).split())


def clamp_score(value: float | None) -> float:
    if value is None:
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def round_score(value: float) -> float:
    return round(float(value), 6)


def _normalized_score_weights(
    weights: dict[str, float],
    keys: tuple[str, ...],
    fallback: dict[str, float],
) -> dict[str, float]:
    return normalize_score_weights(weights, keys=keys, fallback=fallback)


def _field_embedding_summary_from_metadata(metadata: dict[str, Any]) -> _FieldEmbeddingSummary:
    raw_scores = metadata.get("field_embedding_scores")
    score_source = raw_scores if isinstance(raw_scores, dict) else {}
    scores: dict[str, float] = {}
    for name in FIELD_NAMES:
        if name not in score_source and f"{name}_embedding_score" not in metadata:
            continue
        try:
            scores[name] = clamp_score(float(score_source.get(name, metadata.get(f"{name}_embedding_score", 0.0))))
        except (TypeError, ValueError):
            scores[name] = 0.0
    best_field, best_score = _best_score_item(scores)
    raw_hits = metadata.get("field_embedding_hits")
    hits = tuple(
        dict(item)
        for item in raw_hits
        if isinstance(raw_hits, list) and isinstance(item, dict)
    ) if isinstance(raw_hits, list) else ()
    return _FieldEmbeddingSummary(
        scores={name: round_score(score) for name, score in scores.items()},
        best_field=best_field,
        best_score=round_score(best_score),
        hits=hits,
    )


def _best_score_item(scores: dict[str, float]) -> tuple[str, float]:
    if not scores:
        return "", 0.0
    field_name, score = max(scores.items(), key=lambda item: (item[1], -FIELD_NAMES.index(item[0])))
    if score <= 0.0:
        return "", 0.0
    return field_name, clamp_score(score)


def _best_matching_field(field_summary: _FieldEmbeddingSummary, field_scores: _FieldScores) -> str:
    if field_summary.best_field:
        return field_summary.best_field
    deterministic = {
        "title": field_scores.title_score,
        "abstract": field_scores.abstract_score,
        "caption": field_scores.caption_score,
        "equation": field_scores.equation_score,
        "body": field_scores.body_score,
    }
    field_name, score = _best_score_item(deterministic)
    return field_name if score > 0.0 else ""


def _field_scores_for_chunk(
    query_text: str,
    chunk: PaperChunk,
    weights: dict[str, float],
    *,
    enabled: bool,
) -> _FieldScores:
    if not enabled:
        zero_weights = normalized_field_score_weights(weights)
        return _FieldScores(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, zero_weights, "disabled")

    normalized_weights = normalized_field_score_weights(weights)
    field_texts = extract_field_texts(chunk)
    title_score = _lexical_match_score(query_text, field_texts.title)
    abstract_score = _lexical_match_score(query_text, field_texts.abstract)
    caption_score = _lexical_match_score(query_text, field_texts.caption)
    equation_score = _lexical_match_score(query_text, field_texts.equation)
    body_score = _lexical_match_score(query_text, field_texts.body)
    field_score = weighted_component_score(
        {
            "title": title_score,
            "abstract": abstract_score,
            "caption": caption_score,
            "equation": equation_score,
            "body": body_score,
        },
        normalized_weights,
    )
    return _FieldScores(
        title_score=round_score(title_score),
        abstract_score=round_score(abstract_score),
        caption_score=round_score(caption_score),
        equation_score=round_score(equation_score),
        body_score=round_score(body_score),
        field_score=round_score(field_score),
        weights=normalized_weights,
    )


def _child_position_score(
    policy: Any,
    intent: str,
    section_index: int,
    current_section_index: int,
) -> float:
    alpha = policy.alpha_for(intent)
    if alpha <= 0.0:
        return 0.0
    raw = policy.position_weight(intent, section_index, current_section_index)
    return clamp_score(raw / alpha)


def _child_graph_score(chunk: PaperChunk) -> float:
    metadata = chunk.metadata
    if metadata.get("expansion_edge"):
        return 1.0
    if metadata.get("referenced_by_chunks"):
        return 1.0
    if metadata.get("nearby_context_chunk_id"):
        return 0.8
    if chunk.references:
        return 0.6
    if metadata.get("parent_table_chunk_id"):
        return 0.5
    return 0.0


def _route_match_score(route: Any, chunk: PaperChunk) -> float:
    matched_routes = _matched_recall_routes(route, chunk)
    if not matched_routes:
        return 0.0
    if route.intent == "numerical_result":
        if "table_chunks" in matched_routes:
            return 1.0
        if "result_paragraphs" in matched_routes or "conclusion_context" in matched_routes:
            return 0.8
    if route.intent == "comparison" and "table_chunks" in matched_routes:
        return 0.75
    return 1.0


def _matched_recall_routes(route: Any, chunk: PaperChunk) -> tuple[str, ...]:
    routes: list[str] = []
    route_set = set(route.recall_routes)
    if "figure_chunks" in route_set and _is_figure_chunk(chunk):
        routes.append("figure_chunks")
    if "table_chunks" in route_set and _is_table_chunk(chunk):
        routes.append("table_chunks")
    if "formula_chunks" in route_set and _is_formula_chunk(chunk):
        routes.append("formula_chunks")
    if "abstract_body" in route_set and chunk.chunk_type in {"abstract", "paragraph"}:
        routes.append("abstract_body")
    if "method_body" in route_set and _has_section_role(chunk, {"method"}):
        routes.append("method_body")
    if "result_paragraphs" in route_set and _has_result_context(chunk):
        routes.append("result_paragraphs")
    if "conclusion_context" in route_set and _has_section_role(chunk, {"analysis", "conclusion"}):
        routes.append("conclusion_context")
    if "comparison_paragraphs" in route_set and _has_section_role(chunk, {"related_work"}):
        routes.append("comparison_paragraphs")
    return tuple(routes)


def _element_label_match_score(query_text: str, intent: str, chunk: PaperChunk) -> float:
    labels = _element_query_labels(query_text, intent)
    if not labels:
        return 0.0
    chunk_labels = _chunk_reference_labels(chunk)
    if not chunk_labels:
        return 0.0
    return 1.0 if labels & chunk_labels else 0.0


def _element_query_labels(query_text: str, intent: str) -> set[str]:
    prefixes_by_intent: dict[str, tuple[str, ...]] = {
        "formula_query": ("equation", "formula", "eq"),
        "table_query": ("table", "tab"),
        "figure_query": ("figure", "fig"),
        "numerical_result": ("table", "tab", "figure", "fig"),
    }
    prefixes = prefixes_by_intent.get(intent, ())
    if not prefixes:
        return set()
    normalized = query_text.casefold()
    labels: set[str] = set()
    for prefix in prefixes:
        pattern = rf"\b{re.escape(prefix)}(?:\.|\s+)([a-z0-9][a-z0-9._-]*)"
        for match in re.finditer(pattern, normalized):
            labels.add(_normalize_element_label(match.group(1)))
    return {label for label in labels if label}


def _chunk_reference_labels(chunk: PaperChunk) -> set[str]:
    values: list[Any] = [
        chunk.metadata.get("reference_labels"),
        chunk.metadata.get("formula_reference_labels"),
        chunk.metadata.get("equation_number"),
        chunk.metadata.get("equation_id"),
        chunk.metadata.get("table_id"),
        chunk.metadata.get("figure_id"),
        chunk.figure_id,
    ]
    labels: set[str] = set()
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            text = str(item or "").casefold().strip()
            if not text:
                continue
            labels.add(_normalize_element_label(text))
            for prefix in ("eq_", "eq", "tbl_", "tbl", "fig_", "fig"):
                if text.startswith(prefix):
                    labels.add(_normalize_element_label(text[len(prefix):]))
    return {label for label in labels if label}


def _normalize_element_label(value: str) -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"^(?:equation|formula|eq|table|tab|figure|fig)\.?\s*", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _lexical_match_score(query_text: str, field_text: str) -> float:
    query_tokens = _query_tokens(query_text)
    if not query_tokens or not field_text.strip():
        return 0.0
    field_tokens = set(_query_tokens(field_text))
    if not field_tokens:
        return 0.0
    overlap = len(set(query_tokens) & field_tokens) / len(set(query_tokens))
    query_phrase = " ".join(query_tokens)
    field_phrase = " ".join(_query_tokens(field_text))
    if query_phrase and query_phrase in field_phrase:
        overlap = max(overlap, 0.95)
    return clamp_score(overlap)


def _citation_claim_match_score(question: str, chunk: PaperChunk) -> float:
    claim = claim_from_citation_question(question)
    if not claim:
        return 0.0
    return _lexical_match_score(claim, chunk.content)


def _query_tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(text)]


def _metadata_float(metadata: dict[str, Any], key: str, default: float) -> float:
    value = metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_table_chunk(chunk: PaperChunk) -> bool:
    return (
        chunk.chunk_type == "table"
        or chunk.has_table
        or bool(chunk.metadata.get("table_id"))
        or bool(chunk.metadata.get("parent_table_chunk_id"))
    )


def _is_figure_chunk(chunk: PaperChunk) -> bool:
    return chunk.chunk_type == "figure" or chunk.has_figure or bool(chunk.figure_id)


def _is_formula_chunk(chunk: PaperChunk) -> bool:
    return chunk.chunk_type == "formula" or chunk.has_formula or bool(chunk.formula_latex)


def _has_section_role(chunk: PaperChunk, roles: set[str]) -> bool:
    return bool({str(role).casefold() for role in chunk.section_role} & roles)


def _has_result_context(chunk: PaperChunk) -> bool:
    if chunk.chunk_type != "paragraph":
        return False
    if _has_section_role(chunk, {"experiment", "analysis", "conclusion"}):
        return True
    return _result_title_rank(chunk.section_title) < 100 or _result_title_rank(chunk.content[:240]) < 100


def _result_title_rank(text: str) -> int:
    normalized = text.casefold()
    for index, keyword in enumerate(_RESULT_CONTEXT_KEYWORDS):
        if keyword in normalized:
            return index
    return 100


__all__ = [
    "ChildCandidateScorer",
    "claim_from_citation_question",
    "clamp_score",
    "normalized_child_fallback_score_weights",
    "normalized_child_final_score_weights",
    "normalized_field_score_weights",
    "normalized_parent_score_weights",
    "round_score",
]
