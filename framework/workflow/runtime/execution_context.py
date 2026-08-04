from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.specs import StepStatus, WorkflowSpec, WorkflowStatus
from framework.shared.attempts import ExecutionLimits, RetryCreditLedger
from framework.workflow.buffer import DataBuffer, DataBufferSnapshot, step_scope_from_spec
from framework.events.canonical import BusinessContext
from framework.events.ports import EventReaderPort, EventRuntimePort
from framework.events.schema import EventSchemaCatalog, default_event_schema_catalog
from framework.events.trace import TraceContext
from framework.agent.artifacts import ArtifactManager, validate_artifact_path_segment
from framework.workflow.runtime.event_emitter import (
    ScopedDurableWorkflowEventEmitter,
    WorkflowEventRecorderFacade,
)
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
    event_emitter: ScopedDurableWorkflowEventEmitter
    recorder: WorkflowEventRecorderFacade
    trace_context: TraceContext
    buffer: DataBuffer
    initial_buffer_snapshot: DataBufferSnapshot
    started_at: str
    started_monotonic: float
    execution_limits: ExecutionLimits
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
    event_runtime: EventRuntimePort | None = None,
    event_reader: EventReaderPort | None = None,
    event_schema_catalog: EventSchemaCatalog | None = None,
    started_monotonic: float,
    run_id: str | None = None,
    initial_buffer_values: dict[str, Any] | None = None,
    current_step_ids: list[str] | None = None,
    initial_path: list[str] | None = None,
    initial_step_results: dict[str, StepOutcome] | None = None,
    resumed_from_checkpoint: bool = False,
) -> WorkflowExecutionContext:
    actual_run_id = (
        uuid4().hex
        if run_id is None
        else validate_artifact_path_segment(run_id, field="run_id")
    )
    if event_runtime is None:
        raise ValueError("event_runtime is required for durable workflow execution")
    if event_reader is None:
        raise ValueError("event_reader is required for durable workflow execution")
    execution_policy = workflow.policies.execution_policy
    max_total_retries = execution_policy.max_total_retries
    retry_policy_source = "policies.execution_policy.max_total_retries"
    if max_total_retries is None:
        max_total_retries = _compiled_retry_ceiling(workflow)
        retry_policy_source = "spec_compiler"
    hard_timeout_candidates = [
        value
        for value in (
            workflow.policies.timeout_policy.timeout_seconds,
            workflow.policies.resource_policy.max_runtime_seconds,
        )
        if value is not None
    ]
    hard_timeout = (
        min(float(value) for value in hard_timeout_candidates)
        if hard_timeout_candidates
        else None
    )
    root_reserve = (
        execution_policy.verify_reserve_seconds
        + execution_policy.commit_reserve_seconds
    )
    if hard_timeout is not None and root_reserve >= hard_timeout:
        raise ValueError(
            "workflow deadline reserves must leave a positive execution window"
        )
    hard_deadline = (
        started_monotonic + hard_timeout
        if hard_timeout is not None
        else None
    )
    execution_limits = ExecutionLimits(
        execution_id=actual_run_id,
        hard_deadline=hard_deadline,
        retry_credits=RetryCreditLedger(
            max_total_retries=max_total_retries
        ),
        cancellation_grace_seconds=execution_policy.cancellation_grace_seconds,
        verify_reserve_seconds=execution_policy.verify_reserve_seconds,
        commit_reserve_seconds=execution_policy.commit_reserve_seconds,
    )
    run_dir = artifact_manager.start_run(actual_run_id)
    schema_catalog = event_schema_catalog or default_event_schema_catalog()
    event_emitter = ScopedDurableWorkflowEventEmitter(
        runtime=event_runtime,
        reader=event_reader,
        schema_catalog=schema_catalog,
        stream_id=f"run:{actual_run_id}",
        base_business_context=BusinessContext(
            run_id=actual_run_id,
            workflow_id=workflow.workflow_id,
        ),
    )
    recorder = WorkflowEventRecorderFacade(event_emitter)
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
    manifest["trace_id"] = trace_context.trace_id
    manifest["root_span_id"] = trace_context.span_id
    manifest["trace_events_ref"] = "events.jsonl"
    manifest["step_spans"] = {}
    manifest["attempt_execution_limits"] = {
        "schema_version": "attempt-execution-limits/v1",
        "max_total_retries": max_total_retries,
        "retry_policy_source": retry_policy_source,
        "hard_timeout_seconds": hard_timeout,
        "hard_deadline_monotonic_runtime_only": hard_deadline,
        "cancellation_grace_seconds": execution_policy.cancellation_grace_seconds,
        "verify_reserve_seconds": execution_policy.verify_reserve_seconds,
        "commit_reserve_seconds": execution_policy.commit_reserve_seconds,
        "resume_budget_reset": bool(resumed_from_checkpoint),
    }
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
        event_emitter=event_emitter,
        recorder=recorder,
        trace_context=trace_context,
        buffer=buffer,
        initial_buffer_snapshot=initial_buffer_snapshot,
        started_at=started_at,
        started_monotonic=started_monotonic,
        execution_limits=execution_limits,
        manifest=manifest,
        status=WorkflowStatus.CREATED,
        path=list(initial_path or []),
        step_results=step_results,
        current_step_ids=list(current_step_ids or [workflow.start_step_id]),
    )


def _compiled_retry_ceiling(workflow: WorkflowSpec) -> int:
    """Compile a fixed root ceiling before live execution begins."""

    total = 0
    for step in workflow.steps:
        max_attempts = step.retry_policy.max_attempts
        if max_attempts is None:
            max_attempts = step.retry_policy.max_retries + 1
        total += max(0, int(max_attempts) - 1)
        tool_policy = (step.metadata or {}).get("tool_policy")
        if isinstance(tool_policy, dict):
            if "max_total_attempts" in tool_policy:
                raise ValueError(
                    "legacy tool_policy.max_total_attempts requires explicit "
                    "migration to max_total_retries"
                )
            nested_retries = tool_policy.get("max_total_retries")
            if nested_retries is not None:
                if type(nested_retries) is not int or nested_retries < 0:
                    raise ValueError(
                        "tool_policy.max_total_retries must be a non-negative integer"
                    )
                total += nested_retries
        if step.step_type.value == "parallel_group":
            branches = (step.metadata or {}).get("branches")
            if isinstance(branches, list):
                for branch in branches:
                    if not isinstance(branch, dict):
                        continue
                    retry_policy = branch.get("retry_policy")
                    if not isinstance(retry_policy, dict):
                        continue
                    max_retries = retry_policy.get("max_retries", 0)
                    if type(max_retries) is not int or max_retries < 0:
                        raise ValueError(
                            "parallel branch max_retries must be a non-negative integer"
                        )
                    total += max_retries
    return total


def is_terminal_step_outcome(outcome: StepOutcome) -> bool:
    return outcome.status in {
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.BLOCKED,
        StepStatus.SKIPPED,
        StepStatus.TIMEOUT,
        StepStatus.CANCELLED,
    }
