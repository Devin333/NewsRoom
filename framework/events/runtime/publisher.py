from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    PayloadReference,
    ProducerIdentity,
    StoredEvent,
    TraceBlock,
    assert_same_event_identity,
    normalize_canonical_json,
)
from framework.events.errors import EventContractError
from framework.events.runtime.fallback import (
    LocalRuntimeDiagnosticFallback,
    RuntimeDiagnosticCategory,
    RuntimeDiagnosticComponent,
    RuntimeDiagnosticOperation,
)
from framework.events.runtime.models import AppendResult
from framework.events.schema.catalog import EventSchemaCatalog
from framework.events.schema.security import (
    EventSecurityProjector,
    SecurityClassification,
)

if TYPE_CHECKING:
    from framework.events.ports import EventStorePort, EventUnitOfWorkPort


@dataclass(frozen=True, slots=True)
class EventPublishRequest:
    """Immutable producer input before schema and security acceptance.

    The request deliberately has no store-assigned fields or checksums.  Its
    payload and extensions are detached from caller-owned objects immediately,
    but only ``EventRuntime`` may turn it into a post-security
    :class:`EventCandidate`.
    """

    event_id: str
    event_type: str
    data_schema: str
    source: str
    occurred_at: datetime
    stream_id: str
    business_context: BusinessContext
    producer: ProducerIdentity
    subject: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    trace: TraceBlock | None = None
    tenant_id: str | None = None
    security_classification: SecurityClassification | str = SecurityClassification.INTERNAL
    content_type: str = "application/json"
    payload: Mapping[str, Any] | None = None
    payload_ref: PayloadReference | Mapping[str, Any] | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "event_type",
            "data_schema",
            "source",
            "stream_id",
            "content_type",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "occurred_at", _required_utc(self.occurred_at))
        for field_name in ("subject", "correlation_id", "causation_id", "tenant_id"):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "security_classification",
            SecurityClassification(self.security_classification),
        )

        if not isinstance(self.business_context, BusinessContext):
            object.__setattr__(
                self,
                "business_context",
                BusinessContext.from_dict(self.business_context),
            )
        if not isinstance(self.producer, ProducerIdentity):
            object.__setattr__(
                self,
                "producer",
                ProducerIdentity.from_dict(self.producer),
            )
        if self.trace is not None and not isinstance(self.trace, TraceBlock):
            object.__setattr__(self, "trace", TraceBlock.from_dict(self.trace))

        if self.payload is not None and self.payload_ref is not None:
            raise ValueError("payload and payload_ref are mutually exclusive")
        if self.payload is not None:
            normalized_payload = normalize_canonical_json(self.payload, path="$.payload")
            if not isinstance(normalized_payload, Mapping):
                raise TypeError("payload must be an object")
            object.__setattr__(self, "payload", normalized_payload)
        if self.payload_ref is not None and not isinstance(
            self.payload_ref,
            PayloadReference,
        ):
            if not isinstance(self.payload_ref, Mapping):
                raise TypeError("payload_ref must be a PayloadReference or object")
            object.__setattr__(
                self,
                "payload_ref",
                PayloadReference.from_dict(self.payload_ref),
            )

        normalized_extensions = normalize_canonical_json(
            self.extensions,
            path="$.extensions",
        )
        if not isinstance(normalized_extensions, Mapping):
            raise TypeError("extensions must be an object")
        object.__setattr__(self, "extensions", normalized_extensions)


class EventRuntime:
    """The sole live boundary that can construct a durable event candidate."""

    def __init__(
        self,
        *,
        store: EventStorePort,
        schema_catalog: EventSchemaCatalog,
        security_projector: EventSecurityProjector | None = None,
        diagnostic_fallback: LocalRuntimeDiagnosticFallback | None = None,
    ) -> None:
        self._store = store
        self._schema_catalog = schema_catalog
        self._security_projector = security_projector or EventSecurityProjector()
        self._diagnostic_fallback = (
            diagnostic_fallback
            if diagnostic_fallback is not None
            else LocalRuntimeDiagnosticFallback()
        )

    @property
    def diagnostic_fallback(self) -> LocalRuntimeDiagnosticFallback:
        return self._diagnostic_fallback

    def publish(
        self,
        event: EventPublishRequest,
        *,
        unit_of_work: EventUnitOfWorkPort | None = None,
    ) -> StoredEvent:
        if not isinstance(event, EventPublishRequest):
            raise TypeError("event must be EventPublishRequest")
        registration = self._schema_catalog.get(event.event_type, event.data_schema)
        policy = registration.sensitivity_policy

        validated_payload: Mapping[str, Any] | None
        if event.payload_ref is None:
            validated_payload = self._schema_catalog.validate(
                event.event_type,
                event.data_schema,
                event.payload or {},
            )
        else:
            # Referenced bytes are not fetched through the event runtime.  The
            # shared projector owns the schema reference disposition and proves
            # the ordinary or secure integrity boundary before append.
            validated_payload = None

        projection = self._security_projector.project(
            payload=validated_payload,
            payload_ref=event.payload_ref,
            extensions=event.extensions,
            policy=policy,
            classification=event.security_classification,
            tenant_id=event.tenant_id,
        )
        payload_ref = (
            None
            if projection.payload_ref is None
            else PayloadReference.from_dict(projection.payload_ref)
        )
        candidate = EventCandidate(
            event_id=event.event_id,
            event_type=event.event_type,
            data_schema=event.data_schema,
            source=event.source,
            occurred_at=event.occurred_at,
            stream_id=event.stream_id,
            business_context=event.business_context,
            producer=event.producer,
            subject=event.subject,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            trace=event.trace,
            tenant_id=projection.tenant_id,
            security_classification=projection.classification,
            content_type=event.content_type,
            payload=projection.payload,
            payload_ref=payload_ref,
            extensions=projection.extensions,
            max_inline_payload_bytes=policy.max_inline_payload_bytes,
        )

        try:
            if unit_of_work is not None:
                return _append_verified(unit_of_work, candidate)

            with self._store.unit_of_work() as owned_unit_of_work:
                stored = _append_verified(owned_unit_of_work, candidate)
                owned_unit_of_work.commit()
            return stored
        except Exception as error:
            self._diagnostic_fallback.record(
                category=RuntimeDiagnosticCategory.EVENT_STORE_FAILURE,
                component=RuntimeDiagnosticComponent.EVENT_PUBLISHER,
                operation=RuntimeDiagnosticOperation.PUBLISH,
                error=error,
            )
            raise


def _append_verified(
    unit_of_work: EventUnitOfWorkPort,
    candidate: EventCandidate,
) -> StoredEvent:
    result = unit_of_work.append_event(candidate)
    if not isinstance(result, AppendResult):
        raise EventContractError("durable event store returned an invalid append result")
    assert_same_event_identity(result.event, candidate)
    result.event.verify_integrity()
    return result.event


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _required_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("occurred_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["EventPublishRequest", "EventRuntime"]
