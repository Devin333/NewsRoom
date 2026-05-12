from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.artifacts.source_artifacts import SourceArtifactWriter
from core.framework.events.recorder import EventRecorder
from core.framework.specs import EdgeCondition, StepSpec, StepStatus, WorkflowSpec, WorkflowStatus
from core.framework.workflow.buffer import DataBuffer
from core.framework.workflow.result import StepOutcome, WorkflowError, WorkflowResult
from core.framework.workflow.routing import RoutingDecision, RoutingEngine
from core.framework.workflow.step_runner import (
    FunctionStepRunner,
    StepExecutionError,
    StepRunnerRegistry,
)
from storage.checkpoint import WorkflowCheckpoint

_WORKFLOW_STEP_TIMEOUT_ERROR = "WorkflowStepTimeoutError"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class WorkflowExecutor:
    def __init__(
        self,
        function_step_runner: FunctionStepRunner | None,
        artifact_manager: ArtifactManager,
        routing_engine: RoutingEngine | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        step_runner_registry: StepRunnerRegistry | None = None,
        checkpoint_store: Any | None = None,
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

    def execute(
        self,
        workflow: WorkflowSpec,
        request: dict[str, Any],
        *,
        profile: str,
        run_id: str | None = None,
    ) -> WorkflowResult:
        workflow.validate()
        _validate_step_runners(workflow, self._step_runner_registry)

        actual_run_id = run_id or uuid4().hex
        run_dir = self._artifact_manager.start_run(actual_run_id)
        recorder = EventRecorder(actual_run_id)
        buffer = DataBuffer({"request": request})
        initial_buffer_snapshot = buffer.snapshot()
        started_at = _utc_now()

        self._artifact_manager.write_json(actual_run_id, "request.json", request)
        self._artifact_manager.write_json(actual_run_id, "workflow_spec.json", workflow)
        self._artifact_manager.write_json(
            actual_run_id,
            "data_buffer.initial.json",
            initial_buffer_snapshot.to_dict(),
        )

        manifest: dict[str, Any] = {
            "run_id": actual_run_id,
            "workflow_id": workflow.workflow_id,
            "workflow_version": workflow.version,
            "profile": profile,
            "status": WorkflowStatus.RUNNING.value,
            "started_at": started_at,
            "finished_at": None,
            "path": [],
            "steps": {},
            "artifacts": {
                "request": "request.json",
                "workflow_spec": "workflow_spec.json",
                "events": "events.jsonl",
                "manifest": "manifest.json",
                "data_buffer_snapshot": "data_buffer_snapshot.json",
                "data_buffer_initial": "data_buffer.initial.json",
                "data_buffer_final": "data_buffer.final.json",
                "data_buffer_diff": "data_buffer.diff.json",
            },
        }

        recorder.emit(
            "workflow_started",
            {
                "workflow_id": workflow.workflow_id,
                "workflow_version": workflow.version,
                "profile": profile,
            },
        )

        status = WorkflowStatus.RUNNING
        error: WorkflowError | None = None
        path: list[str] = []
        step_results: dict[str, StepOutcome] = {}
        checkpoint_ids: list[str] = []
        step_visit_counts: dict[str, int] = {}
        current_step_id: str | None = workflow.start_step_id

        while current_step_id:
            visit_count = step_visit_counts.get(current_step_id, 0) + 1
            step_visit_counts[current_step_id] = visit_count
            if visit_count > workflow.max_step_visits:
                status = WorkflowStatus.FAILED
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
                current_step_id = None
                break

            step = workflow.step_by_id(current_step_id)
            path.append(step.step_id)
            outcome = self._run_step_with_retries(step, buffer, recorder)

            step_results[step.step_id] = outcome
            manifest["steps"][step.step_id] = outcome.to_dict()
            _record_step_artifacts(manifest, outcome)
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
                    )
                except Exception as exc:
                    status = WorkflowStatus.FAILED
                    error = WorkflowError(
                        error_type=type(exc).__name__,
                        message=str(exc),
                        step_id=step.step_id,
                        details={"phase": "routing"},
                    )
                    current_step_id = None
                else:
                    _emit_routing_events(recorder, routing_decision)
                    current_step_id = routing_decision.target_step_id
                    if current_step_id is None:
                        status = WorkflowStatus.SUCCEEDED
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
                    status = WorkflowStatus.BLOCKED
                    error = step_error
                    current_step_id = None
                else:
                    fallback_step_id = _failure_fallback_step_id(workflow, step)
                    if fallback_step_id is not None:
                        current_step_id = fallback_step_id
                    else:
                        status = WorkflowStatus.FAILED
                        error = step_error
                        current_step_id = None
            checkpoint_id = self._write_checkpoint(
                run_id=actual_run_id,
                workflow=workflow,
                profile=profile,
                current_step_id=current_step_id,
                buffer=buffer,
                step_results=step_results,
                path=path,
                recorder=recorder,
            )
            if checkpoint_id is not None:
                checkpoint_ids.append(checkpoint_id)

        final_buffer_snapshot = buffer.snapshot()
        output = final_buffer_snapshot.to_dict()
        buffer_diff = buffer.diff(initial_buffer_snapshot)
        manifest["status"] = status.value
        manifest["finished_at"] = _utc_now()
        manifest["event_count"] = len(recorder.list_events()) + 1
        manifest["step_count"] = len(step_results)
        manifest["checkpoint_count"] = len(checkpoint_ids)
        if checkpoint_ids:
            manifest["latest_checkpoint_id"] = checkpoint_ids[-1]

        if status == WorkflowStatus.SUCCEEDED:
            recorder.emit("workflow_succeeded", {"path": path})
            self._artifact_manager.write_json(actual_run_id, "output.json", output)
            manifest["artifacts"]["output"] = "output.json"
            if "agent_loop_metrics" in output:
                manifest["agent_loop_metrics"] = output["agent_loop_metrics"]
                metrics = output["agent_loop_metrics"]
                manifest["llm_calls"] = metrics.get("llm_calls", 0)
                manifest["tool_calls"] = metrics.get("tool_calls", 0)
                manifest["token_usage"] = metrics.get("token_usage", {})
            if "agent_loop_events" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "agent_loop_events.json",
                    output["agent_loop_events"],
                )
                manifest["artifacts"]["agent_loop_events"] = "agent_loop_events.json"
            self._write_source_diagnostic_artifacts(actual_run_id, manifest, output)
            if "evidence_bundle" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "evidence_bundle.json",
                    output["evidence_bundle"],
                )
                manifest["artifacts"]["evidence_bundle"] = "evidence_bundle.json"
                source_map = _evidence_source_map(output["evidence_bundle"])
                if source_map is not None:
                    self._artifact_manager.write_json(
                        actual_run_id,
                        "evidence_source_map.json",
                        source_map,
                    )
                    manifest["artifacts"]["evidence_source_map"] = "evidence_source_map.json"
            if "evidence_scores" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "evidence_scores.json",
                    output["evidence_scores"],
                )
                manifest["artifacts"]["evidence_scores"] = "evidence_scores.json"
            if "citation_check_result" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "citation_check_result.json",
                    output["citation_check_result"],
                )
                manifest["artifacts"]["citation_check_result"] = "citation_check_result.json"
            if "editor_review" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "editor_review.json",
                    output["editor_review"],
                )
                manifest["artifacts"]["editor_review"] = "editor_review.json"
            if "support_matrix" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "support_matrix.json",
                    output["support_matrix"],
                )
                manifest["artifacts"]["support_matrix"] = "support_matrix.json"
            if "report_quality_summary" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "report_quality_summary.json",
                    output["report_quality_summary"],
                )
                manifest["artifacts"]["report_quality_summary"] = "report_quality_summary.json"
                summary = output["report_quality_summary"]
                if hasattr(summary, "quality_score"):
                    manifest["quality_score"] = summary.quality_score
                elif isinstance(summary, dict):
                    manifest["quality_score"] = summary.get("quality_score")
            if "quality_events" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "quality_events.json",
                    output["quality_events"],
                )
                manifest["artifacts"]["quality_events"] = "quality_events.json"
                manifest["quality_event_count"] = len(output["quality_events"])
            if "quality_gate_metrics" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "quality_gate_metrics.json",
                    output["quality_gate_metrics"],
                )
                manifest["artifacts"]["quality_gate_metrics"] = "quality_gate_metrics.json"
            if "final_report" in output:
                self._artifact_manager.write_json(actual_run_id, "report.json", output["final_report"])
                manifest["artifacts"]["report_json"] = "report.json"
            if isinstance(output.get("report_markdown"), str):
                self._artifact_manager.write_text(actual_run_id, "report.md", output["report_markdown"])
                manifest["artifacts"]["report_markdown"] = "report.md"
            if "blocked_report" in output:
                self._artifact_manager.write_json(
                    actual_run_id,
                    "blocked_report.json",
                    output["blocked_report"],
                )
                manifest["artifacts"]["blocked_report"] = "blocked_report.json"
        else:
            terminal_event = (
                "workflow_blocked" if status == WorkflowStatus.BLOCKED else "workflow_failed"
            )
            recorder.emit(terminal_event, {"path": path, "error": error})
            self._artifact_manager.write_json(actual_run_id, "error.json", error)
            manifest["artifacts"]["error"] = "error.json"
            self._write_source_diagnostic_artifacts(actual_run_id, manifest, output)

        self._artifact_manager.write_json(
            actual_run_id,
            "data_buffer_snapshot.json",
            output,
        )
        self._artifact_manager.write_json(
            actual_run_id,
            "data_buffer.final.json",
            output,
        )
        self._artifact_manager.write_json(
            actual_run_id,
            "data_buffer.diff.json",
            buffer_diff.to_dict(),
        )
        manifest_path = self._artifact_manager.write_json(actual_run_id, "manifest.json", manifest)
        events_path = recorder.write_jsonl(run_dir / "events.jsonl")

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
            scoped_buffer = buffer.scope(step.read_keys, step.write_keys)
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
            runner = self._step_runner_registry.get(step.step_type)
            return runner.run(step, scoped_buffer)
        except Exception as exc:  # pragma: no cover - concrete branches covered by tests
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_details={"attempt": attempt, "max_attempts": max_attempts},
            )

    def _write_source_diagnostic_artifacts(
        self,
        run_id: str,
        manifest: dict[str, Any],
        output: dict[str, Any],
    ) -> None:
        if "raw_items" in output:
            self._artifact_manager.write_json(run_id, "raw_items.json", output["raw_items"])
            manifest["artifacts"]["raw_items"] = "raw_items.json"
        if "source_errors" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_errors.json",
                output["source_errors"],
            )
            manifest["artifacts"]["source_errors"] = "source_errors.json"
        if "skipped_sources" in output:
            self._artifact_manager.write_json(
                run_id,
                "skipped_sources.json",
                output["skipped_sources"],
            )
            manifest["artifacts"]["skipped_sources"] = "skipped_sources.json"
        if "failed_sources" in output:
            self._artifact_manager.write_json(
                run_id,
                "failed_sources.json",
                output["failed_sources"],
            )
            manifest["artifacts"]["failed_sources"] = "failed_sources.json"
        if "source_fetch_requests" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_fetch_requests.json",
                output["source_fetch_requests"],
            )
            manifest["artifacts"]["source_fetch_requests"] = "source_fetch_requests.json"
        if "source_fetch_results" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_fetch_results.json",
                output["source_fetch_results"],
            )
            manifest["artifacts"]["source_fetch_results"] = "source_fetch_results.json"
        if "source_health_updates" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_health_updates.json",
                output["source_health_updates"],
            )
            manifest["artifacts"]["source_health_updates"] = "source_health_updates.json"
        if "source_duplicate_groups" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_duplicate_groups.json",
                output["source_duplicate_groups"],
            )
            manifest["artifacts"]["source_duplicate_groups"] = "source_duplicate_groups.json"
        if "source_events" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_events.json",
                output["source_events"],
            )
            manifest["artifacts"]["source_events"] = "source_events.json"
            manifest["source_event_count"] = len(output["source_events"])
        if "source_pipeline_metrics" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_pipeline_metrics.json",
                output["source_pipeline_metrics"],
            )
            manifest["artifacts"]["source_pipeline_metrics"] = "source_pipeline_metrics.json"
        if "source_selection_report" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_selection_report.json",
                output["source_selection_report"],
            )
            manifest["artifacts"]["source_selection_report"] = "source_selection_report.json"
        if "source_coverage_report" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_coverage_report.json",
                output["source_coverage_report"],
            )
            manifest["artifacts"]["source_coverage_report"] = "source_coverage_report.json"
        if "source_quality_scores" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_quality_scores.json",
                output["source_quality_scores"],
            )
            manifest["artifacts"]["source_quality_scores"] = "source_quality_scores.json"
            manifest["source_quality_score_count"] = len(output["source_quality_scores"])
        source_artifacts = SourceArtifactWriter(self._artifact_manager).write_source_artifacts(
            run_id,
            raw_items=output.get("raw_items"),
            source_fetch_requests=output.get("source_fetch_requests"),
            source_fetch_results=output.get("source_fetch_results"),
            source_errors=output.get("source_errors"),
        )
        if source_artifacts:
            manifest["artifacts"]["source_artifacts"] = "source_artifacts/index.json"
            manifest["source_artifacts"] = {
                "item_count": source_artifacts["item_count"],
                "error_count": source_artifacts["error_count"],
                "raw_content_count": source_artifacts["raw_content_count"],
                "fetch_request_count": source_artifacts["fetch_request_count"],
                "fetch_result_count": source_artifacts["fetch_result_count"],
                "total_count": len(source_artifacts["entries"]),
            }
            if source_artifacts.get("response_headers_count"):
                manifest["source_artifacts"]["response_headers_count"] = source_artifacts[
                    "response_headers_count"
                ]

    def _write_checkpoint(
        self,
        *,
        run_id: str,
        workflow: WorkflowSpec,
        profile: str,
        current_step_id: str | None,
        buffer: DataBuffer,
        step_results: dict[str, StepOutcome],
        path: list[str],
        recorder: EventRecorder,
    ) -> str | None:
        if self._checkpoint_store is None:
            return None

        current_step_ids = [current_step_id] if current_step_id is not None else []
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


