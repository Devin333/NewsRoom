from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import time
from typing import Any, Protocol

from framework.events.canonical import StoredEvent
from framework.events.trace import TraceContext
from framework.specs import WorkflowSpec
from framework.shared.attempts import ExecutionLimits
from framework.workflow.buffer import DataBuffer
from framework.workflow.checkpoint.durable import (
    DurableWorkflowCheckpoint,
    canonical_run_stream_id,
)
from framework.workflow.checkpoint.reference import CheckpointReference
from framework.workflow.runtime.manifest import add_manifest_checkpoint, add_manifest_checkpoint_ref
from framework.workflow.runtime.result import StepOutcome


class CheckpointEventRecorder(Protocol):
    @property
    def last_accepted_event(self) -> StoredEvent | None: ...

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        trace_context: TraceContext | None = None,
        component: str | None = None,
    ) -> Any: ...


class CheckpointCoordinator:
    def __init__(
        self,
        *,
        checkpoint_store: Any | None,
        global_budget_tracker: Any | None = None,
    ) -> None:
        self._checkpoint_store = checkpoint_store
        self._global_budget_tracker = global_budget_tracker

    def write_checkpoint(
        self,
        *,
        run_id: str,
        workflow: WorkflowSpec,
        profile: str,
        current_step_ids: list[str],
        buffer: DataBuffer,
        step_results: dict[str, StepOutcome],
        path: list[str],
        recorder: CheckpointEventRecorder,
        manifest: dict[str, Any] | None = None,
        checkpoint_ids: list[str] | None = None,
        execution_limits: ExecutionLimits | None = None,
        trace_context: TraceContext | None = None,
        emit_event: bool = True,
    ) -> str | None:
        if self._checkpoint_store is None:
            return None

        stream_id = canonical_run_stream_id(run_id)
        boundary_event = recorder.last_accepted_event
        last_sequence, last_event_id = _durable_boundary(
            boundary_event,
            stream_id=stream_id,
            run_id=run_id,
        )
        checkpoint_id = checkpoint_id_for(
            path[-1] if path else "start",
            last_sequence,
        )
        metadata: dict[str, Any] = {"profile": profile}
        if self._global_budget_tracker is not None and hasattr(
            self._global_budget_tracker,
            "snapshot",
        ):
            metadata["budget_usage"] = self._global_budget_tracker.snapshot()
        if execution_limits is not None:
            snapshot = execution_limits.snapshot(now=time.monotonic())
            snapshot["resume_policy"] = (
                "diagnostic_only_new_execution_scope_on_resume"
            )
            metadata["attempt_execution_snapshot"] = snapshot
        checkpoint = DurableWorkflowCheckpoint(
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
            stream_id=stream_id,
            last_durable_stream_sequence=last_sequence,
            last_event_id=last_event_id,
            metadata=metadata,
        )
        self._checkpoint_store.save_checkpoint(checkpoint)

        # The checkpoint fact can only be published after its durable file exists.
        # Pause transitions defer it into their authoritative atomic event batch.
        if emit_event:
            recorder.emit(
                "checkpoint_created",
                checkpoint_created_payload(
                    checkpoint_id=checkpoint_id,
                    current_step_ids=current_step_ids,
                    path=path,
                ),
                trace_context=trace_context,
            )
        if checkpoint_ids is not None:
            checkpoint_ids.append(checkpoint_id)
        if manifest is not None:
            add_manifest_checkpoint(manifest, checkpoint_id)
            add_manifest_checkpoint_ref(
                manifest,
                CheckpointReference(
                    checkpoint_id=checkpoint_id,
                    run_id=run_id,
                    step_id=path[-1] if path else None,
                    status="created",
                    path=f"checkpoints/{checkpoint_id}.json",
                    metadata={
                        "stream_id": stream_id,
                        "last_durable_stream_sequence": last_sequence,
                        "last_event_id": last_event_id,
                        "profile": profile,
                        "current_step_ids": list(current_step_ids),
                        "path": list(path),
                    },
                ),
            )
        if path and step_results:
            current_step_id = path[-1]
            outcome = step_results.get(current_step_id)
            if outcome is not None:
                updated = replace(outcome, checkpoint_ref=checkpoint_id)
                step_results[current_step_id] = updated
                if manifest is not None:
                    manifest.setdefault("steps", {})[current_step_id] = updated.to_dict()
                    summary = manifest.setdefault("step_outcome_summary", {}).get(
                        current_step_id,
                        {},
                    )
                    if isinstance(summary, dict):
                        summary["checkpoint_ref"] = checkpoint_id
                        manifest["step_outcome_summary"][current_step_id] = summary
        return checkpoint_id

    def has_checkpoint_store(self) -> bool:
        return self._checkpoint_store is not None


def checkpoint_id_for(step_id: str, stream_sequence: int | None) -> str:
    if stream_sequence is None:
        checkpoint_sequence = 0
    elif (
        isinstance(stream_sequence, bool)
        or not isinstance(stream_sequence, int)
        or stream_sequence < 1
    ):
        raise ValueError("stream_sequence must be a positive 1-based integer or None")
    else:
        checkpoint_sequence = stream_sequence
    safe_step_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in step_id
    ).strip("._-")
    return f"cp-{checkpoint_sequence:06d}-{safe_step_id or 'step'}"


def checkpoint_created_payload(
    *,
    checkpoint_id: str,
    current_step_ids: list[str],
    path: list[str],
) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint_id,
        "current_step_ids": list(current_step_ids),
        "path": list(path),
    }


def _durable_boundary(
    event: StoredEvent | None,
    *,
    stream_id: str,
    run_id: str,
) -> tuple[int | None, str | None]:
    if event is None:
        return None, None
    if not isinstance(event, StoredEvent):
        raise TypeError("checkpoint recorder must expose an accepted StoredEvent boundary")
    event.verify_integrity()
    if event.stream_id != stream_id:
        raise ValueError("checkpoint boundary event does not belong to the run stream")
    if event.business_context.run_id != run_id:
        raise ValueError("checkpoint boundary event run_id does not match the checkpoint")
    return event.stream_sequence, event.event_id
