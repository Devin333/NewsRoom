from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.events.recorder import EventBus, EventRecorder
from core.framework.specs import (
    EdgeCondition,
    StepSpec,
    StepStatus,
    StepType,
    WorkflowSpec,
    WorkflowStatus,
)
from core.framework.workflow.buffer import DataBuffer, step_scope_from_spec
from core.framework.workflow.artifact_publishers import (
    ArtifactPublishContext,
    ArtifactPublishPhase,
    RuntimeArtifactPublisher,
    WorkflowArtifactPublisher,
    WorkflowArtifactPublisherRegistry,
)
from core.framework.workflow.budget_governance import (
    budget_summary_from_tracker,
    restore_global_budget_tracker_usage,
)
from core.framework.workflow.checkpointing import (
    ResumeMode,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
    envelope_from_checkpoint,
    envelope_to_checkpoint,
    inspect_checkpoint_artifacts,
)
from core.framework.workflow.manifest import (
    add_manifest_checkpoint,
    build_runner_manifest,
    build_run_manifest,
    register_manifest_artifact,
    register_manifest_step_artifact,
    update_manifest_metrics,
    update_manifest_runner_versions,
)
from core.framework.workflow.resource_governance import (
    StepResourceEstimator,
    StepResourceGuard,
)
from core.framework.workflow.result import StepOutcome, WorkflowError, WorkflowResult
from core.framework.workflow.routing import RoutingDecision, RoutingEngine
from core.framework.workflow.safety_governance import safety_violation_for_step
from core.framework.workflow.state_machine import (
    WorkflowRuntimeEvent,
    WorkflowRuntimeEventType,
    WorkflowStateMachine,
)
from core.framework.workflow.step_runner import (
    FunctionStepRunner,
    StepExecutionError,
    StepRunnerRegistry,
)
from core.framework.workflow.runner import StepRunnerResolutionError
from storage.artifacts import ArtifactRef
from storage.checkpoint import WorkflowCheckpoint

_WORKFLOW_STEP_TIMEOUT_ERROR = "WorkflowStepTimeoutError"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _artifact_publisher_registry(
    artifact_publishers: list[WorkflowArtifactPublisher]
    | WorkflowArtifactPublisherRegistry
    | None,
) -> WorkflowArtifactPublisherRegistry:
    if isinstance(artifact_publishers, WorkflowArtifactPublisherRegistry):
        return artifact_publishers
    return WorkflowArtifactPublisherRegistry(
        [*(artifact_publishers or []), RuntimeArtifactPublisher()]
    )