def _evidence_source_map(evidence_bundle: Any) -> dict[str, list[str]] | None:
    if isinstance(evidence_bundle, dict):
        source_map = evidence_bundle.get("source_map")
    else:
        source_map = getattr(evidence_bundle, "source_map", None)
    if source_map is None:
        return None
    return {str(key): list(value) for key, value in source_map.items()}


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
    if outcome.status == StepStatus.FAILED:
        return True
    if outcome.status == StepStatus.TIMEOUT:
        return step.timeout_policy.on_timeout == "retry"
    return False


def _checkpoint_id(step_id: str, event_offset: int) -> str:
    safe_step_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in step_id
    ).strip("._-")
    return f"cp-{event_offset:06d}-{safe_step_id or 'step'}"


def _emit_routing_events(recorder: EventRecorder, decision: RoutingDecision) -> None:
    for evaluation in decision.evaluations:
        payload = evaluation.to_dict()
        recorder.emit("edge_evaluated", payload)
        if evaluation.matched:
            recorder.emit("edge_traversed", payload)
        else:
            recorder.emit("edge_rejected", payload)


def _record_step_artifacts(manifest: dict[str, Any], outcome: StepOutcome) -> None:
    if not outcome.artifacts:
        return
    step_artifacts = manifest.setdefault("step_artifacts", [])
    for artifact_ref in outcome.artifacts:
        step_artifacts.append(artifact_ref.to_dict())
        manifest["artifacts"][_step_artifact_key(artifact_ref)] = artifact_ref.path


def _step_artifact_key(artifact_ref: Any) -> str:
    step_id = artifact_ref.step_id or "workflow"
    return f"step.{step_id}.{artifact_ref.artifact_type}.{artifact_ref.artifact_id}"


def _validate_step_runners(workflow: WorkflowSpec, registry: StepRunnerRegistry) -> None:
    missing = registry.missing_step_types([step.step_type for step in workflow.steps])
    if missing:
        labels = ", ".join(step_type.value for step_type in missing)
        raise StepExecutionError(f"step runner is not registered: {labels}")
