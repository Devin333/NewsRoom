from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from framework.events.canonical import StoredEvent, thaw_canonical_json
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
class HarnessTranscriptEntry:
    run_id: str
    phase: str
    entry_id: str | None = None
    step_id: str | None = None
    decision: dict[str, Any] | None = None
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    gate_results: tuple[dict[str, Any], ...] = ()
    budget_snapshot: dict[str, Any] | None = None
    worker_call_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    skill_refs: tuple[str, ...] = ()
    candidate_refs: tuple[str, ...] = ()
    rag_session_refs: tuple[str, ...] = ()
    retrieval_plan_refs: tuple[str, ...] = ()
    context_pack_refs: tuple[str, ...] = ()
    context_envelope_ref: str | None = None
    context_snapshot_ref: str | None = None
    compression_record_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    eval_refs: tuple[str, ...] = ()
    release_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        if not str(self.phase).strip():
            raise HarnessValidationError("phase is required")
        metadata = dict(self.metadata)
        entry_id = self.entry_id or _stable_entry_id(self.run_id, self.phase, self.step_id, metadata, self.timestamp)
        object.__setattr__(self, "entry_id", entry_id)
        object.__setattr__(self, "decision", dict(self.decision) if self.decision is not None else None)
        object.__setattr__(self, "input_refs", tuple(str(ref) for ref in self.input_refs))
        object.__setattr__(self, "output_refs", tuple(str(ref) for ref in self.output_refs))
        object.__setattr__(self, "gate_results", tuple(dict(result) for result in self.gate_results))
        object.__setattr__(self, "artifact_refs", tuple(str(ref) for ref in self.artifact_refs))
        object.__setattr__(self, "skill_refs", tuple(str(ref) for ref in self.skill_refs))
        object.__setattr__(self, "candidate_refs", tuple(str(ref) for ref in self.candidate_refs))
        object.__setattr__(self, "rag_session_refs", tuple(str(ref) for ref in self.rag_session_refs))
        object.__setattr__(self, "retrieval_plan_refs", tuple(str(ref) for ref in self.retrieval_plan_refs))
        object.__setattr__(self, "context_pack_refs", tuple(str(ref) for ref in self.context_pack_refs))
        object.__setattr__(self, "compression_record_refs", tuple(str(ref) for ref in self.compression_record_refs))
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in self.evidence_refs))
        object.__setattr__(self, "eval_refs", tuple(str(ref) for ref in self.eval_refs))
        object.__setattr__(self, "release_refs", tuple(str(ref) for ref in self.release_refs))
        object.__setattr__(self, "budget_snapshot", dict(self.budget_snapshot) if self.budget_snapshot else None)
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "phase": self.phase,
            "decision": to_jsonable(self.decision),
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "gate_results": to_jsonable(list(self.gate_results)),
            "budget_snapshot": to_jsonable(self.budget_snapshot),
            "worker_call_ref": self.worker_call_ref,
            "artifact_refs": list(self.artifact_refs),
            "skill_refs": list(self.skill_refs),
            "candidate_refs": list(self.candidate_refs),
            "rag_session_refs": list(self.rag_session_refs),
            "retrieval_plan_refs": list(self.retrieval_plan_refs),
            "context_pack_refs": list(self.context_pack_refs),
            "context_envelope_ref": self.context_envelope_ref,
            "context_snapshot_ref": self.context_snapshot_ref,
            "compression_record_refs": list(self.compression_record_refs),
            "evidence_refs": list(self.evidence_refs),
            "eval_refs": list(self.eval_refs),
            "release_refs": list(self.release_refs),
            "timestamp": format_datetime(self.timestamp),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessTranscriptEntry":
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "Harness transcript entry payload must be an object"
            )
        payload = dict(value)
        try:
            run_id = payload.pop("run_id")
            phase = payload.pop("phase")
        except KeyError as exc:
            raise HarnessValidationError(
                f"Harness transcript entry field is required: {exc.args[0]}"
            ) from exc
        timestamp = _required_timestamp(payload.pop("timestamp", None))
        values = {
            "entry_id": _transcript_optional_text(
                payload.pop("entry_id", None),
                "entry_id",
            ),
            "step_id": _transcript_optional_text(
                payload.pop("step_id", None),
                "step_id",
            ),
            "decision": _transcript_optional_mapping(
                payload.pop("decision", None),
                "decision",
            ),
            "input_refs": _transcript_text_sequence(
                payload.pop("input_refs", ()),
                "input_refs",
            ),
            "output_refs": _transcript_text_sequence(
                payload.pop("output_refs", ()),
                "output_refs",
            ),
            "gate_results": _transcript_mapping_sequence(
                payload.pop("gate_results", ()),
                "gate_results",
            ),
            "budget_snapshot": _transcript_optional_mapping(
                payload.pop("budget_snapshot", None),
                "budget_snapshot",
            ),
            "worker_call_ref": _transcript_optional_text(
                payload.pop("worker_call_ref", None),
                "worker_call_ref",
            ),
            "artifact_refs": _transcript_text_sequence(
                payload.pop("artifact_refs", ()),
                "artifact_refs",
            ),
            "skill_refs": _transcript_text_sequence(
                payload.pop("skill_refs", ()),
                "skill_refs",
            ),
            "candidate_refs": _transcript_text_sequence(
                payload.pop("candidate_refs", ()),
                "candidate_refs",
            ),
            "rag_session_refs": _transcript_text_sequence(
                payload.pop("rag_session_refs", ()),
                "rag_session_refs",
            ),
            "retrieval_plan_refs": _transcript_text_sequence(
                payload.pop("retrieval_plan_refs", ()),
                "retrieval_plan_refs",
            ),
            "context_pack_refs": _transcript_text_sequence(
                payload.pop("context_pack_refs", ()),
                "context_pack_refs",
            ),
            "context_envelope_ref": _transcript_optional_text(
                payload.pop("context_envelope_ref", None),
                "context_envelope_ref",
            ),
            "context_snapshot_ref": _transcript_optional_text(
                payload.pop("context_snapshot_ref", None),
                "context_snapshot_ref",
            ),
            "compression_record_refs": _transcript_text_sequence(
                payload.pop("compression_record_refs", ()),
                "compression_record_refs",
            ),
            "evidence_refs": _transcript_text_sequence(
                payload.pop("evidence_refs", ()),
                "evidence_refs",
            ),
            "eval_refs": _transcript_text_sequence(
                payload.pop("eval_refs", ()),
                "eval_refs",
            ),
            "release_refs": _transcript_text_sequence(
                payload.pop("release_refs", ()),
                "release_refs",
            ),
            "metadata": _transcript_mapping(
                payload.pop("metadata", {}),
                "metadata",
            ),
        }
        if payload:
            raise HarnessValidationError(
                "Harness transcript entry payload contains unsupported fields: "
                + ", ".join(sorted(payload))
            )
        return cls(
            run_id=str(run_id),
            phase=str(phase),
            timestamp=timestamp,
            **values,
        )


