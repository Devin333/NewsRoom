from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, utc_now


@dataclass(frozen=True)
class SubAgentTranscript:
    transcript_id: str
    child_run_id: str
    parent_run_id: str
    subagent_id: str
    context_envelope_ref: str
    input_refs: tuple[str, ...] = ()
    tool_call_refs: tuple[str, ...] = ()
    memory_context_refs: tuple[str, ...] = ()
    output_ref: str | None = None
    gate_results: tuple[dict[str, Any], ...] = ()
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for field_name in ("transcript_id", "child_run_id", "parent_run_id", "subagent_id", "context_envelope_ref"):
            if not str(getattr(self, field_name)).strip():
                raise HarnessValidationError(f"{field_name} is required")
        object.__setattr__(self, "input_refs", tuple(str(ref) for ref in self.input_refs))
        object.__setattr__(self, "tool_call_refs", tuple(str(ref) for ref in self.tool_call_refs))
        object.__setattr__(self, "memory_context_refs", tuple(str(ref) for ref in self.memory_context_refs))
        object.__setattr__(self, "gate_results", tuple(dict(result) for result in self.gate_results))
        object.__setattr__(self, "budget_snapshot", dict(self.budget_snapshot))
        object.__setattr__(self, "errors", tuple(str(error) for error in self.errors))
        object.__setattr__(self, "events", tuple(dict(event) for event in self.events))

    @property
    def ref(self) -> str:
        return f"subagent-transcript://{self.transcript_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcript_id": self.transcript_id,
            "child_run_id": self.child_run_id,
            "parent_run_id": self.parent_run_id,
            "subagent_id": self.subagent_id,
            "context_envelope_ref": self.context_envelope_ref,
            "input_refs": list(self.input_refs),
            "tool_call_refs": list(self.tool_call_refs),
            "memory_context_refs": list(self.memory_context_refs),
            "output_ref": self.output_ref,
            "gate_results": to_jsonable(list(self.gate_results)),
            "budget_snapshot": to_jsonable(self.budget_snapshot),
            "errors": list(self.errors),
            "events": to_jsonable(list(self.events)),
            "created_at": format_datetime(self.created_at),
            "ref": self.ref,
        }


class FakeSubAgentTranscriptStore:
    def __init__(self) -> None:
        self.transcripts: dict[str, SubAgentTranscript] = {}
        self.parent_refs: dict[str, list[str]] = {}

    def write(self, transcript: SubAgentTranscript) -> str:
        self.transcripts[transcript.ref] = transcript
        self.parent_refs.setdefault(transcript.parent_run_id, []).append(transcript.ref)
        return transcript.ref

    def read(self, transcript_ref: str) -> SubAgentTranscript:
        return self.transcripts[transcript_ref]

    def refs_for_parent(self, parent_run_id: str) -> tuple[str, ...]:
        return tuple(self.parent_refs.get(parent_run_id, ()))


__all__ = ["FakeSubAgentTranscriptStore", "SubAgentTranscript"]
