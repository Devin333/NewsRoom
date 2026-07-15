from __future__ import annotations

from typing import Any

from framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec
from framework.workflow.runners.base import StepRunnerCapability, StepRunnerSideEffectLevel
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.artifacts import ArtifactManager
from framework.events import EventRuntime, default_event_schema_catalog
from framework.workflow.runtime.executor import WorkflowExecutor
from framework.workflow.runtime.result import StepOutcome
from infrastructure.storage.events.sqlite import SQLiteEventStore


class _TraceAwareRunner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="trace-aware",
        version="1.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
    )

    def __init__(self) -> None:
        self.trace_context = None

    def configure_trace_context(self, *, trace_context: Any) -> None:
        self.trace_context = trace_context

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, step: StepSpec) -> list[Any]:
        return []

    def run(self, step: StepSpec, buffer: Any) -> StepOutcome:
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"done": True})


def test_workflow_run_manifest_and_events_include_trace_context(tmp_path) -> None:
    runner = _TraceAwareRunner()
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, runner)
    workflow = WorkflowSpec(
        workflow_id="wf-trace",
        name="Trace workflow",
        version="1.0",
        start_step_id="s1",
        steps=[StepSpec(step_id="s1", step_type=StepType.FUNCTION, write_keys=["done"])],
    )
    event_store = SQLiteEventStore(tmp_path / "events.sqlite3")
    event_catalog = default_event_schema_catalog()

    result = WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=registry,
        event_runtime=EventRuntime(store=event_store, schema_catalog=event_catalog),
        event_reader=event_store,
        event_schema_catalog=event_catalog,
    ).execute(workflow, {}, profile="test", run_id="run-trace")

    step_span = result.manifest["step_spans"]["s1"]
    events = (tmp_path / "run-trace" / "events.jsonl").read_text(encoding="utf-8")

    assert result.manifest["trace_id"]
    assert result.manifest["root_span_id"] == "workflow:run-trace"
    assert result.manifest["trace_events_ref"] == "events.jsonl"
    assert step_span["parent_span_id"] == "workflow:run-trace"
    assert runner.trace_context.span_id == "step:s1"
    assert '"trace_id"' in events
    assert '"io.newsroom.legacy"' in events
    assert '"span_id":"step:s1"' in events
