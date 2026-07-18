from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event_log import HarnessEventLogEntry
from framework.harness.control_plane.gate_registry import GateReference
from framework.harness.control_plane.transcript import HarnessTranscript, HarnessTranscriptEntry
from framework.harness.runtime.checkpoint import HarnessCheckpoint
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class HarnessReplayReport:
    run_id: str
    status: str | None
    phase_transitions: tuple[dict[str, Any], ...] = ()
    gate_results: tuple[dict[str, Any], ...] = ()
    budget_summary: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    skill_candidates: tuple[str, ...] = ()
    skill_releases: tuple[str, ...] = ()
    rag_sessions: tuple[str, ...] = ()
    retrieval_rounds: tuple[dict[str, Any], ...] = ()
    context_packs: tuple[str, ...] = ()
    context_snapshots: tuple[str, ...] = ()
    compression_records: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    side_effects_replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "phase_transitions": to_jsonable(list(self.phase_transitions)),
            "gate_results": to_jsonable(list(self.gate_results)),
            "budget_summary": to_jsonable(self.budget_summary),
            "artifacts": list(self.artifacts),
            "skills": list(self.skills),
            "skill_candidates": list(self.skill_candidates),
            "skill_releases": list(self.skill_releases),
            "rag_sessions": list(self.rag_sessions),
            "retrieval_rounds": to_jsonable(list(self.retrieval_rounds)),
            "context_packs": list(self.context_packs),
            "context_snapshots": list(self.context_snapshots),
            "compression_records": list(self.compression_records),
            "errors": list(self.errors),
            "side_effects_replayed": self.side_effects_replayed,
        }


class HarnessReplayReader:
    def replay(
        self,
        *,
        run_id: str,
        events: tuple[HarnessEventLogEntry, ...] = (),
        transcript: HarnessTranscript | None = None,
        checkpoint: HarnessCheckpoint | None = None,
    ) -> HarnessReplayReport:
        entries = transcript.entries() if transcript is not None else ()
        status = checkpoint.state.status.value if checkpoint is not None else _status_from_events(events)
        phase_transitions = tuple(_phase_transition(entry) for entry in entries if entry.phase)
        gate_results = tuple(
            _gate_replay_projection(result)
            for entry in entries
            for result in entry.gate_results
        )
        event_gate_results = tuple(
            event.metadata
            for event in events
            if "gate" in event.event_type or "gate_results" in event.metadata
        )
        budget_summary = _budget_summary(entries, events)
        return HarnessReplayReport(
            run_id=run_id,
            status=status,
            phase_transitions=phase_transitions,
            gate_results=gate_results + event_gate_results,
            budget_summary=budget_summary,
            artifacts=_dedupe(ref for entry in entries for ref in entry.artifact_refs),
            skills=_dedupe(event.skill_name for event in events if event.skill_name),
            skill_candidates=_dedupe(
                [event.skill_candidate_id for event in events if event.skill_candidate_id]
                + [ref for entry in entries for ref in entry.candidate_refs]
            ),
            skill_releases=_dedupe(ref for entry in entries for ref in entry.release_refs),
            rag_sessions=_dedupe(
                [event.rag_session_id for event in events if event.rag_session_id]
                + [ref for entry in entries for ref in entry.rag_session_refs]
            ),
            retrieval_rounds=tuple(
                {"event_id": event.event_id, "round": event.retrieval_round, "metadata": event.metadata}
                for event in events
                if event.retrieval_round is not None
            ),
            context_packs=_dedupe(ref for entry in entries for ref in entry.context_pack_refs),
            context_snapshots=_dedupe(
                [entry.context_snapshot_ref for entry in entries if entry.context_snapshot_ref]
                + [str(event.metadata.get("context_snapshot_ref")) for event in events if event.metadata.get("context_snapshot_ref")]
            ),
            compression_records=_dedupe(
                [ref for entry in entries for ref in entry.compression_record_refs]
                + [
                    str(ref)
                    for event in events
                    for ref in _as_tuple(event.metadata.get("compression_record_refs", ()))
                ]
            ),
            errors=_dedupe(event.error for event in events if event.error),
            side_effects_replayed=False,
        )

    def resume_from_checkpoint(self, checkpoint: HarnessCheckpoint):
        return checkpoint.state


