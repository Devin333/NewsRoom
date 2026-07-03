from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.rag.gates import RAGGateResult
from framework.harness.rag.models import EvidenceCandidate


@runtime_checkable
class RelevanceScorerPort(Protocol):
    """Scores passages against the original RAG goal question."""

    def score(self, question: str, passages: list[str]) -> list[float]:
        """Return one score in [0, 1] for each passage."""
        ...


class RAGRelevanceGate:
    gate_name = "rag_relevance"

    def __init__(self, *, default_threshold: float = 0.30) -> None:
        self._default_threshold = float(default_threshold)

    def evaluate(
        self,
        question: str,
        evidence: tuple[EvidenceCandidate, ...],
        scores: tuple[float, ...],
        *,
        threshold: float | None = None,
    ) -> RAGGateResult:
        limit = self._default_threshold if threshold is None else float(threshold)
        mismatched = len(scores) != len(evidence)
        low_relevance = [
            {
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type,
                "score": round(float(score), 4),
            }
            for item, score in zip(evidence, scores)
            if float(score) < limit
        ]
        passed = not mismatched and not low_relevance
        return RAGGateResult(
            self.gate_name,
            passed,
            None if passed else "one or more evidence candidates fall below the relevance threshold",
            {
                "question": question,
                "threshold": limit,
                "scored": len(scores),
                "evidence_count": len(evidence),
                "score_count_mismatch": mismatched,
                "low_relevance": low_relevance,
            },
        )


__all__ = [
    "RAGRelevanceGate",
    "RelevanceScorerPort",
]
