from __future__ import annotations

import time
from typing import Any

from framework.specs import StepStatus, WorkflowStatus
from framework.workflow.governance.budget import budget_summary_from_tracker
from framework.workflow.runtime.artifact_publishers import (
    ArtifactPublishContext,
    ArtifactPublishPhase,
    WorkflowArtifactPublisherRegistry,
)
from framework.workflow.runtime.artifacts import ArtifactManager
from framework.workflow.runtime.execution_context import WorkflowExecutionContext, utc_now
from framework.workflow.runtime.manifest import register_manifest_artifact, update_manifest_metrics
from framework.workflow.runtime.manifest_updater import sensitive_key
from framework.workflow.runtime.result import (
    StepOutcome,
    WorkflowError,
    WorkflowResult,
    framework_error_envelope,
)
from framework.workflow.runtime.runtime_event_bridge import RuntimeEventBridge


class WorkflowOutcomeFinalizer:
    def __init__(
        self,
        *,
        artifact_manager: ArtifactManager,
        artifact_publishers: WorkflowArtifactPublisherRegistry,
        event_bridge: RuntimeEventBridge,
        global_budget_tracker: Any | None = None,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._artifact_publishers = artifact_publishers
        self._event_bridge = event_bridge
        self._global_budget_tracker = global_budget_tracker

    def finalize(
        self,
        context: WorkflowExecutionContext,
    ) -> WorkflowResult:
        final_buffer_snapshot = context.buffer.snapshot()
        output = final_buffer_snapshot.to_dict()
        buffer_diff = context.buffer.diff(context.initial_buffer_snapshot)
        context.manifest["status"] = context.status.value
        context.manifest["finished_at"] = utc_now()
        context.manifest["event_count"] = len(context.recorder.list_events()) + 1
        context.manifest["step_count"] = len(context.step_results)
        context.manifest["current_step_ids"] = list(context.current_step_ids)
        context.manifest["checkpoint_count"] = len(context.checkpoint_ids)
        if context.checkpoint_ids:
            context.manifest["latest_checkpoint_id"] = context.checkpoint_ids[-1]
        self._write_agent_loop_artifacts(context.run_id, context.manifest, output)

        self._event_bridge.emit_terminal_workflow_event(
            context.recorder,
            status=context.status,
            path=context.path,
            error=context.error,
            trace_context=context.trace_context,
        )

        metrics_payload = workflow_metrics_payload(
            started_monotonic=context.started_monotonic,
            status=context.status,
            path=context.path,
            step_results=context.step_results,
            checkpoint_count=len(context.checkpoint_ids),
            artifact_count=len(context.manifest.get("artifacts") or {}),
            event_count=len(context.recorder.list_events()),
            output=output,
            global_budget_tracker=self._global_budget_tracker,
        )
        context.manifest["memory_operations"] = metrics_payload.get("memory_operations", {})
        redaction_report = redaction_report_for_output(output)
        update_manifest_metrics(context.manifest, metrics_payload)
        events_path = context.recorder.write_jsonl(context.run_dir / "events.jsonl")
        self._artifact_publishers.publish_all(
            ArtifactPublishContext(
                phase=ArtifactPublishPhase.TERMINAL,
                run_id=context.run_id,
                workflow=context.workflow,
                profile=context.profile,
                status=context.status,
                request=context.request,
                output=output,
                manifest=context.manifest,
                artifact_manager=self._artifact_manager,
                step_results=context.step_results,
                path=context.path,
                error=context.error,
                current_step_ids=context.current_step_ids,
                checkpoint_ids=context.checkpoint_ids,
                initial_buffer_snapshot=context.initial_buffer_snapshot,
                final_buffer_snapshot=final_buffer_snapshot,
                buffer_diff=buffer_diff,
                metrics_payload=metrics_payload,
                redaction_report=redaction_report,
                events_path=events_path,
            )
        )
        manifest_path = context.run_dir / "manifest.json"
        artifacts = list((context.manifest.get("artifacts") or {}).values())
        checkpoint_ref = context.checkpoint_ids[-1] if context.checkpoint_ids else None

        return WorkflowResult(
            run_id=context.run_id,
            workflow_id=context.workflow.workflow_id,
            workflow_version=context.workflow.version,
            status=context.status,
            output=output,
            outputs=output,
            error=context.error,
            path=context.path,
            step_results=context.step_results,
            step_outcomes=list(context.step_results.values()),
            manifest=context.manifest,
            artifact_dir=str(context.run_dir),
            manifest_path=str(manifest_path),
            events_path=str(events_path),
            trace_id=context.trace_context.trace_id,
            trace_ref=str(events_path),
            manifest_ref=str(manifest_path),
            checkpoint_ref=checkpoint_ref,
            metrics=metrics_payload,
            artifacts=artifacts,
            warnings=workflow_warnings(context.step_results),
            error_envelope=(
                framework_error_envelope(
                    error_type=context.error.error_type,
                    message=context.error.message,
                    domain="workflow",
                    run_id=context.run_id,
                    step_id=context.error.step_id,
                    details=context.error.details,
                )
                if context.error is not None
                else None
            ),
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


def workflow_metrics_payload(
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
    metrics["memory_operations"] = memory_operations_summary(step_results)
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


def memory_operations_summary(step_results: dict[str, StepOutcome]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    recall_count = 0
    write_count = 0
    consolidate_count = 0
    recalled_memory_ids: set[str] = set()
    written_memory_ids: set[str] = set()
    consolidated_memory_ids: set[str] = set()
    consolidation_source_memory_ids: set[str] = set()
    total_recall_results = 0
    total_written_records = 0
    total_consolidated_records = 0

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
        elif operation_type == "consolidate":
            consolidate_count += 1
            consolidated_count = int(operation.get("consolidated_count") or 0)
            total_consolidated_records += consolidated_count
            source_memory_ids = [
                str(memory_id) for memory_id in operation.get("source_memory_ids") or []
            ]
            item["consolidated_count"] = consolidated_count
            item["skipped_count"] = int(operation.get("skipped_count") or 0)
            item["source_memory_ids"] = source_memory_ids
            consolidated_memory_ids.update(item["memory_ids"])
            consolidation_source_memory_ids.update(source_memory_ids)
        operations.append(item)

    return {
        "operation_count": len(operations),
        "recall_count": recall_count,
        "write_count": write_count,
        "consolidate_count": consolidate_count,
        "total_recall_results": total_recall_results,
        "total_written_records": total_written_records,
        "total_consolidated_records": total_consolidated_records,
        "recalled_memory_ids": sorted(recalled_memory_ids),
        "written_memory_ids": sorted(written_memory_ids),
        "consolidated_memory_ids": sorted(consolidated_memory_ids),
        "consolidation_source_memory_ids": sorted(consolidation_source_memory_ids),
        "operations": operations,
    }


def redaction_report_for_output(output: dict[str, Any]) -> dict[str, Any]:
    redacted_keys = sorted(key for key in output if sensitive_key(str(key)))
    return {
        "redacted": bool(redacted_keys),
        "redacted_keys": redacted_keys,
        "rules": ["sensitive_top_level_buffer_key"],
    }


def workflow_warnings(step_results: dict[str, StepOutcome]) -> list[str]:
    warnings: list[str] = []
    for step_id, outcome in step_results.items():
        for warning in outcome.warnings:
            warnings.append(f"{step_id}: {warning}")
    return warnings
