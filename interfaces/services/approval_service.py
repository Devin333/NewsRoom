from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.framework.workers.approval import (
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalStore,
)
from storage.local_json import LocalJsonApprovalStore


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
