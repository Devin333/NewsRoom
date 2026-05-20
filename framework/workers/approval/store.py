from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from framework.workers.approval.model import (
    ApprovalDecision,
    ApprovalNotFoundError,
    ApprovalRequest,
    ApprovalStatus,
)


class ApprovalStore(Protocol):
    def list_approvals(self, *, status: ApprovalStatus | str | None = None) -> list[ApprovalRequest]: ...

    def get_approval(self, approval_id: str) -> ApprovalRequest: ...

    def upsert_approval(self, request: ApprovalRequest) -> ApprovalRequest: ...

    def record_decision(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
    ) -> ApprovalRequest: ...


class InMemoryApprovalStore:
    def __init__(
        self,
        requests: list[ApprovalRequest] | None = None,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._requests = {request.approval_id: request for request in requests or []}
        self.now_fn = now_fn or (lambda: datetime.now(UTC))

    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        return self.upsert_approval(request)

    def get(self, approval_id: str) -> ApprovalRequest:
        return self.get_approval(approval_id)

    def decide(self, approval_id: str, decision: ApprovalDecision) -> ApprovalRequest:
        return self.record_decision(approval_id, decision=decision)

    def list_approvals(self, *, status: ApprovalStatus | str | None = None) -> list[ApprovalRequest]:
        records = sorted(self._requests.values(), key=lambda request: request.created_at)
        if status is None:
            return records
        actual_status = ApprovalStatus(status)
        return [request for request in records if request.status == actual_status]

    def get_approval(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise ApprovalNotFoundError(approval_id) from exc

    def upsert_approval(self, request: ApprovalRequest) -> ApprovalRequest:
        self._requests[request.approval_id] = request
        return request

    def record_decision(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
    ) -> ApprovalRequest:
        request = self.get_approval(approval_id)
        decided = request.with_decision(decision)
        self.upsert_approval(decided)
        return decided
