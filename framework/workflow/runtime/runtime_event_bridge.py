from __future__ import annotations

from typing import Any

from framework.specs import StepSpec, StepType, WorkflowSpec, WorkflowStatus
from framework.events.trace import TraceContext
from framework.workflow.routing import RoutingDecision
from framework.events import EventRecorder
from framework.workflow.runtime.result import StepOutcome, WorkflowError


class RuntimeEventBridge:
    def emit_workflow_started(
        self,
        recorder: EventRecorder,
        *,
        workflow: WorkflowSpec,
        profile: str,
        trace_context: TraceContext | None = None,
    ) -> None:
        recorder.emit(
            "workflow_started",
            {
                "workflow_id": workflow.workflow_id,
                "workflow_version": workflow.version,
                "profile": profile,
            },
            trace_context=trace_context,
        )

    def emit_workflow_resumed(
        self,
        recorder: EventRecorder,
        *,
        workflow: WorkflowSpec,
        profile: str,
        checkpoint_id: str,
        resume_metadata: dict[str, Any] | None,
        public_resume_metadata: dict[str, Any] | None = None,
        trace_context: TraceContext | None = None,
    ) -> None:
        resumed_payload: dict[str, Any] = {
            "workflow_id": workflow.workflow_id,
            "workflow_version": workflow.version,
            "profile": profile,
            "checkpoint_id": checkpoint_id,
        }
        if resume_metadata:
            resumed_payload["resume_metadata"] = (
                public_resume_metadata
                if public_resume_metadata is not None
                else public_metadata_from_resume(resume_metadata)
            )
        recorder.emit("workflow_resumed", resumed_payload, trace_context=trace_context)
        self.emit_human_review_resume_events(recorder, resume_metadata, trace_context=trace_context)
        recorder.emit(
            "checkpoint_restored",
            {"checkpoint_id": checkpoint_id},
            trace_context=trace_context,
        )

    def emit_routing_events(
        self,
        recorder: EventRecorder,
        decision: RoutingDecision,
        *,
        trace_context: TraceContext | None = None,
    ) -> None:
        for evaluation in decision.evaluations:
            payload = evaluation.to_dict()
            recorder.emit("edge_evaluated", payload, trace_context=trace_context)
            if evaluation.matched:
                recorder.emit("edge_traversed", payload, trace_context=trace_context)
            else:
                recorder.emit("edge_rejected", payload, trace_context=trace_context)

    def emit_human_review_resume_events(
        self,
        recorder: EventRecorder,
        resume_metadata: dict[str, Any] | None,
        *,
        trace_context: TraceContext | None = None,
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
        recorder.emit(
            "human_review_decision_received",
            payload,
            trace_context=trace_context,
        )
        if decision in {"approved", "rejected", "needs_changes"}:
            recorder.emit(f"human_review_{decision}", payload, trace_context=trace_context)

    def emit_agent_loop_stream_events(
        self,
        recorder: EventRecorder,
        step: StepSpec,
        outcome: StepOutcome,
        trace_context: TraceContext | None = None,
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
                trace_context=trace_context,
            )

    def emit_memory_operation_events(
        self,
        recorder: EventRecorder,
        step: StepSpec,
        outcome: StepOutcome,
        trace_context: TraceContext | None = None,
    ) -> None:
        if step.step_type not in {
            StepType.MEMORY_RECALL,
            StepType.MEMORY_WRITE,
            StepType.MEMORY_CONSOLIDATE,
        }:
            return
        operation = outcome.metrics.get("memory_operation")
        if not isinstance(operation, dict):
            return
        event_type = {
            StepType.MEMORY_RECALL: "memory_recall",
            StepType.MEMORY_WRITE: "memory_write",
            StepType.MEMORY_CONSOLIDATE: "memory_consolidate",
        }[step.step_type]
        recorder.emit(
            event_type,
            {
                "step_id": step.step_id,
                "status": outcome.status.value,
                **operation,
            },
            trace_context=trace_context,
        )

    def emit_terminal_workflow_event(
        self,
        recorder: EventRecorder,
        *,
        status: WorkflowStatus,
        path: list[str],
        error: WorkflowError | None,
        trace_context: TraceContext | None = None,
    ) -> None:
        if status == WorkflowStatus.SUCCEEDED:
            recorder.emit("workflow_succeeded", {"path": path}, trace_context=trace_context)
        elif status in {WorkflowStatus.PAUSED, WorkflowStatus.WAITING_FOR_HUMAN}:
            return
        elif status == WorkflowStatus.CANCELLED:
            return
        else:
            recorder.emit(
                terminal_error_event_type(status),
                {"path": path, "error": error},
                trace_context=trace_context,
            )


def public_metadata_from_resume(resume_metadata: dict[str, Any]) -> dict[str, Any]:
    public_metadata = resume_metadata.get("_public_resume_metadata")
    if isinstance(public_metadata, dict):
        return dict(public_metadata)
    return dict(resume_metadata)


def terminal_error_event_type(status: WorkflowStatus) -> str:
    if status == WorkflowStatus.BLOCKED:
        return "workflow_blocked"
    if status == WorkflowStatus.BUDGET_EXCEEDED:
        return "workflow_budget_exceeded"
    return "workflow_failed"
