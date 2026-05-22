from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


PolicyRiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class MemoryPolicyProposal:
    proposal_id: str
    target: str
    old_value: Any
    new_value: Any
    reason: str
    confidence: float
    risk_level: PolicyRiskLevel = "medium"
    evidence: list[str] = field(default_factory=list)
    requires_human_approval: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def can_auto_apply(self) -> bool:
        return self.risk_level == "low" and not self.requires_human_approval

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "target": self.target,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "evidence": list(self.evidence),
            "requires_human_approval": self.requires_human_approval,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AdaptiveThresholdSet:
    source_reliability_min: float = 0.3
    claim_confidence_min: float = 0.5
    event_novelty_min: float = 0.2
    duplicate_penalty_threshold: float = 0.5
    contradiction_block_threshold: float = 0.8


__all__ = ["AdaptiveThresholdSet", "MemoryPolicyProposal", "PolicyRiskLevel"]
