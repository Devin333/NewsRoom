from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
    StoredEvent,
)
from framework.events.errors import EventContractError, EventStoreUnavailableError
from framework.events.runtime.models import EventPage, StreamSequenceCursor
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventAuthorizationContractError,
    EventAuthorizationDecision,
    EventAuthorizationError,
    EventPermission,
    EventReaderService,
    EventServiceAvailability,
)


NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


class _Authorizer:
    def __init__(self, *, authorized: bool = True, mismatch: bool = False) -> None:
        self.authorized = authorized
        self.mismatch = mismatch
        self.requests = []

    def authorize(self, request):
        self.requests.append(request)
        decided_request = request
        if self.mismatch:
            decided_request = type(request)(
                principal_id=request.principal_id,
                tenant_id=request.tenant_id,
                authentication_evidence_ref=request.authentication_evidence_ref,
                operation=request.operation,
                target={"stream_id": "run:another-run"},
            )
        return EventAuthorizationDecision(
            request=decided_request,
            authorized=self.authorized,
            authorization_evidence_ref=(
                "authz://decision/reader-1" if self.authorized else None
            ),
            denial_reason_class=None if self.authorized else "policy_denied",
        )


class _Reader:
    def __init__(self, events: list[StoredEvent]) -> None:
        self.events = events
        self.requests = []
        self.get_scopes = []
        self.unavailable = False

    def read_stream(self, request):
        self.requests.append(request)
        if self.unavailable:
            raise EventStoreUnavailableError("database credentials must not escape")
        high_watermark = request.through_sequence or max(
            (
                event.stream_sequence
                for event in self.events
                if event.stream_id == request.stream_id
                and event.tenant_id == request.tenant_id
            ),
            default=None,
        )
        after = request.cursor.after_sequence if request.cursor is not None else 0
        matching = tuple(
            event
            for event in self.events
            if event.stream_id == request.stream_id
            and event.tenant_id == request.tenant_id
            and after < event.stream_sequence <= (high_watermark or 0)
            and (not request.event_types or event.event_type in request.event_types)
        )[: request.limit]
        next_cursor = None
        if matching and matching[-1].stream_sequence < (high_watermark or 0):
            next_cursor = StreamSequenceCursor(
                stream_id=request.stream_id,
                tenant_id=request.tenant_id,
                after_sequence=matching[-1].stream_sequence,
                high_watermark=high_watermark,
            )
        return EventPage(
            stream_id=request.stream_id,
            tenant_id=request.tenant_id,
            events=matching,
            high_watermark=high_watermark,
            next_cursor=next_cursor,
        )

    def get_event(self, event_id, *, tenant_id=None):
        self.get_scopes.append(tenant_id)
        if self.unavailable:
            raise EventStoreUnavailableError("database credentials must not escape")
        return next(
            (
                event
                for event in self.events
                if event.event_id == event_id and event.tenant_id == tenant_id
            ),
            None,
        )

    def get_stream_high_watermark(self, stream_id, *, tenant_id=None):
        if self.unavailable:
            raise EventStoreUnavailableError("database credentials must not escape")
        return max(
            (
                event.stream_sequence
                for event in self.events
                if event.stream_id == stream_id and event.tenant_id == tenant_id
            ),
            default=None,
        )


def test_run_reader_binds_authorized_tenant_and_exact_node_instance() -> None:
    reader = _Reader(
        [
            _event(1, tenant_id="tenant-a", node_instance_id="node-a"),
            _event(2, tenant_id="tenant-a", node_instance_id="node-b"),
            _event(1, tenant_id="tenant-b", node_instance_id="node-b"),
        ]
    )
    authorizer = _Authorizer()
    service = EventReaderService(reader, authorizer=authorizer)

    result = service.read_run_events(
        "run-reader",
        authorization=_authorization(),
        node_instance_id="node-b",
    )

    assert result.availability is EventServiceAvailability.AVAILABLE
    assert [event.event_id for event in result.events] == ["evt-tenant-a-2"]
    assert result.high_watermark == 2
    assert reader.requests[0].tenant_id == "tenant-a"
    assert reader.requests[0].stream_id == "run:run-reader"
    assert authorizer.requests[0].operation is EventPermission.READ
    assert authorizer.requests[0].target["node_instance_id"] == "node-b"


