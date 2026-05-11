from core.framework.workers import ApprovalStatus, InMemoryApprovalStore
from interfaces.services.approval_service import ApprovalApplicationService


def test_approval_service_submits_and_reads_request() -> None:
    store = InMemoryApprovalStore()
    service = ApprovalApplicationService(store=store)

    result = service.submit_request(
        requested_action="publish_report",
        risk_level="high",
        reason="operator approval required",
        payload={"report_id": "report-1"},
        task_id="task-1",
        run_id="run-1",
        requested_by="worker",
    )
    detail = service.get_approval(result.approval.approval_id)

    assert result.approval.status == ApprovalStatus.PENDING
    assert detail.to_dict()["approval"]["payload"] == {"report_id": "report-1"}


def test_approval_service_lists_by_status_and_approves() -> None:
    store = InMemoryApprovalStore()
    service = ApprovalApplicationService(store=store)
    submitted = service.submit_request(
        requested_action="publish_report",
        payload={"report_id": "report-1"},
    )

    approved = service.approve(
        submitted.approval.approval_id,
        decided_by="operator",
        reason="ready",
    )

    assert service.list_approvals(status="pending").to_dict()["approval_count"] == 0
    assert approved.approval.status == ApprovalStatus.APPROVED
    assert approved.approval.decision.decided_by == "operator"
    assert approved.approval.decision.reason == "ready"


def test_approval_service_rejects_request() -> None:
    service = ApprovalApplicationService(store=InMemoryApprovalStore())
    submitted = service.submit_request(
        requested_action="send_notification",
        payload={"channel": "email"},
    )

    rejected = service.reject(
        submitted.approval.approval_id,
        decided_by="operator",
        reason="wrong audience",
    )

    assert rejected.approval.status == ApprovalStatus.REJECTED
    assert rejected.approval.decision.reason == "wrong audience"


def test_approval_service_modifies_request() -> None:
    service = ApprovalApplicationService(store=InMemoryApprovalStore())
    submitted = service.submit_request(
        requested_action="send_notification",
        payload={"channel": "email"},
    )

    modified = service.modify(
        submitted.approval.approval_id,
        decided_by="operator",
        modifications={"channel": "slack"},
        reason="send internally first",
    )

    assert modified.approval.status == ApprovalStatus.MODIFIED
    assert modified.approval.decision.modifications == {"channel": "slack"}
