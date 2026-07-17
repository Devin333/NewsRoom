from __future__ import annotations

from pathlib import Path
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from framework.workflow.runners.base import StepRunnerCapability, StepRunnerSideEffectLevel
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.workflow.runtime.artifact_publishers import WorkflowArtifactPublisherRegistry
from framework.artifacts import ArtifactManager
from framework.events import EventRuntime, default_event_schema_catalog
from framework.workflow.runtime.execution_context import build_execution_context
from framework.workflow.runtime.execution_loop import commit_workflow_transition
from framework.workflow.runtime.manifest_updater import ManifestUpdater
from framework.workflow.runtime.outcome_finalizer import WorkflowOutcomeFinalizer
from framework.workflow.runtime.result import StepOutcome, WorkflowResult
from framework.workflow.runtime.runtime_event_bridge import RuntimeEventBridge
from framework.workflow.runtime.state_machine import (
    WorkflowRuntimeEvent,
    WorkflowRuntimeEventType,
    WorkflowStateMachine,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore


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

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, step: StepSpec) -> list[Any]:
        return []

    def run(self, step: StepSpec, buffer: Any) -> StepOutcome:
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"ok": True})


def test_workflow_result_supports_output_aliases_and_step_outcomes() -> None:
    outcome = StepOutcome(status=StepStatus.SUCCEEDED, outputs={"ok": True}, step_id="s1")
    result = WorkflowResult(
        run_id="run-1",
        workflow_id="wf-1",
        workflow_version="1.0",
        status="succeeded",
        outputs={"done": True},
        step_outcomes=[outcome],
    )

    payload = result.to_dict()
    restored = WorkflowResult.from_dict(payload)

    assert result.output == {"done": True}
    assert payload["output"] == {"done": True}
    assert payload["outputs"] == {"done": True}
    assert restored.step_results["s1"].outputs == {"ok": True}
    assert restored.step_outcomes[0].step_id == "s1"


def test_outcome_finalizer_populates_standard_workflow_result_fields(tmp_path: Path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    step = StepSpec(step_id="s1", step_type=StepType.FUNCTION, write_keys=["ok"])
    workflow = WorkflowSpec(
        workflow_id="wf-standard",
        name="Workflow",
        version="1.0",
        start_step_id="s1",
        steps=[step],
    )
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, _Runner())
    event_store = SQLiteEventStore(tmp_path / "events.sqlite3")
    event_catalog = default_event_schema_catalog()
    context = build_execution_context(
        workflow=workflow,
        request={},
        profile="test",
        artifact_manager=artifact_manager,
        step_runner_registry=registry,
        event_runtime=EventRuntime(store=event_store, schema_catalog=event_catalog),
        event_reader=event_store,
        event_schema_catalog=event_catalog,
        started_monotonic=0.0,
        run_id="run-standard",
    )
    step_trace = context.trace_context.child(span_id="step:s1", step_id="s1")
    updater = ManifestUpdater(
        artifact_manager=artifact_manager,
        run_id=context.run_id,
        manifest=context.manifest,
    )
    outcome = updater.finalize_step_outcome_contract(
        workflow,
        step,
        StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"ok": True},
            started_at="2026-05-21T00:00:00Z",
            completed_at="2026-05-21T00:00:01Z",
            warnings=["heads up"],
        ),
        trace_context=step_trace,
    )
    updater.record_step_outcome(
        step=step,
        outcome=outcome,
        path=["s1"],
        step_results=context.step_results,
    )
    context.path = ["s1"]
    context.status = WorkflowStatus.RUNNING
    event_bridge = RuntimeEventBridge()
    commit_workflow_transition(
        context=context,
        state_machine=WorkflowStateMachine(),
        event=WorkflowRuntimeEvent(
            event_type=WorkflowRuntimeEventType.SUCCEED,
            reason="test_finalization",
        ),
        append=lambda status: event_bridge.emit_terminal_workflow_event(
            context.recorder,
            status=status,
            path=context.path,
            error=None,
            trace_context=context.trace_context,
        ),
    )

    result = WorkflowOutcomeFinalizer(
        artifact_manager=artifact_manager,
        artifact_publishers=WorkflowArtifactPublisherRegistry([]),
        event_bridge=event_bridge,
    ).finalize(context)

    assert result.outputs == result.output
    assert result.trace_id == context.trace_context.trace_id
    assert result.trace_ref and result.trace_ref.endswith("events.jsonl")
    assert result.manifest_ref and result.manifest_ref.endswith("manifest.json")
    assert result.metrics["step_count"] == 1
    assert result.step_outcomes[0].step_id == "s1"
    assert result.warnings == ["s1: heads up"]
    summary = result.manifest["step_outcome_summary"]["s1"]
    assert summary["duration_ms"] == 1000.0
    assert summary["trace_id"] == context.trace_context.trace_id
    assert summary["span_id"] == "step:s1"


def test_llm_call_artifact_post_processing_preserves_standard_step_fields(tmp_path: Path) -> None:
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("run-llm-standard")
    updater = ManifestUpdater(
        artifact_manager=artifact_manager,
        run_id="run-llm-standard",
        manifest={"artifacts": {}},
    )
    step = StepSpec(step_id="s1", write_keys=["llm_call_artifacts"])
    outcome = StepOutcome(
        status=StepStatus.SUCCEEDED,
        outputs={
            "llm_call_artifacts": [
                {
                    "artifact_id": "llm-1",
                    "iteration": 1,
                    "request": {},
                    "response": {},
                }
            ]
        },
        step_id="s1",
        trace_id="trace-1",
        span_id="step:s1",
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:00:01Z",
        warnings=["keep me"],
        metadata={"source": "test"},
        trace_events=[{"event": "agent"}],
    )

    updated = updater.write_llm_call_artifacts(step, outcome)

    assert updated.trace_id == "trace-1"
    assert updated.span_id == "step:s1"
    assert updated.duration_ms == 1000.0
    assert updated.warnings == ["keep me"]
    assert updated.metadata == {"source": "test"}
    assert updated.trace_events == [{"event": "agent"}]
    assert updated.artifact_refs[0].artifact_type == "llm_call"
