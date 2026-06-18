from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from business.research.document.models import PaperChunk
from business.research.rag.retriever import RetrievalResult


@dataclass
class GeneratedAnswer:
    question: str
    answer: str
    context_chunk_ids: list[str] = field(default_factory=list)  # chunks fed to the LLM
    contexts: list[str] = field(default_factory=list)           # context texts (for eval)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "context_chunk_ids": self.context_chunk_ids,
            "contexts": self.contexts,
        }


_SYSTEM_INSTR = (
    "You are a research assistant answering questions about an academic paper. "
    "Answer ONLY from the numbered context passages below. "
    "Cite the passages you use with bracketed numbers like [1], [2]. "
    "If the context does not contain the answer, say so explicitly. "
    "Be concise and precise."
)


class AnswerGenerator:
    """Generates a grounded answer from retrieval context (RAG generation step)."""

    def __init__(
        self,
        llm_call: Callable[[str], Awaitable[str]],
        *,
        max_context_chunks: int = 3,
        max_chars_per_chunk: int = 1000,
    ) -> None:
        self._llm = llm_call
        self._max_chunks = max_context_chunks
        self._max_chars = max_chars_per_chunk

    async def generate(self, question: str, retrieval: RetrievalResult) -> GeneratedAnswer:
        import time
        import logging
        t0 = time.perf_counter()
        chunks = self._select_context(retrieval)
        contexts = [c.content[: self._max_chars] for c in chunks]
        prompt = self._build_prompt(question, contexts)
        try:
            answer = (await self._llm(prompt)).strip()
        except Exception as exc:
            logging.getLogger(__name__).warning("generation failed, using empty answer: %s", exc)
            answer = ""
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        logging.getLogger(__name__).info(
            "generation %s",
            {"context_chunks": len(chunks), "answer_chars": len(answer), "elapsed_ms": elapsed_ms},
        )
        return GeneratedAnswer(
            question=question,
            answer=answer,
            context_chunk_ids=[c.chunk_id for c in chunks],
            contexts=contexts,
        )

    def _select_context(self, retrieval: RetrievalResult) -> list[PaperChunk]:
        # Feed the reranker-ranked paragraph (child) chunks — they are the highest-precision
        # unit. Parent (section) chunks carry too much off-topic text and hurt Context Precision.
        # Fall back to parents only when no children were matched.
        chunks = retrieval.child_chunks or retrieval.parent_chunks
        return chunks[: self._max_chunks]

    def _build_prompt(self, question: str, contexts: list[str]) -> str:
        numbered = "\n\n".join(f"[{i + 1}] {text}" for i, text in enumerate(contexts))
        return (
            f"{_SYSTEM_INSTR}\n\n"
            f"Context passages:\n{numbered}\n\n"
            f"Question: {question}\n\n"
            "Answer (with citations):"
        )


__all__ = ["AnswerGenerator", "GeneratedAnswer"]
