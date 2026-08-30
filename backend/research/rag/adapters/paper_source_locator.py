from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from framework.rag.core import SourceLocator

from backend.research.document.models import PaperChunk


def source_locator_from_paper_chunk(chunk: PaperChunk) -> SourceLocator | None:
    raw_locator = str(chunk.metadata.get("source_locator") or chunk.metadata.get("source_ref") or "")
    page = _first_int(chunk.metadata, ("page",)) or _page_from_locator(raw_locator)
    bbox = _bbox_from_value(chunk.metadata.get("pdf_rect")) or _bbox_from_locator(raw_locator)
    source_id = raw_locator or str(chunk.metadata.get("source_ref") or "")
    if not source_id:
        return None
    section_path = (chunk.section_title,) if chunk.section_title else ()
    return SourceLocator(
        source_id=source_id,
        page=page,
        bbox=bbox,
        section_path=section_path,
        raw_locator=raw_locator,
        metadata={
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.paper_id,
            "caption_source_locator": str(chunk.metadata.get("caption_source_locator") or ""),
        },
    )


def _first_int(metadata: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, bool):
            continue
        try:
            if value is not None and str(value).strip():
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _page_from_locator(locator: str) -> int | None:
    query = _locator_fragment_query(locator)
    raw = query.get("page", [""])[0]
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _bbox_from_locator(locator: str) -> tuple[float, float, float, float] | None:
    query = _locator_fragment_query(locator)
    return _bbox_from_value(query.get("pdf_rect", [""])[0])


def _locator_fragment_query(locator: str) -> dict[str, list[str]]:
    if not locator:
        return {}
    fragment = urlparse(locator).fragment
    return parse_qs(fragment, keep_blank_values=False)


def _bbox_from_value(value: Any) -> tuple[float, float, float, float] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    elif isinstance(value, (tuple, list)):
        parts = list(value)
    else:
        return None
    if len(parts) != 4:
        return None
    try:
        return tuple(float(part) for part in parts)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


__all__ = ["source_locator_from_paper_chunk"]
