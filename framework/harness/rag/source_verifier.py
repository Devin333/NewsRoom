from __future__ import annotations

from dataclasses import dataclass

from framework.harness.rag.gates import RAGGateResult, RAGLineageGate, RAGSourceQualityGate
from framework.harness.rag.models import EvidenceCandidate
from framework.harness.rag.policy import RAGExecutionPolicy
from framework.harness.rag.relevance import RAGRelevanceGate, RelevanceScorerPort


@dataclass(frozen=True)
class SourceVerificationResult:
    accepted: tuple[EvidenceCandidate, ...]
    rejected: tuple[EvidenceCandidate, ...]
    conflicting: tuple[EvidenceCandidate, ...]
    gate_results: tuple[RAGGateResult, ...]

    def to_dict(self) -> dict:
        return {
            "accepted": [item.to_dict() for item in self.accepted],
            "rejected": [item.to_dict() for item in self.rejected],
            "conflicting": [item.to_dict() for item in self.conflicting],
            "gate_results": [item.to_dict() for item in self.gate_results],
        }


class SourceVerifier:
    def __init__(
        self,
        *,
        relevance_scorer: RelevanceScorerPort | None = None,
        relevance_gate: RAGRelevanceGate | None = None,
    ) -> None:
        self.source_quality = RAGSourceQualityGate()
        self.lineage = RAGLineageGate()
        self.relevance_scorer = relevance_scorer
        self.relevance_gate = relevance_gate or RAGRelevanceGate()

    def verify(
        self,
        evidence: tuple[EvidenceCandidate, ...],
        *,
        policy: RAGExecutionPolicy,
        question: str | None = None,
    ) -> SourceVerificationResult:
        relevance_result = _relevance_result(
            evidence,
            policy=policy,
            question=question,
            scorer=self.relevance_scorer,
        )
        accepted: list[EvidenceCandidate] = []
        rejected: list[EvidenceCandidate] = []
        conflicting: list[EvidenceCandidate] = []
        for candidate in evidence:
            relevance_threshold = _relevance_threshold(candidate, policy)
            candidate_results = (
                self.source_quality.evaluate((candidate,), policy),
                self.lineage.evaluate((candidate,)),
            )
            if candidate.metadata.get("conflict") is True or candidate.metadata.get("conflicts_with"):
                conflicting.append(candidate)
            elif (
                self.relevance_scorer is not None
                and candidate.evidence_id in relevance_result.scores_by_id
                and relevance_result.scores_by_id[candidate.evidence_id] < relevance_threshold
            ):
                rejected.append(_with_rejection_metadata(
                    candidate,
                    reason="low_relevance"
                    if len(relevance_result.ordered_scores) == len(evidence)
                    else "relevance_score_unavailable",
                    relevance_score=relevance_result.scores_by_id[candidate.evidence_id],
                    relevance_threshold=relevance_threshold,
                ))
            elif all(result.passed for result in candidate_results):
                accepted.append(candidate)
            else:
                rejected.append(candidate)
        gate_results = (
            self.source_quality.evaluate(evidence, policy),
            self.lineage.evaluate(evidence),
        )
        if self.relevance_scorer is not None and question and evidence:
            gate_results = (
                *gate_results,
                self.relevance_gate.evaluate(
                    question,
                    evidence,
                    relevance_result.ordered_scores,
                    threshold=_default_relevance_threshold(policy),
                    thresholds_by_evidence_type=_typed_relevance_thresholds(policy),
                ),
            )
        return SourceVerificationResult(
            accepted=tuple(accepted),
            rejected=tuple(rejected),
            conflicting=tuple(conflicting),
            gate_results=gate_results,
        )


class FakeSourceVerifier(SourceVerifier):
    pass


__all__ = ["FakeSourceVerifier", "SourceVerificationResult", "SourceVerifier"]


@dataclass(frozen=True)
class _RelevanceResult:
    scores_by_id: dict[str, float]
    ordered_scores: tuple[float, ...]


def _relevance_result(
    evidence: tuple[EvidenceCandidate, ...],
    *,
    policy: RAGExecutionPolicy,
    question: str | None,
    scorer: RelevanceScorerPort | None,
) -> _RelevanceResult:
    if scorer is None or not question or not evidence:
        return _RelevanceResult(scores_by_id={}, ordered_scores=())
    scores = scorer.score(question, [item.summary for item in evidence])
    if len(scores) != len(evidence):
        threshold = float(policy.source_policy.get("min_relevance", 0.30))
        return _RelevanceResult(
            scores_by_id={item.evidence_id: threshold - 1.0 for item in evidence},
            ordered_scores=tuple(float(score) for score in scores),
        )
    clamped_scores = tuple(max(0.0, min(float(score), 1.0)) for score in scores)
    return _RelevanceResult(
        scores_by_id={
            item.evidence_id: score
            for item, score in zip(evidence, clamped_scores)
        },
        ordered_scores=clamped_scores,
    )


def _default_relevance_threshold(policy: RAGExecutionPolicy) -> float:
    return _safe_float(policy.source_policy.get("min_relevance"), default=0.30)


def _typed_relevance_thresholds(policy: RAGExecutionPolicy) -> dict[str, float]:
    raw = policy.source_policy.get("min_relevance_by_type", {})
    if not isinstance(raw, dict):
        return {}
    thresholds: dict[str, float] = {}
    for key, value in raw.items():
        thresholds[str(key)] = _safe_float(value, default=_default_relevance_threshold(policy))
    return thresholds


def _relevance_threshold(candidate: EvidenceCandidate, policy: RAGExecutionPolicy) -> float:
    typed_thresholds = _typed_relevance_thresholds(policy)
    for key in _threshold_keys(candidate):
        if key in typed_thresholds:
            return typed_thresholds[key]
    return _default_relevance_threshold(policy)


def _safe_float(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _threshold_keys(candidate: EvidenceCandidate) -> tuple[str, ...]:
    keys = [candidate.evidence_type]
    chunk_type = candidate.metadata.get("chunk_type")
    if chunk_type is not None:
        keys.append(str(chunk_type))
    return tuple(dict.fromkeys(key for key in keys if key))


def _with_rejection_metadata(
    candidate: EvidenceCandidate,
    *,
    reason: str,
    relevance_score: float,
    relevance_threshold: float,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=candidate.evidence_id,
        title=candidate.title,
        summary=candidate.summary,
        source_ref=candidate.source_ref,
        span_refs=candidate.span_refs,
        evidence_type=candidate.evidence_type,
        claim_refs=candidate.claim_refs,
        confidence=candidate.confidence,
        freshness=candidate.freshness,
        lineage=candidate.lineage,
        artifact_refs=candidate.artifact_refs,
        metadata={
            **candidate.metadata,
            "rejection_reason": reason,
            "relevance_score": relevance_score,
            "relevance_threshold": relevance_threshold,
        },
    )
