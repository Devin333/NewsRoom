from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.rag.models import GroundedAnswerCandidate, RAGContextPack
from framework.shared.graph_identity import GraphExecutionIdentity


@runtime_checkable
class AnswerWorkerPort(Protocol):
    """Drafts grounded answer candidates from verified context packs."""

    def generate_answer(
        self,
        *,
        question: str,
        pack: RAGContextPack,
        execution_identity: GraphExecutionIdentity | None = None,
    ) -> GroundedAnswerCandidate:
        """Return an answer candidate. Controller/gates decide acceptance."""
        ...


__all__ = ["AnswerWorkerPort"]