class WorkflowExecutor:
    def __init__(
        self,
        function_step_runner: FunctionStepRunner | None,
        artifact_manager: ArtifactManager,
        routing_engine: RoutingEngine | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        step_runner_registry: StepRunnerRegistry | None = None,
        checkpoint_store: Any | None = None,
        event_bus: EventBus | None = None,
        global_budget_tracker: Any | None = None,
        artifact_publishers: list[WorkflowArtifactPublisher]
        | WorkflowArtifactPublisherRegistry
        | None = None,
    ) -> None:
        if step_runner_registry is None:
            if function_step_runner is None:
                raise ValueError("function_step_runner is required without step_runner_registry")
            step_runner_registry = StepRunnerRegistry.with_function_runner(function_step_runner)
        self._step_runner_registry = step_runner_registry
        self._artifact_manager = artifact_manager
        self._routing_engine = routing_engine or RoutingEngine()
        self._sleep_fn = sleep_fn or time.sleep
        self._checkpoint_store = checkpoint_store
        self._event_bus = event_bus
        self._global_budget_tracker = global_budget_tracker
        self._artifact_publishers = _artifact_publisher_registry(artifact_publishers)
        self._workflow_state_machine = WorkflowStateMachine()

    def execute(
        self,
        workflow: WorkflowSpec,
        request: dict[str, Any],
        *,
        profile: str,
        run_id: str | None = None,
        _initial_buffer_values: dict[str, Any] | None = None,
        _current_step_ids: list[str] | None = None,
        _initial_path: list[str] | None = None,
        _initial_step_results: dict[str, StepOutcome] | None = None,
        _resumed_checkpoint_id: str | None = None,
        _resume_metadata: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        initial_buffer_values = _initial_buffer_values or {"request": request}
        workflow.validate(
            request_keys=list(initial_buffer_values),
            strict=True,
            checkpoint_store_available=self._checkpoint_store is not None,
            allow_pause_artifact_strategy=True,
        )
        _validate_step_runners(workflow, self._step_runner_registry)

        actual_run_id = run_id or uuid4().hex
        run_dir = self._artifact_manager.start_run(actual_run_id)
        _configure_step_runners(
            self._step_runner_registry,
            artifact_manager=self._artifact_manager,
            run_id=actual_run_id,
            workflow=workflow,
            global_budget_tracker=self._global_budget_tracker,
        )
        recorder = EventRecorder(actual_run_id, event_bus=self._event_bus)
        buffer = DataBuffer(initial_buffer_values)
        buffer.register_scopes(step_scope_from_spec(step) for step in workflow.steps)
        initial_buffer_snapshot = buffer.snapshot()
        started_at = _utc_now()
        started_monotonic = time.perf_counter()

        runner_manifest = build_runner_manifest(
            workflow,
            self._step_runner_registry,
        )
        manifest = build_run_manifest(
            run_id=actual_run_id,
            workflow=workflow,
            profile=profile,
            started_at=started_at,
        )
        manifest["runners"] = runner_manifest.to_dict()["runners"]
        update_manifest_runner_versions(manifest, runner_manifest)
        if _resumed_checkpoint_id is not None:
            manifest["resumed_from_checkpoint_id"] = _resumed_checkpoint_id
        if _resume_metadata:
            manifest["resume_metadata"] = _public_resume_metadata(_resume_metadata)
            _apply_resume_metadata_to_manifest(manifest, _resume_metadata)
            _apply_human_review_resume_metadata_to_manifest(manifest, _resume_metadata)

        status = self._workflow_state_machine.transition(
            WorkflowStatus.CREATED,
            WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.START,
                reason=(
                    "workflow_resumed"
                    if _resumed_checkpoint_id is not None
                    else "workflow_execution_started"
                ),
                checkpoint_id=_resumed_checkpoint_id,
            ),
        )

        self._artifact_publishers.publish_all(
            ArtifactPublishContext(
                phase=ArtifactPublishPhase.START,
                run_id=actual_run_id,
                workflow=workflow,
                profile=profile,
                status=status,
                request=request,
                output={},
                manifest=manifest,
                artifact_manager=self._artifact_manager,
                step_results={},
                path=[],
                initial_buffer_snapshot=initial_buffer_snapshot,
            )
        )

        if _resumed_checkpoint_id is None:
            recorder.emit(
                "workflow_started",
                {
                    "workflow_id": workflow.workflow_id,
                    "workflow_version": workflow.version,
                    "profile": profile,
                },
            )
        else:
            resumed_payload = {
                "workflow_id": workflow.workflow_id,
                "workflow_version": workflow.version,
                "profile": profile,
                "checkpoint_id": _resumed_checkpoint_id,
            }
            if _resume_metadata:
                resumed_payload["resume_metadata"] = _public_resume_metadata(
                    _resume_metadata
                )
            recorder.emit(
                "workflow_resumed",
                resumed_payload,
            )
            _emit_human_review_resume_events(recorder, _resume_metadata)
            recorder.emit("checkpoint_restored", {"checkpoint_id": _resumed_checkpoint_id})

        error: WorkflowError | None = None
        path: list[str] = list(_initial_path or [])
        step_results: dict[str, StepOutcome] = dict(_initial_step_results or {})
        if step_results:
            manifest["steps"].update(
                {
                    step_id: outcome.to_dict()
                    for step_id, outcome in step_results.items()
                }
            )
        checkpoint_ids: list[str] = []
        step_visit_counts: dict[str, int] = {}
        current_step_ids: list[str] = list(_current_step_ids or [workflow.start_step_id])

        while current_step_ids:
            if self._is_run_cancelled(actual_run_id):
                status = _workflow_transition(
                    self._workflow_state_machine,
                    status,
                    WorkflowRuntimeEvent(
                        event_type=WorkflowRuntimeEventType.CANCEL,
                        reason="cancel marker found",
                    ),
                )
                recorder.emit("workflow_cancelled", {"run_id": actual_run_id})
                current_step_ids = []
                break
            current_step_id = current_step_ids.pop(0)
            visit_count = step_visit_counts.get(current_step_id, 0) + 1
            step_visit_counts[current_step_id] = visit_count
            if visit_count > workflow.max_step_visits:
                status = _workflow_transition(
                    self._workflow_state_machine,
                    status,
                    WorkflowRuntimeEvent(
                        event_type=WorkflowRuntimeEventType.FAIL,
                        reason="workflow_loop_limit_exceeded",
                        step_id=current_step_id,
                        metadata={
                            "max_step_visits": workflow.max_step_visits,
                            "visit_count": visit_count,
                        },
                    ),
                )
                error = WorkflowError(
                    error_type="WorkflowLoopLimitExceeded",
                    message=(
                        f"step visit limit exceeded for {current_step_id}: "
                        f"{workflow.max_step_visits}"
                    ),
                    step_id=current_step_id,
                    details={
                        "max_step_visits": workflow.max_step_visits,
                        "visit_count": visit_count,
                    },
                )
                recorder.emit(
                    "workflow_loop_limit_exceeded",
                    {
                        "step_id": current_step_id,
                        "max_step_visits": workflow.max_step_visits,
                        "visit_count": visit_count,
                    },
                )
                current_step_ids = []
                break

            step = workflow.step_by_id(current_step_id)
            path.append(step.step_id)
            _write_step_policy_input_artifact(
                self._artifact_manager,
                actual_run_id,
                step,
                buffer,
                manifest,
            )
            outcome = self._run_step_with_retries(step, buffer, recorder)
            _emit_agent_loop_stream_events(recorder, step, outcome)
            _emit_memory_operation_events(recorder, step, outcome)
            outcome = self._write_llm_call_artifacts(actual_run_id, step, outcome)
            _sync_llm_call_artifacts_to_buffer(buffer, step, outcome)
            outcome = _finalize_step_outcome_contract(step, outcome)
            _write_step_policy_terminal_artifact(
                self._artifact_manager,
                actual_run_id,
                step,
                outcome,
                manifest,
            )
            stop_after_checkpoint = False

            step_results[step.step_id] = outcome
            manifest["steps"][step.step_id] = outcome.to_dict()
            _record_step_artifacts(manifest, outcome)
            _record_child_runs(manifest, outcome)
            manifest["path"] = list(path)

            if outcome.status == StepStatus.SUCCEEDED:
                recorder.emit(
                    "step_succeeded",
                    {"step_id": step.step_id, "outputs": sorted(outcome.outputs.keys())},
                )
                try:
                    routing_decision = self._routing_engine.decide(
                        workflow,
                        step,
                        outcome,
                        buffer=buffer,
                        fan_out=True,
                    )
                except Exception as exc:
                    status = _workflow_transition(
                        self._workflow_state_machine,
                        status,
                        WorkflowRuntimeEvent(
                            event_type=WorkflowRuntimeEventType.FAIL,
                            reason=str(exc),
                            step_id=step.step_id,
                            metadata={
                                "phase": "routing",
                                "exception": repr(exc),
                            },
                        ),
                    )
                    error = WorkflowError(
                        error_type=type(exc).__name__,
                        message=str(exc),
                        step_id=step.step_id,
                        details={"phase": "routing"},
                    )
                    current_step_ids = []
                else:
                    _emit_routing_events(recorder, routing_decision)
                    current_step_ids = _prepend_schedulable_steps(
                        workflow=workflow,
                        new_step_ids=routing_decision.target_step_ids,
                        existing_step_ids=current_step_ids,
                        step_results=step_results,
                    )
                    if not current_step_ids:
                        status = _workflow_transition(
                            self._workflow_state_machine,
                            status,
                            WorkflowRuntimeEvent(
                                event_type=WorkflowRuntimeEventType.SUCCEED,
                                reason="terminal_step_completed",
                                step_id=step.step_id,
                            ),
                        )
            elif outcome.status == StepStatus.PAUSED:
                current_step_ids = [step.step_id, *current_step_ids]
                recorder.emit("step_paused", {"step_id": step.step_id, "outcome": outcome})
                checkpoint_id = self._write_checkpoint(
                    run_id=actual_run_id,
                    workflow=workflow,
                    profile=profile,
                    current_step_ids=current_step_ids,
                    buffer=buffer,
                    step_results=step_results,
                    path=path,
                    recorder=recorder,
                )
                if checkpoint_id is not None:
                    checkpoint_ids.append(checkpoint_id)
                    add_manifest_checkpoint(manifest, checkpoint_id)
                pause_checkpoint_id = checkpoint_id or f"pause-artifact:{actual_run_id}:{step.step_id}"
                if step.step_type == StepType.HUMAN_REVIEW:
                    human_review_request_id = _human_review_request_id(step, outcome)
                    status = _workflow_transition(
                        self._workflow_state_machine,
                        status,
                        WorkflowRuntimeEvent(
                            event_type=WorkflowRuntimeEventType.REQUEST_HUMAN_REVIEW,
                            reason="human_review_required",
                            step_id=step.step_id,
                            checkpoint_id=pause_checkpoint_id,
                            human_review_request_id=human_review_request_id,
                        ),
                    )
                    recorder.emit(
                        "human_review_requested",
                        {
                            "step_id": step.step_id,
                            "request_id": human_review_request_id,
                            "checkpoint_id": pause_checkpoint_id,
                        },
                    )
                    recorder.emit(
                        "human_review_paused",
                        {"step_id": step.step_id, "outcome": outcome},
                    )
                    recorder.emit(
                        "workflow_paused",
                        {"reason": "human_review", "step_id": step.step_id},
                    )
                else:
                    status = _workflow_transition(
                        self._workflow_state_machine,
                        status,
                        WorkflowRuntimeEvent(
                            event_type=WorkflowRuntimeEventType.PAUSE,
                            reason="step_paused",
                            step_id=step.step_id,
                            checkpoint_id=pause_checkpoint_id,
                        ),
                    )
                    recorder.emit(
                        "workflow_paused",
                        {"reason": "step_paused", "step_id": step.step_id},
                    )
                stop_after_checkpoint = True
            elif _is_budget_exceeded_outcome(outcome):
                recorder.emit(
                    "step_blocked" if outcome.status == StepStatus.BLOCKED else "step_failed",
                    {"step_id": step.step_id, "outcome": outcome},
                )
                status = _workflow_transition(
                    self._workflow_state_machine,
                    status,
                    WorkflowRuntimeEvent(
                        event_type=WorkflowRuntimeEventType.BUDGET_EXCEEDED,
                        reason=outcome.error_message or "workflow_budget_exceeded",
                        step_id=step.step_id,
                        metadata=outcome.error_details,
                    ),
                )
                error = WorkflowError(
                    error_type=outcome.error_type or "WorkflowBudgetExceeded",
                    message=outcome.error_message or f"workflow budget exceeded at step: {step.step_id}",
                    step_id=step.step_id,
                    details=outcome.error_details,
                )
                current_step_ids = []
            elif outcome.status == StepStatus.BLOCKED:
                recorder.emit("step_blocked", {"step_id": step.step_id, "outcome": outcome})
                _record_policy_violation(manifest, outcome)
                status = _workflow_transition(
                    self._workflow_state_machine,
                    status,
                    WorkflowRuntimeEvent(
                        event_type=WorkflowRuntimeEventType.BLOCK,
                        reason=outcome.error_message or "step_blocked",
                        step_id=step.step_id,
                        metadata=outcome.error_details,
                    ),
                )
                error = WorkflowError(
                    error_type=outcome.error_type or "StepBlocked",
                    message=outcome.error_message or f"step blocked: {step.step_id}",
                    step_id=step.step_id,
                    details=outcome.error_details,
                )
                current_step_ids = []
            else:
                recorder.emit("step_failed", {"step_id": step.step_id, "outcome": outcome})
                step_error = WorkflowError(
                    error_type=outcome.error_type or "StepFailed",
                    message=outcome.error_message or f"step failed: {step.step_id}",
                    step_id=step.step_id,
                    details=outcome.error_details,
                )
                if _blocks_on_failure(step):
                    recorder.emit("step_blocked", {"step_id": step.step_id, "outcome": outcome})
                    _record_policy_violation(manifest, outcome)
                    status = _workflow_transition(
                        self._workflow_state_machine,
                        status,
                        WorkflowRuntimeEvent(
                            event_type=WorkflowRuntimeEventType.BLOCK,
                            reason=step_error.message,
                            step_id=step.step_id,
                            metadata=step_error.details,
                        ),
                    )
                    error = step_error
                    current_step_ids = []
                else:
                    fallback_step_id = _failure_fallback_step_id(workflow, step)
                    if fallback_step_id is not None:
                        current_step_ids = _prepend_new_steps([fallback_step_id], current_step_ids)
                    else:
                        status = _workflow_transition(
                            self._workflow_state_machine,
                            status,
                            WorkflowRuntimeEvent(
                                event_type=WorkflowRuntimeEventType.FAIL,
                                reason=step_error.message,
                                step_id=step.step_id,
                                metadata=step_error.details,
                            ),
                        )
                        error = step_error
                        current_step_ids = []
            if stop_after_checkpoint:
                break
            checkpoint_id = self._write_checkpoint(
                run_id=actual_run_id,
                workflow=workflow,
                profile=profile,
                current_step_ids=current_step_ids,
                buffer=buffer,
                step_results=step_results,
                path=path,
                recorder=recorder,
            )
            if checkpoint_id is not None:
                checkpoint_ids.append(checkpoint_id)
                add_manifest_checkpoint(manifest, checkpoint_id)

        final_buffer_snapshot = buffer.snapshot()
        output = final_buffer_snapshot.to_dict()
        buffer_diff = buffer.diff(initial_buffer_snapshot)
        manifest["status"] = status.value
        manifest["finished_at"] = _utc_now()
        manifest["event_count"] = len(recorder.list_events()) + 1
        manifest["step_count"] = len(step_results)
        manifest["current_step_ids"] = list(current_step_ids)
        manifest["checkpoint_count"] = len(checkpoint_ids)
        if checkpoint_ids:
            manifest["latest_checkpoint_id"] = checkpoint_ids[-1]
        self._write_agent_loop_artifacts(actual_run_id, manifest, output)

        if status == WorkflowStatus.SUCCEEDED:
            recorder.emit("workflow_succeeded", {"path": path})
        elif status in {WorkflowStatus.PAUSED, WorkflowStatus.WAITING_FOR_HUMAN}:
            pass
        elif status == WorkflowStatus.CANCELLED:
            pass
        else:
            terminal_event = _terminal_error_event_type(status)
            recorder.emit(terminal_event, {"path": path, "error": error})

        metrics_payload = _workflow_metrics_payload(
            started_monotonic=started_monotonic,
            status=status,
            path=path,
            step_results=step_results,
            checkpoint_count=len(checkpoint_ids),
            artifact_count=len(manifest.get("artifacts") or {}),
            event_count=len(recorder.list_events()),
            output=output,
            global_budget_tracker=self._global_budget_tracker,
        )
        manifest["memory_operations"] = metrics_payload.get("memory_operations", {})
        redaction_report = _redaction_report(output)
        update_manifest_metrics(manifest, metrics_payload)
        events_path = recorder.write_jsonl(run_dir / "events.jsonl")
        self._artifact_publishers.publish_all(
            ArtifactPublishContext(
                phase=ArtifactPublishPhase.TERMINAL,
                run_id=actual_run_id,
                workflow=workflow,
                profile=profile,
                status=status,
                request=request,
                output=output,
                manifest=manifest,
                artifact_manager=self._artifact_manager,
                step_results=step_results,
                path=path,
                error=error,
                current_step_ids=current_step_ids,
                checkpoint_ids=checkpoint_ids,
                initial_buffer_snapshot=initial_buffer_snapshot,
                final_buffer_snapshot=final_buffer_snapshot,
                buffer_diff=buffer_diff,
                metrics_payload=metrics_payload,
                redaction_report=redaction_report,
                events_path=events_path,
            )
        )
        manifest_path = run_dir / "manifest.json"

        return WorkflowResult(
            run_id=actual_run_id,
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            status=status,
            output=output,
            error=error,
            path=path,
            step_results=step_results,
            manifest=manifest,
            artifact_dir=str(run_dir),
            manifest_path=str(manifest_path),
            events_path=str(events_path),
        )

    def resume_from_checkpoint(
        self,
        workflow: WorkflowSpec,
        checkpoint: WorkflowCheckpoint,
        *,
        profile: str,
        run_id: str | None = None,
        buffer_updates: dict[str, Any] | None = None,
        resume_metadata: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        envelope = envelope_from_checkpoint(checkpoint)
        public_resume_metadata = dict(resume_metadata or {})
        actual_resume_metadata = dict(public_resume_metadata)
        recovery_report = inspect_checkpoint_artifacts(
            checkpoint=envelope,
            manifest=_load_checkpoint_manifest(self._artifact_manager.root, checkpoint.run_id),
            artifact_root=self._artifact_manager.root,
            strict=False,
        )
        actual_resume_metadata["partial_artifact_recovery"] = recovery_report.to_dict()
        actual_resume_metadata["_public_resume_metadata"] = (
            public_resume_metadata
            if resume_metadata is not None
            else {"partial_artifact_recovery": recovery_report.to_dict()}
        )
        mode = ResumeMode.WITH_PATCH if buffer_updates else ResumeMode.EXACT
        resume_request = WorkflowResumeRequest(
            mode=mode,
            checkpoint=envelope,
            run_id=run_id,
            patch=dict(buffer_updates or {}),
            strict=True,
            metadata=actual_resume_metadata,
        )
        try:
            plan = WorkflowResumePlanner().plan(workflow, resume_request)
        except ValueError as exc:
            raise StepExecutionError(str(exc)) from exc
        budget_usage = plan.resume_metadata.get("budget_usage")
        if restore_global_budget_tracker_usage(self._global_budget_tracker, budget_usage):
            plan.resume_metadata["resume_budget_inherited"] = True
        request = plan.initial_buffer_values.get("request")
        if not isinstance(request, dict):
            request = {}
        return self.execute(
            workflow,
            request,
            profile=profile,
            run_id=plan.run_id,
            _initial_buffer_values=plan.initial_buffer_values,
            _current_step_ids=plan.current_step_ids,
            _initial_path=plan.initial_path,
            _initial_step_results=plan.initial_step_results,
            _resumed_checkpoint_id=plan.resumed_from_checkpoint_id,
            _resume_metadata=plan.resume_metadata,
        )

    def _run_step_with_retries(
        self,
        step: StepSpec,
        buffer: DataBuffer,
        recorder: EventRecorder,
    ) -> StepOutcome:
        retry_policy = step.retry_policy
        max_attempts = retry_policy.max_retries + 1
        attempt = 1
        while True:
            recorder.emit(
                "step_started",
                {
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                },
            )
            resource_violation = _resource_policy_violation(step, buffer)
            if resource_violation is not None:
                recorder.emit("policy_violation", resource_violation)
                return StepOutcome(
                    status=StepStatus.BLOCKED,
                    error_type="WorkflowResourcePolicyViolation",
                    error_message=resource_violation["message"],
                    error_details=resource_violation,
                )
            safety_violation = safety_violation_for_step(step)
            if safety_violation is not None:
                recorder.emit("runtime_safety_violation", safety_violation)
                return StepOutcome(
                    status=StepStatus.BLOCKED,
                    error_type="WorkflowRuntimeSafetyViolation",
                    error_message=safety_violation["message"],
                    error_details=safety_violation,
                )
            capability_violation = _step_runner_capability_violation(
                step,
                self._step_runner_registry,
                resume_mode=False,
            )
            if capability_violation is not None:
                recorder.emit("runner_capability_violation", capability_violation)
                return StepOutcome(
                    status=StepStatus.FAILED,
                    error_type="StepRunnerCapabilityError",
                    error_message=capability_violation["message"],
                    error_details=capability_violation,
                )
            scoped_buffer = buffer.scoped(step.step_id)
            outcome = self._run_step_attempt(step, scoped_buffer, attempt, max_attempts)
            if outcome.status == StepStatus.TIMEOUT:
                recorder.emit(
                    "step_timeout",
                    {
                        "step_id": step.step_id,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "timeout_seconds": step.timeout_policy.timeout_seconds,
                        "on_timeout": step.timeout_policy.on_timeout,
                    },
                )
            if not _is_retryable_outcome(step, outcome):
                return outcome
            if attempt >= max_attempts or not retry_policy.should_retry(
                error_type=outcome.error_type
            ):
                return outcome

            retry_index = attempt
            delay_seconds = retry_policy.delay_for_retry(retry_index)
            recorder.emit(
                "step_retry_scheduled",
                {
                    "step_id": step.step_id,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "error_type": outcome.error_type,
                    "error_message": outcome.error_message,
                    "delay_seconds": delay_seconds,
                },
            )
            if delay_seconds:
                self._sleep_fn(delay_seconds)
            attempt += 1

    def _run_step_attempt(
        self,
        step: StepSpec,
        scoped_buffer: Any,
        attempt: int,
        max_attempts: int,
    ) -> StepOutcome:
        timeout_seconds = step.timeout_policy.timeout_seconds
        if timeout_seconds is None:
            return self._invoke_step_runner(step, scoped_buffer, attempt, max_attempts)

        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-workflow-step")
        future = pool.submit(
            self._invoke_step_runner,
            step,
            scoped_buffer,
            attempt,
            max_attempts,
        )
        timed_out = False
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            timed_out = True
            future.cancel()
            return StepOutcome(
                status=StepStatus.TIMEOUT,
                error_type=_WORKFLOW_STEP_TIMEOUT_ERROR,
                error_message=(
                    f"step {step.step_id} exceeded timeout of {timeout_seconds:g} seconds"
                ),
                error_details={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "timeout_seconds": timeout_seconds,
                    "on_timeout": step.timeout_policy.on_timeout,
                },
            )
        finally:
            pool.shutdown(wait=not timed_out, cancel_futures=True)

    def _invoke_step_runner(
        self,
        step: StepSpec,
        scoped_buffer: Any,
        attempt: int,
        max_attempts: int,
    ) -> StepOutcome:
        try:
            runner = self._step_runner_registry.resolve(step)
            if runner is None:
                raise StepRunnerResolutionError(
                    "step runner cannot resolve step: "
                    f"{step.step_id} ({step.step_type.value}:{step.implementation})"
                )
            outcome = runner.run(step, scoped_buffer)
            if not isinstance(outcome, StepOutcome):
                raise StepExecutionError(
                    f"step runner returned {type(outcome).__name__}, expected StepOutcome"
                )
            return _outcome_with_attempt(outcome, attempt=attempt, max_attempts=max_attempts)
        except Exception as exc:  # pragma: no cover - concrete branches covered by tests
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_details={"attempt": attempt, "max_attempts": max_attempts},
            )

    def _write_agent_loop_artifacts(
        self,
        run_id: str,
        manifest: dict[str, Any],
        output: dict[str, Any],
    ) -> None:
        if isinstance(output.get("agent_loop_metrics"), dict):
            metrics = output["agent_loop_metrics"]
            manifest["agent_loop_metrics"] = metrics
            manifest["llm_calls"] = metrics.get("llm_calls", 0)
            manifest["tool_calls"] = metrics.get("tool_calls", 0)
            manifest["token_usage"] = metrics.get("token_usage", {})
        agent_artifacts = {
            "agent_loop_events": "agent_loop_events.json",
            "agent_loop_diagnostics": "agent_loop_diagnostics.json",
            "agent_loop_trace": "agent_loop_trace.json",
        }
        for output_key, relative_path in agent_artifacts.items():
            if output_key not in output:
                continue
            self._artifact_manager.write_json(run_id, relative_path, output[output_key])
            register_manifest_artifact(manifest, output_key, relative_path)

    def _write_llm_call_artifacts(
        self,
        run_id: str,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> StepOutcome:
        llm_call_artifacts = outcome.outputs.get("llm_call_artifacts")
        if not isinstance(llm_call_artifacts, list) or not llm_call_artifacts:
            return outcome

        artifact_refs: list[ArtifactRef] = []
        written_payloads: list[dict[str, Any]] = []
        for index, payload in enumerate(llm_call_artifacts, start=1):
            if not isinstance(payload, dict):
                continue
            artifact_payload = dict(payload)
            artifact_id = str(
                artifact_payload.get("artifact_id")
                or f"{step.step_id}:llm_call:{index}"
            )
            relative_path = f"llm_calls/{step.step_id}_{index:03d}.json"
            path = self._artifact_manager.write_json(run_id, relative_path, artifact_payload)
            data = path.read_bytes()
            artifact_ref = ArtifactRef(
                artifact_id=artifact_id,
                run_id=run_id,
                step_id=step.step_id,
                artifact_type="llm_call",
                path=relative_path,
                content_type="application/json",
                size_bytes=len(data),
                checksum=sha256(data).hexdigest(),
                redacted=True,
                metadata={
                    "iteration": artifact_payload.get("iteration"),
                    "agent_id": (artifact_payload.get("metadata") or {}).get("agent_id")
                    if isinstance(artifact_payload.get("metadata"), dict)
                    else None,
                },
            )
            artifact_refs.append(artifact_ref)
            written_payloads.append({**artifact_payload, "artifact_ref": artifact_ref.to_dict()})

        if not artifact_refs:
            return outcome
        outputs = dict(outcome.outputs)
        outputs["llm_call_artifacts"] = written_payloads
        return StepOutcome(
            status=outcome.status,
            outputs=outputs,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
            error_details=dict(outcome.error_details),
            metrics=dict(outcome.metrics),
            artifacts=[*outcome.artifacts, *artifact_refs],
            lineage=[dict(item) for item in outcome.lineage],
            next_hint=outcome.next_hint,
        )

    def _write_checkpoint(
        self,
        *,
        run_id: str,
        workflow: WorkflowSpec,
        profile: str,
        current_step_ids: list[str],
        buffer: DataBuffer,
        step_results: dict[str, StepOutcome],
        path: list[str],
        recorder: EventRecorder,
    ) -> str | None:
        if self._checkpoint_store is None:
            return None

        event_offset = len(recorder.list_events())
        checkpoint_id = _checkpoint_id(path[-1] if path else "start", event_offset)
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=checkpoint_id,
            run_id=run_id,
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            current_step_ids=current_step_ids,
            data_buffer_snapshot=buffer.snapshot().to_dict(),
            step_results={
                step_id: outcome.to_dict()
                for step_id, outcome in step_results.items()
            },
            path=list(path),
            event_offset=event_offset,
            metadata={"profile": profile},
        )
        if self._global_budget_tracker is not None and hasattr(
            self._global_budget_tracker,
            "snapshot",
        ):
            checkpoint.metadata["budget_usage"] = self._global_budget_tracker.snapshot()
        checkpoint = envelope_to_checkpoint(envelope_from_checkpoint(checkpoint))
        self._checkpoint_store.save_checkpoint(checkpoint)
        recorder.emit(
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint_id,
                "current_step_ids": current_step_ids,
                "path": list(path),
            },
        )
        return checkpoint_id

    def _is_run_cancelled(self, run_id: str) -> bool:
        return (self._artifact_manager.run_dir(run_id) / "cancel.json").exists()


