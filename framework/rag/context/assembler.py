from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from framework.rag.context.budget import ContextBudget, trim_evidence_to_budget
from framework.rag.core import RAGEvidence, RAGQuery
from framework.rag.retrieval.dedup import dedupe_evidence, order_evidence


@dataclass(frozen=True)
class RAGContextAssembler:
    budget: ContextBudget = ContextBudget()

    def assemble(self, query: RAGQuery, evidence: Sequence[RAGEvidence]) -> list[RAGEvidence]:
        ordered = order_evidence(evidence)
        deduped = dedupe_evidence(ordered)
        return trim_evidence_to_budget(deduped, self.budget)


__all__ = ["RAGContextAssembler"]
