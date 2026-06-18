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
        max_context_chunks: int = 6,
        max_chars_per_chunk: int = 1000,
    ) -> None:
        self._llm = llm_call
        self._max_chunks = max_context_chunks
        self._max_chars = max_chars_per_chunk

    async def generate(self, question: str, retrieval: RetrievalResult) -> GeneratedAnswer:
        chunks = self._select_context(retrieval)
        contexts = [c.content[: self._max_chars] for c in chunks]
        prompt = self._build_prompt(question, contexts)
        try:
            answer = (await self._llm(prompt)).strip()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("generation failed, using empty answer: %s", exc)
            answer = ""
        return GeneratedAnswer(
            question=question,
            answer=answer,
            context_chunk_ids=[c.chunk_id for c in chunks],
            contexts=contexts,
        )

    def _select_context(self, retrieval: RetrievalResult) -> list[PaperChunk]:
        # parent chunks are the section-level context the retriever returns for the LLM;
        # fall back to child chunks if no parents were expanded.
        chunks = retrieval.parent_chunks or retrieval.child_chunks
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
