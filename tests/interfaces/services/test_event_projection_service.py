from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from framework.events import (
    BusinessContext,
    EventCandidate,
    EventPage,
    ProducerIdentity,
    StoredEvent,
    StreamSequenceCursor,
    default_event_schema_catalog,
)
from framework.events.errors import EventStoreUnavailableError
from interfaces.services.event_projection_service import (
    EventProjectionConflictError,
    EventProjectionService,
    EventProjectionStatus,
)
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventAuthorizationDecision,
    EventServiceAvailability,
)


NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)


class _Authorizer:
    def __init__(self) -> None:
        self.requests = []

    def authorize(self, request):
        self.requests.append(request)
        return EventAuthorizationDecision(
            request=request,
            authorized=True,
            authorization_evidence_ref="authz://decision/projection-1",
        )


class _Reader:
    def __init__(self, events: list[StoredEvent]) -> None:
        self.events = events
        self.requests = []
        self.unavailable = False
        self.append_during_first_read: StoredEvent | None = None
        self.write_calls = 0

    def get_event(self, event_id, *, tenant_id=None):
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
            raise EventStoreUnavailableError("store unavailable")
        return max(
            (
                event.stream_sequence
                for event in self.events
                if event.stream_id == stream_id and event.tenant_id == tenant_id
            ),
            default=None,
        )

    def read_stream(self, request):
        if self.unavailable:
            raise EventStoreUnavailableError("store unavailable")
        self.requests.append(request)
        high_watermark = request.through_sequence
        after = request.cursor.after_sequence if request.cursor is not None else 0
        matching = tuple(
            event
            for event in self.events
            if event.stream_id == request.stream_id
            and event.tenant_id == request.tenant_id
            and after < event.stream_sequence <= (high_watermark or 0)
        )[: request.limit]
        if len(self.requests) == 1 and self.append_during_first_read is not None:
            self.events.append(self.append_during_first_read)
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

    def append_event(self, *_args, **_kwargs):
        self.write_calls += 1
        raise AssertionError("projection must never append to the live store")


def test_rebuild_uses_exact_requested_watermark_during_concurrent_append(tmp_path) -> None:
    reader = _Reader([_event(1), _event(2)])
    reader.append_during_first_read = _event(3)
    service = EventProjectionService(
        reader=reader,
        authorizer=_Authorizer(),
        artifact_root=tmp_path,
        schema_catalog=default_event_schema_catalog(),
        page_size=1,
    )

    result = service.rebuild_run_projection(
        "run-projection-service",
        requested_high_watermark=2,
        authorization=_authorization(),
    )

    rows = [
        json.loads(line)
        for line in result.projection.path.read_text(encoding="utf-8").splitlines()
    ]
    assert result.availability is EventServiceAvailability.AVAILABLE
    assert result.requested_high_watermark == 2
    assert result.path == (
        tmp_path / "run-projection-service" / "events.jsonl"
    ).resolve()
    assert [row["stream_sequence"] for row in rows] == [1, 2]
    assert all(request.through_sequence == 2 for request in reader.requests)
    assert reader.get_stream_high_watermark(
        "run:run-projection-service",
        tenant_id="tenant-a",
    ) == 3
    assert reader.write_calls == 0


def test_explicit_empty_prefix_does_not_turn_into_latest_projection(tmp_path) -> None:
    reader = _Reader([_event(1), _event(2)])
    service = EventProjectionService(
        reader=reader,
        authorizer=_Authorizer(),
        artifact_root=tmp_path,
        schema_catalog=default_event_schema_catalog(),
    )

    result = service.rebuild_run_projection(
        "run-projection-service",
        requested_high_watermark=None,
        authorization=_authorization(),
    )

    assert result.projection.path.read_bytes() == b""
    assert result.projection.high_watermark is None
    assert result.durable_high_watermark == 2
    assert reader.requests == []
    assert reader.write_calls == 0


