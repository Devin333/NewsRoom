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
from framework.agent.artifacts import ArtifactManager
from framework.workflow.runtime.execution_context import WorkflowExecutionContext, utc_now
from framework.workflow.runtime.event_projection import (
    WorkflowEventProjectionExporter,
)
from framework.workflow.runtime.manifest import (
    append_manifest_artifact_index,
    register_manifest_artifact,
    update_manifest_metrics,
)
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
        context.manifest["completed_at"] = context.manifest["finished_at"]
        context.manifest["step_count"] = len(context.step_results)
        context.manifest["current_step_ids"] = list(context.current_step_ids)
        context.manifest["checkpoint_count"] = len(context.checkpoint_ids)
        if context.checkpoint_ids:
            context.manifest["latest_checkpoint_id"] = context.checkpoint_ids[-1]
            context.manifest["checkpoint_ref"] = context.checkpoint_ids[-1]
        workflow_gate = workflow_gate_result(context.step_results)
        if workflow_gate is not None:
            context.manifest["workflow_gate_result"] = workflow_gate
        self._write_agent_loop_artifacts(context.run_id, context.manifest, output)

        expected_terminal_event_type = self._event_bridge.terminal_workflow_event_type(
            context.status
        )
        terminal_events = context.event_emitter.list_events(
            event_types=self._event_bridge.terminal_workflow_event_types()
        )
        latest_terminal_event = terminal_events[-1] if terminal_events else None
        if expected_terminal_event_type is None:
            raise RuntimeError("workflow finalization requires a terminal status")
        if (
            latest_terminal_event is None
            or latest_terminal_event.event_type != expected_terminal_event_type
        ):
            raise RuntimeError(
                "workflow terminal status requires a matching committed terminal event"
            )

        durable_event_count = context.event_emitter.last_accepted_sequence or 0
        context.manifest["event_count"] = durable_event_count

        metrics_payload = workflow_metrics_payload(
            started_monotonic=context.started_monotonic,
            status=context.status,
            path=context.path,
            step_results=context.step_results,
            checkpoint_count=len(context.checkpoint_ids),
            artifact_count=len(context.manifest.get("artifacts") or {}),
            event_count=durable_event_count,
            output=output,
            global_budget_tracker=self._global_budget_tracker,
        )
        context.manifest["memory_operations"] = metrics_payload.get("memory_operations", {})
        redaction_report = redaction_report_for_output(output)
        update_manifest_metrics(context.manifest, metrics_payload)
        event_projection = WorkflowEventProjectionExporter(
            reader=context.event_emitter.reader,
            schema_catalog=context.event_emitter.schema_catalog,
        ).export(
            stream_id=context.event_emitter.stream_id,
            tenant_id=context.event_emitter.tenant_id,
            target=context.run_dir / "events.jsonl",
            through_sequence=(
                durable_event_count if durable_event_count > 0 else None
            ),
        )
        events_path = event_projection.path
        context.manifest["event_projection"] = {
            "path": "events.jsonl",
            "stream_id": event_projection.stream_id,
            "tenant_id": context.event_emitter.tenant_id,
            "high_watermark": event_projection.high_watermark,
            "event_count": event_projection.event_count,
            "checksum": event_projection.checksum,
        }
        if context.event_emitter.tenant_id is not None:
            context.manifest["tenant_id"] = context.event_emitter.tenant_id
        context.manifest["event_projection_high_watermark"] = (
            event_projection.high_watermark
        )
        context.manifest["event_projection_checksum"] = event_projection.checksum
        context.manifest["event_count"] = event_projection.event_count
        context.manifest["trace_ref"] = "events.jsonl"
        context.manifest["warnings"] = [
            *[
                str(warning)
                for warning in context.manifest.get("warnings", [])
                if warning is not None
            ],
            *workflow_warnings(context.step_results),
        ]
        context.manifest["errors"] = workflow_errors(context.error, context.step_results)
        if workflow_gate is not None:
            self._artifact_manager.write_json(context.run_id, "gate_result.json", workflow_gate)
            register_manifest_artifact(context.manifest, "gate_result", "gate_result.json")
            append_manifest_artifact_index(
                context.manifest,
                {
                    "artifact_id": "gate_result",
                    "run_id": context.run_id,
                    "kind": "gate_result",
                    "path": "gate_result.json",
                    "content_type": "application/json",
                },
            )
            context.manifest["gate_result_ref"] = "gate_result.json"
        run_history = run_history_records(
            context=context,
            metrics_payload=metrics_payload,
            workflow_gate=workflow_gate,
        )
        self._artifact_manager.write_text(
            context.run_id,
            "run_history.jsonl",
            "\n".join(stable_json_line(item) for item in run_history) + "\n",
        )
        register_manifest_artifact(context.manifest, "run_history", "run_history.jsonl")
        append_manifest_artifact_index(
            context.manifest,
            {
                "artifact_id": "run_history",
                "run_id": context.run_id,
                "kind": "run_history",
                "path": "run_history.jsonl",
                "content_type": "application/x-ndjson",
            },
        )
        context.manifest["run_history_ref"] = "run_history.jsonl"
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
            gate_result=workflow_gate,
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


