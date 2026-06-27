from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

from business.research.document.models import PaperChunk
from business.research.rag.field_text import extract_field_texts
from framework.rag.core import RAGChunk, RAGEvidence, RAGScoreBreakdown, SourceLocator

_SCORE_COMPONENT_KEYS: dict[str, tuple[str, ...]] = {
    "child_similarity": ("child_similarity", "child_semantic_score"),
    "parent_relevance": ("parent_relevance", "parent_relevance_score", "parent_child_relevance_score"),
    "field_score": ("field_score", "field_embedding_score"),
    "section_heading_score": ("section_heading_score", "parent_section_heading_score"),
    "position_bonus": ("position_bonus", "parent_position_score", "child_position_score"),
    "rerank_score": (
        "rerank_score",
        "field_rerank_score",
        "parent_rerank_score",
        "table_context_rerank_score",
    ),
    "final_score": ("final_score", "fused_score", "child_final_score", "parent_final_score"),
}

_SCORE_FALLBACK_KEYS = (
    "final_score",
    "fused_score",
    "child_final_score",
    "parent_final_score",
    "field_score",
    "field_embedding_score",
    "text_score",
)


class PaperChunkAdapter:
    def to_rag_chunk(self, chunk: PaperChunk) -> RAGChunk:
        fields = _chunk_fields(chunk)
        locator = source_locator_from_paper_chunk(chunk)
        return RAGChunk(
            chunk_id=chunk.chunk_id,
            document_id=chunk.paper_id,
            text=chunk.content,
            chunk_type=chunk.chunk_type,
            fields=fields,
            source_locator=locator,
            metadata=_chunk_metadata(chunk, locator),
        )

    def to_rag_evidence(self, chunk: PaperChunk, *, score: float | None = None) -> RAGEvidence:
        rag_chunk = self.to_rag_chunk(chunk)
        breakdown = _score_breakdown(chunk.metadata)
        resolved_score = score
        if resolved_score is None:
            resolved_score = _first_number(chunk.metadata, _SCORE_FALLBACK_KEYS)
        return RAGEvidence(
            evidence_id=chunk.chunk_id,
            chunk_id=rag_chunk.chunk_id,
            document_id=rag_chunk.document_id,
            text=rag_chunk.text,
            score=resolved_score if resolved_score is not None else 0.0,
            score_breakdown=breakdown,
            source_locator=rag_chunk.source_locator,
            metadata=rag_chunk.metadata,
        )


def paper_chunk_to_rag_chunk(chunk: PaperChunk) -> RAGChunk:
    return PaperChunkAdapter().to_rag_chunk(chunk)


def paper_chunk_to_rag_evidence(chunk: PaperChunk, *, score: float | None = None) -> RAGEvidence:
    return PaperChunkAdapter().to_rag_evidence(chunk, score=score)


def paper_chunk_to_evidence_metadata(chunk: PaperChunk) -> dict[str, Any]:
    evidence = paper_chunk_to_rag_evidence(chunk)
    metadata = _evidence_pack_metadata(chunk)
    metadata.update({
        "rag_document_id": evidence.document_id,
        "rag_chunk_id": evidence.chunk_id,
        "rag_score": evidence.score,
        "rag_score_breakdown": evidence.score_breakdown.to_dict(),
    })
    if evidence.source_locator is not None:
        metadata["rag_source_locator"] = evidence.source_locator.to_dict()
    return metadata


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


def _chunk_fields(chunk: PaperChunk) -> dict[str, str]:
    field_text = extract_field_texts(chunk)
    fields = field_text.non_empty()
    if chunk.formula_latex.strip():
        fields.setdefault("formula", chunk.formula_latex)
    visual_description = str(chunk.metadata.get("visual_description") or "").strip()
    if visual_description:
        fields.setdefault("visual_description", visual_description)
    return fields


