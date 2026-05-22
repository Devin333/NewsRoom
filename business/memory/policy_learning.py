from __future__ import annotations

from business.memory.adaptive_thresholds import AdaptiveThresholdSet, MemoryPolicyProposal
from business.memory.evaluation import MemoryEvaluationReport
from business.memory.intelligence_builder import stable_id


class MemoryPolicyLearningService:
    def __init__(self, thresholds: AdaptiveThresholdSet | None = None) -> None:
        self.thresholds = thresholds or AdaptiveThresholdSet()

    def propose_updates(self, report: MemoryEvaluationReport) -> list[MemoryPolicyProposal]:
        proposals: list[MemoryPolicyProposal] = []
        proposals.extend(self.propose_claim_threshold_updates(report))
        proposals.extend(self.propose_source_reliability_updates(report))
        proposals.extend(self.propose_duplicate_threshold_updates(report))
        return proposals

    def propose_claim_threshold_updates(self, report: MemoryEvaluationReport) -> list[MemoryPolicyProposal]:
        proposals: list[MemoryPolicyProposal] = []
        metrics = report.metrics
        if metrics.claim_support_rate < 0.75:
            proposals.append(
                _proposal(
                    target="claim_confidence_min",
                    old_value=self.thresholds.claim_confidence_min,
                    new_value=min(0.9, self.thresholds.claim_confidence_min + 0.05),
                    reason="claim support rate below target",
                    confidence=1.0 - metrics.claim_support_rate,
                    risk_level="medium",
                    evidence=report.warnings,
                )
            )
        if metrics.claim_contradiction_rate > 0.25:
            proposals.append(
                _proposal(
                    target="contradiction_block_threshold",
                    old_value=self.thresholds.contradiction_block_threshold,
                    new_value=max(0.5, self.thresholds.contradiction_block_threshold - 0.05),
                    reason="claim contradiction rate elevated",
                    confidence=metrics.claim_contradiction_rate,
                    risk_level="high",
                    evidence=report.warnings,
                )
            )
        return proposals

    def propose_source_reliability_updates(self, report: MemoryEvaluationReport) -> list[MemoryPolicyProposal]:
        if report.metrics.source_false_positive_rate <= 0.25:
            return []
        return [
            _proposal(
                target="source_reliability_min",
                old_value=self.thresholds.source_reliability_min,
                new_value=min(0.9, self.thresholds.source_reliability_min + 0.05),
                reason="source false positive rate elevated",
                confidence=report.metrics.source_false_positive_rate,
                risk_level="medium",
                evidence=report.warnings,
            )
        ]

    def propose_duplicate_threshold_updates(self, report: MemoryEvaluationReport) -> list[MemoryPolicyProposal]:
        if report.metrics.event_duplicate_rate <= 0.2:
            return []
        return [
            _proposal(
                target="duplicate_penalty_threshold",
                old_value=self.thresholds.duplicate_penalty_threshold,
                new_value=max(0.1, self.thresholds.duplicate_penalty_threshold - 0.05),
                reason="event duplicate rate elevated",
                confidence=report.metrics.event_duplicate_rate,
                risk_level="low",
                evidence=report.warnings,
                requires_human_approval=False,
            )
        ]


def _proposal(
    *,
    target: str,
    old_value,
    new_value,
    reason: str,
    confidence: float,
    risk_level: str,
    evidence: list[str],
    requires_human_approval: bool | None = None,
) -> MemoryPolicyProposal:
    approval = risk_level != "low" if requires_human_approval is None else requires_human_approval
    return MemoryPolicyProposal(
        proposal_id=stable_id("memory-policy-proposal", target, old_value, new_value, reason, prefix="proposal"),
        target=target,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        confidence=max(0.0, min(1.0, float(confidence))),
        risk_level=risk_level,  # type: ignore[arg-type]
        evidence=list(evidence),
        requires_human_approval=approval,
    )


__all__ = ["MemoryPolicyLearningService"]