def test_unavailable_rebuild_preserves_existing_projection(tmp_path) -> None:
    target = tmp_path / "run-projection-service" / "events.jsonl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-complete-projection\n")
    reader = _Reader([])
    reader.unavailable = True
    service = EventProjectionService(
        reader=reader,
        authorizer=_Authorizer(),
        artifact_root=tmp_path,
        schema_catalog=default_event_schema_catalog(),
    )

    result = service.rebuild_run_projection(
        "run-projection-service",
        requested_high_watermark=1,
        authorization=_authorization(),
    )

    assert result.availability is EventServiceAvailability.UNAVAILABLE
    assert result.unavailable_reason_class == "EventStoreUnavailableError"
    assert target.read_bytes() == b"previous-complete-projection\n"
    assert reader.write_calls == 0


def test_projection_status_verifies_file_before_reporting_running_or_stale(
    tmp_path,
) -> None:
    reader = _Reader([_event(1), _event(2)])
    service = EventProjectionService(
        reader=reader,
        authorizer=_Authorizer(),
        artifact_root=tmp_path,
        schema_catalog=default_event_schema_catalog(),
    )
    authorization = _authorization()
    projection = service.rebuild_run_projection(
        "run-projection-service",
        requested_high_watermark=1,
        authorization=authorization,
    ).projection

    running = service.get_run_projection_status(
        "run-projection-service",
        projection_high_watermark=1,
        projection_event_count=projection.event_count,
        projection_checksum=projection.checksum,
        run_is_active=True,
        authorization=authorization,
    )
    stale = service.get_run_projection_status(
        "run-projection-service",
        projection_high_watermark=1,
        projection_event_count=projection.event_count,
        projection_checksum=projection.checksum,
        run_is_active=False,
        authorization=authorization,
    )
    reader.unavailable = True
    unavailable = service.get_run_projection_status(
        "run-projection-service",
        projection_high_watermark=1,
        projection_event_count=projection.event_count,
        projection_checksum=projection.checksum,
        run_is_active=False,
        authorization=authorization,
    )

    assert running.status is EventProjectionStatus.RUNNING
    assert stale.status is EventProjectionStatus.STALE
    assert unavailable.status is EventProjectionStatus.UNAVAILABLE


def test_projection_path_cannot_be_overridden_or_escape_artifact_root(tmp_path) -> None:
    service = EventProjectionService(
        reader=_Reader([_event(1)]),
        authorizer=_Authorizer(),
        artifact_root=tmp_path / "runs",
        schema_catalog=default_event_schema_catalog(),
    )

    with pytest.raises(TypeError, match="unexpected keyword argument 'target'"):
        service.rebuild_run_projection(
            "run-projection-service",
            target=tmp_path / "outside.jsonl",
            requested_high_watermark=1,
            authorization=_authorization(),
        )
    with pytest.raises(ValueError):
        service.rebuild_run_projection(
            "../outside",
            requested_high_watermark=1,
            authorization=_authorization(),
        )

    assert not (tmp_path / "outside.jsonl").exists()


def test_projection_status_rejects_corrupt_file_and_partial_metadata(tmp_path) -> None:
    service = EventProjectionService(
        reader=_Reader([_event(1)]),
        authorizer=_Authorizer(),
        artifact_root=tmp_path,
        schema_catalog=default_event_schema_catalog(),
    )
    projection = service.rebuild_run_projection(
        "run-projection-service",
        requested_high_watermark=1,
        authorization=_authorization(),
    ).projection
    projection.path.write_text("{\"forged\":true}\n", encoding="utf-8")

    with pytest.raises(
        EventProjectionConflictError,
        match="projection_artifact_corrupt",
    ):
        service.get_run_projection_status(
            "run-projection-service",
            projection_high_watermark=1,
            projection_event_count=1,
            projection_checksum=projection.checksum,
            run_is_active=False,
            authorization=_authorization(),
        )
    with pytest.raises(EventProjectionConflictError, match="metadata_partial"):
        service.get_run_projection_status(
            "run-projection-service",
            projection_high_watermark=1,
            projection_event_count=1,
            projection_checksum=None,
            run_is_active=False,
            authorization=_authorization(),
        )


