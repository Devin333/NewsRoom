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
        thresholds_by_evidence_type: dict[str, float] | None = None,
    ) -> RAGGateResult:
        limit = self._default_threshold if threshold is None else float(threshold)
        typed_thresholds = {
            str(key): float(value)
            for key, value in (thresholds_by_evidence_type or {}).items()
        }
        mismatched = len(scores) != len(evidence)
        low_relevance = [
            {
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type,
                "score": round(float(score), 4),
            }
            for item, score in zip(evidence, scores)
            if float(score) < _threshold_for(item, limit, typed_thresholds)
        ]
        passed = not mismatched and not low_relevance
        return RAGGateResult(
            self.gate_name,
            passed,
            None if passed else "one or more evidence candidates fall below the relevance threshold",
            {
                "question": question,
                "threshold": limit,
                "thresholds_by_evidence_type": typed_thresholds,
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


def _threshold_for(
    item: EvidenceCandidate,
    default: float,
    typed_thresholds: dict[str, float],
) -> float:
    for key in _threshold_keys(item):
        if key in typed_thresholds:
            return typed_thresholds[key]
    return default


def _threshold_keys(item: EvidenceCandidate) -> tuple[str, ...]:
    keys = [item.evidence_type]
    chunk_type = item.metadata.get("chunk_type")
    if chunk_type is not None:
        keys.append(str(chunk_type))
    return tuple(dict.fromkeys(key for key in keys if key))
