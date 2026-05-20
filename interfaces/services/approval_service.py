from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.workers.approval import (
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalStore,
)
from infrastructure.storage.local_json import LocalJsonApprovalStore


DEFAULT_APPROVAL_STORE_PATH = ".newsroom/approvals/approvals.json"


@dataclass(frozen=True)
class ApprovalListResult:
    approvals: tuple[ApprovalRequest, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_count": len(self.approvals),
            "approvals": [approval.to_dict() for approval in self.approvals],
        }


@dataclass(frozen=True)
class ApprovalDetailResult:
    approval: ApprovalRequest

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval.approval_id,
            "approval": self.approval.to_dict(),
        }


@dataclass(frozen=True)
class ApprovalResumeContextResult:
    approval: ApprovalRequest
    decision_key: str
    decision_payload: dict[str, Any]
    buffer_updates: dict[str, Any]
    resume_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        resume_metadata = dict(self.resume_metadata)
        resume_metadata.setdefault("reviewer_trace", _approval_reviewer_trace(self.approval))
        return {
            "approval_id": self.approval.approval_id,
            "approval": self.approval.to_dict(),
            "decision_key": self.decision_key,
            "decision_payload": dict(self.decision_payload),
            "buffer_updates": dict(self.buffer_updates),
            "resume_metadata": resume_metadata,
        }


class ApprovalApplicationService:
    def __init__(
        self,
        *,
        store: ApprovalStore | None = None,
        store_path: str | Path = DEFAULT_APPROVAL_STORE_PATH,
    ) -> None:
        self.store = store or LocalJsonApprovalStore(store_path)

    def submit_request(
        self,
        *,
        requested_action: str,
        risk_level: str = "medium",
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        requested_by: str | None = None,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalDetailResult:
        request = ApprovalRequest(
            requested_action=requested_action,
            risk_level=risk_level,
            reason=reason,
            payload=payload or {},
            task_id=task_id,
            run_id=run_id,
            requested_by=requested_by,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        return ApprovalDetailResult(self.store.upsert_approval(request))

    def list_approvals(self, *, status: ApprovalStatus | str | None = None) -> ApprovalListResult:
        return ApprovalListResult(tuple(self.store.list_approvals(status=status)))

    def get_approval(self, approval_id: str) -> ApprovalDetailResult:
        return ApprovalDetailResult(self.store.get_approval(approval_id))

    def build_resume_context(
        self,
        approval_id: str,
        *,
        decision_key: str = "human_review_decision",
    ) -> ApprovalResumeContextResult:
        if not decision_key:
            raise ValueError("decision_key is required")
        approval = self.store.get_approval(approval_id)
        if approval.decision is None or approval.status == ApprovalStatus.PENDING:
            raise ValueError(f"approval decision is not recorded: {approval_id}")
        decision_payload = _approval_decision_payload(approval)
        resume_metadata = _approval_resume_metadata(approval)
        return ApprovalResumeContextResult(
            approval=approval,
            decision_key=decision_key,
            decision_payload=decision_payload,
            buffer_updates={decision_key: decision_payload},
            resume_metadata=resume_metadata,
        )

    def approve(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> ApprovalDetailResult:
        return self._record_decision(
            approval_id,
            decision_type=ApprovalDecisionType.APPROVE,
            decided_by=decided_by,
            reason=reason,
        )

    def reject(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> ApprovalDetailResult:
        return self._record_decision(
            approval_id,
            decision_type=ApprovalDecisionType.REJECT,
            decided_by=decided_by,
            reason=reason,
        )

    def modify(
        self,
        approval_id: str,
        *,
        decided_by: str,
        modifications: dict[str, Any],
        reason: str | None = None,
    ) -> ApprovalDetailResult:
        return self._record_decision(
            approval_id,
            decision_type=ApprovalDecisionType.MODIFY,
            decided_by=decided_by,
            reason=reason,
            modifications=modifications,
        )

    def _record_decision(
        self,
        approval_id: str,
        *,
        decision_type: ApprovalDecisionType,
        decided_by: str,
        reason: str | None = None,
        modifications: dict[str, Any] | None = None,
    ) -> ApprovalDetailResult:
        decision = ApprovalDecision(
            decision_type=decision_type,
            decided_by=decided_by,
            reason=reason,
            modifications=modifications or {},
        )
        return ApprovalDetailResult(
            self.store.record_decision(
                approval_id,
                decision=decision,
            )
        )


def _approval_decision_payload(approval: ApprovalRequest) -> dict[str, Any]:
    if approval.decision is None:
        raise ValueError(f"approval decision is not recorded: {approval.approval_id}")
    decision_type = approval.decision.decision_type.value
    return {
        "decision": _resume_decision(decision_type),
        "status": approval.status.value,
        "decision_type": decision_type,
        "approval_id": approval.approval_id,
        "requested_action": approval.requested_action,
        "risk_level": approval.risk_level,
        "reason": approval.decision.reason,
        "decided_by": approval.decision.decided_by,
        "decided_at": approval.decision.to_dict()["decided_at"],
        "modifications": dict(approval.decision.modifications),
        "task_id": approval.task_id,
        "run_id": approval.run_id,
        "requested_by": approval.requested_by,
    }


def _approval_resume_metadata(approval: ApprovalRequest) -> dict[str, Any]:
    if approval.decision is None:
        raise ValueError(f"approval decision is not recorded: {approval.approval_id}")
    metadata: dict[str, Any] = {
        "approval_id": approval.approval_id,
        "approval_status": approval.status.value,
        "decision_type": approval.decision.decision_type.value,
        "requested_action": approval.requested_action,
        "risk_level": approval.risk_level,
        "decided_by": approval.decision.decided_by,
    }
    if approval.task_id:
        metadata["task_id"] = approval.task_id
    if approval.run_id:
        metadata["approval_run_id"] = approval.run_id
    return metadata


def _approval_reviewer_trace(approval: ApprovalRequest) -> dict[str, Any]:
    if approval.decision is None:
        raise ValueError(f"approval decision is not recorded: {approval.approval_id}")
    return {
        "approval_id": approval.approval_id,
        "approval_status": approval.status.value,
        "decision_type": approval.decision.decision_type.value,
        "requested_action": approval.requested_action,
        "risk_level": approval.risk_level,
        "decided_by": approval.decision.decided_by,
        "reason": approval.decision.reason,
        "modifications": dict(approval.decision.modifications),
    }


def _resume_decision(decision_type: str) -> str:
    if decision_type == ApprovalDecisionType.APPROVE.value:
        return "approved"
    if decision_type == ApprovalDecisionType.REJECT.value:
        return "rejected"
    return "approved"
