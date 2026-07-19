from __future__ import annotations

from typing import Any

from framework.rag.retrieval import expansion_metadata

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.services.tenant_visibility import chunk_visible_to_tenant, tenant_id_from_filters


class CrossRefContextExpander:
    name = "cross_ref"

    def __init__(self, chunk_store: ChunkStorePort) -> None:
        self._store = chunk_store

    def expand(
        self,
        children: list[PaperChunk],
        paper_id: str,
        *,
        filters: dict[str, Any] | None = None,
    ) -> list[PaperChunk]:
        tenant_id = tenant_id_from_filters(filters)
        children = [
            child
            for child in children
            if chunk_visible_to_tenant(child, tenant_id=tenant_id)
        ]
        children_by_id = {child.chunk_id: child for child in children}
        refs: list[tuple[str, str, str]] = []
        seen = {chunk.chunk_id for chunk in children}
        for child in children:
            for ref_id in child.references[:1]:
                if ref_id not in seen:
                    refs.append((ref_id, child.chunk_id, "chunk_reference"))
                    seen.add(ref_id)
            if child.metadata.get("page_visual"):
                for ref in child.metadata.get("related_visual_chunks", []):
                    if not isinstance(ref, dict):
                        continue
                    ref_id = str(ref.get("chunk_id") or "")
                    if ref_id and ref_id not in seen:
                        refs.append((ref_id, child.chunk_id, "page_visual_related_chunk"))
                        seen.add(ref_id)
            if _is_figure_chunk(child):
                for ref_id, reason, _edge in _figure_context_refs(child):
                    if ref_id and ref_id not in seen:
                        refs.append((ref_id, child.chunk_id, reason))
                        seen.add(ref_id)
            if _is_formula_chunk(child):
                for ref_id, reason, _edge in self._formula_context_refs_for_child(
                    child,
                    paper_id,
                    tenant_id=tenant_id,
                ):
                    if ref_id and ref_id not in seen:
                        refs.append((ref_id, child.chunk_id, reason))
                        seen.add(ref_id)

        result: list[PaperChunk] = []
        for ref_id, source_id, reason in refs:
            chunk = self._store.get_chunk(ref_id)
            if (
                chunk is not None
                and chunk.paper_id == paper_id
                and chunk_visible_to_tenant(chunk, tenant_id=tenant_id)
            ):
                result.append(_with_expansion_metadata(
                    chunk,
                    expanded_from_chunk_id=source_id,
                    reason=reason,
                    edge=(
                        "referenced_by_chunks"
                        if reason in {"formula_body_reference", "figure_body_reference"}
                        else reason
                    ),
                    rank=len(result) + 1,
                    source_chunk=children_by_id.get(source_id),
                ))
        return result

    def _formula_context_refs_for_child(
        self,
        child: PaperChunk,
        paper_id: str,
        *,
        tenant_id: str | None,
    ) -> list[tuple[str, str, str]]:
        refs = list(_formula_context_refs(child))
        formula_id = child.chunk_id
        for candidate in self._store.list_chunks(paper_id):
            if (
                candidate.chunk_id == formula_id
                or candidate.paper_id != paper_id
                or not chunk_visible_to_tenant(candidate, tenant_id=tenant_id)
            ):
                continue
            for ref_id, _reason, edge in _formula_reverse_context_refs(candidate):
                if ref_id == formula_id:
                    refs.append((candidate.chunk_id, "formula_reverse_context", edge))
        return _dedupe_ref_tuples(refs)


def _is_figure_chunk(chunk: PaperChunk) -> bool:
    return chunk.chunk_type == "figure" or chunk.has_figure or bool(chunk.figure_id)


def _is_formula_chunk(chunk: PaperChunk) -> bool:
    return chunk.chunk_type == "formula" or chunk.has_formula or bool(chunk.formula_latex)


def _figure_context_refs(chunk: PaperChunk) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    nearby_id = str(chunk.metadata.get("nearby_context_chunk_id") or "")
    if nearby_id:
        refs.append((nearby_id, "figure_nearby_context", "nearby_context_chunk_id"))
    for ref in chunk.metadata.get("referenced_by_chunks", []):
        if not isinstance(ref, dict):
            continue
        ref_id = str(ref.get("chunk_id") or "")
        if ref_id:
            refs.append((ref_id, "figure_body_reference", "referenced_by_chunks"))
    return refs


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


def _with_expansion_metadata(
    chunk: PaperChunk,
    *,
    expanded_from_chunk_id: str,
    reason: str,
    edge: str,
    rank: int,
    source_chunk: PaperChunk | None = None,
) -> PaperChunk:
    metadata = dict(chunk.metadata)
    _preserve_source_locator(metadata, source_chunk)
    metadata["graph_score"] = max(_metadata_float(metadata, "graph_score", 0.0), 1.0)
    metadata.update(expansion_metadata(
        expanded_from_id=expanded_from_chunk_id,
        reason=reason,
        edge=edge,
        rank=rank,
    ))
    return chunk.model_copy(update={"metadata": metadata})


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


__all__ = ["CrossRefContextExpander"]
