from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from framework.events.canonical import (
    StoredEvent,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventStoreCorruptionError
from framework.harness.control_plane.activity import (
    HARNESS_ACTIVITY_EXTENSION,
    HarnessActivity,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.transition import (
    HARNESS_EVENT_SOURCE,
    HARNESS_TRANSITION_EVENT_TYPE,
    HarnessTransitionCommitted,
)
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


@dataclass(frozen=True)
class HarnessEventLogEntry:
    run_id: str
    event_type: str
    event_id: str | None = None
    step_id: str | None = None
    status_before: str | None = None
    status_after: str | None = None
    decision: dict[str, Any] | None = None
    worker_type: str | None = None
    input_ref: str | None = None
    output_ref: str | None = None
    skill_name: str | None = None
    skill_version: str | None = None
    skill_candidate_id: str | None = None
    rag_session_id: str | None = None
    retrieval_round: int | None = None
    retry_count: int | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: Any = field(default_factory=utc_now)
    stream_id: str | None = None
    stream_sequence: int | None = None
    content_checksum: str | None = None
    record_checksum: str | None = None

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        if not str(self.event_type).strip():
            raise HarnessValidationError("event_type is required")
        metadata = normalize_canonical_json(
            to_jsonable(self.metadata),
            path="$.harness_event_log.metadata",
        )
        if not isinstance(metadata, Mapping):
            raise HarnessValidationError("metadata must be an object")
        decision: Mapping[str, Any] | None = None
        if self.decision is not None:
            normalized_decision = normalize_canonical_json(
                to_jsonable(self.decision),
                path="$.harness_event_log.decision",
            )
            if not isinstance(normalized_decision, Mapping):
                raise HarnessValidationError("decision must be an object")
            decision = normalized_decision
        event_id = self.event_id or _stable_event_id(
            self.run_id,
            self.event_type,
            self.step_id,
            metadata,
            self.timestamp,
        )
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "event_type", str(self.event_type))
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "event_type": self.event_type,
            "status_before": self.status_before,
            "status_after": self.status_after,
            "decision": to_jsonable(self.decision),
            "worker_type": self.worker_type,
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "skill_name": self.skill_name,
            "skill_version": self.skill_version,
            "skill_candidate_id": self.skill_candidate_id,
            "rag_session_id": self.rag_session_id,
            "retrieval_round": self.retrieval_round,
            "retry_count": self.retry_count,
            "error": self.error,
            "timestamp": format_datetime(self.timestamp),
            "metadata": to_jsonable(self.metadata),
            "stream_id": self.stream_id,
            "stream_sequence": self.stream_sequence,
            "content_checksum": self.content_checksum,
            "record_checksum": self.record_checksum,
        }


class InMemoryHarnessEventLog:
    def __init__(self) -> None:
        self._entries: list[HarnessEventLogEntry] = []

    def append(self, entry: HarnessEventLogEntry) -> HarnessEventLogEntry:
        if any(existing.event_id == entry.event_id for existing in self._entries):
            raise HarnessValidationError("event log is append-only and event_id must be unique")
        self._entries.append(entry)
        return entry

    def entries_for_run(self, run_id: str) -> tuple[HarnessEventLogEntry, ...]:
        return tuple(entry for entry in self._entries if entry.run_id == run_id)

    def all_entries(self) -> tuple[HarnessEventLogEntry, ...]:
        return tuple(self._entries)

    def to_dict(self) -> dict[str, Any]:
        return {"events": [entry.to_dict() for entry in self._entries]}


def event_log_entry_from_harness_event(event: Any, *, phase_index: int | None = None) -> HarnessEventLogEntry:
    payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    metadata = dict(payload.get("metadata", {}))
    event_payload = dict(payload.get("payload", {}))
    transition_state = _transition_state(
        str(payload.get("event_type")),
        event_payload,
    )
    metadata.update(event_payload if isinstance(event_payload, dict) else {"payload": event_payload})
    if phase_index is not None:
        metadata["phase_index"] = phase_index
    return HarnessEventLogEntry(
        event_id=payload.get("event_id"),
        run_id=str(payload.get("run_id")),
        step_id=payload.get("step_id"),
        event_type=str(payload.get("event_type")),
        status_before=metadata.get("status_before") or event_payload.get("status_before"),
        status_after=(
            metadata.get("status_after")
            or event_payload.get("status_after")
            or transition_state.get("status")
        ),
        decision=event_payload if str(payload.get("event_type")) == "decision_recorded" else None,
        worker_type=event_payload.get("worker_type") if isinstance(event_payload, dict) else None,
        error=event_payload.get("error") if isinstance(event_payload, dict) else None,
        metadata=metadata,
        timestamp=_required_timestamp(payload.get("occurred_at")),
    )


