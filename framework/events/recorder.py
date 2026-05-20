from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from framework.shared.json import to_jsonable
from framework.shared.time import ensure_utc, format_datetime, parse_datetime
from framework.events.envelope import EventEnvelope
from framework.events.event import Event
from framework.events.filters import EventFilter
from framework.events.trace import TraceContext, trace_fields


@dataclass(frozen=True)
class EventRecord:
    run_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    component: str | None = None
    schema_version: str = "newsroom.event_record.v1"

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.event_type:
            raise ValueError("event_type is required")
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))

    def to_event(self) -> Event:
        return Event(
            event_type=self.event_type,
            payload=self.payload,
            source="workflow",
            metadata={"run_id": self.run_id},
            created_at=self.occurred_at,
            run_id=self.run_id,
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            workflow_id=self.workflow_id,
            step_id=self.step_id,
            component=self.component,
        )

    def to_envelope(self) -> EventEnvelope:
        return EventEnvelope(
            event_id=self.event_id,
            event=self.to_event(),
            correlation_id=self.run_id,
            run_id=self.run_id,
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            workflow_id=self.workflow_id,
            step_id=self.step_id,
            component=self.component,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "occurred_at": format_datetime(self.occurred_at),
            "payload": to_jsonable(self.payload),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "component": self.component,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventRecord":
        return cls(
            run_id=str(data["run_id"]),
            event_type=str(data["event_type"]),
            payload=dict(data.get("payload") or {}),
            event_id=str(data.get("event_id") or uuid4().hex),
            occurred_at=parse_datetime(data.get("occurred_at") or data.get("timestamp")) or datetime.now(UTC),
            trace_id=data.get("trace_id"),
            span_id=data.get("span_id"),
            parent_span_id=data.get("parent_span_id"),
            workflow_id=data.get("workflow_id"),
            step_id=data.get("step_id"),
            component=data.get("component"),
            schema_version=str(data.get("schema_version") or "newsroom.event_record.v1"),
        )


class EventRecorderProtocol(Protocol):
    def record(self, envelope: EventEnvelope) -> None: ...

    def list_events(self, filters: EventFilter | None = None) -> list[EventEnvelope]: ...


class InMemoryEventRecorder:
    def __init__(self, envelopes: list[EventEnvelope] | None = None) -> None:
        self._events = list(envelopes or [])

    def record(self, envelope: EventEnvelope) -> None:
        self._events.append(envelope)

    def list_events(self, filters: EventFilter | None = None) -> list[EventEnvelope]:
        events = list(self._events)
        if filters is not None:
            return [event for event in events if filters.matches(event)]
        return events

    def clear(self) -> None:
        self._events.clear()


class EventRecorder:
    """Legacy workflow recorder with PRD record/list support."""

    def __init__(
        self,
        run_id: str | None = None,
        event_bus: Any | None = None,
        trace_context: TraceContext | None = None,
    ) -> None:
        self.run_id = run_id
        self._event_bus = event_bus
        self._trace_context = trace_context
        self._records: list[EventRecord] = []
        self._envelopes: list[EventEnvelope] = []

    @property
    def trace_context(self) -> TraceContext | None:
        return self._trace_context

    def with_trace_context(self, trace_context: TraceContext | None) -> "EventRecorder":
        self._trace_context = trace_context
        return self

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        trace_context: TraceContext | None = None,
        component: str | None = None,
    ) -> EventRecord:
        if not self.run_id:
            raise ValueError("run_id is required for emit()")
        context = trace_context or self._trace_context
        fields = trace_fields(context)
        event = EventRecord(
            run_id=str(fields.get("run_id") or self.run_id),
            event_type=event_type,
            payload=payload or {},
            trace_id=fields.get("trace_id"),
            span_id=fields.get("span_id"),
            parent_span_id=fields.get("parent_span_id"),
            workflow_id=fields.get("workflow_id"),
            step_id=fields.get("step_id"),
            component=component or fields.get("component") or "workflow",
        )
        self._records.append(event)
        self._envelopes.append(event.to_envelope())
        if self._event_bus is not None:
            self._event_bus.publish(event)
        return event

    def record(self, envelope: EventEnvelope) -> None:
        self._envelopes.append(envelope)

    def list_events(self, filters: EventFilter | None = None) -> list[Any]:
        if filters is None and self._records:
            return list(self._records)
        events = list(self._envelopes)
        if filters is not None:
            return [event for event in events if filters.matches(event)]
        return events

    def write_jsonl(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in self._records:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        return target
