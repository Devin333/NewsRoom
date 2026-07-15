from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from framework.shared.ids import generate_id
from framework.events.errors import EventContextConflictError
from framework.events.event import Event


@dataclass(frozen=True)
class EventEnvelope:
    event: Event
    event_id: str = field(default_factory=lambda: generate_id("evt"))
    correlation_id: str | None = None
    causation_id: str | None = None
    sequence: int | None = None
    run_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    component: str | None = None
    schema_version: str = "newsroom.event_envelope.v1"

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if not isinstance(self.event, Event):
            object.__setattr__(self, "event", Event.from_dict(dict(self.event)))
        for name in (
            "run_id",
            "trace_id",
            "span_id",
            "parent_span_id",
            "workflow_id",
            "step_id",
            "component",
        ):
            envelope_value = getattr(self, name)
            event_value = getattr(self.event, name, None)
            if envelope_value is not None and event_value is not None:
                if str(envelope_value) != str(event_value):
                    raise EventContextConflictError(name)
            elif envelope_value is None and event_value is not None:
                object.__setattr__(self, name, event_value)

    def with_sequence(self, sequence: int) -> "EventEnvelope":
        return replace(self, sequence=int(sequence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event": self.event.to_dict(),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "sequence": self.sequence,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "component": self.component,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        return cls(
            event_id=str(data["event_id"]),
            event=Event.from_dict(dict(data["event"])),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            sequence=data.get("sequence"),
            run_id=data.get("run_id"),
            trace_id=data.get("trace_id"),
            span_id=data.get("span_id"),
            parent_span_id=data.get("parent_span_id"),
            workflow_id=data.get("workflow_id"),
            step_id=data.get("step_id"),
            component=data.get("component"),
            schema_version=str(data.get("schema_version") or "newsroom.event_envelope.v1"),
        )
