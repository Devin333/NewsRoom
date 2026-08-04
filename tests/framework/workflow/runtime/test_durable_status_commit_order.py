from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import framework.workflow.runtime.executor as executor_module
from framework.agent.artifacts import ArtifactManager
from framework.events import default_event_schema_catalog
from framework.events.errors import EventStoreUnavailableError
from framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from framework.workflow.routing import RoutingEngine
from framework.workflow.runners.base import (
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
)
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.workflow.runtime.artifact_publishers import (
    WorkflowArtifactPublisherRegistry,
)
from framework.workflow.runtime.checkpoint_coordinator import CheckpointCoordinator
from framework.workflow.runtime.execution_context import build_execution_context
from framework.workflow.runtime.execution_loop import (
    WorkflowExecutionLoop,
    commit_workflow_transition,
)
from framework.workflow.runtime.executor import WorkflowExecutor
from framework.workflow.runtime.manifest_updater import ManifestUpdater
from framework.workflow.runtime.result import StepOutcome, WorkflowError
from framework.workflow.runtime.runtime_event_bridge import RuntimeEventBridge
from framework.workflow.runtime.state_machine import (
    WorkflowRuntimeEvent,
    WorkflowRuntimeEventType,
    WorkflowStateMachine,
)
from framework.workflow.runtime.step_invoker import StepInvoker
from framework.workflow.runtime.verification import WorkflowRuntimeVerifier


class _Runner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="test.commit-order",
        version="1.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
    )

    def __init__(self) -> None:
        self.call_count = 0

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, step: StepSpec) -> list[Any]:
        return []

    def run(self, step: StepSpec, buffer: Any) -> StepOutcome:
        self.call_count += 1
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"ok": True})


class _UnavailableRuntime:
    def publish(self, event: Any, *, unit_of_work: Any = None) -> Any:
        raise EventStoreUnavailableError("durable event append unavailable")


class _UnusedReader:
    def get_stream_high_watermark(self, stream_id: str, *, tenant_id: str | None = None):
        raise AssertionError("reader must not run after a failed append")


class _ArtifactPublisher:
    publisher_id = "commit-order-spy"

    def __init__(self) -> None:
        self.phases: list[str] = []

    def supports(self, context: Any) -> bool:
        return True

    def publish(self, context: Any) -> list[Any]:
        self.phases.append(context.phase.value)
        return []


def _workflow(*, timeout_seconds: float | None = None) -> WorkflowSpec:
    policies = (
        {"timeout": {"timeout_seconds": timeout_seconds}}
        if timeout_seconds is not None
        else {}
    )
    return WorkflowSpec(
        workflow_id="wf-commit-order",
        name="Commit Order",
        version="1.0",
        start_step_id="s1",
        steps=[StepSpec(step_id="s1", write_keys=["ok"])],
        policies=policies,
    )


def _registry(runner: _Runner) -> StepRunnerRegistry:
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, runner)
    return registry


@pytest.mark.parametrize(
    ("current", "event", "expected"),
    [
        (
            WorkflowStatus.CREATED,
            WorkflowRuntimeEvent(WorkflowRuntimeEventType.START),
            WorkflowStatus.RUNNING,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(WorkflowRuntimeEventType.SUCCEED),
            WorkflowStatus.SUCCEEDED,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(WorkflowRuntimeEventType.FAIL),
            WorkflowStatus.FAILED,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(WorkflowRuntimeEventType.BLOCK),
            WorkflowStatus.BLOCKED,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(
                WorkflowRuntimeEventType.PAUSE,
                checkpoint_id="checkpoint-1",
            ),
            WorkflowStatus.PAUSED,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(
                WorkflowRuntimeEventType.REQUEST_HUMAN_REVIEW,
                human_review_request_id="review-1",
            ),
            WorkflowStatus.WAITING_FOR_HUMAN,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(WorkflowRuntimeEventType.BUDGET_EXCEEDED),
            WorkflowStatus.BUDGET_EXCEEDED,
        ),
        (
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(WorkflowRuntimeEventType.CANCEL),
            WorkflowStatus.CANCELLED,
        ),
    ],
)
def test_append_failure_keeps_every_workflow_transition_at_its_prior_status(
    current: WorkflowStatus,
    event: WorkflowRuntimeEvent,
    expected: WorkflowStatus,
) -> None:
    context = SimpleNamespace(status=current)
    observed: list[tuple[WorkflowStatus, WorkflowStatus]] = []

    def fail_append(next_status: WorkflowStatus) -> None:
        observed.append((context.status, next_status))
        raise EventStoreUnavailableError("append failed")

    with pytest.raises(EventStoreUnavailableError, match="append failed"):
        commit_workflow_transition(
            context=context,
            state_machine=WorkflowStateMachine(),
            event=event,
            append=fail_append,
        )

    assert observed == [(current, expected)]
    assert context.status == current


