from __future__ import annotations

from framework import RunResult
from framework.specs import WorkflowStatus
from interfaces.services.approval_resume_service import ApprovalResumeApplicationService
from interfaces.services.run_resolution_service import ResolvedWorkflow
from framework.specs import WorkflowSpec
from framework.workflow import FunctionStepRegistry


def test_approval_resume_service_builds_context_and_resumes(tmp_path) -> None:
    service = ApprovalResumeApplicationService(
        artifact_root=tmp_path,
        resolution_service=_Resolution(),
        workflow_runner_cls=_Runner,
        checkpoint_store_cls=lambda path: ("checkpoint", path),
    )

    result = service.resume_from_approval(
        "approval-1",
        workflow_id="test-no-llm",
        approval_service=_ApprovalService(),
        checkpoint_store_path=tmp_path / "checkpoints",
        run_id="resumed",
    )

    assert result.approval_context["approval_id"] == "approval-1"
    assert result.run_result.run_id == "resumed"
    assert result.to_dict()["status"] == "succeeded"


class _Resolution:
    def resolve_approval_resume_workflow(self, workflow_id, *, profile):
        return ResolvedWorkflow(
            workflow=WorkflowSpec(workflow_id="test-no-llm", name="Test", version="1", steps=[]),
            profile="test-no-llm",
            registry=FunctionStepRegistry(),
        )


class _ApprovalService:
    def build_resume_context(self, approval_id, *, decision_key):
        return _Context({"approval_id": approval_id, "decision_key": decision_key})


class _Context:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload


class _Runner:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def resume_from_approval_context(self, workflow, context, *, profile, run_id):
        return RunResult(
            run_id=run_id,
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            status=WorkflowStatus.SUCCEEDED,
            output={"context": context.to_dict()},
        )
