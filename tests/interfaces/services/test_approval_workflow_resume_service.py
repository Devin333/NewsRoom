from __future__ import annotations

import pytest

from framework import WorkflowRunner
from framework.specs import WorkflowStatus
from interfaces.services.approval_service import ApprovalApplicationService
import interfaces.services.run_service as run_service_module
from interfaces.services.run_service import RunApplicationService
from infrastructure.storage.checkpoint import LocalJsonCheckpointStore


def test_run_service_resumes_workflow_from_decided_approval(tmp_path, monkeypatch) -> None:
    workflow = run_service_module.build_test_no_llm_workflow()
    checkpoint_store_path = tmp_path / "checkpoints"
    checkpoint_store = LocalJsonCheckpointStore(checkpoint_store_path)
    source_run = WorkflowRunner(
        artifact_root=tmp_path / "source-runs",
        function_registry=run_service_module.build_test_no_llm_registry(),
        checkpoint_store=checkpoint_store,
    ).run(
        workflow,
        {"topic": "AI policy"},
        profile="test-no-llm",
        run_id="approval-source-run",
    )
    checkpoint = checkpoint_store.get_latest_checkpoint("approval-source-run")
    approval_service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    submitted = approval_service.submit_request(
        requested_action="continue_agent",
        run_id="approval-source-run",
        task_id="task-paused",
    )
    approval_service.approve(submitted.approval.approval_id, decided_by="operator")
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: _FakePersistenceRepository(),
    )

    result = RunApplicationService(artifact_root=tmp_path / "runs").resume_from_approval(
        submitted.approval.approval_id,
        workflow_id="test-no-llm",
        run_id="approval-resumed-run",
        approval_service=approval_service,
        checkpoint_store_path=checkpoint_store_path,
    )
    payload = result.to_dict()

    assert source_run.status == WorkflowStatus.SUCCEEDED
    assert checkpoint is not None
    assert result.run_result.status == WorkflowStatus.SUCCEEDED
    assert payload["run_id"] == "approval-resumed-run"
    assert payload["status"] == "succeeded"
    assert payload["approval_context"]["resume_metadata"]["approval_run_id"] == "approval-source-run"
    assert payload["output"]["final_report"]["topic"] == "AI policy"
    assert payload["run_result"]["manifest"]["resumed_from_checkpoint_id"] == checkpoint.checkpoint_id


def test_run_service_resolves_daily_approval_resume_to_agentic_workflow(tmp_path) -> None:
    resolved = run_service_module._resolve_approval_resume_workflow("daily", profile="live")

    assert (
        resolved.workflow.workflow_id
        == run_service_module.build_agentic_daily_intelligence_workflow("agentic-live").workflow_id
    )
    assert resolved.profile == "agentic-live"


def test_run_service_rejects_unsupported_approval_resume_workflow(tmp_path) -> None:
    approval_service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    submitted = approval_service.submit_request(
        requested_action="continue_agent",
        run_id="approval-source-run",
    )
    approval_service.approve(submitted.approval.approval_id, decided_by="operator")

    with pytest.raises(ValueError, match="unsupported approval resume workflow_id"):
        RunApplicationService(artifact_root=tmp_path / "runs").resume_from_approval(
            submitted.approval.approval_id,
            workflow_id="unknown-workflow",
            approval_service=approval_service,
            checkpoint_store_path=tmp_path / "checkpoints",
        )


class _FakePersistenceRepository:
    def save_workflow_run(self, record) -> None:
        return None

    def save_report(self, record) -> None:
        return None