def _chunk_metadata(chunk: PaperChunk, locator: SourceLocator | None) -> dict[str, Any]:
    metadata = dict(chunk.metadata)
    metadata.update({
        "paper_id": chunk.paper_id,
        "parse_source": chunk.parse_source,
        "chunk_type": chunk.chunk_type,
        "parent_chunk_id": chunk.parent_chunk_id,
        "section_title": chunk.section_title,
        "section_role": list(chunk.section_role),
        "section_index": chunk.section_index,
        "has_formula": chunk.has_formula,
        "has_figure": chunk.has_figure,
        "figure_id": chunk.figure_id,
        "has_table": chunk.has_table,
        "references": list(chunk.references),
        "propositions_generated": chunk.propositions_generated,
        "proposition_quality": chunk.proposition_quality,
    })
    if locator is not None:
        metadata["source_locator_structured"] = locator.to_dict()
    field_text = extract_field_texts(chunk)
    metadata.setdefault("field_text_available_fields", field_text.available_fields())
    metadata.setdefault("field_text_sources", field_text.sources)
    return metadata


def _evidence_pack_metadata(chunk: PaperChunk) -> dict[str, Any]:
    return {
        "section_role": chunk.section_role,
        "section_index": chunk.section_index,
        "chunk_type": chunk.chunk_type,
        "parent_chunk_id": chunk.parent_chunk_id,
        "has_formula": chunk.has_formula,
        "formula_latex": chunk.formula_latex,
        "has_figure": chunk.has_figure,
        "figure_id": chunk.figure_id,
        "has_table": chunk.has_table,
        "table_id": chunk.metadata.get("table_id", ""),
        "image_ref": chunk.metadata.get("image_ref", ""),
        "source_locator": chunk.metadata.get("source_locator", ""),
        "caption_source_locator": chunk.metadata.get("caption_source_locator", ""),
        "page": chunk.metadata.get("page"),
        "pdf_rect": chunk.metadata.get("pdf_rect"),
        "caption_pdf_rect": chunk.metadata.get("caption_pdf_rect"),
        "content_sources": chunk.metadata.get("content_sources", []),
        "ocr_attempted": chunk.metadata.get("ocr_attempted", False),
        "ocr_chars": chunk.metadata.get("ocr_chars", 0),
        "ocr_error": chunk.metadata.get("ocr_error", ""),
        "ocr_text_source": chunk.metadata.get("ocr_text_source", ""),
        "text_score": chunk.metadata.get("text_score"),
        "visual_score": chunk.metadata.get("visual_score"),
        "fused_score": chunk.metadata.get("fused_score"),
        "fusion_strategy": chunk.metadata.get("fusion_strategy", ""),
        "visual_hit": chunk.metadata.get("visual_hit", False),
        "expanded_from_chunk_id": chunk.metadata.get("expanded_from_chunk_id", ""),
        "expansion_reason": chunk.metadata.get("expansion_reason", ""),
        "expansion_edge": chunk.metadata.get("expansion_edge", ""),
        "expansion_rank": chunk.metadata.get("expansion_rank"),
        "table_context_rerank_score": chunk.metadata.get("table_context_rerank_score"),
        "table_context_rerank_strategy": chunk.metadata.get("table_context_rerank_strategy", ""),
        "parent_expansion_reason": chunk.metadata.get("parent_expansion_reason", ""),
        "parent_anchor_child_id": chunk.metadata.get("parent_anchor_child_id", ""),
        "parent_snippet": chunk.metadata.get("parent_snippet", False),
        "parent_snippet_strategy": chunk.metadata.get("parent_snippet_strategy", ""),
        "source_parent_chunk_id": chunk.metadata.get("source_parent_chunk_id", ""),
        "parent_rerank_score": chunk.metadata.get("parent_rerank_score"),
        "parent_rerank_strategy": chunk.metadata.get("parent_rerank_strategy", ""),
        "parent_child_relevance_score": chunk.metadata.get("parent_child_relevance_score"),
        "parent_relevance_score": chunk.metadata.get("parent_relevance_score"),
        "parent_section_heading_score": chunk.metadata.get("parent_section_heading_score"),
        "parent_position_score": chunk.metadata.get("parent_position_score"),
        "parent_final_score": chunk.metadata.get("parent_final_score"),
        "parent_score_strategy": chunk.metadata.get("parent_score_strategy", ""),
        "parent_score_weights": chunk.metadata.get("parent_score_weights", {}),
        "title_score": chunk.metadata.get("title_score"),
        "abstract_score": chunk.metadata.get("abstract_score"),
        "caption_score": chunk.metadata.get("caption_score"),
        "equation_score": chunk.metadata.get("equation_score"),
        "body_score": chunk.metadata.get("body_score"),
        "field_score": chunk.metadata.get("field_score"),
        "field_score_weights": chunk.metadata.get("field_score_weights", {}),
        "field_score_strategy": chunk.metadata.get("field_score_strategy", ""),
        "title_embedding_score": chunk.metadata.get("title_embedding_score"),
        "abstract_embedding_score": chunk.metadata.get("abstract_embedding_score"),
        "caption_embedding_score": chunk.metadata.get("caption_embedding_score"),
        "equation_embedding_score": chunk.metadata.get("equation_embedding_score"),
        "body_embedding_score": chunk.metadata.get("body_embedding_score"),
        "field_embedding_score": chunk.metadata.get("field_embedding_score"),
        "field_embedding_scores": chunk.metadata.get("field_embedding_scores", {}),
        "field_embedding_hits": chunk.metadata.get("field_embedding_hits", []),
        "best_embedding_field": chunk.metadata.get("best_embedding_field", ""),
        "field_embedding_strategy": chunk.metadata.get("field_embedding_strategy", ""),
        "field_rerank_score": chunk.metadata.get("field_rerank_score"),
        "field_rerank_strategy": chunk.metadata.get("field_rerank_strategy", ""),
        "best_matching_field": chunk.metadata.get("best_matching_field", ""),
        "element_label_boost": chunk.metadata.get("element_label_boost"),
        "graph_score": chunk.metadata.get("graph_score"),
        "child_score_strategy": chunk.metadata.get("child_score_strategy", ""),
        "child_score_components": chunk.metadata.get("child_score_components", {}),
        "field_text_available_fields": chunk.metadata.get("field_text_available_fields", ()),
        "field_text_sources": chunk.metadata.get("field_text_sources", {}),
        "content_span_unit": chunk.metadata.get("content_span_unit", ""),
        "main_span": chunk.metadata.get("main_span", {}),
        "overlap_spans": chunk.metadata.get("overlap_spans", []),
        "child_semantic_score": chunk.metadata.get("child_semantic_score"),
        "child_position_score": chunk.metadata.get("child_position_score"),
        "child_final_score": chunk.metadata.get("child_final_score"),
        "child_score_weights": chunk.metadata.get("child_score_weights", {}),
        "row_start": chunk.metadata.get("row_start"),
        "row_end": chunk.metadata.get("row_end"),
        "parent_table_chunk_id": chunk.metadata.get("parent_table_chunk_id", ""),
        "is_table_row_group": chunk.metadata.get("is_table_row_group", False),
    }


def _score_breakdown(metadata: Mapping[str, Any]) -> RAGScoreBreakdown:
    values: dict[str, float] = {}
    for component, keys in _SCORE_COMPONENT_KEYS.items():
        number = _first_number(metadata, keys)
        if number is not None:
            values[component] = number
    extra = {
        str(key): number
        for key, raw in metadata.items()
        if key.endswith("_score")
        and key not in {alias for aliases in _SCORE_COMPONENT_KEYS.values() for alias in aliases}
        and (number := _as_optional_float(raw)) is not None
    }
    return RAGScoreBreakdown.from_mapping({**values, **extra})


def _first_number(metadata: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        number = _as_optional_float(metadata.get(key))
        if number is not None:
            return number
    return None


def _first_int(metadata: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
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


def _as_optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "PaperChunkAdapter",
    "paper_chunk_to_evidence_metadata",
    "paper_chunk_to_rag_chunk",
    "paper_chunk_to_rag_evidence",
    "source_locator_from_paper_chunk",
]
