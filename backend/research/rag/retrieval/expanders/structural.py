from __future__ import annotations

from typing import Any

from framework.rag.retrieval import expansion_metadata

from backend.research.document.models import PaperChunk
from backend.research.ports.chunk_store import ChunkStorePort
from backend.research.rag.retrieval.expanders.formula_context import FormulaContextExpander
from backend.research.rag.retrieval.expanders.table_context import should_expand_result_context
from backend.research.rag.retrieval.filtering import chunk_visible_for_request, filter_chunks_for_request


class StructuralContextExpander:
    name = "structural"

    def __init__(self, chunk_store: ChunkStorePort, policy: Any) -> None:
        self._store = chunk_store
        self._policy = policy
        self._formula_context = FormulaContextExpander(policy)

    def expand(self, chunks: list[PaperChunk], request: Any, route: Any) -> list[PaperChunk]:
        chunks = filter_chunks_for_request(chunks, request)
        if not chunks:
            return chunks
        out: list[PaperChunk] = []
        seen: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_id not in seen:
                out.append(chunk)
                seen.add(chunk.chunk_id)
            added = 0
            for ref_id, reason, edge in self._structural_context_refs(chunk, request, route):
                if ref_id in seen:
                    continue
                ref = self._store.get_chunk(ref_id)
                if (
                    ref is None
                    or ref.paper_id != request.paper_id
                    or not chunk_visible_for_request(ref, request)
                ):
                    continue
                seen.add(ref.chunk_id)
                added += 1
                out.append(_with_expansion_metadata(
                    ref,
                    expanded_from_chunk_id=chunk.chunk_id,
                    reason=reason,
                    edge=edge,
                    rank=added,
                    source_chunk=chunk,
                ))
        return out

    def _structural_context_refs(
        self,
        chunk: PaperChunk,
        request: Any,
        route: Any,
    ) -> list[tuple[str, str, str]]:
        if route.intent == "figure_query" and self._policy.max_figure_context_chunks > 0 and _is_figure_chunk(chunk):
            return _figure_context_refs(chunk)[: self._policy.max_figure_context_chunks]
        if _is_table_chunk(chunk) and should_expand_result_context(route.intent, request.question):
            return _table_context_refs(chunk)[: self._policy.max_table_context_chunks]
        formula_refs = self._formula_context.refs_for(chunk, request, route)
        if formula_refs:
            return formula_refs
        return []


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


def _table_context_refs(chunk: PaperChunk) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    nearby_id = str(chunk.metadata.get("nearby_context_chunk_id") or "")
    if nearby_id:
        refs.append((nearby_id, "table_nearby_context", "nearby_context_chunk_id"))
    for ref in chunk.metadata.get("referenced_by_chunks", []):
        if not isinstance(ref, dict):
            continue
        ref_id = str(ref.get("chunk_id") or "")
        if ref_id:
            refs.append((ref_id, "table_body_reference", "referenced_by_chunks"))
    parent_table_id = str(chunk.metadata.get("parent_table_chunk_id") or "")
    if parent_table_id:
        refs.append((parent_table_id, "table_row_group_parent", "parent_table_chunk_id"))
    parent_id = chunk.parent_chunk_id or ""
    if parent_id:
        refs.append((parent_id, "table_parent_context", "parent_chunk_id"))
    return refs


def _is_table_chunk(chunk: PaperChunk) -> bool:
    return (
        chunk.chunk_type == "table"
        or chunk.has_table
        or bool(chunk.metadata.get("table_id"))
        or bool(chunk.metadata.get("parent_table_chunk_id"))
    )


def _is_figure_chunk(chunk: PaperChunk) -> bool:
    return chunk.chunk_type == "figure" or chunk.has_figure or bool(chunk.figure_id)


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


__all__ = ["StructuralContextExpander"]
