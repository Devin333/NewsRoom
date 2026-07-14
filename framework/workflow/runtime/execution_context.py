from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.specs import StepStatus, WorkflowSpec, WorkflowStatus
from framework.workflow.buffer import DataBuffer, DataBufferSnapshot, step_scope_from_spec
from framework.events.trace import TraceContext
from framework.artifacts import ArtifactManager, validate_artifact_path_segment
from framework.events import EventBus, EventRecorder
from framework.workflow.runtime.manifest import (
    build_runner_manifest,
    build_run_manifest,
    update_manifest_runner_versions,
)
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.registry import StepRunnerRegistry


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class WorkflowExecutionContext:
    run_id: str
    run_dir: Path
    workflow: WorkflowSpec
    request: dict[str, Any]
    profile: str
    recorder: EventRecorder
    trace_context: TraceContext
    buffer: DataBuffer
    initial_buffer_snapshot: DataBufferSnapshot
    started_at: str
    started_monotonic: float
    manifest: dict[str, Any]
    status: WorkflowStatus
    path: list[str] = field(default_factory=list)
    step_results: dict[str, StepOutcome] = field(default_factory=dict)
    checkpoint_ids: list[str] = field(default_factory=list)
    current_step_ids: list[str] = field(default_factory=list)
    step_visit_counts: dict[str, int] = field(default_factory=dict)
    step_trace_contexts: dict[str, TraceContext] = field(default_factory=dict)
    error: Any | None = None


def build_execution_context(
    *,
    workflow: WorkflowSpec,
    request: dict[str, Any],
    profile: str,
    artifact_manager: ArtifactManager,
    step_runner_registry: StepRunnerRegistry,
    event_bus: EventBus | None,
    started_monotonic: float,
    run_id: str | None = None,
    initial_buffer_values: dict[str, Any] | None = None,
    current_step_ids: list[str] | None = None,
    initial_path: list[str] | None = None,
    initial_step_results: dict[str, StepOutcome] | None = None,
) -> WorkflowExecutionContext:
    actual_run_id = (
        uuid4().hex
        if run_id is None
        else validate_artifact_path_segment(run_id, field="run_id")
    )
    run_dir = artifact_manager.start_run(actual_run_id)
    recorder = EventRecorder(actual_run_id, event_bus=event_bus)
    buffer = DataBuffer(initial_buffer_values or {"request": request})
    buffer.register_scopes(step_scope_from_spec(step) for step in workflow.steps)
    initial_buffer_snapshot = buffer.snapshot()
    started_at = utc_now()
    runner_manifest = build_runner_manifest(workflow, step_runner_registry)
    manifest = build_run_manifest(
        run_id=actual_run_id,
        workflow=workflow,
        profile=profile,
        started_at=started_at,
    )
    manifest["runners"] = runner_manifest.to_dict()["runners"]
    update_manifest_runner_versions(manifest, runner_manifest)
    trace_context = TraceContext.root(
        run_id=actual_run_id,
        workflow_id=workflow.workflow_id,
        metadata={"profile": profile},
    )
    recorder.with_trace_context(trace_context)
    manifest["trace_id"] = trace_context.trace_id
    manifest["root_span_id"] = trace_context.span_id
    manifest["trace_events_ref"] = "events.jsonl"
    manifest["step_spans"] = {}
    step_results = dict(initial_step_results or {})
    if step_results:
        manifest["steps"].update(
            {
                step_id: outcome.to_dict()
                for step_id, outcome in step_results.items()
            }
        )
    return WorkflowExecutionContext(
        run_id=actual_run_id,
        run_dir=run_dir,
        workflow=workflow,
        request=request,
        profile=profile,
        recorder=recorder,
        trace_context=trace_context,
        buffer=buffer,
        initial_buffer_snapshot=initial_buffer_snapshot,
        started_at=started_at,
        started_monotonic=started_monotonic,
        manifest=manifest,
        status=WorkflowStatus.RUNNING,
        path=list(initial_path or []),
        step_results=step_results,
        current_step_ids=list(current_step_ids or [workflow.start_step_id]),
    )


def is_terminal_step_outcome(outcome: StepOutcome) -> bool:
    return outcome.status in {
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.BLOCKED,
        StepStatus.SKIPPED,
        StepStatus.TIMEOUT,
        StepStatus.CANCELLED,
    }
