from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from framework.rag.core import RAGEvidence


@dataclass(frozen=True)
class CitationResolution:
    chunk_id: str
    source_locator: str
    resolved_chunk_id: str
    resolved_source_locator: str
    span_kind: str = "main"

    def to_dict(self) -> dict[str, str]:
        return {
            "chunk_id": self.chunk_id,
            "source_locator": self.source_locator,
            "resolved_chunk_id": self.resolved_chunk_id,
            "resolved_source_locator": self.resolved_source_locator,
            "span_kind": self.span_kind,
        }


def resolve_citation(
    evidence: RAGEvidence,
    *,
    span_start: int | None = None,
    span_end: int | None = None,
) -> CitationResolution:
    source_locator = _evidence_source_locator(evidence)
    selected_overlap = _matching_overlap(evidence.metadata, span_start, span_end)
    if selected_overlap is not None:
        return CitationResolution(
            chunk_id=evidence.chunk_id,
            source_locator=source_locator,
            resolved_chunk_id=str(selected_overlap.get("origin_chunk_id") or evidence.chunk_id),
            resolved_source_locator=str(selected_overlap.get("origin_source_locator") or source_locator),
            span_kind="overlap",
        )
    return CitationResolution(
        chunk_id=evidence.chunk_id,
        source_locator=source_locator,
        resolved_chunk_id=evidence.chunk_id,
        resolved_source_locator=source_locator,
        span_kind="main",
    )


def _matching_overlap(
    metadata: Mapping[str, Any],
    span_start: int | None,
    span_end: int | None,
) -> Mapping[str, Any] | None:
    if span_start is None or span_end is None:
        return None
    spans = metadata.get("overlap_spans", [])
    if not isinstance(spans, list):
        return None
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        start = _as_int(span.get("start"))
        end = _as_int(span.get("end"))
        if start is None or end is None:
            continue
        if span_start >= start and span_end <= end:
            return span
    return None


def _evidence_source_locator(evidence: RAGEvidence) -> str:
    if evidence.source_locator is None:
        return str(evidence.metadata.get("source_locator") or "")
    return evidence.source_locator.raw_locator or evidence.source_locator.source_id


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["CitationResolution", "resolve_citation"]
