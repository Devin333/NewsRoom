from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.specs import WorkflowSpec
from framework.workflow.buffer import DataBuffer
from framework.workflow.checkpoint.envelope import envelope_from_checkpoint, envelope_to_checkpoint
from framework.workflow.checkpoint.model import WorkflowCheckpoint
from framework.events.trace import TraceContext
from framework.workflow.runtime.events import EventRecorder
from framework.workflow.runtime.manifest import add_manifest_checkpoint
from framework.workflow.runtime.result import StepOutcome


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
        recorder: EventRecorder,
        manifest: dict[str, Any] | None = None,
        checkpoint_ids: list[str] | None = None,
        trace_context: TraceContext | None = None,
    ) -> str | None:
        if self._checkpoint_store is None:
            return None

        event_offset = len(recorder.list_events())
        checkpoint_id = checkpoint_id_for(path[-1] if path else "start", event_offset)
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
            trace_context=trace_context,
        )
        if checkpoint_ids is not None:
            checkpoint_ids.append(checkpoint_id)
        if manifest is not None:
            add_manifest_checkpoint(manifest, checkpoint_id)
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


def checkpoint_id_for(step_id: str, event_offset: int) -> str:
    safe_step_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in step_id
    ).strip("._-")
    return f"cp-{event_offset:06d}-{safe_step_id or 'step'}"