def test_projection_status_rejects_missing_projection_artifact(tmp_path) -> None:
    service = EventProjectionService(
        reader=_Reader([_event(1)]),
        authorizer=_Authorizer(),
        artifact_root=tmp_path,
        schema_catalog=default_event_schema_catalog(),
    )

    with pytest.raises(EventProjectionConflictError, match="artifact_missing"):
        service.get_run_projection_status(
            "run-projection-service",
            projection_high_watermark=1,
            projection_event_count=1,
            projection_checksum="sha256:" + "a" * 64,
            run_is_active=False,
            authorization=_authorization(),
        )


def test_projection_status_rejects_projection_ahead_of_durable_stream(tmp_path) -> None:
    service = EventProjectionService(
        reader=_Reader([_event(1)]),
        authorizer=_Authorizer(),
        artifact_root=tmp_path,
        schema_catalog=default_event_schema_catalog(),
    )

    with pytest.raises(EventProjectionConflictError, match="ahead_of_durable"):
        service.get_run_projection_status(
            "run-projection-service",
            projection_high_watermark=2,
            projection_event_count=2,
            projection_checksum="sha256:" + "a" * 64,
            run_is_active=False,
            authorization=_authorization(),
        )


def test_projection_status_requires_boolean_active_flag_and_authorizes_it(
    tmp_path,
) -> None:
    authorizer = _Authorizer()
    service = EventProjectionService(
        reader=_Reader([]),
        authorizer=authorizer,
        artifact_root=tmp_path,
        schema_catalog=default_event_schema_catalog(),
    )
    projection = service.rebuild_run_projection(
        "run-projection-service",
        requested_high_watermark=None,
        authorization=_authorization(),
    ).projection

    with pytest.raises(TypeError, match="must be a boolean"):
        service.get_run_projection_status(
            "run-projection-service",
            projection_high_watermark=None,
            projection_event_count=0,
            projection_checksum=projection.checksum,
            run_is_active=1,
            authorization=_authorization(),
        )
    status = service.get_run_projection_status(
        "run-projection-service",
        projection_high_watermark=None,
        projection_event_count=0,
        projection_checksum=projection.checksum,
        run_is_active=True,
        authorization=_authorization(),
    )

    assert status.status is EventProjectionStatus.CURRENT
    assert authorizer.requests[-1].target["run_is_active"] is True


def _authorization() -> EventAuthorizationContext:
    return EventAuthorizationContext(
        principal_id="operator-1",
        tenant_id="tenant-a",
        authentication_evidence_ref="authn://session/projection-1",
    )


def _event(sequence: int) -> StoredEvent:
    first = sequence == 1
    candidate = EventCandidate(
        event_id=f"evt-projection-{sequence}",
        event_type="workflow_started" if first else "step_started",
        data_schema="newsroom.workflow-event/v1",
        source="io.newsroom.workflow.runtime",
        occurred_at=NOW + timedelta(seconds=sequence),
        stream_id="run:run-projection-service",
        correlation_id="run-projection-service",
        business_context=BusinessContext(
            run_id="run-projection-service",
            workflow_id="workflow-projection",
            step_id=None if first else f"step-{sequence}",
        ),
        producer=ProducerIdentity(
            component="framework.workflow.runtime",
            version="1",
        ),
        payload=(
            {
                "workflow_id": "workflow-projection",
                "workflow_version": "1",
                "profile": "test",
            }
            if first
            else {
                "step_id": f"step-{sequence}",
                "step_type": "function",
                "attempt": 1,
                "max_attempts": 1,
            }
        ),
        tenant_id="tenant-a",
    )
    return StoredEvent(
        candidate=candidate,
        observed_at=NOW + timedelta(seconds=sequence, microseconds=1),
        stream_sequence=sequence,
    )
