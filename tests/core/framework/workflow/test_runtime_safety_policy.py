from __future__ import annotations

import json

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    RuntimeSafetyPolicy,
    StepOutcome,
    StepRunnerRegistry,
    WorkflowExecutor,
)
from core.framework.specs import StepStatus


def test_runtime_safety_policy_serializes_defaults() -> None:
    assert RuntimeSafetyPolicy().to_dict() == {
        "require_approval_for_external_write": True,
        "require_approval_for_publish": True,
        "require_approval_for_notification": True,
        "blocked_step_types": [],
    }


def test_dangerous_persist_without_approval_is_blocked(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.PERSIST, _SuccessRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        _workflow(
            StepSpec(
                "persist",
                "persist.external",
                step_type=StepType.PERSIST,
                metadata={"external_write": True},
            )
        ),
        {},
        profile="test",
        run_id="run-safety-blocked",
    )
    manifest = json.loads(
        (tmp_path / "run-safety-blocked" / "manifest.json").read_text(encoding="utf-8")
    )
    event_types = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-safety-blocked" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert result.status == WorkflowStatus.BLOCKED
    assert result.error.error_type == "WorkflowRuntimeSafetyViolation"
    assert manifest["policy_violations"][0]["policy"] == (
        "runtime_safety.external_write_requires_approval"
    )
    assert "runtime_safety_violation" in event_types


def test_dangerous_persist_with_approval_can_continue(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.PERSIST, _SuccessRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        _workflow(
            StepSpec(
                "persist",
                "persist.external",
                step_type=StepType.PERSIST,
                write_keys=["ok"],
                metadata={"external_write": True, "approval_id": "appr-1"},
            )
        ),
        {},
        profile="test",
        run_id="run-safety-approved",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["ok"] is True


def test_memory_write_without_approval_is_blocked(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.MEMORY_WRITE, _SuccessRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        _workflow(
            StepSpec(
                "memory_write",
                "memory.write",
                step_type=StepType.MEMORY_WRITE,
            )
        ),
        {},
        profile="test",
        run_id="run-memory-write-blocked",
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.error.details["policy"] == "runtime_safety.external_write_requires_approval"


def test_notification_without_approval_is_blocked(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.NOTIFICATION, _SuccessRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        _workflow(
            StepSpec(
                "notify",
                "notify.send",
                step_type=StepType.NOTIFICATION,
            )
        ),
        {},
        profile="test",
        run_id="run-notify-blocked",
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.error.details["policy"] == "runtime_safety.notification_requires_approval"


def _workflow(step: StepSpec) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="runtime-safety",
        name="Runtime Safety",
        version="1.0",
        start_step_id=step.step_id,
        steps=[step],
    )


class _SuccessRunner:
    def run(self, step, buffer):
        for key in step.write_keys:
            buffer.write(key, True)
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={key: True for key in step.write_keys},
        )
