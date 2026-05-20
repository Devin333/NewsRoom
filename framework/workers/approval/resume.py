from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.workers.approval.model import ApprovalDecisionType, ApprovalRequest, ApprovalStatus


@dataclass(frozen=True)
class ApprovalResumeContext:
    approval_id: str
    run_id: str
    task_id: str | None
    decision_type: ApprovalDecisionType
    modifications: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "decision_type": self.decision_type.value,
            "modifications": dict(self.modifications),
            "metadata": dict(self.metadata),
        }


def build_approval_resume_context(request: ApprovalRequest) -> ApprovalResumeContext:
    if request.decision is None:
        raise ValueError("approval decision is required")
    if not request.run_id:
        raise ValueError("approval run_id is required")
    return ApprovalResumeContext(
        approval_id=request.approval_id,
        run_id=request.run_id,
        task_id=request.task_id,
        decision_type=ApprovalDecisionType(request.decision.decision_type),
        modifications=dict(request.decision.modifications),
        metadata={
            **dict(request.metadata),
            "approval_status": ApprovalStatus(request.status).value,
            "requested_action": request.requested_action,
        },
    )