def _blocks_on_failure(step: StepSpec) -> bool:
    policy = step.failure_policy
    return policy.mark_as_blocked or policy.on_failure == "mark_as_blocked"


def _failure_fallback_step_id(workflow: WorkflowSpec, step: StepSpec) -> str | None:
    if step.failure_policy.fallback_step_id is not None:
        return step.failure_policy.fallback_step_id
    edges = [
        edge
        for edge in workflow.edges
        if edge.source_step_id == step.step_id and edge.condition == EdgeCondition.ON_FAILURE
    ]
    edges.sort(key=lambda edge: (edge.priority, edge.edge_id))
    if not edges:
        return None
    return edges[0].target_step_id


def _is_retryable_outcome(step: StepSpec, outcome: StepOutcome) -> bool:
    if _is_budget_exceeded_outcome(outcome):
        return False
    if outcome.status == StepStatus.FAILED:
        return True
    if outcome.status == StepStatus.TIMEOUT:
        return step.timeout_policy.on_timeout == "retry"
    return False


def _is_budget_exceeded_outcome(outcome: StepOutcome) -> bool:
    if outcome.status not in {StepStatus.FAILED, StepStatus.BLOCKED, StepStatus.TIMEOUT}:
        return False
    if outcome.outputs.get("budget_exceeded") is True:
        return True
    if outcome.error_details.get("budget_exceeded") is True:
        return True
    error_type = str(outcome.error_type or "").casefold()
    return "budget" in error_type and "exceed" in error_type


