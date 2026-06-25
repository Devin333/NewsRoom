from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk


CONTENT_SPAN_UNIT = "char_offset"


def build_paragraph_span_metadata(
    *,
    content: str,
    overlap_text: str = "",
    overlap_origin_chunk_id: str = "",
    overlap_origin_source_locator: str = "",
    overlap_type: str = "previous_paragraph_trailing_sentence",
) -> dict[str, Any]:
    main_start = len(overlap_text) + (1 if overlap_text else 0)
    metadata: dict[str, Any] = {
        "content_span_unit": CONTENT_SPAN_UNIT,
        "main_span": {
            "start": 0 if not content or not overlap_text else main_start,
            "end": len(content),
        },
        "overlap_spans": [],
    }
    if overlap_text:
        metadata["overlap_spans"] = [{
            "start": 0,
            "end": len(overlap_text),
            "origin_chunk_id": overlap_origin_chunk_id,
            "origin_source_locator": overlap_origin_source_locator,
            "overlap_type": overlap_type,
        }]
    return metadata


def remap_span_origin_ids(metadata: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
    out = dict(metadata)
    main_span = out.get("main_span")
    if isinstance(main_span, dict):
        out["main_span"] = _remap_span_origin_id(main_span, id_map)

    overlap_spans = out.get("overlap_spans")
    if isinstance(overlap_spans, list):
        out["overlap_spans"] = [
            _remap_span_origin_id(span, id_map) if isinstance(span, dict) else span
            for span in overlap_spans
        ]
    return out


def resolve_citation_span(
    chunk: PaperChunk,
    *,
    span_start: int | None = None,
    span_end: int | None = None,
    snippet: str | None = None,
) -> dict[str, Any]:
    metadata = chunk.metadata
    main_span = _normalize_span(metadata.get("main_span"))
    overlap_spans = [
        _normalize_span(span)
        for span in metadata.get("overlap_spans", [])
        if isinstance(span, dict)
    ]
    content = chunk.content
    resolved_start = span_start
    resolved_end = span_end
    if (resolved_start is None or resolved_end is None) and snippet:
        resolved = _locate_snippet_span(content, snippet)
        if resolved is not None:
            resolved_start, resolved_end = resolved
    if resolved_start is None:
        resolved_start = 0
    if resolved_end is None:
        resolved_end = resolved_start

    selected_span = _span_for_offset(resolved_start, main_span, overlap_spans)
    if selected_span.get("kind") == "overlap":
        return {
            "span_kind": "overlap",
            "chunk_id": chunk.chunk_id,
            "source_locator": str(metadata.get("source_locator") or ""),
            "resolved_chunk_id": str(selected_span.get("origin_chunk_id") or chunk.chunk_id),
            "resolved_source_locator": str(selected_span.get("origin_source_locator") or metadata.get("source_locator") or ""),
            "span": selected_span.get("span"),
        }
    return {
        "span_kind": "main",
        "chunk_id": chunk.chunk_id,
        "source_locator": str(metadata.get("source_locator") or ""),
        "resolved_chunk_id": chunk.chunk_id,
        "resolved_source_locator": str(metadata.get("source_locator") or ""),
        "span": main_span,
    }


def _remap_span_origin_id(span: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
    out = dict(span)
    origin_chunk_id = out.get("origin_chunk_id")
    if origin_chunk_id:
        resolved = id_map.get(str(origin_chunk_id))
        if resolved:
            out["origin_chunk_id"] = resolved
    return out


def _normalize_span(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("start", "end", "origin_chunk_id", "origin_source_locator"):
        if key in value:
            out[key] = value.get(key)
    return out


def _span_for_offset(
    offset: int,
    main_span: dict[str, Any],
    overlap_spans: list[dict[str, Any]],
) -> dict[str, Any]:
    for span in overlap_spans:
        start = _coerce_int(span.get("start"))
        end = _coerce_int(span.get("end"))
        if start is None or end is None:
            continue
        if start <= offset < end:
            return {
                "kind": "overlap",
                "span": span,
                "origin_chunk_id": str(span.get("origin_chunk_id") or ""),
                "origin_source_locator": str(span.get("origin_source_locator") or ""),
            }
    main_start = _coerce_int(main_span.get("start")) or 0
    main_end = _coerce_int(main_span.get("end"))
    if main_end is not None and main_start <= offset < main_end:
        return {"kind": "main", "span": main_span}
    return {"kind": "main", "span": main_span}


def _locate_snippet_span(content: str, snippet: str) -> tuple[int, int] | None:
    normalized_content, content_map = _normalize_with_map(content)
    normalized_snippet, _ = _normalize_with_map(snippet)
    if not normalized_content or not normalized_snippet:
        return None
    index = normalized_content.find(normalized_snippet)
    if index < 0:
        return None
    start = content_map[index]
    end_index = index + max(0, len(normalized_snippet) - 1)
    end = content_map[end_index] + 1 if end_index < len(content_map) else len(content)
    return start, end


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    i = 0
    length = len(text)
    saw_space = False
    while i < length:
        if text[i].isspace():
            start = i
            while i < length and text[i].isspace():
                i += 1
            if saw_space or not chars:
                continue
            chars.append(" ")
            positions.append(start)
            saw_space = True
            continue
        chars.append(text[i].casefold())
        positions.append(i)
        saw_space = False
        i += 1
    start = 0
    end = len(chars)
    while start < end and chars[start] == " ":
        start += 1
    while end > start and chars[end - 1] == " ":
        end -= 1
    if start >= end:
        return "", []
    return "".join(chars[start:end]), positions[start:end]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CONTENT_SPAN_UNIT",
    "build_paragraph_span_metadata",
    "remap_span_origin_ids",
    "resolve_citation_span",
]
