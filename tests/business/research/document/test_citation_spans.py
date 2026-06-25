from __future__ import annotations

from business.research.document.citation_spans import build_paragraph_span_metadata, resolve_citation_span
from business.research.document.models import PaperChunk


def _chunk(chunk_id: str, content: str, metadata: dict[str, object]) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="paper-1",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Introduction",
        section_role=["background"],
        section_index=1,
        content=content,
        metadata=metadata,
    )


def test_resolve_citation_span_prefers_main_span():
    content = "Alpha beta gamma.\nMore detail here."
    chunk = _chunk(
        "chunk-main",
        content,
        {
            "source_locator": "paper://paper-1/pdf#page=2",
            **build_paragraph_span_metadata(content=content),
        },
    )

    resolved = resolve_citation_span(chunk, snippet="More detail here.")

    assert resolved["span_kind"] == "main"
    assert resolved["resolved_chunk_id"] == "chunk-main"
    assert resolved["resolved_source_locator"] == "paper://paper-1/pdf#page=2"


def test_resolve_citation_span_falls_back_to_overlap_origin():
    content = "Shared trailing sentence.\nNew paragraph body."
    chunk = _chunk(
        "chunk-current",
        content,
        {
            "source_locator": "paper://paper-1/pdf#page=3",
            **build_paragraph_span_metadata(
                content=content,
                overlap_text="Shared trailing sentence.",
                overlap_origin_chunk_id="chunk-previous",
                overlap_origin_source_locator="paper://paper-1/pdf#page=2",
            ),
        },
    )

    resolved = resolve_citation_span(chunk, snippet="Shared trailing sentence.")

    assert resolved["span_kind"] == "overlap"
    assert resolved["resolved_chunk_id"] == "chunk-previous"
    assert resolved["resolved_source_locator"] == "paper://paper-1/pdf#page=2"

