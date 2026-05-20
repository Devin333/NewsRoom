from __future__ import annotations

from datetime import UTC, datetime

from core.framework.artifacts import ArtifactManager
from framework.llm import GlobalBudgetPolicy, GlobalBudgetTracker, TokenUsage
from core.framework.specs import StepSpec, StepStatus, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    StepOutcome,
    StepRunnerRegistry,
    WorkflowExecutor,
    envelope_from_checkpoint,
)
from storage.checkpoint import LocalJsonCheckpointStore, WorkflowCheckpoint


def test_checkpoint_metadata_records_budget_usage(tmp_path) -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=5))
    tracker.record_llm_call(TokenUsage(input_tokens=2, output_tokens=3), estimated_cost_usd=0.01)
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    registry = StepRunnerRegistry()
    registry.register("function", _PauseRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        checkpoint_store=checkpoint_store,
        global_budget_tracker=tracker,
    )

    result = executor.execute(_pause_workflow(), {}, profile="test", run_id="run-budget-pause")
    checkpoint = checkpoint_store.get_latest_checkpoint("run-budget-pause")

    assert result.status == WorkflowStatus.PAUSED
    assert checkpoint.metadata["budget_usage"]["llm_calls"] == 1


def test_resume_plan_inherits_checkpoint_budget_usage_metadata(tmp_path) -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=5))
    tracker.record_llm_call(TokenUsage(input_tokens=2, output_tokens=3), estimated_cost_usd=0.01)
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    registry = StepRunnerRegistry()
    registry.register("function", _PauseRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        checkpoint_store=checkpoint_store,
        global_budget_tracker=tracker,
    )

    executor.execute(_pause_workflow(), {}, profile="test", run_id="run-budget-pause")
    checkpoint = checkpoint_store.get_latest_checkpoint("run-budget-pause")
    envelope = envelope_from_checkpoint(checkpoint)

    assert envelope.metadata["budget_usage"]["llm_calls"] == 1


def test_resume_restores_checkpoint_budget_usage_before_continuing(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register("function", _FinishRunner())
    spec = WorkflowSpec(
        workflow_id="budget-resume-restore",
        name="Budget Resume Restore",
        version="1.0",
        start_step_id="finish",
        steps=[StepSpec("finish", "sample.finish", write_keys=["finished"])],
    )
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=5))
    resume_executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
        global_budget_tracker=tracker,
    )
    resumed = resume_executor.resume_from_checkpoint(
        spec,
        WorkflowCheckpoint(
            checkpoint_id="cp-budget",
            run_id="original-run",
            workflow_id=spec.workflow_id,
            workflow_version=spec.version,
            current_step_ids=["finish"],
            data_buffer_snapshot={"request": {}},
            step_results={},
            path=[],
            created_at=datetime(2026, 5, 16, tzinfo=UTC),
            metadata={
                "budget_usage": {
                    "llm_calls": 1,
                    "token_usage": {
                        "input_tokens": 3,
                        "output_tokens": 0,
                        "reasoning_tokens": 0,
                        "cached_input_tokens": 0,
                        "total_tokens": 3,
                    },
                    "estimated_cost_usd": 0.01,
                }
            },
        ),
        profile="test",
        run_id="run-budget-resume-restore-continued",
    )

    assert resumed.manifest["resume_budget_inherited"] is True
    assert resumed.manifest["metrics"]["budget"]["llm_calls"] == 1
    assert resumed.manifest["metrics"]["budget"]["total_tokens"] == 3


def _pause_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="budget-resume",
        name="Budget Resume",
        version="1.0",
        start_step_id="pause",
        steps=[StepSpec("pause", "pause.now")],
    )


class _PauseRunner:
    def run(self, step, buffer):
        _ = step, buffer
        return StepOutcome(status=StepStatus.PAUSED, next_hint="pause")


class _FinishRunner:
    def run(self, step, buffer):
        _ = step, buffer
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"finished": True})

