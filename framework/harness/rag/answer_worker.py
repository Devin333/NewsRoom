from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.rag.models import GroundedAnswerCandidate, RAGContextPack


@runtime_checkable
class AnswerWorkerPort(Protocol):
    """Drafts grounded answer candidates from verified context packs."""

    def generate_answer(self, *, question: str, pack: RAGContextPack) -> GroundedAnswerCandidate:
        """Return an answer candidate. Controller/gates decide acceptance."""
        ...


__all__ = ["AnswerWorkerPort"]
