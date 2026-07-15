from __future__ import annotations

from collections.abc import Mapping
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from framework.events.canonical import (
    BusinessContext,
    ProducerIdentity,
    StoredEvent,
    TraceBlock,
    thaw_canonical_json,
)
from framework.events.envelope import EventEnvelope
from framework.events.filters import EventFilter
from framework.events.errors import EventContextConflictError
from framework.events.ports import EventReaderPort, EventRuntimePort
from framework.events.runtime.models import StreamReadRequest, StreamSequenceCursor
from framework.events.runtime.publisher import EventPublishRequest
from framework.events.schema.catalog import EventSchemaCatalog
from framework.events.schema.security import SecurityClassification
from framework.events.trace import TraceContext
from framework.shared.json import to_jsonable
from framework.shared.time import ensure_utc


WORKFLOW_DATA_SCHEMA = "newsroom.workflow-event/v1"
WORKFLOW_EVENT_SOURCE = "io.newsroom.workflow.runtime"
_TRACE_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_SPAN_ID_PATTERN = re.compile(r"[0-9a-f]{16}\Z")
_LEGACY_CORRELATION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class WorkflowEventEmitter(Protocol):
    """Workflow-owned append boundary with explicit context on every fact."""

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        business_context: BusinessContext,
        trace: TraceBlock | None = None,
        component: str | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
        subject: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> StoredEvent: ...

    def emit_default(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        business_context: BusinessContext | None = None,
        trace: TraceBlock | None = None,
        component: str | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
        subject: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> StoredEvent: ...

    def list_events(
        self,
        *,
        event_types: frozenset[str] = frozenset(),
        through_sequence: int | None = None,
    ) -> list[StoredEvent]: ...

    def list_compat_events(self) -> list[EventEnvelope]: ...

    def emit_from_trace_context(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        trace_context: TraceContext,
        component: str | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
        subject: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> StoredEvent: ...


class WorkflowEventRecorder(Protocol):
    """Compatibility projection used by workflow components, never a ledger."""

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        trace_context: TraceContext | None = None,
        component: str | None = None,
        occurred_at: datetime | None = None,
    ) -> EventEnvelope: ...


@dataclass(frozen=True, slots=True)
class ScopedDurableWorkflowEventEmitter:
    """Durable workflow emitter without an authoritative in-memory ledger.

    The emitter owns stable stream and producer configuration only. Business
    and trace context are immutable arguments to each append, so concurrent
    steps cannot mutate shared emitter state or inherit another step's scope.
    Compatibility reads always query the configured durable reader.
    """

    runtime: EventRuntimePort
    reader: EventReaderPort
    schema_catalog: EventSchemaCatalog
    stream_id: str
    base_business_context: BusinessContext
    base_trace: TraceBlock | None = None
    producer: ProducerIdentity = ProducerIdentity(
        component="framework.workflow.runtime",
        version="1",
    )
    tenant_id: str | None = None
    security_classification: SecurityClassification | str = (
        SecurityClassification.INTERNAL
    )

    def __post_init__(self) -> None:
        if self.runtime is None:
            raise ValueError("event runtime is required")
        if self.reader is None:
            raise ValueError("event reader is required")
        if not isinstance(self.schema_catalog, EventSchemaCatalog):
            raise TypeError("schema_catalog must be EventSchemaCatalog")
        object.__setattr__(self, "stream_id", _required_text(self.stream_id, "stream_id"))
        if not isinstance(self.base_business_context, BusinessContext):
            raise TypeError("base_business_context must be BusinessContext")
        base_run_id = self.base_business_context.run_id
        if base_run_id is None:
            raise ValueError("base_business_context.run_id is required")
        if self.stream_id != f"run:{base_run_id}":
            raise EventContextConflictError("stream_id")
        if self.base_trace is not None and not isinstance(self.base_trace, TraceBlock):
            raise TypeError("base_trace must be TraceBlock")
        if not isinstance(self.producer, ProducerIdentity):
            object.__setattr__(self, "producer", ProducerIdentity.from_dict(self.producer))
        object.__setattr__(
            self,
            "security_classification",
            SecurityClassification(self.security_classification),
        )

    def emit_from_trace_context(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        trace_context: TraceContext,
        component: str | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
        subject: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> StoredEvent:
        """Adapt one immutable legacy context without retaining it on the emitter."""

        if not isinstance(trace_context, TraceContext):
            raise TypeError("trace_context must be TraceContext")
        business_context = BusinessContext(
            run_id=trace_context.run_id,
            workflow_id=trace_context.workflow_id,
            step_id=trace_context.step_id,
            agent_id=trace_context.agent_id,
            tool_call_id=trace_context.tool_call_id,
        )
        trace, legacy_extension = _trace_from_legacy_context(trace_context)
        return self.emit(
            event_type,
            payload,
            business_context=business_context,
            trace=trace,
            component=component,
            occurred_at=occurred_at,
            event_id=event_id,
            subject=subject,
            correlation_id=correlation_id,
            causation_id=causation_id,
            extensions=_merge_extensions(extensions, legacy_extension),
        )

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        business_context: BusinessContext,
        trace: TraceBlock | None = None,
        component: str | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
        subject: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> StoredEvent:
        event_type = _required_text(event_type, "event_type")
        if not isinstance(business_context, BusinessContext):
            raise TypeError("business_context must be BusinessContext")
        if trace is not None and not isinstance(trace, TraceBlock):
            raise TypeError("trace must be TraceBlock")
        if trace is not None:
            _validate_trace_block(trace)
        _validate_business_scope(business_context, self.base_business_context)

        data_schema = self.schema_catalog.current_schema(event_type)
        payload_snapshot = self.schema_catalog.prepare_publish_payload(
            event_type,
            data_schema,
            payload or {},
            business_context=business_context,
        )
        producer = self.producer
        if component is not None:
            producer = replace(producer, component=_required_text(component, "component"))
        request = EventPublishRequest(
            event_id=event_id if event_id is not None else f"evt_{uuid4().hex}",
            event_type=event_type,
            data_schema=data_schema,
            source=WORKFLOW_EVENT_SOURCE,
            subject=subject,
            occurred_at=ensure_utc(occurred_at or datetime.now(UTC)),
            stream_id=self.stream_id,
            correlation_id=(
                correlation_id
                if correlation_id is not None
                else business_context.run_id
            ),
            causation_id=causation_id,
            business_context=business_context,
            producer=producer,
            trace=trace,
            tenant_id=self.tenant_id,
            security_classification=self.security_classification,
            payload=payload_snapshot,
            extensions=dict(extensions or {}),
        )
        stored = self.runtime.publish(request)
        _validate_commit_result(stored, request)
        return stored

    def emit_default(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        business_context: BusinessContext | None = None,
        trace: TraceBlock | None = None,
        component: str | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
        subject: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> StoredEvent:
        return self.emit(
            event_type,
            payload,
            business_context=business_context or self.base_business_context,
            trace=self.base_trace if trace is None else trace,
            component=component,
            occurred_at=occurred_at,
            event_id=event_id,
            subject=subject,
            correlation_id=correlation_id,
            causation_id=causation_id,
            extensions=extensions,
        )

    def list_events(
        self,
        *,
        event_types: frozenset[str] = frozenset(),
        through_sequence: int | None = None,
    ) -> list[StoredEvent]:
        events: list[StoredEvent] = []
        request = StreamReadRequest(
            stream_id=self.stream_id,
            tenant_id=self.tenant_id,
            event_types=event_types,
            through_sequence=through_sequence,
        )
        while True:
            page = self.reader.read_stream(request)
            events.extend(page.events)
            if page.next_cursor is None:
                return events
            request = StreamReadRequest(
                stream_id=self.stream_id,
                cursor=page.next_cursor,
                tenant_id=self.tenant_id,
                event_types=event_types,
                through_sequence=page.high_watermark,
            )

    @property
    def last_accepted_event(self) -> StoredEvent | None:
        high_watermark = self.reader.get_stream_high_watermark(
            self.stream_id,
            tenant_id=self.tenant_id,
        )
        if high_watermark is None:
            return None
        cursor = None
        if high_watermark > 1:
            cursor = StreamSequenceCursor(
                stream_id=self.stream_id,
                after_sequence=high_watermark - 1,
                high_watermark=high_watermark,
                tenant_id=self.tenant_id,
            )
        page = self.reader.read_stream(
            StreamReadRequest(
                stream_id=self.stream_id,
                cursor=cursor,
                limit=1,
                through_sequence=high_watermark,
                tenant_id=self.tenant_id,
            )
        )
        if not page.events or page.events[-1].stream_sequence != high_watermark:
            raise RuntimeError("durable event reader lost its reported high watermark")
        return page.events[-1]

    @property
    def last_accepted_sequence(self) -> int | None:
        event = self.last_accepted_event
        return None if event is None else event.stream_sequence

    @property
    def last_accepted_event_id(self) -> str | None:
        event = self.last_accepted_event
        return None if event is None else event.event_id

    def to_compat_envelope(self, stored: StoredEvent) -> EventEnvelope:
        """Project one accepted canonical event to the bounded legacy facade."""

        from framework.events.event import Event

        trace = stored.trace
        context = stored.business_context
        payload = thaw_canonical_json(stored.payload or {})
        metadata = thaw_canonical_json(stored.extensions)
        return EventEnvelope(
            event_id=stored.event_id,
            event=Event(
                event_type=stored.event_type,
                payload=payload,
                source=stored.source,
                metadata=metadata,
                created_at=stored.occurred_at,
                run_id=context.run_id,
                trace_id=trace.trace_id if trace is not None else None,
                span_id=trace.span_id if trace is not None else None,
                parent_span_id=(trace.parent_span_id if trace is not None else None),
                workflow_id=context.workflow_id,
                step_id=context.step_id,
                component=stored.producer.component,
            ),
            correlation_id=stored.correlation_id,
            causation_id=stored.causation_id,
            sequence=stored.stream_sequence,
            run_id=context.run_id,
            trace_id=trace.trace_id if trace is not None else None,
            span_id=trace.span_id if trace is not None else None,
            parent_span_id=trace.parent_span_id if trace is not None else None,
            workflow_id=context.workflow_id,
            step_id=context.step_id,
            component=stored.producer.component,
        )

    def list_compat_events(self) -> list[EventEnvelope]:
        return [self.to_compat_envelope(event) for event in self.list_events()]


@dataclass(frozen=True, slots=True)
class WorkflowEventRecorderFacade:
    """One-release recorder facade backed only by the durable emitter."""

    emitter: ScopedDurableWorkflowEventEmitter

    @property
    def run_id(self) -> str | None:
        return self.emitter.base_business_context.run_id

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        trace_context: TraceContext | None = None,
        component: str | None = None,
        occurred_at: datetime | None = None,
    ) -> EventEnvelope:
        normalized_payload = to_jsonable(payload or {})
        if not isinstance(normalized_payload, Mapping):
            raise TypeError("workflow event payload must be an object")
        if trace_context is None:
            stored = self.emitter.emit_default(
                event_type,
                normalized_payload,
                component=component,
                occurred_at=occurred_at,
            )
        else:
            stored = self.emitter.emit_from_trace_context(
                event_type,
                normalized_payload,
                trace_context=trace_context,
                component=component,
                occurred_at=occurred_at,
            )
        return self.emitter.to_compat_envelope(stored)

    def list_events(self, filters: EventFilter | None = None) -> list[EventEnvelope]:
        events = self.emitter.list_compat_events()
        if filters is not None:
            return [event for event in events if filters.matches(event)]
        return events

    @property
    def last_accepted_event(self) -> StoredEvent | None:
        return self.emitter.last_accepted_event

    @property
    def last_accepted_sequence(self) -> int | None:
        return self.emitter.last_accepted_sequence

    @property
    def last_accepted_event_id(self) -> str | None:
        return self.emitter.last_accepted_event_id


def _validate_commit_result(stored: StoredEvent, request: EventPublishRequest) -> None:
    if not isinstance(stored, StoredEvent):
        raise TypeError("event runtime must return StoredEvent after commit")
    stored.verify_integrity()
    if stored.event_id != request.event_id:
        raise ValueError("event runtime returned a different workflow event_id")
    if stored.event_type != request.event_type or stored.data_schema != request.data_schema:
        raise ValueError("event runtime returned a different workflow schema identity")
    if stored.stream_id != request.stream_id:
        raise ValueError("event runtime returned a different workflow stream")
    if stored.business_context != request.business_context:
        raise ValueError("event runtime returned different workflow business context")
    if stored.trace != request.trace:
        raise ValueError("event runtime returned different workflow trace context")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _trace_from_legacy_context(
    context: TraceContext,
) -> tuple[TraceBlock | None, Mapping[str, Any]]:
    trace_id = _legacy_correlation_value(context.trace_id, "trace_id")
    span_id = _legacy_correlation_value(context.span_id, "span_id")
    parent_span_id = (
        _legacy_correlation_value(context.parent_span_id, "parent_span_id")
        if context.parent_span_id is not None
        else None
    )
    canonical_trace_id = trace_id.casefold()
    canonical_span_id = span_id.casefold()
    canonical_parent_span_id = (
        parent_span_id.casefold() if parent_span_id is not None else None
    )
    valid = _TRACE_ID_PATTERN.fullmatch(canonical_trace_id) is not None
    valid = valid and canonical_trace_id != "0" * 32
    valid = valid and _SPAN_ID_PATTERN.fullmatch(canonical_span_id) is not None
    valid = valid and canonical_span_id != "0" * 16
    valid = valid and (
        canonical_parent_span_id is None
        or (
            _SPAN_ID_PATTERN.fullmatch(canonical_parent_span_id) is not None
            and canonical_parent_span_id != "0" * 16
        )
    )
    if valid:
        return (
            TraceBlock(
                trace_id=canonical_trace_id,
                span_id=canonical_span_id,
                parent_span_id=canonical_parent_span_id,
            ),
            {},
        )
    return (
        None,
        {
            "io.newsroom.legacy": {
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
            }
        },
    )


def _merge_extensions(
    extensions: Mapping[str, Any] | None,
    legacy_extension: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(extensions or {})
    for key, value in legacy_extension.items():
        if key in merged:
            raise ValueError(f"reserved workflow extension namespace: {key}")
        merged[key] = value
    return merged


def _validate_business_scope(
    context: BusinessContext,
    base: BusinessContext,
) -> None:
    if context.run_id != base.run_id:
        raise EventContextConflictError("run_id")
    if base.workflow_id is not None and context.workflow_id != base.workflow_id:
        raise EventContextConflictError("workflow_id")


def _legacy_correlation_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"legacy {field_name} must be a string")
    if _LEGACY_CORRELATION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"legacy {field_name} is not a safe correlation value")
    return value


def _validate_trace_block(trace: TraceBlock) -> None:
    trace_id = trace.trace_id.casefold()
    span_id = trace.span_id.casefold()
    parent_span_id = (
        trace.parent_span_id.casefold() if trace.parent_span_id is not None else None
    )
    if _TRACE_ID_PATTERN.fullmatch(trace_id) is None or trace_id == "0" * 32:
        raise ValueError("trace.trace_id must be a nonzero W3C trace id")
    if _SPAN_ID_PATTERN.fullmatch(span_id) is None or span_id == "0" * 16:
        raise ValueError("trace.span_id must be a nonzero W3C span id")
    if parent_span_id is not None and (
        _SPAN_ID_PATTERN.fullmatch(parent_span_id) is None
        or parent_span_id == "0" * 16
    ):
        raise ValueError("trace.parent_span_id must be a nonzero W3C span id")


__all__ = [
    "ScopedDurableWorkflowEventEmitter",
    "WORKFLOW_DATA_SCHEMA",
    "WORKFLOW_EVENT_SOURCE",
    "WorkflowEventEmitter",
    "WorkflowEventRecorder",
    "WorkflowEventRecorderFacade",
]