def workflow_errors(
    error: WorkflowError | None,
    step_results: dict[str, StepOutcome],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if error is not None:
        errors.append(error.to_dict())
    for step_id, outcome in step_results.items():
        if outcome.error_type is None and outcome.error_message is None:
            continue
        errors.append(
            {
                "step_id": step_id,
                "error_type": outcome.error_type,
                "message": outcome.error_message,
                "details": dict(outcome.error_details),
            }
        )
    return errors


def run_history_records(
    *,
    context: WorkflowExecutionContext,
    metrics_payload: dict[str, Any],
    workflow_gate: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = [
        {
            "event": "workflow_run_completed",
            "run_id": context.run_id,
            "workflow_id": context.workflow.workflow_id,
            "status": context.status.value,
            "trace_id": context.trace_context.trace_id,
            "trace_ref": context.manifest.get("trace_ref"),
            "checkpoint_ref": context.manifest.get("checkpoint_ref"),
            "gate_result_ref": context.manifest.get("gate_result_ref"),
            "metrics": metrics_payload,
        }
    ]
    for step_id, outcome in context.step_results.items():
        records.append(
            {
                "event": "step_outcome",
                "run_id": context.run_id,
                "step_id": step_id,
                "status": outcome.status.value,
                "duration_ms": outcome.duration_ms,
                "trace_id": outcome.trace_id,
                "span_id": outcome.span_id,
                "checkpoint_ref": outcome.checkpoint_ref,
                "gate_result": outcome.gate_result,
            }
        )
    if workflow_gate is not None:
        records.append(
            {
                "event": "workflow_gate_result",
                "run_id": context.run_id,
                "gate_result": workflow_gate,
            }
        )
    return records


def stable_json_line(payload: dict[str, Any]) -> str:
    import json

    from framework.shared.json import to_jsonable

    return json.dumps(to_jsonable(payload), ensure_ascii=False, sort_keys=True)


def workflow_gate_result(step_results: dict[str, StepOutcome]) -> dict[str, Any] | None:
    gate_results = [
        outcome.gate_result
        for outcome in step_results.values()
        if isinstance(outcome.gate_result, dict)
    ]
    if not gate_results:
        return None
    failed_dimensions = sorted(
        {
            str(dimension)
            for result in gate_results
            for dimension in result.get("failed_dimensions") or []
        }
    )
    blocked = [result for result in gate_results if result.get("decision") == "block"]
    warned = [result for result in gate_results if result.get("decision") == "warn"]
    return {
        "gate_id": "workflow:gate",
        "passed": not blocked,
        "decision": "block" if blocked else "warn" if warned else "pass",
        "failed_dimensions": failed_dimensions,
        "reason": "; ".join(str(result.get("reason") or "") for result in blocked or warned).strip("; "),
        "step_gate_count": len(gate_results),
    }
