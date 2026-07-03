from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from framework.rag.retrieval import RerankScoreSet, rerank_sort_key, weighted_component_score

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort

if TYPE_CHECKING:
    from business.research.ports.reranker import RerankerPort


@dataclass(frozen=True)
class _ParentCandidate:
    parent: PaperChunk
    child: PaperChunk
    child_rank: int
    child_relevance_score: float = 0.0
    parent_relevance_score: float = 0.0
    section_heading_score: float = 0.0
    position_score: float = 0.0
    final_score: float = 0.0
    score_strategy: str = "deterministic"
    score_weights: dict[str, float] = field(default_factory=dict)
    rerank_score: float | None = None
    rerank_query: str = ""


class ParentContextExpander:
    name = "parent"

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        policy: Any,
        *,
        reranker: "RerankerPort | None" = None,
    ) -> None:
        self._store = chunk_store
        self._policy = policy
        self._reranker = reranker

    def expand(
        self,
        children: list[PaperChunk],
        request: Any,
        route: Any,
    ) -> tuple[list[PaperChunk], dict[str, Any]]:
        candidates = self._parent_candidates(children, request.paper_id)
        max_chunks, max_tokens = self._policy.parent_budget_for(route.intent)
        score_weights = self._policy.parent_score_weights_for(route.intent)
        metrics: dict[str, Any] = {
            "parent_budget_chunks": max_chunks,
            "parent_budget_tokens": max_tokens,
            "parent_tokens_used": 0,
            "parent_snippets_returned": 0,
            "parent_budget_exhausted": False,
            "parent_scoring_enabled": bool(candidates),
            "parent_score_weights": score_weights,
            "parent_candidates_scored": 0,
            "parent_score_top": None,
            "parent_score_min": None,
        }
        if not candidates:
            return list(children), metrics
        if max_chunks <= 0 or max_tokens <= 0:
            metrics["parent_budget_exhausted"] = True
            return [], metrics

        ranked = self._rank_parent_candidates(candidates, request, route, score_weights)
        if ranked:
            final_scores = [candidate.final_score for candidate in ranked]
            metrics.update({
                "parent_candidates_scored": len(ranked),
                "parent_score_top": round(max(final_scores), 6),
                "parent_score_min": round(min(final_scores), 6),
            })

        parents: list[PaperChunk] = []
        tokens_used = 0
        snippets = 0
        exhausted = False

        for candidate in ranked:
            if len(parents) >= max_chunks:
                exhausted = True
                break
            remaining_tokens = max_tokens - tokens_used
            if remaining_tokens <= 0:
                exhausted = True
                break
            chunk = self._parent_context_chunk(
                candidate,
                rank=len(parents) + 1,
                token_window=min(self._policy.parent_snippet_token_window, remaining_tokens),
            )
            token_estimate = _estimate_tokens(chunk.content)
            if token_estimate > remaining_tokens:
                chunk = self._parent_context_chunk(
                    candidate,
                    rank=len(parents) + 1,
                    token_window=remaining_tokens,
                    force_snippet=True,
                )
                token_estimate = _estimate_tokens(chunk.content)
            if token_estimate <= 0:
                continue
            if token_estimate > remaining_tokens:
                exhausted = True
                continue
            parents.append(chunk)
            tokens_used += token_estimate
            if chunk.metadata.get("parent_snippet"):
                snippets += 1

        metrics.update({
            "parent_tokens_used": tokens_used,
            "parent_snippets_returned": snippets,
            "parent_budget_exhausted": exhausted,
        })
        return parents, metrics

    def _parent_candidates(self, children: list[PaperChunk], paper_id: str) -> list[_ParentCandidate]:
        seen: set[str] = set()
        candidates: list[_ParentCandidate] = []
        for child_rank, child in enumerate(children):
            parent_id = child.parent_chunk_id
            if not parent_id or parent_id in seen:
                continue
            parent = self._store.get_chunk(parent_id)
            if parent is None or parent.paper_id != paper_id:
                continue
            seen.add(parent.chunk_id)
            candidates.append(_ParentCandidate(
                parent=parent,
                child=child,
                child_rank=child_rank,
                child_relevance_score=_child_relevance_score(child, child_rank),
            ))
        return candidates

    def _rank_parent_candidates(
        self,
        candidates: list[_ParentCandidate],
        request: Any,
        route: Any,
        score_weights: dict[str, float],
    ) -> list[_ParentCandidate]:
        if not candidates:
            return []
        rerank_query = ""
        rerank_scores: list[float] | None = None
        if self._reranker is not None and self._policy.reranker_enabled_for(route.intent):
            rerank_query = _parent_context_rerank_query(request, route, candidates)
            passages = [_parent_context_rerank_passage(candidate) for candidate in candidates]
            try:
                scores = self._reranker.score(rerank_query, passages)
                normalized_scores = RerankScoreSet.from_raw(scores, expected_count=len(candidates))
                if normalized_scores is None:
                    logging.getLogger(__name__).warning(
                        "parent context reranker returned %s scores for %s candidates",
                        len(scores),
                        len(candidates),
                    )
                else:
                    rerank_scores = list(normalized_scores.scores)
            except Exception:
                logging.getLogger(__name__).warning("parent context reranker failed", exc_info=True)

        ranked = [
            self._score_parent_candidate(
                candidate,
                request,
                route,
                score_weights,
                rerank_score=rerank_scores[index] if rerank_scores is not None else None,
                rerank_query=rerank_query if rerank_scores is not None else "",
            )
            for index, candidate in enumerate(candidates)
        ]
        ranked.sort(key=lambda candidate: (-candidate.final_score, candidate.child_rank, candidate.parent.chunk_id))
        threshold = self._policy.parent_rerank_score_threshold
        if threshold <= 0.0 or rerank_scores is None:
            return ranked
        filtered = [
            candidate for candidate in ranked
            if candidate.rerank_score is not None and candidate.rerank_score >= threshold
        ]
        return filtered or ranked[:1]

    def _score_parent_candidate(
        self,
        candidate: _ParentCandidate,
        request: Any,
        route: Any,
        score_weights: dict[str, float],
        *,
        rerank_score: float | None,
        rerank_query: str,
    ) -> _ParentCandidate:
        heading_score = _parent_section_heading_score(route.intent, candidate.parent)
        position_score = _parent_position_score(self._policy, route.intent, candidate.parent, request)
        parent_relevance_score = (
            _clamp_score(rerank_score)
            if rerank_score is not None
            else _deterministic_parent_relevance(candidate.child_relevance_score, heading_score)
        )
        final_score = weighted_component_score(
            {
                "child": candidate.child_relevance_score,
                "parent": parent_relevance_score,
                "heading": heading_score,
                "position": position_score,
            },
            score_weights,
        )
        return _ParentCandidate(
            parent=candidate.parent,
            child=candidate.child,
            child_rank=candidate.child_rank,
            child_relevance_score=_round_score(candidate.child_relevance_score),
            parent_relevance_score=_round_score(parent_relevance_score),
            section_heading_score=_round_score(heading_score),
            position_score=_round_score(position_score),
            final_score=_round_score(final_score),
            score_strategy="cross_encoder" if rerank_score is not None else "deterministic",
            score_weights=score_weights,
            rerank_score=rerank_score,
            rerank_query=rerank_query,
        )

    def _parent_context_chunk(
        self,
        candidate: _ParentCandidate,
        *,
        rank: int,
        token_window: int,
        force_snippet: bool = False,
    ) -> PaperChunk:
        parent = candidate.parent
        original_token_estimate = _estimate_tokens(parent.content)
        should_snippet = (
            force_snippet
            or original_token_estimate > self._policy.long_parent_token_threshold
        )
        content = parent.content
        snippet_metadata: dict[str, Any] = {
            "parent_snippet": False,
            "parent_snippet_strategy": "full_parent",
        }
        if should_snippet:
            snippet, start, end, strategy = _child_anchor_snippet(
                parent.content,
                candidate.child.content,
                max(1, token_window),
            )
            content = snippet
            snippet_metadata = {
                "parent_snippet": True,
                "parent_snippet_strategy": strategy,
                "parent_snippet_char_start": start,
                "parent_snippet_char_end": end,
            }

        metadata = dict(parent.metadata)
        _preserve_source_locator(metadata, candidate.child)
        metadata.update({
            "expanded_from_chunk_id": candidate.child.chunk_id,
            "expansion_reason": "child_parent_context",
            "expansion_edge": "parent_chunk_id",
            "expansion_rank": rank,
            "parent_expansion_reason": "child_parent_context",
            "parent_anchor_child_id": candidate.child.chunk_id,
            "parent_rank": rank,
            "parent_token_estimate": _estimate_tokens(content),
            "parent_original_token_estimate": original_token_estimate,
            "source_parent_chunk_id": parent.chunk_id,
            "parent_child_relevance_score": candidate.child_relevance_score,
            "parent_relevance_score": candidate.parent_relevance_score,
            "parent_section_heading_score": candidate.section_heading_score,
            "parent_position_score": candidate.position_score,
            "parent_final_score": candidate.final_score,
            "parent_score_strategy": candidate.score_strategy,
            "parent_score_weights": dict(candidate.score_weights),
        })
        metadata.update(snippet_metadata)
        if candidate.rerank_score is not None:
            metadata.update({
                "parent_rerank_score": round(candidate.rerank_score, 6),
                "parent_rerank_strategy": "cross_encoder",
                "parent_rerank_query": candidate.rerank_query[:400],
            })
        return parent.model_copy(update={"content": content, "metadata": metadata})


