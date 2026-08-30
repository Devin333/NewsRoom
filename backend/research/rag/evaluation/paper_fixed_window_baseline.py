from __future__ import annotations

from dataclasses import dataclass

from backend.research.document.models import PaperChunk
from framework.rag.core import build_rag_stable_id


@dataclass(frozen=True)
class FixedWindowChunkerConfig:
    window_tokens: int = 220
    overlap_tokens: int | None = None
    max_windows_per_paper: int = 500

    def __post_init__(self) -> None:
        if self.window_tokens <= 0:
            raise ValueError("window_tokens must be positive")
        overlap_tokens = self.overlap_tokens
        if overlap_tokens is None:
            overlap_tokens = min(40, max(0, self.window_tokens // 5))
            object.__setattr__(self, "overlap_tokens", overlap_tokens)
        if overlap_tokens < 0:
            raise ValueError("overlap_tokens must be non-negative")
        if overlap_tokens >= self.window_tokens:
            raise ValueError("overlap_tokens must be smaller than window_tokens")
        if self.max_windows_per_paper <= 0:
            raise ValueError("max_windows_per_paper must be positive")


class FixedWindowBaselineChunker:
    """Creates fixed-window chunks for evaluation-only A/B baselines."""

    def __init__(self, config: FixedWindowChunkerConfig | None = None) -> None:
        self._config = config or FixedWindowChunkerConfig()

    def chunk(self, chunks: list[PaperChunk]) -> list[PaperChunk]:
        by_paper: dict[str, list[PaperChunk]] = {}
        for chunk in chunks:
            if chunk.metadata.get("page_visual"):
                continue
            by_paper.setdefault(chunk.paper_id, []).append(chunk)

        out: list[PaperChunk] = []
        for paper_id, paper_chunks in by_paper.items():
            out.extend(self._chunk_paper(paper_id, paper_chunks))
        return out

    def _chunk_paper(self, paper_id: str, chunks: list[PaperChunk]) -> list[PaperChunk]:
        ordered = chunks
        tokens: list[str] = []
        token_sources: list[PaperChunk] = []
        for chunk in ordered:
            chunk_tokens = _tokenize(chunk.content)
            tokens.extend(chunk_tokens)
            token_sources.extend([chunk] * len(chunk_tokens))
        if not tokens:
            return []

        step = self._config.window_tokens - self._config.overlap_tokens
        windows: list[PaperChunk] = []
        start = 0
        window_index = 0
        while start < len(tokens) and len(windows) < self._config.max_windows_per_paper:
            end = min(start + self._config.window_tokens, len(tokens))
            source_slice = token_sources[start:end]
            anchor = source_slice[0]
            source_chunk_ids = _unique_texts([source.chunk_id for source in source_slice])
            source_evidence_types = _unique_texts([_evidence_type(source) for source in source_slice])
            source_locators = _unique_texts([
                str(source.metadata.get("source_locator") or source.metadata.get("source_ref") or "")
                for source in source_slice
            ])
            source_image_refs = _unique_texts([
                str(source.metadata.get("image_ref") or "")
                for source in source_slice
            ])
            content = " ".join(tokens[start:end])
            windows.append(PaperChunk(
                chunk_id=build_rag_stable_id("fixed_window", paper_id, window_index, content[:240]),
                paper_id=paper_id,
                parse_source=anchor.parse_source,
                chunk_type="paragraph",
                parent_chunk_id=None,
                section_title=anchor.section_title,
                section_role=list(anchor.section_role),
                section_index=anchor.section_index,
                content=content,
                metadata={
                    "source_ref": f"fixed-window://{paper_id}/{window_index}",
                    "baseline": "fixed_window",
                    "window_index": window_index,
                    "window_token_start": start,
                    "window_token_end": end,
                    "source_chunk_ids": source_chunk_ids,
                    "source_evidence_types": source_evidence_types,
                    "source_locators": source_locators,
                    "source_image_refs": source_image_refs,
                },
            ))
            if end >= len(tokens):
                break
            start += step
            window_index += 1
        return windows


def _tokenize(text: str) -> list[str]:
    return [token for token in str(text or "").split() if token]


def _evidence_type(chunk: PaperChunk) -> str:
    if chunk.chunk_type == "formula" or chunk.has_formula:
        return "formula"
    if chunk.chunk_type == "figure" or chunk.has_figure:
        return "figure"
    if chunk.chunk_type == "table" or chunk.has_table:
        return "table"
    return chunk.chunk_type


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


__all__ = ["FixedWindowBaselineChunker", "FixedWindowChunkerConfig"]
