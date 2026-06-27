from __future__ import annotations

from framework.rag.context.assembler import RAGContextAssembler
from framework.rag.context.budget import ContextBudget, trim_evidence_to_budget
from framework.rag.context.citation import CitationResolution, resolve_citation
from framework.rag.context.source_span import (
    CONTENT_SPAN_UNIT,
    SourceSpanResolution,
    build_main_overlap_span_metadata,
    locate_snippet_span,
    remap_span_origin_ids,
    resolve_source_span,
)

__all__ = [
    "CONTENT_SPAN_UNIT",
    "CitationResolution",
    "ContextBudget",
    "RAGContextAssembler",
    "SourceSpanResolution",
    "build_main_overlap_span_metadata",
    "locate_snippet_span",
    "remap_span_origin_ids",
    "resolve_citation",
    "resolve_source_span",
    "trim_evidence_to_budget",
]
