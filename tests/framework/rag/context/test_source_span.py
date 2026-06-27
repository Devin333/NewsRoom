from __future__ import annotations

from framework.rag.context import (
    build_main_overlap_span_metadata,
    locate_snippet_span,
    remap_span_origin_ids,
    resolve_source_span,
)


def test_build_main_overlap_span_metadata_records_main_and_overlap_spans():
    content = "Borrowed sentence.\nCurrent body."
    metadata = build_main_overlap_span_metadata(
        content=content,
        overlap_text="Borrowed sentence.",
        overlap_origin_chunk_id="previous",
        overlap_origin_source_locator="source://previous",
    )

    assert metadata["content_span_unit"] == "char_offset"
    assert metadata["main_span"] == {"start": len("Borrowed sentence.") + 1, "end": len(content)}
    assert metadata["overlap_spans"][0]["origin_chunk_id"] == "previous"


def test_resolve_source_span_uses_overlap_origin_for_snippet():
    content = "Borrowed sentence.\nCurrent body."
    metadata = {
        "source_locator": "source://current",
        **build_main_overlap_span_metadata(
            content=content,
            overlap_text="Borrowed sentence.",
            overlap_origin_chunk_id="previous",
            overlap_origin_source_locator="source://previous",
        ),
    }

    resolved = resolve_source_span(
        chunk_id="current",
        content=content,
        metadata=metadata,
        snippet="Borrowed sentence.",
    )

    assert resolved.span_kind == "overlap"
    assert resolved.resolved_chunk_id == "previous"
    assert resolved.resolved_source_locator == "source://previous"


def test_resolve_source_span_defaults_to_main_span():
    content = "Alpha beta.\nCurrent body."
    metadata = {
        "source_locator": "source://current",
        **build_main_overlap_span_metadata(content=content),
    }

    resolved = resolve_source_span(
        chunk_id="current",
        content=content,
        metadata=metadata,
        snippet="Current body.",
    )

    assert resolved.span_kind == "main"
    assert resolved.resolved_chunk_id == "current"


def test_remap_span_origin_ids_updates_overlap_origins():
    metadata = {
        "overlap_spans": [{"origin_chunk_id": "old", "start": 0, "end": 3}],
        "main_span": {"start": 4, "end": 10},
    }

    remapped = remap_span_origin_ids(metadata, {"old": "new"})

    assert remapped["overlap_spans"][0]["origin_chunk_id"] == "new"
    assert remapped["main_span"] == {"start": 4, "end": 10}


def test_locate_snippet_span_normalizes_case_and_whitespace():
    assert locate_snippet_span("Alpha\n  Beta.", "alpha beta") == (0, 12)
