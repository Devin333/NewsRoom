from __future__ import annotations

from pathlib import Path
from typing import Any

from framework.specs import EdgeSpec, StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from framework.workflow.checkpoint.model import WorkflowCheckpoint
from framework.workflow.routing import RoutingDecision
from framework.workflow.runners.base import StepRunnerCapability, StepRunnerSideEffectLevel
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.workflow.runtime.artifact_publishers import WorkflowArtifactPublisherRegistry
from framework.artifacts import ArtifactManager
from framework.workflow.runtime.checkpoint_coordinator import CheckpointCoordinator
from framework.workflow.runtime.execution_context import build_execution_context
from framework.workflow.runtime.execution_loop import WorkflowExecutionLoop
from framework.workflow.runtime.manifest_updater import ManifestUpdater
from framework.workflow.runtime.outcome_finalizer import WorkflowOutcomeFinalizer
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runtime.runtime_event_bridge import RuntimeEventBridge
from framework.workflow.runtime.state_machine import WorkflowStateMachine
from framework.workflow.runtime.step_invoker import StepInvoker
from framework.workflow.runtime.timeout import workflow_timeout_budget
from framework.workflow.routing import RoutingEngine


class _Runner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="test.function",
        version="1.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
    )

    def __init__(self, outcomes: list[StepOutcome]) -> None:
        self._outcomes = list(outcomes)

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, step: StepSpec) -> list[Any]:
        return []

    def run(self, step: StepSpec, buffer: Any) -> StepOutcome:
        return self._outcomes.pop(0)


class _CheckpointStore:
    def __init__(self) -> None:
        self.saved: list[WorkflowCheckpoint] = []

    def save_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        self.saved.append(checkpoint)


def _registry(runner: _Runner) -> StepRunnerRegistry:
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, runner)
    return registry


def _workflow(step: StepSpec | None = None) -> WorkflowSpec:
    step = step or StepSpec(
        step_id="s1",
        step_type=StepType.FUNCTION,
        write_keys=["ok"],
    )
    return WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1.0",
        start_step_id=step.step_id,
        steps=[step],
    )


class _MonotonicClock:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._last = values[-1] if values else 0.0

    def __call__(self) -> float:
        if self._values:
            self._last = self._values.pop(0)
        return self._last


def test_step_invoker_retries_and_preserves_attempt_metrics(tmp_path: Path) -> None:
    step = StepSpec(
        step_id="s1",
        step_type=StepType.FUNCTION,
        write_keys=["ok"],
        retry_policy={"max_retries": 1},
    )
    runner = _Runner(
        [
            StepOutcome(status=StepStatus.FAILED, error_type="Transient"),
            StepOutcome(status=StepStatus.SUCCEEDED, outputs={"ok": True}),
        ]
    )
    context = build_execution_context(
        workflow=_workflow(step),
        request={},
        profile="test",
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=_registry(runner),
        event_bus=None,
        started_monotonic=0.0,
        run_id="run-step-invoker",
    )

    outcome = StepInvoker(
        step_runner_registry=_registry(runner),
        sleep_fn=lambda _delay: None,
    ).run_step_with_retries(step, context.buffer, context.recorder)

    event_types = [event.event_type for event in context.recorder.list_events()]
    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.metrics["attempt"] == 2
    assert "step_retry_scheduled" in event_types


def test_checkpoint_coordinator_writes_checkpoint_and_manifest(tmp_path: Path) -> None:
    store = _CheckpointStore()
    step = StepSpec(step_id="s1", write_keys=["ok"])
    context = build_execution_context(
        workflow=_workflow(step),
        request={},
        profile="test",
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=_registry(_Runner([])),
        event_bus=None,
        started_monotonic=0.0,
        run_id="run-checkpoint",
    )
    context.path.append("s1")
    context.step_results["s1"] = StepOutcome(status=StepStatus.SUCCEEDED, outputs={"ok": True})

    checkpoint_id = CheckpointCoordinator(checkpoint_store=store).write_checkpoint(
        run_id=context.run_id,
        workflow=context.workflow,
        profile=context.profile,
        current_step_ids=[],
        buffer=context.buffer,
        step_results=context.step_results,
        path=context.path,
        recorder=context.recorder,
        manifest=context.manifest,
        checkpoint_ids=context.checkpoint_ids,
    )

    assert checkpoint_id is not None
    assert store.saved[0].checkpoint_id == checkpoint_id
    assert context.checkpoint_ids == [checkpoint_id]
    assert context.manifest["checkpoints"] == [checkpoint_id]
    assert context.recorder.list_events()[-1].event_type == "checkpoint_created"


