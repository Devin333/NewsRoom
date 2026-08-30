from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from framework.rag.retrieval import RerankScoreSet

from backend.research.document.models import PaperChunk
from backend.research.rag.adapters.paper_field_text import FIELD_NAMES, extract_field_texts

if TYPE_CHECKING:
    from backend.research.ports.reranker import RerankerPort


class RerankCascade:
    def __init__(
        self,
        policy: object,
        *,
        reranker: "RerankerPort | None" = None,
        field_reranker: "RerankerPort | None" = None,
    ) -> None:
        self._policy = policy
        self._reranker = reranker
        self._field_reranker = field_reranker

    def base_enabled_for(self, intent: str) -> bool:
        return (
            self._reranker is not None
            and bool(self._policy.reranker_enabled_for(intent))  # type: ignore[attr-defined]
        )

    def field_enabled_for(self, intent: str) -> bool:
        return (
            self._field_reranker is not None
            and bool(self._policy.field_reranker_enabled_for(intent))  # type: ignore[attr-defined]
        )

    def base_scores(
        self,
        question: str,
        candidates: list[tuple[PaperChunk, float]],
        *,
        intent: str,
    ) -> list[float]:
        if not self.base_enabled_for(intent) or not candidates:
            return [sem for _chunk, sem in candidates]
        passages = [chunk.content for chunk, _score in candidates]
        try:
            scores = self._reranker.score(question, passages)  # type: ignore[union-attr]
        except Exception:
            logging.getLogger(__name__).warning("reranker failed, falling back to vector scores")
            return [sem for _chunk, sem in candidates]
        normalized_scores = RerankScoreSet.from_raw(scores, expected_count=len(candidates))
        if normalized_scores is None:
            logging.getLogger(__name__).warning(
                "reranker returned %s scores for %s candidates",
                len(scores),
                len(candidates),
            )
            return [sem for _chunk, sem in candidates]
        return list(normalized_scores.scores)

    def field_scores(
        self,
        question: str,
        chunks: list[PaperChunk],
        *,
        intent: str,
    ) -> dict[str, float]:
        if not self.field_enabled_for(intent) or not chunks:
            return {}
        passages = [field_rerank_passage(chunk) for chunk in chunks]
        try:
            scores = self._field_reranker.score(question, passages)  # type: ignore[union-attr]
        except Exception:
            logging.getLogger(__name__).warning("field reranker failed", exc_info=True)
            return {}
        normalized_scores = RerankScoreSet.from_raw(scores, expected_count=len(chunks))
        if normalized_scores is None:
            logging.getLogger(__name__).warning(
                "field reranker returned %s scores for %s candidates",
                len(scores),
                len(chunks),
            )
            return {}
        return normalized_scores.as_id_map([chunk.chunk_id for chunk in chunks])


def field_rerank_passage(chunk: PaperChunk) -> str:
    field_texts = extract_field_texts(chunk)
    labels = {
        "title": "Title",
        "abstract": "Abstract",
        "caption": "Caption",
        "equation": "Equation",
        "body": "Body",
        "table_rows": "Table rows",
        "table_columns": "Table columns",
        "visual_description": "Visual description",
        "referenced_text": "Referenced text",
    }
    lines = [
        f"Section: {chunk.section_title or ''}".strip(),
        f"Chunk type: {chunk.chunk_type}",
    ]
    for field_name in FIELD_NAMES:
        text = field_texts.text_for(field_name)
        if not text:
            continue
        lines.extend([f"{labels.get(field_name, field_name)}:", text[:1600], ""])
    return "\n".join(lines).strip() or chunk.content[:2000]


__all__ = ["RerankCascade", "field_rerank_passage"]