def _workflow_transition(
    state_machine: WorkflowStateMachine,
    current: WorkflowStatus,
    event: WorkflowRuntimeEvent,
) -> WorkflowStatus:
    if current == WorkflowStatus.RUNNING:
        return state_machine.transition(current, event)
    return current


def _human_review_request_id(step: StepSpec, outcome: StepOutcome) -> str:
    request_key = str(step.metadata.get("request_key") or "human_review_request")
    request = outcome.outputs.get(request_key)
    for source in (
        request,
        outcome.outputs.get("human_review_request"),
        outcome.outputs.get("human_review_decision"),
    ):
        request_id = _field_value(source, "request_id") or _field_value(source, "id")
        if request_id is not None:
            return str(request_id)
    return f"{step.step_id}:human_review_request"


def _field_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    if hasattr(value, key):
        return getattr(value, key)
    return None


def _terminal_error_event_type(status: WorkflowStatus) -> str:
    if status == WorkflowStatus.BLOCKED:
        return "workflow_blocked"
    if status == WorkflowStatus.BUDGET_EXCEEDED:
        return "workflow_budget_exceeded"
    return "workflow_failed"


def _prepend_new_steps(new_step_ids: list[str], existing_step_ids: list[str]) -> list[str]:
    queued = list(existing_step_ids)
    for step_id in reversed(new_step_ids):
        if step_id not in queued:
            queued.insert(0, step_id)
    return queued


