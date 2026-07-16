from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from framework.artifacts.paths import validate_artifact_path_segment
from framework.events.canonical import (
    StoredEvent,
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventContractError, EventStoreUnavailableError
from framework.events.ports import EventReaderPort
from framework.events.runtime.models import (
    MAX_PAGE_LIMIT,
    EventPage,
    StreamReadRequest,
    StreamSequenceCursor,
)


_EVIDENCE_REF_PATTERN = re.compile(
    r"[a-z][a-z0-9+.-]{1,31}://[A-Za-z0-9][A-Za-z0-9._/-]{0,477}\Z"
)


class EventPermission(str, Enum):
    READ = "event.read"
    PROJECTION_READ = "event.projection.read"
    PROJECTION_REBUILD = "event.projection.rebuild"
    REPLAY_READ = "event.replay.read"
    REPLAY_START = "event.replay.start"
    DEAD_LETTER_READ = "event.dead_letter.read"
    DEAD_LETTER_REQUEUE = "event.dead_letter.requeue"
    DEAD_LETTER_RESOLVE = "event.dead_letter.resolve"
    DELIVERY_STATUS_READ = "event.delivery_status.read"
    REDELIVER = "event.redeliver"
    QUARANTINE_READ = "event.quarantine.read"
    QUARANTINE_RESOLVE = "event.quarantine.resolve"


class EventServiceAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class EventDataSource(str, Enum):
    DURABLE_STORE = "durable_store"


class EventAuthorizationError(PermissionError):
    """The application authorizer denied or could not decide an operation."""


class EventAuthorizationContractError(EventAuthorizationError):
    """The authorizer returned a mismatched or corrupt decision."""


@dataclass(frozen=True, slots=True)
class EventAuthorizationContext:
    """Authenticated caller scope; it never self-asserts event permissions."""

    principal_id: str
    tenant_id: str | None
    authentication_evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "principal_id",
            _required_text(self.principal_id, "principal_id"),
        )
        object.__setattr__(
            self,
            "tenant_id",
            _optional_text(self.tenant_id, "tenant_id"),
        )
        object.__setattr__(
            self,
            "authentication_evidence_ref",
            _safe_evidence_ref(
                self.authentication_evidence_ref,
                "authentication_evidence_ref",
            ),
        )


@dataclass(frozen=True, slots=True)
class EventAuthorizationRequest:
    principal_id: str
    tenant_id: str | None
    authentication_evidence_ref: str
    operation: EventPermission
    target: Mapping[str, Any]
    request_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "principal_id",
            _required_text(self.principal_id, "principal_id"),
        )
        object.__setattr__(
            self,
            "tenant_id",
            _optional_text(self.tenant_id, "tenant_id"),
        )
        object.__setattr__(
            self,
            "authentication_evidence_ref",
            _safe_evidence_ref(
                self.authentication_evidence_ref,
                "authentication_evidence_ref",
            ),
        )
        object.__setattr__(self, "operation", EventPermission(self.operation))
        target = normalize_canonical_json(self.target, path="$.authorization.target")
        if not isinstance(target, Mapping) or not target:
            raise ValueError("authorization target must be a non-empty object")
        object.__setattr__(self, "target", target)
        object.__setattr__(
            self,
            "request_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "authentication_evidence_ref": self.authentication_evidence_ref,
            "operation": self.operation.value,
            "target": thaw_canonical_json(self.target),
        }

    def verify_integrity(self) -> None:
        if checksum_for(self.checksum_projection()) != self.request_checksum:
            raise ValueError("authorization request checksum does not match")


