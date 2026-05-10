from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.framework.artifacts.filesystem import ArtifactManager
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
            if "final_report" in output:
                self._artifact_manager.write_json(actual_run_id, "report.json", output["final_report"])
                manifest["artifacts"]["report_json"] = "report.json"
            if isinstance(output.get("report_markdown"), str):
                self._artifact_manager.write_text(actual_run_id, "report.md", output["report_markdown"])
                manifest["artifacts"]["report_markdown"] = "report.md"
        else:
            recorder.emit("workflow_failed", {"path": path, "error": error})
            self._artifact_manager.write_json(actual_run_id, "error.json", error)
            manifest["artifacts"]["error"] = "error.json"

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
