from __future__ import annotations

from framework import RunResult
from framework.specs import StepSpec, WorkflowStatus
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


def test_approval_resume_service_projects_daily_human_review_route(tmp_path) -> None:
    service = ApprovalResumeApplicationService(
        artifact_root=tmp_path,
        resolution_service=_DailyResolution(),
        workflow_runner_cls=_Runner,
        checkpoint_store_cls=lambda path: ("checkpoint", path),
    )

    result = service.resume_from_approval(
        "approval-1",
        workflow_id="daily-intelligence-agentic",
        approval_service=_DailyApprovalService(),
        checkpoint_store_path=tmp_path / "checkpoints",
        run_id="resumed-daily",
    )

    context = result.approval_context
    route = context["human_review_resume_route"]
    assert route["route"] == "rewrite"
    assert route["next_step_id"] == "writer_agent"
    assert route["modifications"] == {"summary": "tighten lead"}
    assert context["buffer_updates"]["human_review_resume_route"] == route
    assert context["buffer_updates"]["quality.human_review_resume_route"] == route
    assert context["resume_metadata"]["human_review_resume_route"] == route
    assert context["resume_metadata"]["resume_next_step_id"] == "writer_agent"
    assert context["resume_metadata"]["allowed_patch_keys"] == [
        "human_review_resume_route",
        "quality.human_review_resume_route",
    ]
    assert result.run_result.output["context"] == context


class _Resolution:
    def resolve_approval_resume_workflow(self, workflow_id, *, profile):
        return ResolvedWorkflow(
            workflow=WorkflowSpec(workflow_id="test-no-llm", name="Test", version="1", steps=[]),
            profile="test-no-llm",
            registry=FunctionStepRegistry(),
        )


class _DailyResolution:
    def resolve_approval_resume_workflow(self, workflow_id, *, profile):
        return ResolvedWorkflow(
            workflow=WorkflowSpec(
                workflow_id="daily-intelligence-agentic",
                name="Daily",
                version="1",
                steps=[
                    StepSpec("writer_agent"),
                    StepSpec(
                        "finalize_report",
                        read_keys=[
                            "human_review_resume_route",
                            "quality.human_review_resume_route",
                        ],
                        write_keys=[
                            "human_review_resume_route",
                            "quality.human_review_resume_route",
                        ],
                    ),
                ],
            ),
            profile="daily-intelligence-agentic",
            registry=FunctionStepRegistry(),
        )


class _ApprovalService:
    def build_resume_context(self, approval_id, *, decision_key):
        return _Context({"approval_id": approval_id, "decision_key": decision_key})


class _DailyApprovalService:
    def build_resume_context(self, approval_id, *, decision_key):
        return _Context(
            {
                "approval_id": approval_id,
                "decision_payload": {
                    "decision": "approved",
                    "decision_type": "modify",
                    "status": "modified",
                    "approval_id": approval_id,
                    "decided_by": "editor",
                    "modifications": {"summary": "tighten lead"},
                },
                "buffer_updates": {
                    decision_key: {
                        "decision": "approved",
                        "approval_id": approval_id,
                    }
                },
                "resume_metadata": {"approval_id": approval_id},
            }
        )


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
            output={"context": _context_to_dict(context)},
        )


def _context_to_dict(context):
    if isinstance(context, dict):
        return context
    return context.to_dict()
