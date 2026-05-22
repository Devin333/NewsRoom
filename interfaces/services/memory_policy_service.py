from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.memory.evaluation import MemoryEvaluationReport
from business.memory.policy_learning import MemoryPolicyLearningService


@dataclass(frozen=True)
class MemoryPolicyProposalResult:
    proposals: list[Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "count": len(self.proposals),
            "requires_human_approval": [
                proposal.to_dict()
                for proposal in self.proposals
                if proposal.requires_human_approval
            ],
        }


class MemoryPolicyApplicationService:
    def __init__(self, policy_service: MemoryPolicyLearningService) -> None:
        self.policy_service = policy_service

    def propose_from_report(self, report: MemoryEvaluationReport) -> MemoryPolicyProposalResult:
        return MemoryPolicyProposalResult(proposals=self.policy_service.propose_updates(report))


__all__ = ["MemoryPolicyApplicationService", "MemoryPolicyProposalResult"]