class HarnessTranscript:
    def __init__(self, run_id: str, entries: tuple[HarnessTranscriptEntry, ...] = ()) -> None:
        if not str(run_id).strip():
            raise HarnessValidationError("run_id is required")
        if not all(isinstance(entry, HarnessTranscriptEntry) for entry in entries):
            raise HarnessValidationError("entries must be HarnessTranscriptEntry values")
        self.run_id = str(run_id)
        self._entries: list[HarnessTranscriptEntry] = list(entries)

    def append(self, entry: HarnessTranscriptEntry) -> HarnessTranscriptEntry:
        if entry.run_id != self.run_id:
            raise HarnessValidationError("transcript entry run_id must match transcript run_id")
        if any(existing.entry_id == entry.entry_id for existing in self._entries):
            raise HarnessValidationError("transcript is append-only and entry_id must be unique")
        self._entries.append(entry)
        return entry

    def entries(self) -> tuple[HarnessTranscriptEntry, ...]:
        return tuple(self._entries)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "entries": [entry.to_dict() for entry in self._entries]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessTranscript":
        if not isinstance(value, Mapping):
            raise HarnessValidationError("Harness transcript payload must be an object")
        payload = dict(value)
        try:
            run_id = str(payload.pop("run_id"))
        except KeyError as exc:
            raise HarnessValidationError("Harness transcript run_id is required") from exc
        raw_entries = payload.pop("entries", ())
        if not isinstance(raw_entries, (list, tuple)):
            raise HarnessValidationError("Harness transcript entries must be a list")
        if payload:
            raise HarnessValidationError(
                "Harness transcript payload contains unsupported fields: "
                + ", ".join(sorted(payload))
            )
        entries = tuple(
            HarnessTranscriptEntry.from_dict(entry) for entry in raw_entries
        )
        if any(entry.run_id != run_id for entry in entries):
            raise HarnessValidationError(
                "Harness transcript entry run_id must match transcript run_id"
            )
        return cls(run_id, entries)