def _child_relevance_score(child: PaperChunk, child_rank: int) -> float:
    fallback = 1.0 / max(1, child_rank + 1)
    score = _metadata_float(
        child.metadata,
        "child_final_score",
        _metadata_float(child.metadata, "fused_score", _metadata_float(child.metadata, "text_score", fallback)),
    )
    return _round_score(_clamp_score(score))


def _deterministic_parent_relevance(child_relevance_score: float, heading_score: float) -> float:
    return _clamp_score((child_relevance_score * 0.65) + (heading_score * 0.35))


def _parent_position_score(policy: Any, intent: str, parent: PaperChunk, request: Any) -> float:
    alpha = policy.alpha_for(intent)
    if alpha <= 0.0:
        return 0.0
    raw = policy.position_weight(intent, parent.section_index, request.current_section_index)
    return _clamp_score(raw / alpha)


def _parent_section_heading_score(intent: str, parent: PaperChunk) -> float:
    role_keywords: dict[str, tuple[set[str], tuple[str, ...]]] = {
        "concept_method": (
            {"method"},
            ("method", "approach", "architecture", "model", "algorithm", "design", "encoder", "decoder"),
        ),
        "contribution": (
            {"background", "method"},
            ("abstract", "introduction", "contribution", "novel", "propose", "overview", "summary"),
        ),
        "numerical_result": (
            {"experiment", "analysis", "conclusion"},
            (
                "result", "results", "experiment", "experiments", "evaluation", "benchmark",
                "ablation", "analysis", "conclusion", "performance", "accuracy", "score",
            ),
        ),
        "comparison": (
            {"related_work", "experiment", "analysis"},
            ("comparison", "compare", "baseline", "versus", "related work", "prior work", "result", "results"),
        ),
        "table_query": (
            {"experiment", "analysis"},
            ("table", "result", "results", "experiment", "evaluation", "benchmark", "ablation"),
        ),
        "formula_query": (
            {"method"},
            ("formula", "equation", "method", "model", "objective", "loss", "derivation"),
        ),
    }
    roles, keywords = role_keywords.get(intent, (set(), ()))
    normalized_roles = {str(role).casefold() for role in parent.section_role}
    title = parent.section_title.casefold()
    score = 0.0
    if normalized_roles & roles:
        score = max(score, 0.75)
    if any(keyword in title for keyword in keywords):
        score = max(score, 1.0)
    elif any(keyword.replace("_", " ") in title for keyword in roles):
        score = max(score, 0.85)
    return score


