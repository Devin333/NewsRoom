from __future__ import annotations

import pytest

from business.research.document.models import PaperChunk
from business.research.rag.evaluation.paper_fixed_window_baseline import FixedWindowBaselineChunker, FixedWindowChunkerConfig
from business.research.rag.evaluation.evidence_eval_runner import _matches_filters


def _chunk(chunk_id: str, content: str, *, chunk_type: str = "paragraph", section_index: int = 1) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="nougat",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Section",
        section_role=["method"],  # type: ignore[list-item]
        section_index=section_index,
        has_table=chunk_type == "table",
        has_figure=chunk_type == "figure",
        content=content,
        metadata={"source_ref": f"arxiv://p1/{chunk_id}"},
    )


def test_fixed_window_baseline_chunks_text_with_overlap_and_source_mapping() -> None:
    chunks = [
        _chunk("para-1", "a b c d e", section_index=1),
        _chunk("para-2", "f g h i j", section_index=2),
    ]

    windows = FixedWindowBaselineChunker(
        FixedWindowChunkerConfig(window_tokens=4, overlap_tokens=1)
    ).chunk(chunks)

    assert [window.content for window in windows] == [
        "a b c d",
        "d e f g",
        "g h i j",
    ]
    assert windows[1].metadata["source_chunk_ids"] == ["para-1", "para-2"]
    assert windows[1].metadata["baseline"] == "fixed_window"


def test_fixed_window_baseline_includes_visual_text_but_skips_page_visual_chunks() -> None:
    chunks = [
        _chunk("fig-1", "figure caption", chunk_type="figure"),
        _chunk("tbl-1", "table rows", chunk_type="table"),
        _chunk("para-1", "body text"),
        _chunk(
            "page-1",
            "rendered page visual",
            chunk_type="figure",
        ).model_copy(update={"metadata": {"page_visual": True}}),
    ]

    windows = FixedWindowBaselineChunker(FixedWindowChunkerConfig(window_tokens=10)).chunk(chunks)

    assert len(windows) == 1
    assert windows[0].metadata["source_chunk_ids"] == ["fig-1", "tbl-1", "para-1"]
    assert windows[0].metadata["source_evidence_types"] == ["figure", "table", "paragraph"]
    assert _matches_filters(windows[0], {"chunk_type": "table"}) is True
    assert _matches_filters(windows[0], {"chunk_type": "figure"}) is True


def test_fixed_window_config_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError, match="smaller than window_tokens"):
        FixedWindowChunkerConfig(window_tokens=10, overlap_tokens=10)