def event_log_entry_from_stored_event(event: StoredEvent) -> HarnessEventLogEntry:
    """Build the legacy Harness read model from one canonical stored fact."""

    if not isinstance(event, StoredEvent):
        raise TypeError("event must be StoredEvent")
    event.verify_integrity()
    if event.source != HARNESS_EVENT_SOURCE:
        raise EventStoreCorruptionError("stored Harness event source is invalid")
    run_id = event.business_context.run_id
    if run_id is None:
        raise HarnessValidationError("stored Harness event requires business_context.run_id")
    event_payload = thaw_canonical_json(event.payload or {})
    if not isinstance(event_payload, dict):
        raise HarnessValidationError("stored Harness payload must be an object")
    if event.event_type == HARNESS_TRANSITION_EVENT_TYPE:
        event_payload = HarnessTransitionCommitted.from_stored_event(
            event
        ).to_payload()
    elif event.data_schema != "newsroom.harness-event/v1":
        raise EventStoreCorruptionError("stored Harness event schema is invalid")
    harness_extension = thaw_canonical_json(event.extensions.get("harness", {}))
    if not isinstance(harness_extension, dict):
        raise HarnessValidationError("stored Harness extension must be an object")
    transition_metadata = harness_extension.get("metadata", {})
    if not isinstance(transition_metadata, dict):
        raise HarnessValidationError("stored Harness metadata must be an object")
    activity_projection = _stored_activity_projection(event)
    metadata = {
        **transition_metadata,
        **event_payload,
        **activity_projection,
        "canonical_source": event.source,
        "canonical_data_schema": event.data_schema,
    }
    transition_state = _transition_state(event.event_type, event_payload)
    return HarnessEventLogEntry(
        event_id=event.event_id,
        run_id=run_id,
        step_id=event.business_context.step_id,
        event_type=event.event_type,
        status_before=_optional_text(
            transition_metadata.get("status_before", event_payload.get("status_before"))
        ),
        status_after=_optional_text(
            transition_metadata.get(
                "status_after",
                event_payload.get("status_after", transition_state.get("status")),
            )
        ),
        decision=event_payload if event.event_type == "decision_recorded" else None,
        worker_type=_optional_text(
            event_payload.get("worker_type", activity_projection.get("activity_type"))
        ),
        input_ref=_optional_text(
            event_payload.get("input_ref", activity_projection.get("input_ref"))
        ),
        output_ref=_optional_text(
            event_payload.get("output_ref", activity_projection.get("output_ref"))
        ),
        retry_count=_optional_int(event_payload.get("retry_count")),
        error=_optional_text(event_payload.get("error")),
        metadata=metadata,
        timestamp=event.occurred_at,
        stream_id=event.stream_id,
        stream_sequence=event.stream_sequence,
        content_checksum=event.content_checksum,
        record_checksum=event.record_checksum,
    )


def _stable_event_id(
    run_id: str,
    event_type: str,
    step_id: str | None,
    metadata: Mapping[str, Any],
    timestamp: Any,
) -> str:
    payload = {
        "run_id": run_id,
        "event_type": event_type,
        "step_id": step_id,
        "metadata": metadata,
        "timestamp": format_datetime(timestamp),
    }
    digest = hashlib.sha256(stable_json_dumps(payload).encode()).hexdigest()[:16]
    return f"harness-event://{run_id}/{digest}"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _transition_state(
    event_type: str,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    if event_type != HARNESS_TRANSITION_EVENT_TYPE:
        return {}
    state = payload.get("state")
    if not isinstance(state, Mapping):
        raise HarnessValidationError("Harness transition event requires a state projection")
    return state


def _stored_activity_projection(event: StoredEvent) -> dict[str, Any]:
    if event.payload_ref is None:
        return {}
    extension = thaw_canonical_json(
        event.extensions.get(HARNESS_ACTIVITY_EXTENSION, {})
    )
    if not isinstance(extension, Mapping):
        raise HarnessValidationError(
            "stored Harness activity extension must be an object"
        )
    activity_value = extension.get("activity")
    if not isinstance(activity_value, Mapping):
        raise HarnessValidationError(
            "stored Harness activity descriptor is missing"
        )
    try:
        activity = HarnessActivity.from_dict(activity_value)
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise HarnessValidationError(
            "stored Harness activity descriptor is invalid"
        ) from exc
    return {
        "activity_id": activity.activity_id,
        "activity_type": activity.activity_type,
        "activity_attempt": activity.attempt,
        "activity_status": _optional_text(extension.get("status")),
        "input_ref": activity.input_checksum,
        "output_ref": event.payload_ref.expected_checksum,
    }


def _required_timestamp(value: Any):
    try:
        timestamp = parse_datetime(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HarnessValidationError("Harness event requires a valid occurred_at") from exc
    if timestamp is None:
        raise HarnessValidationError("Harness event requires a valid occurred_at")
    return timestamp


__all__ = [
    "HarnessEventLogEntry",
    "InMemoryHarnessEventLog",
    "event_log_entry_from_harness_event",
    "event_log_entry_from_stored_event",
]
