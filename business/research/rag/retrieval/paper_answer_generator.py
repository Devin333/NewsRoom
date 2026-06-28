from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import re
from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.adapters.paper_field_text import extract_field_texts
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
_CONTEXT_FIELD_ORDER = ("title", "abstract", "caption", "equation", "body")


class AnswerContextAssembler:
    """Builds compact generation context from retrieval hits and expansions."""

    strategy_name = "answer_context_assembler_v1"

    def __init__(self, *, max_context_chunks: int = 5) -> None:
        self._max_chunks = max_context_chunks

    def select(
        self,
        retrieval: RetrievalResult,
        *,
        required_context_ids: list[str] | tuple[str, ...] = (),
    ) -> AnswerContextSelection:
        candidates = _dedupe_chunks([
            *retrieval.child_chunks,
            *retrieval.ref_chunks,
            *retrieval.parent_chunks,
        ])
        by_id = {chunk.chunk_id: chunk for chunk in candidates}
        bucket_by_id = _bucket_map(retrieval)
        selected: list[PaperChunk] = []
        related_ids: list[str] = []
        required_ids = _unique_texts(list(required_context_ids))
        missing_required_ids: list[str] = []

        for chunk_id in required_ids:
            chunk = by_id.get(chunk_id)
            if chunk is None:
                missing_required_ids.append(chunk_id)
                continue
            _append_chunk(selected, chunk)
        required_chunks = list(selected)
        for chunk in required_chunks:
            for related_id in _related_context_ids(chunk):
                related = by_id.get(related_id)
                if related is None:
                    continue
                related_ids.append(related_id)
                _append_chunk(selected, related)
            if len(selected) >= self._max_chunks:
                break

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
                "required_context_ids": required_ids,
                "selected_required_context_ids": [
                    chunk.chunk_id for chunk in selected
                    if chunk.chunk_id in set(required_ids)
                ],
                "missing_required_context_ids": missing_required_ids,
                "required_context_coverage": _required_context_coverage(selected, required_ids),
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

    async def generate(
        self,
        question: str,
        retrieval: RetrievalResult,
        *,
        required_context_ids: list[str] | tuple[str, ...] = (),
    ) -> GeneratedAnswer:
        import logging
        import time

        t0 = time.perf_counter()
        selection = self._context_assembler.select(
            retrieval,
            required_context_ids=required_context_ids,
        )
        contexts = [
            _render_context_for_answer(chunk, question=question, max_chars=self._max_chars)
            for chunk in selection.chunks
        ]
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

    def _select_context(
        self,
        retrieval: RetrievalResult,
        *,
        required_context_ids: list[str] | tuple[str, ...] = (),
    ) -> list[PaperChunk]:
        return self._context_assembler.select(
            retrieval,
            required_context_ids=required_context_ids,
        ).chunks

    def _build_prompt(self, question: str, contexts: list[str]) -> str:
        system_instruction = _system_instruction_for_question(question)
        return build_numbered_context_prompt(
            question=question,
            contexts=contexts,
            system_instruction=system_instruction,
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


def _system_instruction_for_question(question: str) -> str:
    lowered = str(question or "").casefold()
    extras: list[str] = []
    if any(token in lowered for token in ("table", "experiment", "result", "benchmark", "accuracy", "score")):
        extras.append(
            "For table or experiment-result questions, include the concrete metrics, averages, deltas, "
            "best/worst comparisons, and the paper's stated conclusion when those details appear in context."
        )
    if any(token in lowered for token in ("equation", "formula")):
        extras.append(
            "For equation questions, explain the variables and what the equation computes; do not only restate LaTeX."
        )
    if "figure" in lowered:
        extras.append(
            "For figure questions, describe the visual/caption evidence and connect it to the nearby text."
        )
    extras.append(
        "When multiple contexts jointly support the answer, cite each supporting context number."
    )
    return " ".join([_SYSTEM_INSTR, *extras])


def _render_context_for_answer(chunk: PaperChunk, *, question: str, max_chars: int) -> str:
    text = _answer_context_text(chunk)
    return _compact_context_text(text, question=question, max_chars=max_chars)


def _answer_context_text(chunk: PaperChunk) -> str:
    fields = extract_field_texts(chunk)
    parts: list[str] = []
    seen: set[str] = set()
    for field_name in _CONTEXT_FIELD_ORDER:
        text = fields.text_for(field_name)
        if text:
            _append_context_part(parts, seen, f"{field_name.title()}: {text}")
    if not parts:
        _append_context_part(parts, seen, chunk.content)
    return "\n".join(parts)


def _append_context_part(parts: list[str], seen: set[str], raw: str) -> None:
    text = " ".join(str(raw or "").split())
    if not text:
        return
    key = text.casefold()
    if key in seen:
        return
    parts.append(text)
    seen.add(key)


def _compact_context_text(text: str, *, question: str, max_chars: int) -> str:
    text = str(text or "").strip()
    max_chars = max(200, int(max_chars))
    if len(text) <= max_chars:
        return text

    head_size = max(120, int(max_chars * 0.55))
    tail_size = max(80, int(max_chars * 0.25))
    middle_size = max_chars - head_size - tail_size - 12
    head = text[:head_size].rsplit(" ", 1)[0].strip() or text[:head_size].strip()
    tail = text[-tail_size:].split(" ", 1)[-1].strip() or text[-tail_size:].strip()
    middle = _query_focused_window(text, question=question, max_chars=middle_size)
    return "\n...\n".join(_unique_texts([head, middle, tail]))[:max_chars].rstrip()


def _query_focused_window(text: str, *, question: str, max_chars: int) -> str:
    if max_chars < 120:
        return ""
    lowered = text.casefold()
    positions = [
        lowered.find(term)
        for term in _context_query_terms(question)
        if lowered.find(term) >= 0
    ]
    if not positions:
        return ""
    best_pos = min(positions)
    start = max(0, best_pos - max_chars // 2)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    window = text[start:end]
    return window.split(" ", 1)[-1].rsplit(" ", 1)[0].strip()


def _context_query_terms(question: str) -> list[str]:
    tokens = [
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", str(question or ""))
    ]
    priority = [
        "average",
        "averages",
        "overall",
        "result",
        "results",
        "accuracy",
        "score",
        "scores",
        "benchmark",
        "benchmarks",
        "table",
        "figure",
        *tokens,
    ]
    return _unique_texts(priority)


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


def _required_context_coverage(chunks: list[PaperChunk], required_ids: list[str]) -> float | None:
    required = set(required_ids)
    if not required:
        return None
    selected = {chunk.chunk_id for chunk in chunks}
    return len(required & selected) / len(required)


__all__ = ["AnswerContextAssembler", "AnswerGenerator", "GeneratedAnswer"]
