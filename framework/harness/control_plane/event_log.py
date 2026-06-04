from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
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

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        if not str(self.event_type).strip():
            raise HarnessValidationError("event_type is required")
        metadata = dict(self.metadata)
        event_id = self.event_id or _stable_event_id(self.run_id, self.event_type, self.step_id, metadata, self.timestamp)
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "event_type", str(self.event_type))
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "decision", dict(self.decision) if self.decision is not None else None)
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
    metadata.update(event_payload if isinstance(event_payload, dict) else {"payload": event_payload})
    if phase_index is not None:
        metadata["phase_index"] = phase_index
    return HarnessEventLogEntry(
        run_id=str(payload.get("run_id")),
        step_id=payload.get("step_id"),
        event_type=str(payload.get("event_type")),
        decision=event_payload if str(payload.get("event_type")) == "decision_recorded" else None,
        worker_type=event_payload.get("worker_type") if isinstance(event_payload, dict) else None,
        error=event_payload.get("error") if isinstance(event_payload, dict) else None,
        metadata=metadata,
        timestamp=parse_datetime(payload.get("occurred_at")) or utc_now(),
    )


def _stable_event_id(run_id: str, event_type: str, step_id: str | None, metadata: dict[str, Any], timestamp: Any) -> str:
    payload = {
        "run_id": run_id,
        "event_type": event_type,
        "step_id": step_id,
        "metadata": metadata,
        "timestamp": format_datetime(timestamp),
    }
    digest = hashlib.sha256(stable_json_dumps(payload).encode()).hexdigest()[:16]
    return f"harness-event://{run_id}/{digest}"


__all__ = ["HarnessEventLogEntry", "InMemoryHarnessEventLog", "event_log_entry_from_harness_event"]
