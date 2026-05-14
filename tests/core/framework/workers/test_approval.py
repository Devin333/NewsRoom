from datetime import UTC, datetime

import pytest

from core.framework.workers import (
    ApprovalAlreadyDecidedError,
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalNotFoundError,
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
    build_approval_resume_context,
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


def test_approval_decision_builds_resume_context_without_artifact_mutation() -> None:
    workflow_artifact = {"run_id": "run-1", "status": "waiting_for_human"}
    store = InMemoryApprovalStore(
        [
            ApprovalRequest(
                approval_id="appr-1",
                requested_action="quality_human_review",
                payload={"report_id": "report-1"},
                task_id="task-1",
                run_id="run-1",
                metadata={"checkpoint_id": "ckpt-1"},
            )
        ]
    )

    decided = store.record_decision(
        "appr-1",
        decision=ApprovalDecision(
            decision_type="modify",
            decided_by="operator",
            modifications={"headline": "Use narrower claim"},
        ),
    )
    context = build_approval_resume_context(decided)

    assert context.run_id == "run-1"
    assert context.task_id == "task-1"
    assert context.decision_type == ApprovalDecisionType.MODIFY
    assert context.modifications == {"headline": "Use narrower claim"}
    assert context.metadata["approval_status"] == "modified"
    assert context.metadata["requested_action"] == "quality_human_review"
    assert workflow_artifact == {"run_id": "run-1", "status": "waiting_for_human"}


def test_approval_resume_context_requires_decision_and_run_id() -> None:
    pending = ApprovalRequest(
        approval_id="appr-1",
        requested_action="tool_approval",
        task_id="task-1",
        run_id="run-1",
    )
    missing_run_id = ApprovalRequest(
        approval_id="appr-2",
        requested_action="tool_approval",
        decision=ApprovalDecision(decision_type="approve", decided_by="operator"),
    )

    with pytest.raises(ValueError, match="decision"):
        build_approval_resume_context(pending)
    with pytest.raises(ValueError, match="run_id"):
        build_approval_resume_context(missing_run_id)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
