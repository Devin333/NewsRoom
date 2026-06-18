from datetime import UTC, datetime

import pytest

from framework.workers import (
    ApprovalDecision,
    ApprovalNotFoundError,
    ApprovalRequest,
    ApprovalStatus,
)
from infrastructure.storage.local_json import LocalJsonApprovalStore


def test_local_json_approval_store_persists_requests(tmp_path) -> None:
    path = tmp_path / "approvals.json"
    store = LocalJsonApprovalStore(path)
    request = ApprovalRequest(
        approval_id="appr-1",
        requested_action="publish_report",
        payload={"report_id": "report-1"},
        created_at=_dt("2026-05-11T00:00:00Z"),
    )

    store.upsert_approval(request)
    restored = LocalJsonApprovalStore(path).get_approval("appr-1")

    assert restored.approval_id == "appr-1"
    assert restored.requested_action == "publish_report"
    assert restored.payload == {"report_id": "report-1"}


def test_local_json_approval_store_filters_and_records_decision(tmp_path) -> None:
    store = LocalJsonApprovalStore(tmp_path / "approvals.json")
    store.upsert_approval(
        ApprovalRequest(
            approval_id="appr-1",
            requested_action="publish_report",
            created_at=_dt("2026-05-11T00:00:00Z"),
        )
    )
    store.upsert_approval(
        ApprovalRequest(
            approval_id="appr-2",
            requested_action="send_notification",
            status="rejected",
            decision=ApprovalDecision(decision_type="reject", decided_by="operator"),
            created_at=_dt("2026-05-11T01:00:00Z"),
        )
    )

    approved = store.record_decision(
        "appr-1",
        decision=ApprovalDecision(decision_type="approve", decided_by="operator"),
    )

    assert approved.status == ApprovalStatus.APPROVED
    assert store.list_approvals(status="pending") == []
    assert [item.approval_id for item in store.list_approvals(status="rejected")] == ["appr-2"]
    assert LocalJsonApprovalStore(tmp_path / "approvals.json").get_approval("appr-1").status == ApprovalStatus.APPROVED


def test_local_json_approval_store_raises_for_missing(tmp_path) -> None:
    store = LocalJsonApprovalStore(tmp_path / "approvals.json")

    with pytest.raises(ApprovalNotFoundError):
        store.get_approval("missing")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