@dataclass(frozen=True, slots=True)
class EventAuthorizationDecision:
    request: EventAuthorizationRequest
    authorized: bool
    authorization_evidence_ref: str | None = None
    denial_reason_class: str | None = None
    decision_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, EventAuthorizationRequest):
            raise TypeError("request must be EventAuthorizationRequest")
        self.request.verify_integrity()
        if not isinstance(self.authorized, bool):
            raise TypeError("authorized must be a boolean")
        evidence_ref = (
            None
            if self.authorization_evidence_ref is None
            else _safe_evidence_ref(
                self.authorization_evidence_ref,
                "authorization_evidence_ref",
            )
        )
        denial_reason = _optional_reason_class(self.denial_reason_class)
        if self.authorized:
            if evidence_ref is None:
                raise ValueError("authorized decision requires an evidence reference")
            if denial_reason is not None:
                raise ValueError("authorized decision cannot contain a denial reason")
        else:
            if evidence_ref is not None:
                raise ValueError("denied decision cannot contain authorization evidence")
            if denial_reason is None:
                raise ValueError("denied decision requires a reason class")
        object.__setattr__(self, "authorization_evidence_ref", evidence_ref)
        object.__setattr__(self, "denial_reason_class", denial_reason)
        object.__setattr__(
            self,
            "decision_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "request_checksum": self.request.request_checksum,
            "authorized": self.authorized,
            "authorization_evidence_ref": self.authorization_evidence_ref,
            "denial_reason_class": self.denial_reason_class,
        }

    def verify_integrity(self) -> None:
        self.request.verify_integrity()
        if checksum_for(self.checksum_projection()) != self.decision_checksum:
            raise ValueError("authorization decision checksum does not match")


@runtime_checkable
class EventAuthorizerPort(Protocol):
    def authorize(
        self,
        request: EventAuthorizationRequest,
    ) -> EventAuthorizationDecision: ...


def authorize_event_operation(
    authorizer: EventAuthorizerPort,
    authorization: EventAuthorizationContext,
    operation: EventPermission,
    *,
    target: Mapping[str, Any],
) -> EventAuthorizationDecision:
    request = EventAuthorizationRequest(
        principal_id=authorization.principal_id,
        tenant_id=authorization.tenant_id,
        authentication_evidence_ref=authorization.authentication_evidence_ref,
        operation=operation,
        target=target,
    )
    try:
        decision = authorizer.authorize(request)
    except Exception:
        raise EventAuthorizationError("event authorization failed") from None
    if not isinstance(decision, EventAuthorizationDecision):
        raise EventAuthorizationContractError(
            "event authorizer returned an invalid decision"
        )
    try:
        decision.verify_integrity()
    except Exception:
        raise EventAuthorizationContractError(
            "event authorization decision failed integrity validation"
        ) from None
    if decision.request != request:
        raise EventAuthorizationContractError(
            "event authorization decision does not match the exact request"
        )
    if not decision.authorized:
        raise EventAuthorizationError("event operation is not authorized")
    return decision


@dataclass(frozen=True, slots=True)
class EventStreamReadResult:
    availability: EventServiceAvailability
    stream_id: str
    tenant_id: str | None
    events: tuple[StoredEvent, ...] = ()
    high_watermark: int | None = None
    next_cursor: StreamSequenceCursor | None = None
    unavailable_reason_class: str | None = None
    source: EventDataSource = EventDataSource.DURABLE_STORE

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        object.__setattr__(self, "stream_id", _required_text(self.stream_id, "stream_id"))
        object.__setattr__(self, "tenant_id", _optional_text(self.tenant_id, "tenant_id"))
        events = tuple(self.events)
        if any(not isinstance(event, StoredEvent) for event in events):
            raise TypeError("events must contain StoredEvent values")
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "source", EventDataSource(self.source))
        if self.availability is EventServiceAvailability.AVAILABLE:
            if self.unavailable_reason_class is not None:
                raise ValueError("available event result cannot contain an unavailable reason")
        elif events or self.high_watermark is not None or self.next_cursor is not None:
            raise ValueError("unavailable event result cannot contain durable data")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable event result requires a reason class")

    @property
    def event_count(self) -> int:
        return len(self.events)