class InMemoryHarnessTranscriptStore:
    def __init__(self) -> None:
        self._transcripts: dict[str, HarnessTranscript] = {}

    def append(self, entry: HarnessTranscriptEntry) -> HarnessTranscriptEntry:
        transcript = self._transcripts.setdefault(entry.run_id, HarnessTranscript(entry.run_id))
        return transcript.append(entry)

    def export_run(self, run_id: str) -> HarnessTranscript:
        return self._transcripts.get(run_id, HarnessTranscript(run_id))

    def entries_for_run(self, run_id: str) -> tuple[HarnessTranscriptEntry, ...]:
        return self.export_run(run_id).entries()


def transcript_entry_from_event(event: Any, *, phase_index: int | None = None) -> HarnessTranscriptEntry:
    payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    event_type = str(payload.get("event_type"))
    event_payload = dict(payload.get("payload", {})) if isinstance(payload.get("payload", {}), dict) else {}
    phase = _transcript_phase_label(
        event_payload.get("phase", _phase_from_event(event_type, event_payload))
    )
    metadata = dict(payload.get("metadata", {}))
    metadata.update({"event_type": event_type, "event_payload": event_payload})
    if phase_index is not None:
        metadata["phase_index"] = phase_index
    budget_fact = (
        event_payload if event_type == "budget_fact_recorded" else None
    )
    return HarnessTranscriptEntry(
        entry_id=_optional_text(payload.get("event_id")),
        run_id=str(payload.get("run_id")),
        step_id=payload.get("step_id"),
        phase=phase,
        decision=event_payload if event_type == "decision_recorded" else None,
        input_refs=(
            (str(event_payload["fact_ref"]),)
            if budget_fact is not None
            and isinstance(event_payload.get("fact_ref"), str)
            else tuple(event_payload.get("input_refs", ()))
        ),
        output_refs=tuple(event_payload.get("output_refs", ())),
        gate_results=tuple(event_payload.get("gate_results", ())),
        budget_snapshot=(
            budget_fact
            or event_payload.get("budget_snapshot")
            or event_payload.get("metadata", {}).get("budget_snapshot")
        ),
        worker_call_ref=event_payload.get("worker_call_ref"),
        artifact_refs=tuple(event_payload.get("artifact_refs", event_payload.get("artifacts", ()))),
        metadata=metadata,
        timestamp=_required_timestamp(payload.get("occurred_at")),
    )


def transcript_entry_from_stored_event(
    event: StoredEvent,
    *,
    phase_index: int | None = None,
) -> HarnessTranscriptEntry:
    """Project one canonical Harness fact into the bounded transcript view."""

    if not isinstance(event, StoredEvent):
        raise TypeError("event must be StoredEvent")
    event.verify_integrity()
    if event.source != HARNESS_EVENT_SOURCE:
        raise EventStoreCorruptionError("stored Harness event source is invalid")
    run_id = event.business_context.run_id
    if run_id is None:
        raise HarnessValidationError(
            "stored Harness event requires business_context.run_id"
        )
    payload = thaw_canonical_json(event.payload or {})
    if not isinstance(payload, dict):
        raise HarnessValidationError("stored Harness payload must be an object")
    if event.event_type == HARNESS_TRANSITION_EVENT_TYPE:
        payload = HarnessTransitionCommitted.from_stored_event(event).to_payload()
    elif event.data_schema != "newsroom.harness-event/v1":
        raise EventStoreCorruptionError("stored Harness event schema is invalid")
    if event.payload_ref is not None:
        payload = _stored_activity_payload(event)
    return transcript_entry_from_event(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "run_id": run_id,
            "step_id": event.business_context.step_id,
            "payload": payload,
            "occurred_at": format_datetime(event.occurred_at),
            "metadata": {
                "stream_id": event.stream_id,
                "stream_sequence": event.stream_sequence,
                "content_checksum": event.content_checksum,
                "record_checksum": event.record_checksum,
            },
        },
        phase_index=phase_index,
    )