def _prepend_schedulable_steps(
    *,
    workflow: WorkflowSpec,
    new_step_ids: list[str],
    existing_step_ids: list[str],
    step_results: dict[str, StepOutcome],
) -> list[str]:
    schedulable = [
        step_id
        for step_id in new_step_ids
        if _should_schedule_join(
            workflow=workflow,
            join_step=workflow.step_by_id(step_id),
            step_results=step_results,
        )
    ]
    return _prepend_new_steps(schedulable, existing_step_ids)


def _should_schedule_join(
    *,
    workflow: WorkflowSpec,
    join_step: StepSpec,
    step_results: dict[str, StepOutcome],
) -> bool:
    if join_step.step_type != StepType.JOIN:
        return True
    required_upstream_step_ids = _join_required_upstream_step_ids(workflow, join_step)
    if not required_upstream_step_ids:
        return True
    return all(
        step_id in step_results and _is_terminal_step_outcome(step_results[step_id])
        for step_id in required_upstream_step_ids
    )


def _join_required_upstream_step_ids(workflow: WorkflowSpec, join_step: StepSpec) -> list[str]:
    raw = join_step.metadata.get("required_upstream_step_ids") or join_step.metadata.get("upstream_step_ids")
    if isinstance(raw, list) and raw:
        return [str(step_id) for step_id in raw]
    return [
        edge.source_step_id
        for edge in workflow.edges
        if edge.target_step_id == join_step.step_id
    ]