def test_execution_loop_stops_when_workflow_timeout_exceeds_after_step(tmp_path: Path) -> None:
    s1 = StepSpec(step_id="s1", step_type=StepType.FUNCTION, write_keys=["first"])
    s2 = StepSpec(step_id="s2", step_type=StepType.FUNCTION, write_keys=["second"])
    workflow = WorkflowSpec(
        workflow_id="wf-timeout",
        name="Workflow Timeout",
        version="1.0",
        start_step_id="s1",
        steps=[s1, s2],
        edges=[EdgeSpec(source_step_id="s1", target_step_id="s2")],
        policies={"timeout": {"timeout_seconds": 0.5}},
    )
    runner = _Runner(
        [
            StepOutcome(status=StepStatus.SUCCEEDED, outputs={"first": True}),
            StepOutcome(status=StepStatus.SUCCEEDED, outputs={"second": True}),
        ]
    )
    registry = _registry(runner)
    artifact_manager = ArtifactManager(tmp_path)
    context = build_execution_context(
        workflow=workflow,
        request={},
        profile="test",
        artifact_manager=artifact_manager,
        step_runner_registry=registry,
        event_bus=None,
        started_monotonic=0.0,
        run_id="run-workflow-timeout",
    )

    WorkflowExecutionLoop(
        state_machine=WorkflowStateMachine(),
        routing_engine=RoutingEngine(),
        step_invoker=StepInvoker(step_runner_registry=registry, sleep_fn=lambda _delay: None),
        checkpoint_coordinator=CheckpointCoordinator(checkpoint_store=None),
        event_bridge=RuntimeEventBridge(),
        manifest_updater=ManifestUpdater(
            artifact_manager=artifact_manager,
            run_id=context.run_id,
            manifest=context.manifest,
        ),
        is_run_cancelled=lambda _run_id: False,
        monotonic_fn=_MonotonicClock([0.1, 0.75]),
    ).run(context)

    assert context.status == WorkflowStatus.FAILED
    assert context.error is not None
    assert context.error.error_type == "WorkflowTimeoutExceeded"
    assert context.error.step_id == "s1"
    assert context.step_results["s1"].status == StepStatus.SUCCEEDED
    assert "s2" not in context.step_results
    assert context.current_step_ids == []
    assert context.manifest["runtime_timeout"]["policy_source"] == (
        "policies.timeout_policy.timeout_seconds"
    )
    assert any(
        event.event_type == "workflow_timeout_exceeded"
        for event in context.recorder.list_events()
    )


def test_workflow_timeout_budget_uses_earliest_runtime_policy() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-timeout-budget",
        name="Workflow Timeout Budget",
        version="1.0",
        steps=[StepSpec(step_id="s1", step_type=StepType.FUNCTION)],
        policies={
            "timeout": {"timeout_seconds": 10},
            "resource": {"max_runtime_seconds": 5},
        },
    )

    budget = workflow_timeout_budget(workflow, started_monotonic=100.0)

    assert budget is not None
    assert budget.timeout_seconds == 5.0
    assert budget.policy_source == "policies.resource_policy.max_runtime_seconds"
    assert budget.is_exceeded(104.9) is False
    assert budget.is_exceeded(105.0) is True


def test_runtime_event_bridge_emits_routing_events(tmp_path: Path) -> None:
    context = build_execution_context(
        workflow=_workflow(),
        request={},
        profile="test",
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=_registry(_Runner([])),
        event_bus=None,
        started_monotonic=0.0,
        run_id="run-events",
    )
    decision = RoutingDecision(target_step_id=None, evaluations=[])

    RuntimeEventBridge().emit_routing_events(context.recorder, decision)

    assert context.recorder.list_events() == []


def test_outcome_finalizer_returns_workflow_result_and_terminal_manifest(tmp_path: Path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    context = build_execution_context(
        workflow=_workflow(),
        request={},
        profile="test",
        artifact_manager=artifact_manager,
        step_runner_registry=_registry(_Runner([])),
        event_bus=None,
        started_monotonic=0.0,
        run_id="run-finalizer",
    )
    updater = ManifestUpdater(
        artifact_manager=artifact_manager,
        run_id=context.run_id,
        manifest=context.manifest,
    )
    outcome = StepOutcome(status=StepStatus.SUCCEEDED, outputs={"ok": True})
    updater.record_step_outcome(
        step=context.workflow.steps[0],
        outcome=outcome,
        path=["s1"],
        step_results=context.step_results,
    )
    context.status = WorkflowStatus.SUCCEEDED
    context.path = ["s1"]

    result = WorkflowOutcomeFinalizer(
        artifact_manager=artifact_manager,
        artifact_publishers=WorkflowArtifactPublisherRegistry([]),
        event_bridge=RuntimeEventBridge(),
    ).finalize(context)

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.manifest["status"] == "succeeded"
    assert result.events_path.endswith("events.jsonl")
