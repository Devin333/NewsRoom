from fastapi.testclient import TestClient

from core.framework.run_result import RunResult
from core.framework.specs import WorkflowStatus
from interfaces.api import create_app
from interfaces.services.approval_service import ApprovalApplicationService


def test_approval_api_lifecycle_uses_local_json_store(tmp_path) -> None:
    service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    client = TestClient(create_app(approval_service_factory=lambda: service))

    submit_response = client.post(
        "/api/v1/approvals",
        json={
            "requested_action": "publish_report",
            "risk_level": "high",
            "reason": "operator approval required",
            "payload": {"report_id": "report-1"},
            "requested_by": "worker",
        },
    )
    submitted = submit_response.json()
    approval_id = submitted["data"]["approval_id"]

    list_response = client.get("/api/v1/approvals?status=pending")
    approve_response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decided_by": "operator", "reason": "ready"},
    )
    show_response = client.get(f"/api/v1/approvals/{approval_id}")

    assert submit_response.status_code == 200
    assert submitted["success"] is True
    assert list_response.json()["data"]["approval_count"] == 1
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["approval"]["status"] == "approved"
    assert show_response.json()["data"]["approval"]["status"] == "approved"


def test_approval_api_missing_uses_unified_error(tmp_path) -> None:
    service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    client = TestClient(create_app(approval_service_factory=lambda: service))

    response = client.get("/api/v1/approvals/missing")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "approval_not_found"


def test_approval_api_already_decided_uses_conflict(tmp_path) -> None:
    service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    client = TestClient(create_app(approval_service_factory=lambda: service))
    approval_id = client.post(
        "/api/v1/approvals",
        json={"requested_action": "send_notification", "payload": {"channel": "email"}},
    ).json()["data"]["approval_id"]
    client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        json={"decided_by": "operator", "reason": "not ready"},
    )

    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decided_by": "operator"},
    )
    payload = response.json()

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["error"]["code"] == "approval_already_decided"


def test_approval_api_resume_context_for_decided_approval(tmp_path) -> None:
    service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    client = TestClient(create_app(approval_service_factory=lambda: service))
    approval_id = client.post(
        "/api/v1/approvals",
        json={
            "requested_action": "continue_agent",
            "risk_level": "medium",
            "task_id": "task-paused",
            "run_id": "run-paused",
        },
    ).json()["data"]["approval_id"]
    client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decided_by": "operator", "reason": "resume"},
    )

    response = client.post(
        f"/api/v1/approvals/{approval_id}/resume-context",
        json={"decision_key": "editor_decision"},
    )
    payload = response.json()["data"]

    assert response.status_code == 200
    assert payload["decision_key"] == "editor_decision"
    assert payload["buffer_updates"]["editor_decision"]["approval_id"] == approval_id
    assert payload["buffer_updates"]["editor_decision"]["decision"] == "approved"
    assert payload["resume_metadata"]["approval_run_id"] == "run-paused"
    assert payload["resume_metadata"]["task_id"] == "task-paused"
    assert payload["resume_metadata"]["reviewer_trace"]["approval_id"] == approval_id
    assert payload["resume_metadata"]["reviewer_trace"]["decision_type"] == "approve"




def test_approval_api_resume_context_rejects_pending_approval(tmp_path) -> None:
    service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    client = TestClient(create_app(approval_service_factory=lambda: service))
    approval_id = client.post(
        "/api/v1/approvals",
        json={"requested_action": "continue_agent"},
    ).json()["data"]["approval_id"]

    response = client.post(f"/api/v1/approvals/{approval_id}/resume-context", json={})
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "approval_resume_context_unavailable"


def test_approval_api_resume_workflow_uses_run_service_and_envelope(tmp_path) -> None:
    approval_service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    run_service = _FakeRunService()
    client = TestClient(
        create_app(
            approval_service_factory=lambda: approval_service,
            run_service_factory=lambda: run_service,
        )
    )
    approval_id = client.post(
        "/api/v1/approvals",
        json={"requested_action": "continue_agent", "run_id": "approval-source-run"},
    ).json()["data"]["approval_id"]
    client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decided_by": "operator"},
    )

    response = client.post(
        f"/api/v1/approvals/{approval_id}/resume-workflow",
        json={
            "workflow_id": "test-no-llm",
            "profile": "test-no-llm",
            "run_id": "approval-resumed-run",
            "decision_key": "editor_decision",
            "checkpoint_store_path": str(tmp_path / "checkpoints"),
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["run_id"] == "approval-resumed-run"
    assert payload["data"]["status"] == "succeeded"
    assert run_service.calls[0]["approval_id"] == approval_id
    assert run_service.calls[0]["workflow_id"] == "test-no-llm"
    assert run_service.calls[0]["profile"] == "test-no-llm"
    assert run_service.calls[0]["decision_key"] == "editor_decision"
    assert run_service.calls[0]["approval_service"] is approval_service
    assert run_service.calls[0]["checkpoint_store_path"] == str(tmp_path / "checkpoints")


def test_approval_api_resume_workflow_defaults_daily_to_agentic_profile(tmp_path) -> None:
    approval_service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    run_service = _FakeRunService()
    client = TestClient(
        create_app(
            approval_service_factory=lambda: approval_service,
            run_service_factory=lambda: run_service,
        )
    )
    approval_id = client.post(
        "/api/v1/approvals",
        json={"requested_action": "continue_agent", "run_id": "approval-source-run"},
    ).json()["data"]["approval_id"]
    client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decided_by": "operator"},
    )

    response = client.post(f"/api/v1/approvals/{approval_id}/resume-workflow", json={})
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert run_service.calls[0]["workflow_id"] == "daily"
    assert run_service.calls[0]["profile"] is None


    client = TestClient(
        create_app(
            approval_service_factory=lambda: approval_service,
            run_service_factory=lambda: _FailingRunService(),
        )
    )
    approval_id = client.post(
        "/api/v1/approvals",
        json={"requested_action": "continue_agent", "run_id": "approval-source-run"},
    ).json()["data"]["approval_id"]
    client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decided_by": "operator"},
    )

    response = client.post(f"/api/v1/approvals/{approval_id}/resume-workflow", json={})
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "approval_workflow_resume_unavailable"


class _FakeApprovalWorkflowResumeResult:
    def __init__(self, approval_id: str, run_id: str) -> None:
        self.approval_id = approval_id
        self.run_result = RunResult(
            run_id=run_id,
            workflow_id="daily-intelligence-test-no-llm",
            workflow_version="0.1.0",
            status=WorkflowStatus.SUCCEEDED,
            output={"ok": True},
        )

    def to_dict(self) -> dict:
        return {
            "approval_context": {"approval_id": self.approval_id},
            "run_result": self.run_result.to_dict(),
            "run_id": self.run_result.run_id,
            "workflow_id": self.run_result.workflow_id,
            "workflow_version": self.run_result.workflow_version,
            "status": self.run_result.status.value,
            "output": self.run_result.output,
            "artifact_dir": self.run_result.artifact_dir,
            "manifest_path": self.run_result.manifest_path,
            "events_path": self.run_result.events_path,
            "error": self.run_result.error,
        }


class _FakeRunService:
    def __init__(self) -> None:
        self.calls = []

    def resume_from_approval(self, approval_id: str, **kwargs):
        self.calls.append({"approval_id": approval_id, **kwargs})
        return _FakeApprovalWorkflowResumeResult(
            approval_id,
            kwargs.get("run_id") or "approval-resumed-run",
        )


class _FailingRunService:
    def resume_from_approval(self, approval_id: str, **kwargs):
        raise ValueError("unsupported approval resume workflow_id: unknown")