def _is_terminal_step_outcome(outcome: StepOutcome) -> bool:
    return outcome.status in {
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.BLOCKED,
        StepStatus.SKIPPED,
        StepStatus.TIMEOUT,
        StepStatus.CANCELLED,
    }


def _step_outcomes_from_checkpoint(payload: dict[str, Any]) -> dict[str, StepOutcome]:
    outcomes: dict[str, StepOutcome] = {}
    for step_id, raw_outcome in payload.items():
        if not isinstance(raw_outcome, dict):
            continue
        outcomes[str(step_id)] = StepOutcome.from_dict(raw_outcome)
    return outcomes


def _resource_policy_violation(step: StepSpec, buffer: DataBuffer) -> dict[str, Any] | None:
    estimate = StepResourceEstimator().estimate_inputs(step, buffer)
    violations = StepResourceGuard().check(step, estimate)
    if not violations:
        return None
    violation = violations[0]
    payload = violation.to_dict()
    payload["policy"] = violation.code
    payload["resource_estimate"] = estimate.to_dict()
    if violation.code == "resource.max_items":
        payload["item_count"] = int(violation.actual)
        payload["max_items"] = int(violation.limit)
    return payload


def _record_policy_violation(manifest: dict[str, Any], outcome: StepOutcome) -> None:
    if outcome.error_type not in {
        "WorkflowResourcePolicyViolation",
        "WorkflowRuntimeSafetyViolation",
    }:
        return
    violations = manifest.setdefault("policy_violations", [])
    if not isinstance(violations, list):
        return
    violations.append(dict(outcome.error_details))


def _step_runner_capability_violation(
    step: StepSpec,
    registry: StepRunnerRegistry,
    *,
    resume_mode: bool,
) -> dict[str, Any] | None:
    runner = registry.resolve(step)
    if runner is None:
        return {
            "step_id": step.step_id,
            "step_type": step.step_type.value,
            "implementation": step.implementation,
            "message": (
                "No StepRunner can resolve step "
                f"{step.step_id}: {step.step_type.value}/{step.implementation}"
            ),
        }
    capability = getattr(runner, "capability", None)
    if capability is None:
        return None
    if step.timeout_policy.timeout_seconds is not None and not capability.supports_timeout:
        return {
            "step_id": step.step_id,
            "runner_id": capability.runner_id,
            "capability": "timeout",
            "message": (
                f"Runner {capability.runner_id} does not support timeout "
                f"for step {step.step_id}."
            ),
        }
    if step.retry_policy.max_retries > 0 and not capability.supports_retry:
        return {
            "step_id": step.step_id,
            "runner_id": capability.runner_id,
            "capability": "retry",
            "message": (
                f"Runner {capability.runner_id} does not support retry "
                f"for step {step.step_id}."
            ),
        }
    if resume_mode and not capability.supports_resume:
        return {
            "step_id": step.step_id,
            "runner_id": capability.runner_id,
            "capability": "resume",
            "message": (
                f"Runner {capability.runner_id} does not support resume "
                f"for step {step.step_id}."
            ),
        }
    return None


def _checkpoint_id(step_id: str, event_offset: int) -> str:
    safe_step_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in step_id
    ).strip("._-")
    return f"cp-{event_offset:06d}-{safe_step_id or 'step'}"


def _load_checkpoint_manifest(artifact_root: Path, run_id: str) -> dict[str, Any] | None:
    path = artifact_root / run_id / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _apply_resume_metadata_to_manifest(
    manifest: dict[str, Any],
    resume_metadata: dict[str, Any],
) -> None:
    for key in (
        "resume_mode",
        "resume_original_run_id",
        "resume_patch_keys",
        "resume_actor_id",
        "resume_approval_id",
        "resume_human_decision",
        "resume_human_review_request_id",
        "resume_current_step_ids",
        "checkpoint_schema_version",
        "checkpoint_checksum",
        "checkpoint_migrations",
        "operation_id",
        "operation_type",
        "original_run_id",
        "rerun_from_run_id",
        "rerun_from_step_id",
        "skip_step_id",
        "skip_reason",
        "skip_next_step_ids",
        "resume_budget_inherited",
    ):
        if key in resume_metadata:
            manifest[key] = resume_metadata[key]


def _apply_human_review_resume_metadata_to_manifest(
    manifest: dict[str, Any],
    resume_metadata: dict[str, Any],
) -> None:
    decision = resume_metadata.get("resume_human_decision")
    if decision is None:
        return
    reviews = manifest.setdefault("human_reviews", [])
    if not isinstance(reviews, list):
        return
    reviews.append(
        {
            "request_id": resume_metadata.get("resume_human_review_request_id"),
            "approval_id": resume_metadata.get("resume_approval_id"),
            "step_id": _resume_current_step_id(resume_metadata),
            "decision": decision,
            "actor_id": resume_metadata.get("resume_actor_id"),
            "decided_at": _utc_now(),
        }
    )


def _resume_current_step_id(resume_metadata: dict[str, Any]) -> str | None:
    current_step_ids = resume_metadata.get("resume_current_step_ids")
    if isinstance(current_step_ids, list) and current_step_ids:
        return str(current_step_ids[0])
    return None


def _public_resume_metadata(resume_metadata: dict[str, Any]) -> dict[str, Any]:
    public_metadata = resume_metadata.get("_public_resume_metadata")
    if isinstance(public_metadata, dict):
        return dict(public_metadata)
    return dict(resume_metadata)


def _emit_routing_events(recorder: EventRecorder, decision: RoutingDecision) -> None:
    for evaluation in decision.evaluations:
        payload = evaluation.to_dict()
        recorder.emit("edge_evaluated", payload)
        if evaluation.matched:
            recorder.emit("edge_traversed", payload)
        else:
            recorder.emit("edge_rejected", payload)


def _emit_human_review_resume_events(
    recorder: EventRecorder,
    resume_metadata: dict[str, Any] | None,
) -> None:
    if not resume_metadata:
        return
    decision = resume_metadata.get("resume_human_decision")
    if decision is None:
        return
    payload = {
        "decision": decision,
        "actor_id": resume_metadata.get("resume_actor_id"),
        "approval_id": resume_metadata.get("resume_approval_id"),
        "request_id": resume_metadata.get("resume_human_review_request_id"),
    }
    recorder.emit("human_review_decision_received", payload)
    if decision in {"approved", "rejected", "needs_changes"}:
        recorder.emit(f"human_review_{decision}", payload)