def _estimate_tokens(text: str) -> int:
    compact = " ".join(text.split())
    if not compact:
        return 0
    return max(1, math.ceil(len(compact) / 4))


def _parent_context_rerank_query(
    request: Any,
    route: Any,
    candidates: list[_ParentCandidate],
) -> str:
    anchors = []
    seen: set[str] = set()
    for candidate in candidates[:5]:
        if candidate.child.chunk_id in seen:
            continue
        seen.add(candidate.child.chunk_id)
        anchors.append(f"- {candidate.child.content[:240]}")
    return "\n".join([
        request.question.strip(),
        f"Intent: {route.intent}",
        "Matched child evidence:",
        *anchors,
    ]).strip()


def _parent_context_rerank_passage(candidate: _ParentCandidate) -> str:
    return "\n".join([
        f"Parent section: {candidate.parent.section_title}",
        f"Child anchor: {candidate.child.content[:500]}",
        f"Parent context: {candidate.parent.content[:1500]}",
    ]).strip()


def _child_anchor_snippet(parent_text: str, child_text: str, token_window: int) -> tuple[str, int, int, str]:
    char_window = max(80, token_window * 4)
    if len(parent_text) <= char_window:
        return parent_text.strip(), 0, len(parent_text), "full_parent_under_window"

    anchor_start = _find_child_anchor(parent_text, child_text)
    if anchor_start < 0:
        end = min(len(parent_text), char_window)
        return parent_text[:end].strip(), 0, end, "leading_window"

    child_len = min(max(len(child_text.strip()), 1), char_window // 2)
    start = max(0, anchor_start - (char_window - child_len) // 2)
    end = min(len(parent_text), start + char_window)
    if end - start < char_window:
        start = max(0, end - char_window)
    return parent_text[start:end].strip(), start, end, "child_anchor_window"


def _find_child_anchor(parent_text: str, child_text: str) -> int:
    parent_lower = parent_text.casefold()
    normalized_child = " ".join(child_text.split())
    candidates = [
        child_text.strip(),
        normalized_child,
        normalized_child[:300],
        normalized_child[:160],
    ]
    for candidate in candidates:
        if len(candidate) < 24:
            continue
        index = parent_lower.find(candidate.casefold())
        if index >= 0:
            return index
    return -1


def _preserve_source_locator(metadata: dict[str, Any], source_chunk: PaperChunk | None) -> None:
    if source_chunk is None:
        return
    if metadata.get("source_locator"):
        return
    source_locator = str(
        source_chunk.metadata.get("source_locator")
        or source_chunk.metadata.get("source_ref")
        or ""
    )
    if not source_locator:
        return
    metadata["source_locator"] = source_locator
    metadata["source_locator_inherited"] = True
    metadata["source_locator_origin_chunk_id"] = source_chunk.chunk_id
    source_locators = source_chunk.metadata.get("source_locators")
    if source_locators and not metadata.get("source_locators"):
        metadata["source_locators"] = source_locators


def _metadata_float(metadata: dict[str, Any], key: str, default: float) -> float:
    value = metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_score(value: float | None) -> float:
    if value is None:
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _round_score(value: float) -> float:
    return round(float(value), 6)


__all__ = ["ParentContextExpander"]
