from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.domain.document import ResearchDocument, ResearchFigure, ResearchTable


_VISUAL_METADATA_KEYS = (
    "visual_description",
    "visual_description_model",
    "visual_description_source",
    "visual_description_status",
    "visual_description_generated_at",
    "visual_description_image_path",
    "visual_description_skip_reason",
    "visual_description_error_type",
)


def sync_visual_descriptions_to_document(
    document: ResearchDocument,
    chunks: list[PaperChunk],
) -> ResearchDocument:
    """Copy figure/table visual description metadata from chunks back to the document artifact."""
    figure_metadata = _visual_metadata_by_element(chunks, chunk_type="figure", id_key="figure_id")
    table_metadata = _visual_metadata_by_element(chunks, chunk_type="table", id_key="table_id")
    if not figure_metadata and not table_metadata:
        return document

    figures = [
        _merge_figure_metadata(figure, figure_metadata.get(figure.figure_id))
        for figure in document.figures
    ]
    tables = [
        _merge_table_metadata(table, table_metadata.get(table.table_id))
        for table in document.tables
    ]
    metadata = dict(document.metadata)
    metadata["visual_described_figures"] = sum(
        1 for figure in figures if figure.metadata.get("visual_description")
    )
    metadata["visual_described_tables"] = sum(
        1 for table in tables if table.metadata.get("visual_description")
    )
    return document.model_copy(update={
        "figures": figures,
        "tables": tables,
        "metadata": metadata,
    })


def _visual_metadata_by_element(
    chunks: list[PaperChunk],
    *,
    chunk_type: str,
    id_key: str,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        if chunk.chunk_type != chunk_type:
            continue
        element_id = str(chunk.metadata.get(id_key) or getattr(chunk, id_key, "") or "")
        if not element_id:
            continue
        metadata = _extract_visual_metadata(chunk.metadata)
        if metadata:
            out[element_id] = metadata
    return out


def _extract_visual_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    out = {
        key: metadata[key]
        for key in _VISUAL_METADATA_KEYS
        if key in metadata and metadata[key] not in ("", None)
    }
    if "visual_description_status" not in out:
        if out.get("visual_description"):
            out["visual_description_status"] = "ok"
        elif metadata.get("visual_description_skipped"):
            out["visual_description_status"] = "skipped"
    return out


def _merge_figure_metadata(
    figure: ResearchFigure,
    visual_metadata: dict[str, Any] | None,
) -> ResearchFigure:
    if not visual_metadata:
        return figure
    metadata = dict(figure.metadata)
    metadata.update(visual_metadata)
    return figure.model_copy(update={"metadata": metadata})


def _merge_table_metadata(
    table: ResearchTable,
    visual_metadata: dict[str, Any] | None,
) -> ResearchTable:
    if not visual_metadata:
        return table
    metadata = dict(table.metadata)
    metadata.update(visual_metadata)
    return table.model_copy(update={"metadata": metadata})


__all__ = ["sync_visual_descriptions_to_document"]