def test_reader_denies_before_touching_the_durable_port() -> None:
    reader = _Reader([_event(1, tenant_id="tenant-a", node_instance_id=None)])
    service = EventReaderService(reader, authorizer=_Authorizer(authorized=False))

    with pytest.raises(EventAuthorizationError, match="not authorized"):
        service.read_stream(
            "run:run-reader",
            authorization=_authorization(),
        )

    assert reader.requests == []


def test_unavailable_reader_returns_typed_status_without_projection_fallback() -> None:
    reader = _Reader([])
    reader.unavailable = True
    service = EventReaderService(reader, authorizer=_Authorizer())

    result = service.read_stream(
        "run:run-reader",
        authorization=_authorization(),
    )

    assert result.availability is EventServiceAvailability.UNAVAILABLE
    assert result.events == ()
    assert result.high_watermark is None
    assert result.unavailable_reason_class == "EventStoreUnavailableError"
    assert "credentials" not in result.unavailable_reason_class


def test_event_lookup_never_treats_none_tenant_as_a_wildcard() -> None:
    reader = _Reader([_event(1, tenant_id="tenant-b", node_instance_id=None)])
    service = EventReaderService(reader, authorizer=_Authorizer())

    result = service.get_event(
        "evt-tenant-b-1",
        authorization=EventAuthorizationContext(
            principal_id="operator-1",
            tenant_id=None,
            authentication_evidence_ref="authn://session/unscoped",
        ),
    )

    assert result.found is False
    assert reader.get_scopes == [None]


def test_node_instance_filter_scans_pages_and_returns_a_stable_matching_cursor() -> None:
    events = [
        _event(
            sequence,
            tenant_id="tenant-a",
            node_instance_id="wanted" if sequence in {3, 5, 7} else "other",
        )
        for sequence in range(1, 8)
    ]
    reader = _Reader(events)
    service = EventReaderService(reader, authorizer=_Authorizer())

    first = service.read_run_events(
        "run-reader",
        authorization=_authorization(),
        node_instance_id="wanted",
        limit=2,
    )
    second = service.read_run_events(
        "run-reader",
        authorization=_authorization(),
        node_instance_id="wanted",
        limit=2,
        cursor=first.next_cursor,
    )

    assert [event.stream_sequence for event in first.events] == [3, 5]
    assert first.next_cursor.after_sequence == 5
    assert first.next_cursor.high_watermark == 7
    assert [event.stream_sequence for event in second.events] == [7]
    assert second.next_cursor is None
    assert len(reader.requests) >= 3


def test_authorizer_decision_must_match_the_exact_request() -> None:
    reader = _Reader([_event(1, tenant_id="tenant-a", node_instance_id=None)])
    service = EventReaderService(reader, authorizer=_Authorizer(mismatch=True))

    with pytest.raises(EventAuthorizationContractError, match="exact request"):
        service.read_stream(
            "run:run-reader",
            authorization=_authorization(),
        )

    assert reader.requests == []


