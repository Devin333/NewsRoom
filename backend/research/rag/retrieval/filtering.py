from __future__ import annotations

from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.services.tenant_visibility import chunk_visible_to_tenant, tenant_id_from_filters


def request_filters(request: Any) -> dict[str, Any]:
    raw = getattr(request, "filters", {}) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def merge_request_filters(request: Any, extra_filters: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = request_filters(request)
    if extra_filters:
        filters.update(extra_filters)
    return filters


def request_tenant_id(request: Any) -> str | None:
    return tenant_id_from_filters(request_filters(request))


def chunk_visible_for_request(chunk: PaperChunk, request: Any) -> bool:
    return chunk_visible_to_tenant(chunk, tenant_id=request_tenant_id(request))


def filter_chunks_for_request(chunks: list[PaperChunk], request: Any) -> list[PaperChunk]:
    tenant_id = request_tenant_id(request)
    return [chunk for chunk in chunks if chunk_visible_to_tenant(chunk, tenant_id=tenant_id)]


def filter_scored_chunks_for_request(
    scored: list[tuple[PaperChunk, float]],
    request: Any,
) -> list[tuple[PaperChunk, float]]:
    tenant_id = request_tenant_id(request)
    return [
        (chunk, score)
        for chunk, score in scored
        if chunk_visible_to_tenant(chunk, tenant_id=tenant_id)
    ]


__all__ = [
    "chunk_visible_for_request",
    "filter_chunks_for_request",
    "filter_scored_chunks_for_request",
    "merge_request_filters",
    "request_filters",
    "request_tenant_id",
]
