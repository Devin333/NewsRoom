from __future__ import annotations

from framework.rag.context import resolve_citation
from framework.rag.core import RAGEvidence, SourceLocator


def _evidence() -> RAGEvidence:
    return RAGEvidence(
        evidence_id="ev-1",
        chunk_id="chunk-current",
        document_id="doc-1",
        text="Borrowed sentence. Main paragraph.",
        source_locator=SourceLocator(
            source_id="paper://doc/pdf#page=4",
            raw_locator="paper://doc/pdf#page=4",
        ),
        metadata={
            "main_span": {"start": 19, "end": 34},
            "overlap_spans": [
                {
                    "start": 0,
                    "end": 18,
                    "origin_chunk_id": "chunk-previous",
                    "origin_source_locator": "paper://doc/pdf#page=3",
                }
            ],
        },
    )


def test_resolve_citation_uses_overlap_origin_when_span_lands_inside_overlap():
    resolved = resolve_citation(_evidence(), span_start=0, span_end=8)

    assert resolved.resolved_chunk_id == "chunk-previous"
    assert resolved.resolved_source_locator == "paper://doc/pdf#page=3"
    assert resolved.span_kind == "overlap"


def test_resolve_citation_defaults_to_current_evidence_for_main_span():
    resolved = resolve_citation(_evidence(), span_start=20, span_end=25)

    assert resolved.resolved_chunk_id == "chunk-current"
    assert resolved.resolved_source_locator == "paper://doc/pdf#page=4"
    assert resolved.span_kind == "main"
