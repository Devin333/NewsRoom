from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.artifacts.source_artifacts import SourceArtifactWriter
from core.framework.events.recorder import EventRecorder
from core.framework.specs import StepStatus, WorkflowSpec, WorkflowStatus
from core.framework.workflow.buffer import DataBuffer
from core.framework.workflow.result import StepOutcome, WorkflowError, WorkflowResult
from core.framework.workflow.routing import RoutingEngine
from core.framework.workflow.step_runner import FunctionStepRunner


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class WorkflowExecutor:
    def __init__(
        self,
        function_step_runner: FunctionStepRunner,
        artifact_manager: ArtifactManager,
        routing_engine: RoutingEngine | None = None,
    ) -> None:
        self._function_step_runner = function_step_runner
        self._artifact_manager = artifact_manager
        self._routing_engine = routing_engine or RoutingEngine()

    def execute(
        self,
        workflow: WorkflowSpec,
        request: dict[str, Any],
        *,
        profile: str,
        run_id: str | None = None,
    ) -> WorkflowResult:
        workflow.validate()

        actual_run_id = run_id or uuid4().hex
        run_dir = self._artifact_manager.start_run(actual_run_id)
        recorder = EventRecorder(actual_run_id)
        buffer = DataBuffer({"request": request})
        started_at = _utc_now()

        self._artifact_manager.write_json(actual_run_id, "request.json", request)
        self._artifact_manager.write_json(actual_run_id, "workflow_spec.json", workflow)

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
        current_step_id: str | None = workflow.start_step_id

        while current_step_id:
            step = workflow.step_by_id(current_step_id)
            path.append(step.step_id)
            recorder.emit("step_started", {"step_id": step.step_id, "step_type": step.step_type})

            scoped_buffer = buffer.scope(step.read_keys, step.write_keys)
            try:
                outcome = self._function_step_runner.run(step, scoped_buffer)
            except Exception as exc:  # pragma: no cover - concrete branches covered by tests
                outcome = StepOutcome(
                    status=StepStatus.FAILED,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

            step_results[step.step_id] = outcome
            manifest["steps"][step.step_id] = outcome.to_dict()
            manifest["path"] = list(path)

            if outcome.status == StepStatus.SUCCEEDED:
                recorder.emit(
                    "step_succeeded",
                    {"step_id": step.step_id, "outputs": sorted(outcome.outputs.keys())},
                )
                current_step_id = self._routing_engine.next_step(workflow, step, outcome)
                if current_step_id is None:
                    status = WorkflowStatus.SUCCEEDED
            else:
                recorder.emit("step_failed", {"step_id": step.step_id, "outcome": outcome})
                status = WorkflowStatus.FAILED
                error = WorkflowError(
                    error_type=outcome.error_type or "StepFailed",
                    message=outcome.error_message or f"step failed: {step.step_id}",
                    step_id=step.step_id,
                    details=outcome.error_details,
                )
                current_step_id = None

        output = buffer.snapshot().to_dict()
        manifest["status"] = status.value
        manifest["finished_at"] = _utc_now()
        manifest["event_count"] = len(recorder.list_events()) + 1
        manifest["step_count"] = len(step_results)

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
            recorder.emit("workflow_failed", {"path": path, "error": error})
            self._artifact_manager.write_json(actual_run_id, "error.json", error)
            manifest["artifacts"]["error"] = "error.json"
            self._write_source_diagnostic_artifacts(actual_run_id, manifest, output)

        self._artifact_manager.write_json(
            actual_run_id,
            "data_buffer_snapshot.json",
            output,
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
        if "source_health_updates" in output:
            self._artifact_manager.write_json(
                run_id,
                "source_health_updates.json",
                output["source_health_updates"],
            )
            manifest["artifacts"]["source_health_updates"] = "source_health_updates.json"
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
        source_artifacts = SourceArtifactWriter(self._artifact_manager).write_source_artifacts(
            run_id,
            raw_items=output.get("raw_items"),
            source_errors=output.get("source_errors"),
        )
        if source_artifacts:
            manifest["artifacts"]["source_artifacts"] = "source_artifacts/index.json"
            manifest["source_artifacts"] = {
                "item_count": source_artifacts["item_count"],
                "error_count": source_artifacts["error_count"],
                "total_count": len(source_artifacts["entries"]),
            }