class HarnessTraceExporter:
    def export(self, report: HarnessReplayReport) -> dict[str, Any]:
        return {
            "run_id": report.run_id,
            "status": report.status,
            "steps": [
                {"step_id": item.get("step_id"), "phase": item.get("phase")}
                for item in report.phase_transitions
            ],
            "decisions": [
                item
                for item in report.phase_transitions
                if item.get("decision")
            ],
            "errors": list(report.errors),
            "artifacts": list(report.artifacts),
            "skills": list(report.skills),
            "skill_candidates": list(report.skill_candidates),
            "skill_releases": list(report.skill_releases),
            "rag_sessions": list(report.rag_sessions),
            "retrieval_rounds": to_jsonable(list(report.retrieval_rounds)),
            "context_packs": list(report.context_packs),
            "context_snapshots": list(report.context_snapshots),
            "compression_records": list(report.compression_records),
            "phase_transitions": to_jsonable(list(report.phase_transitions)),
            "gate_results": to_jsonable(list(report.gate_results)),
            "budget_summary": to_jsonable(report.budget_summary),
            "metrics": {"side_effects_replayed": report.side_effects_replayed},
        }


def _phase_transition(entry: HarnessTranscriptEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "step_id": entry.step_id,
        "phase": entry.phase,
        "decision": entry.decision,
        "context_snapshot_ref": entry.context_snapshot_ref,
        "budget_snapshot": entry.budget_snapshot,
        "metadata": entry.metadata,
    }


def _gate_replay_projection(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    details = result.get("details")
    evidence = details.get("harness_gate") if isinstance(details, Mapping) else None
    if not isinstance(evidence, Mapping):
        result["verification_status"] = "legacy_unverified"
        return result
    try:
        reference = GateReference.parse(str(evidence.get("reference") or ""))
    except HarnessValidationError:
        result["verification_status"] = "malformed_unverified"
        return result
    input_ref = evidence.get("input_ref")
    result_ref = evidence.get("result_ref")
    reason_code = evidence.get("reason_code")
    raw_details = dict(details)
    raw_details.pop("harness_gate", None)
    raw_result = {
        "gate": result.get("gate"),
        "passed": result.get("passed"),
        "reason": result.get("reason"),
        "details": raw_details,
    }
    valid = (
        reference.gate_id == result.get("gate")
        and _is_checksum_ref(input_ref)
        and _is_checksum_ref(result_ref)
        and result_ref == checksum_for(raw_result)
        and isinstance(reason_code, str)
        and bool(reason_code.strip())
    )
    result["verification_status"] = (
        "versioned_evidence" if valid else "malformed_unverified"
    )
    return result


def _is_checksum_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _status_from_events(events: tuple[HarnessEventLogEntry, ...]) -> str | None:
    statuses = [event.status_after for event in events if event.status_after]
    if statuses:
        return statuses[-1]
    for event in reversed(events):
        if event.event_type == "run_state_changed" and event.metadata.get("status"):
            return str(event.metadata["status"])
    return None


def _budget_summary(entries: tuple[HarnessTranscriptEntry, ...], events: tuple[HarnessEventLogEntry, ...]) -> dict[str, Any]:
    snapshots = [entry.budget_snapshot for entry in entries if entry.budget_snapshot]
    snapshots.extend(event.metadata.get("budget_snapshot") for event in events if event.metadata.get("budget_snapshot"))
    return snapshots[-1] if snapshots else {}


def _dedupe(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if value))


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


__all__ = ["HarnessReplayReader", "HarnessReplayReport", "HarnessTraceExporter"]