def _emit_agent_loop_stream_events(
    recorder: EventRecorder,
    step: StepSpec,
    outcome: StepOutcome,
) -> None:
    events = outcome.outputs.get("agent_loop_events")
    if not isinstance(events, list):
        return
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("event_type") != "llm_stream_event":
            continue
        recorder.emit(
            "agent_llm_stream_event",
            {
                "step_id": step.step_id,
                "agent_id": event.get("agent_id"),
                "iteration": event.get("iteration"),
                "sequence": event.get("sequence"),
                "stream_event_type": event.get("stream_event_type"),
                "text_delta_chars": event.get("text_delta_chars"),
                "stream_event": event.get("stream_event"),
            },
        )


def _emit_memory_operation_events(
    recorder: EventRecorder,
    step: StepSpec,
    outcome: StepOutcome,
) -> None:
    if step.step_type not in {StepType.MEMORY_RECALL, StepType.MEMORY_WRITE}:
        return
    operation = outcome.metrics.get("memory_operation")
    if not isinstance(operation, dict):
        return
    event_type = "memory_recall" if step.step_type == StepType.MEMORY_RECALL else "memory_write"
    recorder.emit(
        event_type,
        {
            "step_id": step.step_id,
            "status": outcome.status.value,
            **operation,
        },
    )


def _record_step_artifacts(manifest: dict[str, Any], outcome: StepOutcome) -> None:
    if not outcome.artifacts:
        return
    for artifact_ref in outcome.artifacts:
        register_manifest_step_artifact(manifest, artifact_ref)


def _record_child_runs(manifest: dict[str, Any], outcome: StepOutcome) -> None:
    raw_child_runs = outcome.outputs.get("child_runs")
    if not isinstance(raw_child_runs, list):
        return
    child_runs = manifest.setdefault("child_runs", [])
    if not isinstance(child_runs, list):
        return
    child_run_ids = manifest.setdefault("child_run_ids", [])
    if not isinstance(child_run_ids, list):
        return
    existing_ids = {
        item.get("child_run_id")
        for item in child_runs
        if isinstance(item, dict)
    }
    for item in raw_child_runs:
        if not isinstance(item, dict):
            continue
        child_run_id = item.get("child_run_id")
        if child_run_id is None:
            continue
        if child_run_id not in existing_ids:
            child_runs.append(dict(item))
            existing_ids.add(child_run_id)
        if child_run_id not in child_run_ids:
            child_run_ids.append(child_run_id)


def _outcome_with_attempt(outcome: StepOutcome, *, attempt: int, max_attempts: int) -> StepOutcome:
    metrics = dict(outcome.metrics)
    metrics.setdefault("attempt", attempt)
    metrics.setdefault("max_attempts", max_attempts)
    error_details = dict(outcome.error_details)
    if outcome.status in {StepStatus.FAILED, StepStatus.TIMEOUT, StepStatus.BLOCKED}:
        error_details.setdefault("attempt", attempt)
        error_details.setdefault("max_attempts", max_attempts)
    return StepOutcome(
        status=outcome.status,
        outputs=dict(outcome.outputs),
        error_type=outcome.error_type,
        error_message=outcome.error_message,
        error_details=error_details,
        metrics=metrics,
        artifacts=list(outcome.artifacts),
        lineage=[dict(item) for item in outcome.lineage],
        next_hint=outcome.next_hint,
    )


def _finalize_step_outcome_contract(step: StepSpec, outcome: StepOutcome) -> StepOutcome:
    allowed_output_keys = set(step.write_keys)
    filtered_outputs = {
        key: value
        for key, value in outcome.outputs.items()
        if key in allowed_output_keys
    }
    if outcome.status == StepStatus.SUCCEEDED:
        missing = sorted(set(step.required_output_keys) - set(filtered_outputs))
        if missing:
            error_details = {
                **dict(outcome.error_details),
                "missing_required_output_keys": missing,
            }
            return StepOutcome(
                status=StepStatus.FAILED,
                outputs=filtered_outputs,
                error_type="StepOutputContractViolation",
                error_message=(
                    f"step {step.step_id} did not return required output keys: "
                    f"{', '.join(missing)}"
                ),
                error_details=error_details,
                metrics=_ensure_contract_metrics(step, outcome, filtered_outputs),
                artifacts=list(outcome.artifacts),
                lineage=[dict(item) for item in outcome.lineage],
                next_hint=outcome.next_hint,
            )
    if filtered_outputs == outcome.outputs and _has_contract_metrics(outcome.metrics):
        return outcome
    return StepOutcome(
        status=outcome.status,
        outputs=filtered_outputs,
        error_type=outcome.error_type,
        error_message=outcome.error_message,
        error_details=dict(outcome.error_details),
        metrics=_ensure_contract_metrics(step, outcome, filtered_outputs),
        artifacts=list(outcome.artifacts),
        lineage=[dict(item) for item in outcome.lineage],
        next_hint=outcome.next_hint,
    )


def _ensure_contract_metrics(
    step: StepSpec,
    outcome: StepOutcome,
    outputs: dict[str, Any],
) -> dict[str, Any]:
    metrics = dict(outcome.metrics)
    metrics.setdefault("duration_ms", 0.0)
    metrics.setdefault("attempt", int(metrics.get("attempt") or 1))
    metrics.setdefault("input_key_count", len(step.read_keys))
    metrics["output_key_count"] = len(outputs)
    metrics.setdefault("artifact_count", len(outcome.artifacts))
    return metrics


def _has_contract_metrics(metrics: dict[str, Any]) -> bool:
    return all(
        key in metrics
        for key in (
            "duration_ms",
            "attempt",
            "input_key_count",
            "output_key_count",
            "artifact_count",
        )
    )


def _sync_llm_call_artifacts_to_buffer(
    buffer: DataBuffer,
    step: StepSpec,
    outcome: StepOutcome,
) -> None:
    artifacts = outcome.outputs.get("llm_call_artifacts")
    if "llm_call_artifacts" in step.write_keys and isinstance(artifacts, list):
        buffer.write(
            key="llm_call_artifacts",
            value=artifacts,
            step_id=step.step_id,
            lineage={"step_id": step.step_id, "post_processed": True},
        )


def _workflow_metrics_payload(
    *,
    started_monotonic: float,
    status: WorkflowStatus,
    path: list[str],
    step_results: dict[str, StepOutcome],
    checkpoint_count: int,
    artifact_count: int,
    event_count: int,
    output: dict[str, Any],
    global_budget_tracker: Any | None = None,
) -> dict[str, Any]:
    failed_steps = [
        step_id
        for step_id, outcome in step_results.items()
        if outcome.status in {StepStatus.FAILED, StepStatus.TIMEOUT, StepStatus.BLOCKED}
    ]
    retry_count = sum(
        int((outcome.error_details or {}).get("attempt", 1)) - 1
        for outcome in step_results.values()
        if isinstance((outcome.error_details or {}).get("attempt", 1), int)
    )
    metrics = {
        "run_duration_ms": round((time.perf_counter() - started_monotonic) * 1000, 3),
        "status": status.value,
        "step_count": len(step_results),
        "path_length": len(path),
        "failed_step_count": len(failed_steps),
        "failed_steps": failed_steps,
        "retry_count": retry_count,
        "checkpoint_count": checkpoint_count,
        "artifact_count": artifact_count,
        "event_count": event_count,
    }
    if "agent_loop_metrics" in output:
        agent_metrics = output["agent_loop_metrics"]
        if isinstance(agent_metrics, dict):
            metrics["llm_calls"] = agent_metrics.get("llm_calls", 0)
            metrics["tool_calls"] = agent_metrics.get("tool_calls", 0)
            metrics["token_usage"] = agent_metrics.get("token_usage", {})
            if agent_metrics.get("global_budget_check") is not None:
                metrics["global_budget_check"] = agent_metrics.get("global_budget_check")
            if agent_metrics.get("global_budget_usage") is not None:
                metrics["global_budget_usage"] = agent_metrics.get("global_budget_usage")
    if global_budget_tracker is not None and hasattr(global_budget_tracker, "snapshot"):
        metrics["global_budget_usage"] = global_budget_tracker.snapshot()
        budget_summary = budget_summary_from_tracker(global_budget_tracker)
        if budget_summary is not None:
            metrics["budget"] = budget_summary
    metrics["memory_operations"] = _memory_operations_summary(step_results)
    if "budget" not in metrics:
        metrics["budget"] = {
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "llm_calls": 0,
            "tool_calls": 0,
            "wall_time_seconds": 0.0,
            "exceeded": status == WorkflowStatus.BUDGET_EXCEEDED,
            "exceeded_reason": (
                "workflow_budget_exceeded"
                if status == WorkflowStatus.BUDGET_EXCEEDED
                else None
            ),
        }
    return metrics


