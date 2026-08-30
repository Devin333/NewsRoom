from __future__ import annotations

from pathlib import Path

from backend.research.document.models import PaperChunk
from backend.research.rag.visual.page_visual_chunks import build_page_visual_chunks


def test_build_page_visual_chunks_groups_visual_elements_by_page(tmp_path: Path) -> None:
    paper_dir = tmp_path / "papers" / "p1" / "page_images"
    paper_dir.mkdir(parents=True)
    (paper_dir / "p1_page_002.png").write_bytes(b"fake-page-image")
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        metadata={
            "page": 2,
            "image_ref": "figures/fig1.png",
            "figure_id": "fig1",
        },
    )
    table = _chunk(
        "tbl-1",
        chunk_type="table",
        metadata={
            "page": 2,
            "image_ref": "tables/table1.png",
            "table_id": "tbl1",
        },
    )

    [page_chunk] = build_page_visual_chunks(
        [figure, table],
        papers_dir=tmp_path / "papers",
        render_pages=False,
    )

    assert page_chunk.metadata["page_visual"] is True
    assert page_chunk.metadata["page"] == 2
    assert page_chunk.metadata["image_ref"] == "page_images/p1_page_002.png"
    assert [item["chunk_id"] for item in page_chunk.metadata["related_visual_chunks"]] == ["fig-1", "tbl-1"]
    assert "figure fig1" in page_chunk.content
    assert "table tbl1" in page_chunk.content


def _chunk(
    chunk_id: str,
    *,
    chunk_type: str,
    metadata: dict,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="nougat",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Results",
        section_role=["experiment"],  # type: ignore[list-item]
        section_index=2,
        content=f"{chunk_type} content",
        metadata=metadata,
    )
