from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk


class FormulaContextExpander:
    name = "formula_context"

    def __init__(self, policy: Any) -> None:
        self._policy = policy

    def refs_for(self, chunk: PaperChunk, request: Any, route: Any) -> list[tuple[str, str, str]]:
        if self._policy.max_formula_context_chunks <= 0:
            return []
        if (
            _is_formula_chunk(chunk)
            and (
                should_expand_formula_context(route.intent, request.question)
                or self._policy.formula_sparse_enabled
            )
        ):
            return _formula_context_refs(chunk)[: self._policy.max_formula_context_chunks]
        if (
            route.intent == "formula_query"
            and (
                should_expand_formula_context(route.intent, request.question)
                or self._policy.formula_sparse_enabled
            )
        ):
            return _formula_reverse_context_refs(chunk)[: self._policy.max_formula_context_chunks]
        return []


def should_expand_formula_context(intent: str, question: str) -> bool:
    if intent != "formula_query":
        return False
    lowered = str(question or "").casefold()
    return any(token in lowered for token in (
        "surrounding text",
        "explained",
        "explain",
        "meaning",
    ))


def _is_formula_chunk(chunk: PaperChunk) -> bool:
    return chunk.chunk_type == "formula" or chunk.has_formula or bool(chunk.formula_latex)


def _formula_context_refs(chunk: PaperChunk) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    nearby_id = str(chunk.metadata.get("nearby_context_chunk_id") or "")
    if nearby_id:
        refs.append((nearby_id, "formula_nearby_context", "nearby_context_chunk_id"))
    for key in ("explained_by_chunks", "formula_explanation_chunks", "formula_context_chunk_ids"):
        for ref_id in _metadata_chunk_refs(chunk.metadata.get(key)):
            refs.append((ref_id, "formula_explained_by", key))
    for ref_id in _metadata_chunk_refs(chunk.metadata.get("referenced_by_chunks")):
        refs.append((ref_id, "formula_body_reference", "referenced_by_chunks"))
    parent_id = chunk.parent_chunk_id or ""
    if parent_id:
        refs.append((parent_id, "formula_parent_context", "parent_chunk_id"))
    return _dedupe_ref_tuples(refs)


def _formula_reverse_context_refs(chunk: PaperChunk) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    metadata = chunk.metadata
    for key in (
        "formula_chunk_id",
        "linked_formula_chunk_id",
        "explains_formula_chunk_id",
        "formula_context_for_chunk_id",
        "referenced_formula_chunk_ids",
        "formula_chunk_ids",
    ):
        for ref_id in _metadata_chunk_refs(metadata.get(key)):
            refs.append((ref_id, "formula_reverse_reference", key))
    for ref_id in chunk.references:
        refs.append((str(ref_id), "formula_explicit_reference", "chunk.references"))
    return _dedupe_ref_tuples(refs)


def _metadata_chunk_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        for key in ("chunk_id", "id", "ref_id", "target_chunk_id"):
            ref_id = str(value.get(key) or "").strip()
            if ref_id:
                return [ref_id]
        return []
    if isinstance(value, (list, tuple, set)):
        refs: list[str] = []
        for item in value:
            refs.extend(_metadata_chunk_refs(item))
        return refs
    text = str(value or "").strip()
    return [text] if text else []


def _dedupe_ref_tuples(refs: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for ref_id, reason, edge in refs:
        normalized = str(ref_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append((normalized, reason, edge))
    return out


__all__ = ["FormulaContextExpander", "should_expand_formula_context"]
