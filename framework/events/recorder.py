from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import uuid4

from framework.events.canonical import normalize_canonical_json
from framework.events.errors import EventContextConflictError, EventTimeError
from framework.events.schema import (
    EventSchemaCatalog,
    EventSecurityProjector,
    default_event_schema_catalog,
)
from framework.events.schema.security import redact_event_value
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
    payload: Mapping[str, Any] = field(default_factory=dict)
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
        normalized_payload = normalize_canonical_json(
            to_jsonable(self.payload),
            path="$.payload",
        )
        if not isinstance(normalized_payload, Mapping):
            raise TypeError("event payload must be an object")
        object.__setattr__(self, "payload", normalized_payload)
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
        occurred_at = parse_datetime(data.get("occurred_at") or data.get("timestamp"))
        if occurred_at is None:
            raise EventTimeError("event occurred_at is required")
        event_id = str(data.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("event_id is required for historical event records")
        return cls(
            run_id=str(data["run_id"]),
            event_type=str(data["event_type"]),
            payload=dict(data.get("payload") or {}),
            event_id=event_id,
            occurred_at=occurred_at,
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
        schema_catalog: EventSchemaCatalog | None = None,
        security_projector: EventSecurityProjector | None = None,
    ) -> None:
        self.run_id = run_id
        self._event_bus = event_bus
        self._trace_context = trace_context
        self._schema_catalog = schema_catalog or default_event_schema_catalog()
        self._security_projector = security_projector or EventSecurityProjector()
        self._events: list[EventEnvelope] = []

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
    ) -> EventEnvelope:
        if not self.run_id:
            raise ValueError("run_id is required for emit()")
        context = trace_context or self._trace_context
        fields = trace_fields(context)
        context_run_id = fields.get("run_id")
        if context_run_id is not None and str(context_run_id) != str(self.run_id):
            raise EventContextConflictError("run_id")
        run_id = str(self.run_id)
        event = Event(
            event_type=event_type,
            payload=payload or {},
            source="workflow",
            metadata={"run_id": run_id},
            run_id=run_id,
            trace_id=fields.get("trace_id"),
            span_id=fields.get("span_id"),
            parent_span_id=fields.get("parent_span_id"),
            workflow_id=fields.get("workflow_id"),
            step_id=fields.get("step_id"),
            component=component or fields.get("component") or "workflow",
        )
        envelope = EventEnvelope(
            event=event,
            correlation_id=run_id,
            run_id=run_id,
            trace_id=event.trace_id,
            span_id=event.span_id,
            parent_span_id=event.parent_span_id,
            workflow_id=event.workflow_id,
            step_id=event.step_id,
            component=event.component,
        )
        self._events.append(envelope)
        if self._event_bus is not None:
            self._event_bus.publish(envelope)
        return envelope

    def record(self, envelope: EventEnvelope) -> None:
        if not isinstance(envelope, EventEnvelope):
            raise TypeError("record() requires EventEnvelope")
        if self.run_id is not None and envelope.run_id is not None:
            if str(self.run_id) != str(envelope.run_id):
                raise EventContextConflictError("run_id")
        self._events.append(envelope)

    def list_events(self, filters: EventFilter | None = None) -> list[EventEnvelope]:
        events = list(self._events)
        if filters is not None:
            return [event for event in events if filters.matches(event)]
        return events

    def write_jsonl(self, path: str | Path) -> Path:
        target = Path(path)
        safe_rows = [self._safe_export_row(event) for event in self._events]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for safe_row in safe_rows:
                handle.write(json.dumps(safe_row, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        return target

    def _safe_export_row(self, envelope: EventEnvelope) -> dict[str, Any]:
        event_type = str(envelope.event.event_type)
        data_schema = self._schema_catalog.current_schema(event_type)
        registration = self._schema_catalog.get(event_type, data_schema)
        validated_payload = self._schema_catalog.validate(
            event_type,
            data_schema,
            envelope.event.payload,
        )
        projection = self._security_projector.project_export(
            payload=validated_payload,
            extensions=envelope.event.metadata,
            policy=registration.sensitivity_policy,
        )
        safe_payload = to_jsonable(projection.payload or {})
        row = envelope.to_dict()
        row.update(
            {
                "event_type": event_type,
                "payload": safe_payload,
                "occurred_at": format_datetime(envelope.event.created_at),
            }
        )
        nested_event = dict(row["event"])
        nested_event["payload"] = safe_payload
        nested_event["metadata"] = to_jsonable(projection.extensions)
        row["event"] = nested_event
        return redact_event_value(to_jsonable(row))
