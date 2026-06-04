from __future__ import annotations

from dataclasses import dataclass

from framework.harness.rag.gates import RAGGateResult, RAGLineageGate, RAGSourceQualityGate
from framework.harness.rag.models import EvidenceCandidate
from framework.harness.rag.policy import RAGExecutionPolicy


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
    def __init__(self) -> None:
        self.source_quality = RAGSourceQualityGate()
        self.lineage = RAGLineageGate()

    def verify(
        self,
        evidence: tuple[EvidenceCandidate, ...],
        *,
        policy: RAGExecutionPolicy,
    ) -> SourceVerificationResult:
        accepted: list[EvidenceCandidate] = []
        rejected: list[EvidenceCandidate] = []
        conflicting: list[EvidenceCandidate] = []
        for candidate in evidence:
            candidate_results = (
                self.source_quality.evaluate((candidate,), policy),
                self.lineage.evaluate((candidate,)),
            )
            if candidate.metadata.get("conflict") is True or candidate.metadata.get("conflicts_with"):
                conflicting.append(candidate)
            elif all(result.passed for result in candidate_results):
                accepted.append(candidate)
            else:
                rejected.append(candidate)
        gate_results = (
            self.source_quality.evaluate(evidence, policy),
            self.lineage.evaluate(evidence),
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
