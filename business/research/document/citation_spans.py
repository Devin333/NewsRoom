from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from framework.rag.context import (
    CONTENT_SPAN_UNIT,
    build_main_overlap_span_metadata,
    remap_span_origin_ids as remap_kernel_span_origin_ids,
    resolve_source_span,
)


def build_paragraph_span_metadata(
    *,
    content: str,
    overlap_text: str = "",
    overlap_origin_chunk_id: str = "",
    overlap_origin_source_locator: str = "",
    overlap_type: str = "previous_paragraph_trailing_sentence",
) -> dict[str, Any]:
    return build_main_overlap_span_metadata(
        content=content,
        overlap_text=overlap_text,
        overlap_origin_chunk_id=overlap_origin_chunk_id,
        overlap_origin_source_locator=overlap_origin_source_locator,
        overlap_type=overlap_type,
    )


def remap_span_origin_ids(metadata: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
    return remap_kernel_span_origin_ids(metadata, id_map)


def resolve_citation_span(
    chunk: PaperChunk,
    *,
    span_start: int | None = None,
    span_end: int | None = None,
    snippet: str | None = None,
) -> dict[str, Any]:
    return resolve_source_span(
        chunk_id=chunk.chunk_id,
        content=chunk.content,
        metadata=chunk.metadata,
        span_start=span_start,
        span_end=span_end,
        snippet=snippet,
    ).to_dict()


__all__ = [
    "CONTENT_SPAN_UNIT",
    "build_paragraph_span_metadata",
    "remap_span_origin_ids",
    "resolve_citation_span",
]
