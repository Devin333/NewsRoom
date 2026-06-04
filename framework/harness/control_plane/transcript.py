from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
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
    phase = _transcript_phase_label(event_payload.get("phase", _phase_from_event_type(event_type)))
    metadata = dict(payload.get("metadata", {}))
    metadata.update({"event_type": event_type, "event_payload": event_payload})
    if phase_index is not None:
        metadata["phase_index"] = phase_index
    return HarnessTranscriptEntry(
        run_id=str(payload.get("run_id")),
        step_id=payload.get("step_id"),
        phase=phase,
        decision=event_payload if event_type == "decision_recorded" else None,
        input_refs=tuple(event_payload.get("input_refs", ())),
        output_refs=tuple(event_payload.get("output_refs", ())),
        gate_results=tuple(event_payload.get("gate_results", ())),
        budget_snapshot=event_payload.get("budget_snapshot") or event_payload.get("metadata", {}).get("budget_snapshot"),
        worker_call_ref=event_payload.get("worker_call_ref"),
        artifact_refs=tuple(event_payload.get("artifact_refs", event_payload.get("artifacts", ()))),
        metadata=metadata,
        timestamp=parse_datetime(payload.get("occurred_at")) or utc_now(),
    )


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
    if "decision" in event_type:
        return "decision"
    return "event"


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


__all__ = [
    "HarnessTranscript",
    "HarnessTranscriptEntry",
    "InMemoryHarnessTranscriptStore",
    "transcript_entry_from_event",
]
