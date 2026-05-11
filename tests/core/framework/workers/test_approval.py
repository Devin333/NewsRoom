from datetime import UTC, datetime

import pytest

from core.framework.workers import (
    ApprovalAlreadyDecidedError,
    ApprovalDecision,
    ApprovalNotFoundError,
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
)


def test_approval_request_round_trips_json_safe_dict() -> None:
    request = ApprovalRequest(
        approval_id="appr-1",
        requested_action="publish_report",
        risk_level="high",
        reason="publish requires operator approval",
        payload={"report_id": "report-1"},
        task_id="task-1",
        run_id="run-1",
        requested_by="worker",
        created_at=_dt("2026-05-11T00:00:00Z"),
        expires_at=_dt("2026-05-12T00:00:00Z"),
        metadata={"queue_name": "news:queue:publish"},
    )

    restored = ApprovalRequest.from_dict(request.to_dict())

    assert restored.approval_id == "appr-1"
    assert restored.status == ApprovalStatus.PENDING
    assert restored.requested_action == "publish_report"
    assert restored.payload == {"report_id": "report-1"}
    assert restored.created_at == _dt("2026-05-11T00:00:00Z")
    assert restored.expires_at == _dt("2026-05-12T00:00:00Z")


def test_approval_request_rejects_secret_payload_keys() -> None:
    with pytest.raises(ValueError, match="payload key"):
        ApprovalRequest(
            requested_action="send_notification",
            payload={"api_key": "do-not-store"},
        )


def test_in_memory_approval_store_lists_pending_and_records_decision() -> None:
    pending = ApprovalRequest(
        approval_id="pending",
        requested_action="publish_report",
        created_at=_dt("2026-05-11T00:00:00Z"),
    )
    rejected = ApprovalRequest(
        approval_id="rejected",
        requested_action="send_notification",
        status="rejected",
        created_at=_dt("2026-05-11T01:00:00Z"),
        decision=ApprovalDecision(
            decision_type="reject",
            decided_by="operator",
            reason="not ready",
            decided_at=_dt("2026-05-11T01:01:00Z"),
        ),
    )
    store = InMemoryApprovalStore([rejected, pending])

    approved = store.record_decision(
        "pending",
        decision=ApprovalDecision(
            decision_type="approve",
            decided_by="operator",
            reason="looks good",
            decided_at=_dt("2026-05-11T02:00:00Z"),
        ),
    )

    assert store.list_approvals(status="pending") == []
    assert store.list_approvals(status="rejected") == [rejected]
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.decision.decided_by == "operator"
    assert approved.decision.reason == "looks good"


def test_approval_modify_requires_modifications() -> None:
    with pytest.raises(ValueError, match="modifications"):
        ApprovalDecision(decision_type="modify", decided_by="operator")


def test_approval_cannot_be_decided_twice() -> None:
    store = InMemoryApprovalStore(
        [
            ApprovalRequest(
                approval_id="approved",
                requested_action="publish_report",
                status="approved",
                decision=ApprovalDecision(decision_type="approve", decided_by="operator"),
            )
        ]
    )

    with pytest.raises(ApprovalAlreadyDecidedError):
        store.record_decision(
            "approved",
            decision=ApprovalDecision(decision_type="reject", decided_by="operator"),
        )


def test_in_memory_approval_store_raises_for_missing() -> None:
    store = InMemoryApprovalStore()

    with pytest.raises(ApprovalNotFoundError):
        store.get_approval("missing")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