def test_reader_rejects_non_contiguous_or_filter_violating_pages() -> None:
    gap_reader = _Reader(
        [
            _event(1, tenant_id="tenant-a", node_instance_id="node-a"),
            _event(3, tenant_id="tenant-a", node_instance_id="node-a"),
        ]
    )
    service = EventReaderService(gap_reader, authorizer=_Authorizer())

    with pytest.raises(EventContractError, match="non-contiguous"):
        service.read_stream(
            "run:run-reader",
            authorization=_authorization(),
        )

    class FilterViolatingReader(_Reader):
        def read_stream(self, request):
            self.requests.append(request)
            event = self.events[0]
            return EventPage(
                stream_id=request.stream_id,
                tenant_id=request.tenant_id,
                events=(event,),
                high_watermark=event.stream_sequence,
            )

    violating = EventReaderService(
        FilterViolatingReader(
            [_event(1, tenant_id="tenant-a", node_instance_id="node-a")]
        ),
        authorizer=_Authorizer(),
    )
    with pytest.raises(EventContractError, match="event-type filter"):
        violating.read_stream(
            "run:run-reader",
            authorization=_authorization(),
            event_types=frozenset({"workflow_started"}),
        )


def test_node_instance_scan_rejects_a_cursor_that_does_not_advance() -> None:
    class StuckCursorReader(_Reader):
        def read_stream(self, request):
            page = super().read_stream(request)
            if request.cursor is not None and page.next_cursor is not None:
                object.__setattr__(page, "next_cursor", request.cursor)
            return page

    reader = StuckCursorReader(
        [
            _event(
                sequence,
                tenant_id="tenant-a",
                node_instance_id="wanted" if sequence == 205 else "other",
            )
            for sequence in range(1, 206)
        ]
    )
    service = EventReaderService(reader, authorizer=_Authorizer())

    with pytest.raises(EventContractError, match="cursor did not advance"):
        service.read_run_events(
            "run-reader",
            authorization=_authorization(),
            node_instance_id="wanted",
            limit=1,
        )


def test_event_lookup_rejects_another_event_identity() -> None:
    class WrongLookupReader(_Reader):
        def get_event(self, event_id, *, tenant_id=None):
            return self.events[0]

    service = EventReaderService(
        WrongLookupReader([_event(1, tenant_id="tenant-a", node_instance_id=None)]),
        authorizer=_Authorizer(),
    )

    with pytest.raises(EventContractError, match="another event target"):
        service.get_event("event-requested", authorization=_authorization())


@pytest.mark.parametrize(
    "evidence_ref",
    [
        "Bearer secret-token",
        "authn://session/../admin",
        "authn://session/value?token=secret",
        "authn://" + "x" * 600,
    ],
)
def test_authorization_context_rejects_unsafe_evidence_references(
    evidence_ref: str,
) -> None:
    with pytest.raises(ValueError, match="safe URI|unsafe path"):
        EventAuthorizationContext(
            principal_id="operator-1",
            tenant_id="tenant-a",
            authentication_evidence_ref=evidence_ref,
        )


def _authorization() -> EventAuthorizationContext:
    return EventAuthorizationContext(
        principal_id="operator-1",
        tenant_id="tenant-a",
        authentication_evidence_ref="authn://session/reader-1",
    )


def _event(
    sequence: int,
    *,
    tenant_id: str,
    node_instance_id: str | None,
) -> StoredEvent:
    candidate = EventCandidate(
        event_id=f"evt-{tenant_id}-{sequence}",
        event_type="step_started",
            data_schema="newsroom.harness-event/v1",
            source="io.newsroom.harness.runtime",
        occurred_at=NOW + timedelta(seconds=sequence),
        stream_id="run:run-reader",
        correlation_id="run-reader",
            business_context=BusinessContext(
                run_id="run-reader",
                graph_id="research.reader-repair.graph",
                graph_version="2",
                graph_ref="research.reader-repair.graph@2",
                graph_checksum="sha256:" + "a" * 64,
                stage_id="step-reader",
                node_instance_id=node_instance_id,
            ),
            producer=ProducerIdentity(
                component="framework.harness.runtime",
                version="1",
        ),
        payload={
            "step_id": "step-reader",
            "step_type": "function",
            "attempt": 1,
            "max_attempts": 1,
        },
        tenant_id=tenant_id,
    )
    return StoredEvent(
        candidate=candidate,
        observed_at=NOW + timedelta(seconds=sequence, microseconds=1),
        stream_sequence=sequence,
    )
