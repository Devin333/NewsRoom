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


def test_approval_service_builds_resume_context_from_decision() -> None:
    service = ApprovalApplicationService(store=InMemoryApprovalStore())
    submitted = service.submit_request(
        requested_action="review:analysis",
        risk_level="high",
        payload={"draft_id": "draft-1"},
        task_id="review-step",
        run_id="run-paused",
        requested_by="analyst",
    )
    service.approve(
        submitted.approval.approval_id,
        decided_by="editor",
        reason="ready",
    )

    context = service.build_resume_context(
        submitted.approval.approval_id,
        decision_key="editor_decision",
    )

    assert context.decision_key == "editor_decision"
    assert context.buffer_updates["editor_decision"]["decision"] == "approved"
    assert context.buffer_updates["editor_decision"]["approval_id"] == submitted.approval.approval_id
    assert context.buffer_updates["editor_decision"]["requested_action"] == "review:analysis"
    assert context.resume_metadata == {
        "approval_id": submitted.approval.approval_id,
        "approval_status": "approved",
        "decision_type": "approve",
        "requested_action": "review:analysis",
        "risk_level": "high",
        "decided_by": "editor",
        "task_id": "review-step",
        "approval_run_id": "run-paused",
    }
    assert context.to_dict()["buffer_updates"]["editor_decision"]["decided_by"] == "editor"


def test_approval_service_rejects_resume_context_for_pending_approval() -> None:
    service = ApprovalApplicationService(store=InMemoryApprovalStore())
    submitted = service.submit_request(
        requested_action="review:analysis",
        payload={"draft_id": "draft-1"},
    )

    try:
        service.build_resume_context(submitted.approval.approval_id)
    except ValueError as exc:
        assert "decision is not recorded" in str(exc)
    else:
        raise AssertionError("expected pending approval resume context to fail")


def test_approval_service_modified_resume_context_routes_as_approved() -> None:
    service = ApprovalApplicationService(store=InMemoryApprovalStore())
    submitted = service.submit_request(
        requested_action="review:analysis",
        payload={"draft_id": "draft-1"},
    )
    service.modify(
        submitted.approval.approval_id,
        decided_by="editor",
        modifications={"summary": "tighten lead"},
    )

    context = service.build_resume_context(submitted.approval.approval_id)

    assert context.decision_payload["decision"] == "approved"
    assert context.decision_payload["status"] == "modified"
    assert context.decision_payload["decision_type"] == "modify"
    assert context.decision_payload["modifications"] == {"summary": "tighten lead"}


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