@dataclass(frozen=True, slots=True)
class EventLookupResult:
    availability: EventServiceAvailability
    tenant_id: str | None
    event: StoredEvent | None = None
    unavailable_reason_class: str | None = None
    source: EventDataSource = EventDataSource.DURABLE_STORE

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        object.__setattr__(self, "tenant_id", _optional_text(self.tenant_id, "tenant_id"))
        if self.event is not None and not isinstance(self.event, StoredEvent):
            raise TypeError("event must be a StoredEvent")
        object.__setattr__(self, "source", EventDataSource(self.source))
        if self.availability is EventServiceAvailability.AVAILABLE:
            if self.unavailable_reason_class is not None:
                raise ValueError("available lookup cannot contain an unavailable reason")
        elif self.event is not None:
            raise ValueError("unavailable lookup cannot contain an event")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable lookup requires a reason class")

    @property
    def found(self) -> bool:
        return self.event is not None


@dataclass(frozen=True, slots=True)
class EventHighWatermarkResult:
    availability: EventServiceAvailability
    stream_id: str
    tenant_id: str | None
    high_watermark: int | None = None
    unavailable_reason_class: str | None = None


class EventReaderService:
    """Tenant-scoped authoritative event reads with no projection fallback."""

    def __init__(
        self,
        reader: EventReaderPort,
        *,
        authorizer: EventAuthorizerPort,
    ) -> None:
        if reader is None:
            raise ValueError("event reader is required")
        if authorizer is None:
            raise ValueError("event authorizer is required")
        self._reader = reader
        self._authorizer = authorizer

    def read_run_events(
        self,
        run_id: str,
        *,
        authorization: EventAuthorizationContext,
        cursor: StreamSequenceCursor | None = None,
        limit: int = 100,
        through_sequence: int | None = None,
        event_types: frozenset[str] = frozenset(),
        data_schemas: frozenset[str] = frozenset(),
        step_id: str | None = None,
    ) -> EventStreamReadResult:
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        stream_id = f"run:{safe_run_id}"
        normalized_step_id = _optional_text(step_id, "step_id")
        initial_request = StreamReadRequest(
            stream_id=stream_id,
            cursor=cursor,
            limit=limit,
            through_sequence=through_sequence,
            tenant_id=authorization.tenant_id,
            event_types=event_types,
            data_schemas=data_schemas,
        )
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.READ,
            target={
                "stream_id": stream_id,
                "cursor": _cursor_target(cursor),
                "limit": limit,
                "through_sequence": initial_request.through_sequence,
                "event_types": sorted(initial_request.event_types),
                "data_schemas": sorted(initial_request.data_schemas),
                "step_id": normalized_step_id,
            },
        )
        if normalized_step_id is None:
            return self._read_page(initial_request)
        return self._read_step_page(
            initial_request,
            step_id=normalized_step_id,
            result_limit=limit,
        )

    def read_stream(
        self,
        stream_id: str,
        *,
        authorization: EventAuthorizationContext,
        cursor: StreamSequenceCursor | None = None,
        limit: int = 100,
        through_sequence: int | None = None,
        event_types: frozenset[str] = frozenset(),
        data_schemas: frozenset[str] = frozenset(),
    ) -> EventStreamReadResult:
        normalized_stream_id = _required_text(stream_id, "stream_id")
        request = StreamReadRequest(
            stream_id=normalized_stream_id,
            cursor=cursor,
            limit=limit,
            through_sequence=through_sequence,
            tenant_id=authorization.tenant_id,
            event_types=event_types,
            data_schemas=data_schemas,
        )
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.READ,
            target={
                "stream_id": normalized_stream_id,
                "cursor": _cursor_target(cursor),
                "limit": limit,
                "through_sequence": request.through_sequence,
                "event_types": sorted(request.event_types),
                "data_schemas": sorted(request.data_schemas),
            },
        )
        return self._read_page(request)

    def get_event(
        self,
        event_id: str,
        *,
        authorization: EventAuthorizationContext,
    ) -> EventLookupResult:
        normalized_event_id = _required_text(event_id, "event_id")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.READ,
            target={"event_id": normalized_event_id},
        )
        try:
            event = self._reader.get_event(
                normalized_event_id,
                tenant_id=authorization.tenant_id,
            )
        except EventStoreUnavailableError as error:
            return EventLookupResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                tenant_id=authorization.tenant_id,
                unavailable_reason_class=type(error).__name__,
            )
        if event is not None and event.tenant_id != authorization.tenant_id:
            raise EventContractError("event reader crossed the authorized tenant scope")
        if event is not None and event.event_id != normalized_event_id:
            raise EventContractError("event reader returned another event target")
        return EventLookupResult(
            availability=EventServiceAvailability.AVAILABLE,
            tenant_id=authorization.tenant_id,
            event=event,
        )

    def get_high_watermark(
        self,
        stream_id: str,
        *,
        authorization: EventAuthorizationContext,
    ) -> EventHighWatermarkResult:
        normalized_stream_id = _required_text(stream_id, "stream_id")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.READ,
            target={"stream_id": normalized_stream_id, "read": "high_watermark"},
        )
        try:
            high_watermark = self._reader.get_stream_high_watermark(
                normalized_stream_id,
                tenant_id=authorization.tenant_id,
            )
        except EventStoreUnavailableError as error:
            return EventHighWatermarkResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                stream_id=normalized_stream_id,
                tenant_id=authorization.tenant_id,
                unavailable_reason_class=type(error).__name__,
            )
        if (
            high_watermark is not None
            and (
                isinstance(high_watermark, bool)
                or not isinstance(high_watermark, int)
                or high_watermark < 1
            )
        ):
            raise EventContractError("event reader returned an invalid high watermark")
        return EventHighWatermarkResult(
            availability=EventServiceAvailability.AVAILABLE,
            stream_id=normalized_stream_id,
            tenant_id=authorization.tenant_id,
            high_watermark=high_watermark,
        )

    def _read_step_page(
        self,
        request: StreamReadRequest,
        *,
        step_id: str,
        result_limit: int,
    ) -> EventStreamReadResult:
        collected: list[StoredEvent] = []
        current = request
        fixed_high_watermark = (
            request.cursor.high_watermark
            if request.cursor is not None
            else request.through_sequence
        )
        while True:
            raw = self._read_page(current)
            if raw.availability is EventServiceAvailability.UNAVAILABLE:
                return raw
            if fixed_high_watermark is None:
                fixed_high_watermark = raw.high_watermark
            for event in raw.events:
                if event.business_context.step_id != step_id:
                    continue
                collected.append(event)
                if len(collected) == result_limit:
                    next_cursor = (
                        None
                        if fixed_high_watermark is None
                        or event.stream_sequence >= fixed_high_watermark
                        else StreamSequenceCursor(
                            stream_id=request.stream_id,
                            tenant_id=request.tenant_id,
                            after_sequence=event.stream_sequence,
                            high_watermark=fixed_high_watermark,
                        )
                    )
                    return EventStreamReadResult(
                        availability=EventServiceAvailability.AVAILABLE,
                        stream_id=request.stream_id,
                        tenant_id=request.tenant_id,
                        events=tuple(collected),
                        high_watermark=fixed_high_watermark,
                        next_cursor=next_cursor,
                    )
            if raw.next_cursor is None:
                return EventStreamReadResult(
                    availability=EventServiceAvailability.AVAILABLE,
                    stream_id=request.stream_id,
                    tenant_id=request.tenant_id,
                    events=tuple(collected),
                    high_watermark=fixed_high_watermark,
                )
            current = StreamReadRequest(
                stream_id=request.stream_id,
                cursor=raw.next_cursor,
                limit=min(MAX_PAGE_LIMIT, max(result_limit, 100)),
                through_sequence=fixed_high_watermark,
                tenant_id=request.tenant_id,
                event_types=request.event_types,
                data_schemas=request.data_schemas,
            )

    def _read_page(self, request: StreamReadRequest) -> EventStreamReadResult:
        try:
            page = self._reader.read_stream(request)
        except EventStoreUnavailableError as error:
            return EventStreamReadResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                stream_id=request.stream_id,
                tenant_id=request.tenant_id,
                unavailable_reason_class=type(error).__name__,
            )
        self._validate_page(page, request)
        return EventStreamReadResult(
            availability=EventServiceAvailability.AVAILABLE,
            stream_id=page.stream_id,
            tenant_id=page.tenant_id,
            events=page.events,
            high_watermark=page.high_watermark,
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _validate_page(page: Any, request: StreamReadRequest) -> None:
        if not isinstance(page, EventPage):
            raise EventContractError("event reader returned an invalid page")
        if page.stream_id != request.stream_id or page.tenant_id != request.tenant_id:
            raise EventContractError("event reader returned another stream scope")
        expected_high_watermark = (
            request.cursor.high_watermark
            if request.cursor is not None
            else request.through_sequence
        )
        if (
            expected_high_watermark is not None
            and page.high_watermark != expected_high_watermark
        ):
            raise EventContractError("event reader changed the requested high watermark")
        after_sequence = (
            request.cursor.after_sequence if request.cursor is not None else 0
        )
        sequences = tuple(event.stream_sequence for event in page.events)
        if sequences and (
            sequences[0] <= after_sequence
            or any(current <= previous for previous, current in zip(sequences, sequences[1:]))
        ):
            raise EventContractError("event reader returned a non-increasing sequence page")
        if request.event_types and any(
            event.event_type not in request.event_types for event in page.events
        ):
            raise EventContractError("event reader violated the event-type filter")
        if request.data_schemas and any(
            event.data_schema not in request.data_schemas for event in page.events
        ):
            raise EventContractError("event reader violated the data-schema filter")
        unfiltered = not request.event_types and not request.data_schemas
        if unfiltered and page.high_watermark is not None:
            expected_sequences = tuple(
                range(after_sequence + 1, after_sequence + 1 + len(sequences))
            )
            if sequences != expected_sequences:
                raise EventContractError("event reader returned a non-contiguous stream page")
            if page.next_cursor is None and after_sequence + len(sequences) < page.high_watermark:
                raise EventContractError("event reader truncated a stream page without a cursor")
        if page.next_cursor is not None and (
            page.next_cursor.after_sequence <= after_sequence
            or page.next_cursor.high_watermark != page.high_watermark
        ):
            raise EventContractError("event reader cursor did not advance")


def _cursor_target(cursor: StreamSequenceCursor | None) -> dict[str, Any] | None:
    if cursor is None:
        return None
    return {
        "stream_id": cursor.stream_id,
        "tenant_id": cursor.tenant_id,
        "after_sequence": cursor.after_sequence,
        "high_watermark": cursor.high_watermark,
    }


def _safe_evidence_ref(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    if len(normalized) > 512 or _EVIDENCE_REF_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a bounded safe URI reference")
    body = normalized.partition("://")[2]
    if any(part in {"", ".", ".."} for part in body.split("/")):
        raise ValueError(f"{field_name} contains an unsafe path segment")
    return normalized


def _optional_reason_class(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _required_text(value, "denial_reason_class")
    if len(normalized) > 128 or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", normalized) is None:
        raise ValueError("denial_reason_class must be a bounded identifier")
    return normalized


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    normalized = value.strip()
    if normalized != value:
        raise ValueError(f"{field_name} cannot contain surrounding whitespace")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


__all__ = [
    "EventAuthorizationContext",
    "EventAuthorizationContractError",
    "EventAuthorizationDecision",
    "EventAuthorizationError",
    "EventAuthorizationRequest",
    "EventAuthorizerPort",
    "EventDataSource",
    "EventHighWatermarkResult",
    "EventLookupResult",
    "EventPermission",
    "EventReaderService",
    "EventServiceAvailability",
    "EventStreamReadResult",
    "authorize_event_operation",
]
