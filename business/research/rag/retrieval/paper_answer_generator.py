from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.paper_retriever import RetrievalResult
from framework.rag.context import collect_nearby_context_ids
from framework.rag.generation import (
    DEFAULT_GROUNDED_SYSTEM_INSTRUCTION,
    GeneratedRAGAnswer,
    build_numbered_context_prompt,
)


@dataclass
class GeneratedAnswer:
    question: str
    answer: str
    context_chunk_ids: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    context_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "context_chunk_ids": self.context_chunk_ids,
            "contexts": self.contexts,
            "context_metadata": dict(self.context_metadata),
        }

    def to_kernel_answer(self) -> GeneratedRAGAnswer:
        return GeneratedRAGAnswer(
            question=self.question,
            answer=self.answer,
            context_ids=tuple(self.context_chunk_ids),
            contexts=tuple(self.contexts),
            metadata=dict(self.context_metadata),
        )


@dataclass(frozen=True)
class AnswerContextSelection:
    chunks: list[PaperChunk]
    metadata: dict[str, Any]


_SYSTEM_INSTR = DEFAULT_GROUNDED_SYSTEM_INSTRUCTION


class AnswerContextAssembler:
    """Builds compact generation context from retrieval hits and expansions."""

    strategy_name = "answer_context_assembler_v1"

    def __init__(self, *, max_context_chunks: int = 5) -> None:
        self._max_chunks = max_context_chunks

    def select(self, retrieval: RetrievalResult) -> AnswerContextSelection:
        candidates = _dedupe_chunks([
            *retrieval.child_chunks,
            *retrieval.ref_chunks,
            *retrieval.parent_chunks,
        ])
        by_id = {chunk.chunk_id: chunk for chunk in candidates}
        bucket_by_id = _bucket_map(retrieval)
        selected: list[PaperChunk] = []
        related_ids: list[str] = []

        anchors = retrieval.child_chunks or retrieval.parent_chunks
        for anchor in anchors:
            _append_chunk(selected, anchor)
            for related_id in _related_context_ids(anchor):
                related = by_id.get(related_id)
                if related is None:
                    continue
                related_ids.append(related_id)
                _append_chunk(selected, related)
            if len(selected) >= self._max_chunks:
                break

        for chunk in candidates:
            if len(selected) >= self._max_chunks:
                break
            _append_chunk(selected, chunk)

        selected = selected[: self._max_chunks]
        return AnswerContextSelection(
            chunks=selected,
            metadata={
                "context_selection_strategy": self.strategy_name,
                "context_source_buckets": {
                    chunk.chunk_id: bucket_by_id.get(chunk.chunk_id, "unknown")
                    for chunk in selected
                },
                "related_context_ids": _unique_texts(related_ids),
                "retrieved_chunk_ids": [chunk.chunk_id for chunk in candidates],
            },
        )


class AnswerGenerator:
    """Generates a grounded answer from retrieval context."""

    def __init__(
        self,
        llm_call: Callable[[str], Awaitable[str]],
        *,
        max_context_chunks: int = 5,
        max_chars_per_chunk: int = 1000,
    ) -> None:
        self._llm = llm_call
        self._max_chars = max_chars_per_chunk
        self._context_assembler = AnswerContextAssembler(max_context_chunks=max_context_chunks)

    async def generate(self, question: str, retrieval: RetrievalResult) -> GeneratedAnswer:
        import logging
        import time

        t0 = time.perf_counter()
        selection = self._context_assembler.select(retrieval)
        contexts = [chunk.content[: self._max_chars] for chunk in selection.chunks]
        prompt = self._build_prompt(question, contexts)
        try:
            answer = (await self._llm(prompt)).strip()
        except Exception as exc:
            logging.getLogger(__name__).warning("generation failed, using empty answer: %s", exc)
            answer = ""
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        logging.getLogger(__name__).info(
            "generation %s",
            {"context_chunks": len(selection.chunks), "answer_chars": len(answer), "elapsed_ms": elapsed_ms},
        )
        return GeneratedAnswer(
            question=question,
            answer=answer,
            context_chunk_ids=[chunk.chunk_id for chunk in selection.chunks],
            contexts=contexts,
            context_metadata=selection.metadata,
        )

    def _select_context(self, retrieval: RetrievalResult) -> list[PaperChunk]:
        return self._context_assembler.select(retrieval).chunks

    def _build_prompt(self, question: str, contexts: list[str]) -> str:
        return build_numbered_context_prompt(
            question=question,
            contexts=contexts,
            system_instruction=_SYSTEM_INSTR,
        )


def _bucket_map(retrieval: RetrievalResult) -> dict[str, str]:
    out: dict[str, str] = {}
    for bucket, chunks in (
        ("child", retrieval.child_chunks),
        ("ref", retrieval.ref_chunks),
        ("parent", retrieval.parent_chunks),
    ):
        for chunk in chunks:
            out.setdefault(chunk.chunk_id, bucket)
    return out


def _related_context_ids(chunk: PaperChunk) -> list[str]:
    return list(collect_nearby_context_ids(
        metadata=chunk.metadata,
        parent_id=chunk.parent_chunk_id or "",
    ).ids)


def _append_chunk(chunks: list[PaperChunk], chunk: PaperChunk) -> None:
    if any(existing.chunk_id == chunk.chunk_id for existing in chunks):
        return
    chunks.append(chunk)


def _dedupe_chunks(chunks: list[PaperChunk]) -> list[PaperChunk]:
    seen: set[str] = set()
    out: list[PaperChunk] = []
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        out.append(chunk)
    return out


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


__all__ = ["AnswerContextAssembler", "AnswerGenerator", "GeneratedAnswer"]