def _memory_operations_summary(step_results: dict[str, StepOutcome]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    recall_count = 0
    write_count = 0
    recalled_memory_ids: set[str] = set()
    written_memory_ids: set[str] = set()
    total_recall_results = 0
    total_written_records = 0

    for step_id, outcome in step_results.items():
        operation = outcome.metrics.get("memory_operation")
        if not isinstance(operation, dict):
            continue
        operation_type = str(operation.get("operation") or "")
        item = {
            "step_id": step_id,
            "operation": operation_type,
            "status": outcome.status.value,
            "memory_ids": [str(memory_id) for memory_id in operation.get("memory_ids") or []],
        }
        if operation_type == "recall":
            recall_count += 1
            result_count = int(operation.get("result_count") or 0)
            total_recall_results += result_count
            item["result_count"] = result_count
            item["context_token_estimate"] = int(operation.get("context_token_estimate") or 0)
            recalled_memory_ids.update(item["memory_ids"])
        elif operation_type == "write":
            write_count += 1
            written_count = int(operation.get("written_count") or 0)
            total_written_records += written_count
            item["accepted_count"] = int(operation.get("accepted_count") or 0)
            item["written_count"] = written_count
            item["skipped_count"] = int(operation.get("skipped_count") or 0)
            written_memory_ids.update(item["memory_ids"])
        operations.append(item)

    return {
        "operation_count": len(operations),
        "recall_count": recall_count,
        "write_count": write_count,
        "total_recall_results": total_recall_results,
        "total_written_records": total_written_records,
        "recalled_memory_ids": sorted(recalled_memory_ids),
        "written_memory_ids": sorted(written_memory_ids),
        "operations": operations,
    }


def _redaction_report(output: dict[str, Any]) -> dict[str, Any]:
    redacted_keys = sorted(key for key in output if _sensitive_key(str(key)))
    return {
        "redacted": bool(redacted_keys),
        "redacted_keys": redacted_keys,
        "rules": ["sensitive_top_level_buffer_key"],
    }


def _write_step_policy_input_artifact(
    artifact_manager: ArtifactManager,
    run_id: str,
    step: StepSpec,
    buffer: DataBuffer,
    manifest: dict[str, Any],
) -> None:
    policy = step.artifact_policy
    if policy is None or not policy.write_step_input:
        return
    payload = {
        key: buffer.read(key)
        for key in step.read_keys
        if buffer.exists(key)
    }
    if policy.redacted:
        payload = {
            key: "[REDACTED]" if _sensitive_key(key) else value
            for key, value in payload.items()
        }
    relative_path = f"steps/{step.step_id}/input.json"
    artifact_manager.write_json(run_id, relative_path, payload)
    register_manifest_artifact(manifest, f"step.{step.step_id}.input", relative_path)


def _write_step_policy_terminal_artifact(
    artifact_manager: ArtifactManager,
    run_id: str,
    step: StepSpec,
    outcome: StepOutcome,
    manifest: dict[str, Any],
) -> None:
    policy = step.artifact_policy
    if policy is None:
        return
    if policy.write_step_output:
        relative_path = f"steps/{step.step_id}/output.json"
        artifact_manager.write_json(run_id, relative_path, outcome.outputs)
        register_manifest_artifact(manifest, f"step.{step.step_id}.output", relative_path)
    if policy.write_step_error and outcome.status not in {StepStatus.SUCCEEDED, StepStatus.PAUSED}:
        relative_path = f"steps/{step.step_id}/error.json"
        artifact_manager.write_json(
            run_id,
            relative_path,
            {
                "status": outcome.status.value,
                "error_type": outcome.error_type,
                "error_message": outcome.error_message,
                "error_details": outcome.error_details,
            },
        )
        register_manifest_artifact(manifest, f"step.{step.step_id}.error", relative_path)


def _sensitive_key(key: str) -> bool:
    key_lower = key.casefold()
    return any(
        token in key_lower
        for token in (
            "api_key",
            "apikey",
            "authorization",
            "client_secret",
            "password",
            "secret",
            "token",
        )
    )


def _validate_step_runners(workflow: WorkflowSpec, registry: StepRunnerRegistry) -> None:
    validation = registry.validate_workflow(workflow)
    if validation.passed:
        return
    messages = [
        f"{issue.step_id}:{issue.code}:{issue.message}"
        for issue in validation.errors
    ]
    legacy_messages = []
    for issue in validation.errors:
        step_type = issue.details.get("step_type")
        implementation = issue.details.get("implementation")
        if issue.code == "runner_not_found" and step_type:
            legacy_messages.append(f"step runner is not registered: {step_type}")
        if issue.code == "implementation_not_resolvable" and implementation:
            legacy_messages.append(
                f"step implementation is not registered: {implementation}"
            )
    detail_messages = [*messages, *legacy_messages]
    raise StepExecutionError("step runner validation failed: " + "; ".join(detail_messages))


def _configure_step_runners(
    registry: StepRunnerRegistry,
    *,
    artifact_manager: ArtifactManager,
    run_id: str,
    workflow: WorkflowSpec,
    global_budget_tracker: Any | None = None,
) -> None:
    configured_runner_ids: set[str] = set()
    for step_type in registry.registered_step_types():
        runner = registry.get(step_type)
        capability = getattr(runner, "capability", None)
        runner_id = getattr(capability, "runner_id", f"{step_type.value}:{id(runner)}")
        if runner_id in configured_runner_ids:
            continue
        configured_runner_ids.add(str(runner_id))
        configure = getattr(runner, "configure_run_context", None)
        if callable(configure):
            configure(artifact_manager=artifact_manager, run_id=run_id)
        configure_workflow = getattr(runner, "configure_workflow_context", None)
        if callable(configure_workflow):
            configure_workflow(workflow=workflow)
        configure_budget = getattr(runner, "configure_global_budget_tracker", None)
        if callable(configure_budget) and global_budget_tracker is not None:
            configure_budget(global_budget_tracker)
