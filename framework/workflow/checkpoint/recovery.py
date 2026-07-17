"""Partial checkpoint artifact recovery helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from framework.artifacts import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.events.canonical import StoredEvent, thaw_canonical_json
from framework.events.ports import EventReaderPort
from framework.events.runtime.models import StreamReadRequest, StreamSequenceCursor
from framework.workflow.checkpoint.durable import (
    WorkflowCheckpointRecoveryCursor,
    WorkflowCheckpointV2Envelope,
    recovery_cursor_from_durable_checkpoint,
)
from framework.workflow.checkpoint.envelope import WorkflowCheckpointEnvelope

__all__ = [
    "PartialArtifactRecoveryReport",
    "inspect_checkpoint_artifacts",
    "verified_checkpoint_recovery_cursor",
]


@dataclass(frozen=True)
class PartialArtifactRecoveryReport:
    recoverable: bool
    missing_required_artifacts: list[str] = field(default_factory=list)
    missing_optional_artifacts: list[str] = field(default_factory=list)
    recovered_artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recoverable": self.recoverable,
            "missing_required_artifacts": list(self.missing_required_artifacts),
            "missing_optional_artifacts": list(self.missing_optional_artifacts),
            "recovered_artifacts": list(self.recovered_artifacts),
            "warnings": list(self.warnings),
        }


def inspect_checkpoint_artifacts(
    *,
    checkpoint: WorkflowCheckpointEnvelope | WorkflowCheckpointV2Envelope,
    manifest: dict[str, Any] | None,
    artifact_root: Path,
    strict: bool,
) -> PartialArtifactRecoveryReport:
    missing_required: list[str] = []
    missing_optional: list[str] = []
    recovered: list[str] = []
    warnings: list[str] = []

    validated_run_id = validate_artifact_path_segment(checkpoint.run_id, field="run_id")
    run_dir = resolve_artifact_descendant(
        artifact_root,
        validated_run_id,
        field="run_id",
    )
    if manifest is None:
        if strict:
            missing_required.append("manifest.json")
        else:
            missing_optional.append("manifest.json")
            warnings.append("manifest.json is missing")
    else:
        artifacts = manifest.get("artifacts") or {}
        if isinstance(artifacts, dict):
            for artifact_key, artifact_value in sorted(artifacts.items()):
                relative_path = _artifact_manifest_path(artifact_value)
                if relative_path is None:
                    continue
                path = resolve_artifact_descendant(
                    run_dir,
                    relative_path,
                    field=f"manifest_artifact_path[{artifact_key}]",
                )
                if path.exists():
                    recovered.append(str(artifact_key))
                    continue
                if _required_artifact_key(str(artifact_key)):
                    missing_required.append(str(artifact_key))
                else:
                    missing_optional.append(str(artifact_key))
                    warnings.append(f"optional artifact is missing: {artifact_key}")
        events_path = resolve_artifact_descendant(
            run_dir,
            "events.jsonl",
            field="events_path",
        )
        if not events_path.exists():
            missing_optional.append("events")
            warnings.append("events.jsonl is missing")

    if checkpoint.data_buffer_snapshot:
        recovered.append("checkpoint.data_buffer_snapshot")
    else:
        missing_required.append("data_buffer_snapshot")

    return PartialArtifactRecoveryReport(
        recoverable=not missing_required,
        missing_required_artifacts=sorted(set(missing_required)),
        missing_optional_artifacts=sorted(set(missing_optional)),
        recovered_artifacts=sorted(set(recovered)),
        warnings=warnings,
    )


def verified_checkpoint_recovery_cursor(
    *,
    checkpoint: WorkflowCheckpointV2Envelope,
    reader: EventReaderPort,
) -> WorkflowCheckpointRecoveryCursor:
    """Verify the v2 boundary against durable history before resuming after it."""

    sequence = checkpoint.last_durable_stream_sequence
    event_id = checkpoint.last_event_id
    if sequence is None:
        return recovery_cursor_from_durable_checkpoint(checkpoint)
    if event_id is None:
        raise ValueError("durable checkpoint boundary event_id is required")

    boundary = reader.get_event(event_id)
    if boundary is None:
        raise ValueError("checkpoint boundary event is missing from durable history")
    boundary.verify_integrity()
    if boundary.business_context.run_id != checkpoint.run_id:
        raise ValueError("checkpoint boundary event run_id does not match checkpoint")
    cursor = recovery_cursor_from_durable_checkpoint(
        checkpoint,
        boundary_event_stream_id=boundary.stream_id,
        boundary_event_sequence=boundary.stream_sequence,
        boundary_event_id=boundary.event_id,
    )
    return _reconcile_committed_pause_transition(
        checkpoint=checkpoint,
        cursor=cursor,
        reader=reader,
    )


_PLAIN_PAUSE_FACTS = (
    "step_paused",
    "checkpoint_created",
    "workflow_paused",
)
_HUMAN_REVIEW_PAUSE_FACTS = (
    "step_paused",
    "checkpoint_created",
    "human_review_requested",
    "human_review_paused",
    "workflow_paused",
)
_LEGACY_PLAIN_PAUSE_FACTS = _PLAIN_PAUSE_FACTS[1:]
_LEGACY_HUMAN_REVIEW_PAUSE_FACTS = _HUMAN_REVIEW_PAUSE_FACTS[1:]
MAX_PAUSE_RECOVERY_PREFIX_EVENTS = 6


def _reconcile_committed_pause_transition(
    *,
    checkpoint: WorkflowCheckpointV2Envelope,
    cursor: WorkflowCheckpointRecoveryCursor,
    reader: EventReaderPort,
) -> WorkflowCheckpointRecoveryCursor:
    high_watermark = reader.get_stream_high_watermark(checkpoint.stream_id)
    if high_watermark is None:
        return cursor
    if isinstance(high_watermark, bool) or not isinstance(high_watermark, int):
        raise ValueError("durable stream high watermark must be a positive integer")
    if high_watermark < 1:
        raise ValueError("durable stream high watermark must be a positive integer")
    assert cursor.after_sequence is not None
    if high_watermark <= cursor.after_sequence:
        return cursor

    events = _read_recovery_prefix(
        reader=reader,
        checkpoint=checkpoint,
        high_watermark=high_watermark,
    )
    if not events:
        raise ValueError("recovery history is missing after the checkpoint boundary")
    if events[0].event_type == "step_paused":
        return _reconcile_authoritative_pause_prefix(
            checkpoint=checkpoint,
            cursor=cursor,
            events=events,
            high_watermark=high_watermark,
        )
    return _reconcile_legacy_pause_prefix(
        checkpoint=checkpoint,
        cursor=cursor,
        events=events,
        high_watermark=high_watermark,
    )


def _read_recovery_prefix(
    *,
    reader: EventReaderPort,
    checkpoint: WorkflowCheckpointV2Envelope,
    high_watermark: int,
) -> list[StoredEvent]:
    assert checkpoint.last_durable_stream_sequence is not None
    request = StreamReadRequest(
        stream_id=checkpoint.stream_id,
        cursor=StreamSequenceCursor(
            stream_id=checkpoint.stream_id,
            after_sequence=checkpoint.last_durable_stream_sequence,
            high_watermark=high_watermark,
        ),
        limit=MAX_PAUSE_RECOVERY_PREFIX_EVENTS,
        through_sequence=high_watermark,
    )
    events: list[StoredEvent] = []
    expected_sequence = checkpoint.last_durable_stream_sequence + 1
    while len(events) < MAX_PAUSE_RECOVERY_PREFIX_EVENTS:
        page = reader.read_stream(request)
        if page.high_watermark != high_watermark:
            raise ValueError("durable stream changed its captured recovery watermark")
        remaining = MAX_PAUSE_RECOVERY_PREFIX_EVENTS - len(events)
        if len(page.events) > remaining:
            raise ValueError("durable reader exceeded the bounded recovery page limit")
        for event in page.events:
            event.verify_integrity()
            if event.stream_id != checkpoint.stream_id:
                raise ValueError("recovery history crossed the checkpoint stream boundary")
            if event.stream_sequence != expected_sequence:
                raise ValueError("recovery history is not contiguous after the checkpoint")
            if event.business_context.run_id != checkpoint.run_id:
                raise ValueError("recovery event run_id does not match checkpoint")
            events.append(event)
            expected_sequence += 1
        if page.next_cursor is None or len(events) == MAX_PAUSE_RECOVERY_PREFIX_EVENTS:
            break
        if not page.events:
            raise ValueError("durable recovery pagination made no progress")
        remaining = MAX_PAUSE_RECOVERY_PREFIX_EVENTS - len(events)
        request = StreamReadRequest(
            stream_id=checkpoint.stream_id,
            cursor=page.next_cursor,
            limit=remaining,
            through_sequence=high_watermark,
        )
    return events


def _reconcile_authoritative_pause_prefix(
    *,
    checkpoint: WorkflowCheckpointV2Envelope,
    cursor: WorkflowCheckpointRecoveryCursor,
    events: list[StoredEvent],
    high_watermark: int,
) -> WorkflowCheckpointRecoveryCursor:
    if len(events) < 2:
        raise ValueError("checkpoint history contains a partial pause transition")
    checkpoint_fact = events[1]
    if (
        checkpoint_fact.event_type != "checkpoint_created"
        or _event_payload(checkpoint_fact).get("checkpoint_id")
        != checkpoint.checkpoint_id
    ):
        return cursor
    if len(events) < 3:
        raise ValueError("checkpoint history contains a partial pause transition")
    if events[2].event_type == "workflow_paused":
        fact_types = _PLAIN_PAUSE_FACTS
    elif events[2].event_type == "human_review_requested":
        fact_types = _HUMAN_REVIEW_PAUSE_FACTS
    else:
        raise ValueError("checkpoint history contains a partial pause transition")
    expected_types = (*fact_types, "workflow_transition_committed")
    if len(events) < len(expected_types):
        raise ValueError("checkpoint history contains a partial pause transition")
    batch = events[: len(expected_types)]
    if tuple(event.event_type for event in batch) != expected_types:
        raise ValueError("committed transition facts are incomplete or out of order")
    transition = batch[-1]
    if transition.stream_sequence != high_watermark:
        raise ValueError("checkpoint history advanced after the committed pause transition")
    return _reconcile_authoritative_transition(
        checkpoint=checkpoint,
        cursor=cursor,
        facts=batch[:-1],
        transition=transition,
    )


def _reconcile_authoritative_transition(
    *,
    checkpoint: WorkflowCheckpointV2Envelope,
    cursor: WorkflowCheckpointRecoveryCursor,
    facts: list[StoredEvent],
    transition: StoredEvent,
) -> WorkflowCheckpointRecoveryCursor:
    payload = _event_payload(transition)
    if payload.get("checkpoint_id") != checkpoint.checkpoint_id:
        raise ValueError("committed transition checkpoint_id does not match checkpoint")
    if payload.get("previous_status") != "running":
        raise ValueError("committed pause transition must start from running")
    expected_step_id = (
        checkpoint.current_step_ids[0] if checkpoint.current_step_ids else None
    )
    if transition.business_context.workflow_id != checkpoint.workflow_id:
        raise ValueError("committed transition workflow_id does not match checkpoint")
    if expected_step_id is not None and (
        transition.business_context.step_id != expected_step_id
        or payload.get("checkpoint_step_id") != expected_step_id
    ):
        raise ValueError("committed transition step_id does not match checkpoint")
    transition_type = _payload_text(payload, "transition_type")
    expected_status = {
        "pause": "paused",
        "request_human_review": "waiting_for_human",
    }.get(transition_type)
    if expected_status is None or payload.get("next_status") != expected_status:
        raise ValueError("committed pause transition has an invalid target status")
    declared_facts = payload.get("compatibility_event_types")
    if not isinstance(declared_facts, list) or not all(
        isinstance(item, str) for item in declared_facts
    ):
        raise ValueError("committed transition compatibility_event_types is invalid")
    fact_types = tuple(declared_facts)
    expected_fact_types = (
        _PLAIN_PAUSE_FACTS
        if transition_type == "pause"
        else _HUMAN_REVIEW_PAUSE_FACTS
    )
    if fact_types != expected_fact_types:
        raise ValueError("committed transition declared an unexpected fact sequence")
    if tuple(event.event_type for event in facts) != fact_types:
        raise ValueError("committed transition facts are incomplete or out of order")
    _validate_pause_fact_bindings(
        checkpoint=checkpoint,
        facts=facts,
        transition_type=transition_type,
        transition_payload=payload,
    )
    return replace(
        cursor,
        reconciled_through_sequence=transition.stream_sequence,
        reconciled_event_id=transition.event_id,
        recovered_transition_type=transition_type,
        recovered_workflow_status=expected_status,
    )


def _reconcile_legacy_pause_prefix(
    *,
    checkpoint: WorkflowCheckpointV2Envelope,
    cursor: WorkflowCheckpointRecoveryCursor,
    events: list[StoredEvent],
    high_watermark: int,
) -> WorkflowCheckpointRecoveryCursor:
    checkpoint_fact = events[0]
    if (
        checkpoint_fact.event_type != "checkpoint_created"
        or _event_payload(checkpoint_fact).get("checkpoint_id")
        != checkpoint.checkpoint_id
    ):
        return cursor
    if len(events) == 1:
        return cursor
    if events[1].event_type == "workflow_paused":
        expected_types = _LEGACY_PLAIN_PAUSE_FACTS
        transition_type = "pause"
        status = "paused"
    elif events[1].event_type == "human_review_requested":
        expected_types = _LEGACY_HUMAN_REVIEW_PAUSE_FACTS
        transition_type = "request_human_review"
        status = "waiting_for_human"
    else:
        return cursor
    if len(events) < len(expected_types):
        raise ValueError("checkpoint history contains a partial pause transition")
    facts = events[: len(expected_types)]
    if tuple(event.event_type for event in facts) != expected_types:
        raise ValueError("checkpoint history contains a partial pause transition")
    terminal = facts[-1]
    if terminal.stream_sequence != high_watermark:
        return cursor
    _validate_pause_fact_bindings(
        checkpoint=checkpoint,
        facts=facts,
        transition_type=transition_type,
        transition_payload=None,
    )
    return replace(
        cursor,
        reconciled_through_sequence=terminal.stream_sequence,
        reconciled_event_id=terminal.event_id,
        recovered_transition_type=transition_type,
        recovered_workflow_status=status,
    )


def _validate_pause_fact_bindings(
    *,
    checkpoint: WorkflowCheckpointV2Envelope,
    facts: list[StoredEvent],
    transition_type: str,
    transition_payload: dict[str, Any] | None,
) -> None:
    expected_step_id = (
        checkpoint.current_step_ids[0] if checkpoint.current_step_ids else None
    )
    for event in facts:
        context = event.business_context
        if context.workflow_id != checkpoint.workflow_id:
            raise ValueError("pause transition workflow_id does not match checkpoint")
        if expected_step_id is not None and context.step_id != expected_step_id:
            raise ValueError("pause transition step_id does not match checkpoint")

    checkpoint_fact = next(
        event for event in facts if event.event_type == "checkpoint_created"
    )
    checkpoint_payload = _event_payload(checkpoint_fact)
    if checkpoint_payload.get("checkpoint_id") != checkpoint.checkpoint_id:
        raise ValueError("pause fact checkpoint_id does not match checkpoint")
    current_step_ids = checkpoint_payload.get("current_step_ids")
    if current_step_ids is not None and current_step_ids != checkpoint.current_step_ids:
        raise ValueError("pause fact current_step_ids do not match checkpoint")

    workflow_pause = next(event for event in facts if event.event_type == "workflow_paused")
    expected_reason = (
        "human_review"
        if transition_type == "request_human_review"
        else "step_paused"
    )
    if _event_payload(workflow_pause).get("reason") != expected_reason:
        raise ValueError("workflow_paused reason does not match committed transition")

    if transition_type == "request_human_review":
        request_fact = next(
            event for event in facts if event.event_type == "human_review_requested"
        )
        request_payload = _event_payload(request_fact)
        if request_payload.get("checkpoint_id") != checkpoint.checkpoint_id:
            raise ValueError("human review request checkpoint_id does not match checkpoint")
        if transition_payload is not None and (
            request_fact.business_context.request_id
            != transition_payload.get("human_review_request_id")
        ):
            raise ValueError("human review request_id does not match committed transition")


def _event_payload(event: StoredEvent) -> dict[str, Any]:
    payload = thaw_canonical_json(event.payload or {})
    if not isinstance(payload, dict):
        raise ValueError("workflow recovery event payload must be an object")
    return payload


def _payload_text(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"committed transition {field_name} is required")
    return value.strip()


def _artifact_manifest_path(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("path")
    if value is None:
        return None
    return validate_relative_artifact_path(str(value), field="manifest_artifact_path")


def _required_artifact_key(artifact_key: str) -> bool:
    return artifact_key in {"data_buffer_snapshot", "manifest"} or artifact_key.endswith(
        (".input", ".output")
    )