def _phase_from_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == HARNESS_TRANSITION_EVENT_TYPE:
        return _phase_from_transition_kind(payload.get("transition_kind"))
    return _phase_from_event_type(event_type)


def _stored_activity_payload(event: StoredEvent) -> dict[str, Any]:
    extension = thaw_canonical_json(
        event.extensions.get(HARNESS_ACTIVITY_EXTENSION, {})
    )
    if not isinstance(extension, dict):
        raise HarnessValidationError(
            "stored Harness activity extension must be an object"
        )
    activity_value = extension.get("activity")
    if not isinstance(activity_value, dict):
        raise HarnessValidationError(
            "stored Harness activity descriptor is missing"
        )
    try:
        activity = HarnessActivity.from_dict(activity_value)
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise HarnessValidationError(
            "stored Harness activity descriptor is invalid"
        ) from exc
    assert event.payload_ref is not None
    return {
        "activity_id": activity.activity_id,
        "worker_type": activity.activity_type,
        "input_ref": activity.input_checksum,
        "output_ref": event.payload_ref.expected_checksum,
        "status": extension.get("status"),
    }


def _phase_from_event_type(event_type: str) -> str:
    if event_type == "phase_recorded":
        return "phase"
    if "halt" in event_type:
        return "halt"
    if "replan" in event_type:
        return "replan"
    if "worker" in event_type:
        return "execute"
    if "gate" in event_type or "verify" in event_type:
        return "verify"
    if event_type == "budget_fact_recorded":
        return "verify"
    if "decision" in event_type:
        return "decision"
    return "event"


def _phase_from_transition_kind(value: Any) -> str:
    transition_kind = str(value or "").strip()
    for phase in ("plan", "execute", "verify", "replan"):
        if transition_kind == phase or transition_kind.startswith(f"{phase}_"):
            return phase
    if transition_kind == "worker_result_committed":
        return "execute"
    if transition_kind in {"halt", "failure", "budget_exhaustion"}:
        return "halt"
    if transition_kind in {
        "wait",
        "wait_for_approval",
        "approval_resume",
        "approval_cancel",
    }:
        return "wait"
    if transition_kind in {"retry", "route_to_repair", "route_to_step"}:
        return "decision"
    return transition_kind or "transition"


def _transcript_phase_label(value: Any) -> str:
    text = str(value).strip()
    if text in {"plan", "execute", "verify", "replan", "halt"}:
        return text.upper()
    return text


def _stable_entry_id(run_id: str, phase: str, step_id: str | None, metadata: dict[str, Any], timestamp: Any) -> str:
    payload = {
        "run_id": run_id,
        "phase": phase,
        "step_id": step_id,
        "metadata": metadata,
        "timestamp": format_datetime(timestamp),
    }
    digest = hashlib.sha256(stable_json_dumps(payload).encode()).hexdigest()[:16]
    return f"harness-transcript://{run_id}/{digest}"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_timestamp(value: Any):
    try:
        timestamp = parse_datetime(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HarnessValidationError("Harness event requires a valid occurred_at") from exc
    if timestamp is None:
        raise HarnessValidationError("Harness event requires a valid occurred_at")
    return timestamp


def _transcript_optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HarnessValidationError(f"{field_name} must be a string or null")
    return value


def _transcript_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"{field_name} must be an object")
    return dict(value)


def _transcript_optional_mapping(
    value: Any,
    field_name: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return _transcript_mapping(value, field_name)


def _transcript_text_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise HarnessValidationError(f"{field_name} must be a list of strings")
    return tuple(value)


def _transcript_mapping_sequence(
    value: Any,
    field_name: str,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise HarnessValidationError(f"{field_name} must be a list of objects")
    return tuple(dict(item) for item in value)


__all__ = [
    "HarnessTranscript",
    "HarnessTranscriptEntry",
    "InMemoryHarnessTranscriptStore",
    "transcript_entry_from_event",
    "transcript_entry_from_stored_event",
]