def test_executor_start_append_failure_keeps_created_state_and_skips_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner()
    publisher = _ArtifactPublisher()
    captured: list[Any] = []
    real_build_context = executor_module.build_execution_context

    def capture_context(**kwargs: Any):
        context = real_build_context(**kwargs)
        captured.append(context)
        return context

    monkeypatch.setattr(executor_module, "build_execution_context", capture_context)
    executor = WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=_registry(runner),
        event_runtime=_UnavailableRuntime(),
        event_reader=_UnusedReader(),
        event_schema_catalog=default_event_schema_catalog(),
        artifact_publishers=WorkflowArtifactPublisherRegistry([publisher]),
    )

    with pytest.raises(EventStoreUnavailableError, match="append unavailable"):
        executor.execute(
            _workflow(),
            {},
            profile="test",
            run_id="run-start-append-failure",
        )

    assert len(captured) == 1
    assert captured[0].status == WorkflowStatus.CREATED
    assert publisher.phases == []
    assert runner.call_count == 0


def test_timeout_append_failure_keeps_running_state_and_pending_step(
    tmp_path: Path,
) -> None:
    runner = _Runner()
    registry = _registry(runner)
    artifact_manager = ArtifactManager(tmp_path)
    context = build_execution_context(
        workflow=_workflow(timeout_seconds=0.5),
        request={},
        profile="test",
        artifact_manager=artifact_manager,
        step_runner_registry=registry,
        event_runtime=_UnavailableRuntime(),
        event_reader=_UnusedReader(),
        event_schema_catalog=default_event_schema_catalog(),
        started_monotonic=0.0,
        run_id="run-timeout-append-failure",
    )
    context.status = WorkflowStatus.RUNNING
    loop = WorkflowExecutionLoop(
        state_machine=WorkflowStateMachine(),
        routing_engine=RoutingEngine(),
        step_invoker=StepInvoker(
            step_runner_registry=registry,
            sleep_fn=lambda _delay: None,
        ),
        checkpoint_coordinator=CheckpointCoordinator(checkpoint_store=None),
        event_bridge=RuntimeEventBridge(),
        manifest_updater=ManifestUpdater(
            artifact_manager=artifact_manager,
            run_id=context.run_id,
            manifest=context.manifest,
        ),
        is_run_cancelled=lambda _run_id: False,
        monotonic_fn=lambda: 1.0,
    )

    with pytest.raises(EventStoreUnavailableError, match="append unavailable"):
        loop.run(context)

    assert context.status == WorkflowStatus.RUNNING
    assert context.error is None
    assert context.current_step_ids == ["s1"]
    assert "runtime_timeout" not in context.manifest
    assert runner.call_count == 0


def test_context_status_assignment_is_owned_only_by_the_commit_helper() -> None:
    runtime_root = Path(executor_module.__file__).parent
    assignments: list[tuple[str, str]] = []

    for name in ("executor.py", "execution_loop.py", "verification.py"):
        tree = ast.parse((runtime_root / name).read_text(encoding="utf-8"))
        visitor = _ContextStatusAssignmentVisitor(name)
        visitor.visit(tree)
        assignments.extend(visitor.assignments)

    assert assignments == [("execution_loop.py", "commit_workflow_transition")]


def test_strict_verification_preserves_a_primary_terminal_failure(tmp_path: Path) -> None:
    runner = _Runner()
    context = build_execution_context(
        workflow=_workflow(),
        request={},
        profile="test",
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=_registry(runner),
        event_runtime=_UnavailableRuntime(),
        event_reader=_UnusedReader(),
        event_schema_catalog=default_event_schema_catalog(),
        started_monotonic=0.0,
        run_id="run-primary-terminal-failure",
    )
    primary_error = WorkflowError(
        error_type="PrimaryFailure",
        message="primary workflow failure",
    )
    context.status = WorkflowStatus.FAILED
    context.error = primary_error
    context.manifest.pop("status")

    report = WorkflowRuntimeVerifier("strict").apply(context)

    assert report is not None and report.failed
    assert context.status == WorkflowStatus.FAILED
    assert context.error is primary_error


class _ContextStatusAssignmentVisitor(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.functions: list[str] = []
        self.assignments: list[tuple[str, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(_is_context_status(target) for target in node.targets):
            self.assignments.append((self.filename, self.functions[-1]))
        self.generic_visit(node)


def _is_context_status(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "status"
        and isinstance(node.value, ast.Name)
        and node.value.id == "context"
    )
