from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.application import (
    GraphEventHistoryDiagnostic,
    GraphEventHistoryDiagnosticCode,
    GraphEventProjectionApplicationRequest,
    GraphEventProjectionApplicationStatus,
    InactiveGraphEventProjectionAdapter,
    ReadOnlyEventMigrationAssessmentAdapter,
)
from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
    StoredEvent,
)
from framework.events.errors import EventContractError
from framework.events.migration import MigrationSourceKind, MigrationSourceRecord
from framework.events.projection import (
    GRAPH_EVENT_CONTEXT_EXTENSION,
    GRAPH_EVENT_PROJECTION_SCHEMA,
    GraphEventContext,
    GraphRunIdentity,
)
from framework.events.runtime.models import (
    EventPage,
    StreamReadRequest,
    StreamSequenceCursor,
)
from framework.events.schema.catalog import default_event_schema_catalog


_NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
_RUN_ID = "run-graph-application"


def test_inactive_adapter_projects_one_pinned_graph_history(tmp_path) -> None:
    reader = _Reader([_event(1), _event(2, with_node=True)])
    adapter = _adapter(reader)
    request = _request(tmp_path / "events.graph.jsonl")

    result = adapter.project_graph_history(request)

    assert result.status is GraphEventProjectionApplicationStatus.PROJECTED
    assert result.diagnostic is None
    assert result.projection is not None
    assert result.projection.graph_identity == _identity()
    assert result.projection.high_watermark == 2
    rows = [
        json.loads(line)
        for line in result.projection.path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["stream_sequence"] for row in rows] == [1, 2]
    assert all(
        row["projection_schema"] == GRAPH_EVENT_PROJECTION_SCHEMA
        for row in rows
    )
    assert reader.write_calls == 0
    assert {request.through_sequence for request in reader.requests} == {2}


def test_application_request_round_trip_rejects_tampering(tmp_path) -> None:
    request = GraphEventProjectionApplicationRequest(
        graph_identity=_identity(),
        target=tmp_path / "events.graph.jsonl",
        tenant_id="tenant-a",
        through_sequence=2,
    )
    restored = GraphEventProjectionApplicationRequest.from_dict(request.to_dict())
    tampered = request.to_dict()
    tampered["through_sequence"] = 1

    with pytest.raises(EventContractError, match="checksum is invalid"):
        GraphEventProjectionApplicationRequest.from_dict(tampered)

    assert restored == request


@pytest.mark.parametrize(
    ("workflow_id", "expected_code"),
    [
        (
            None,
            GraphEventHistoryDiagnosticCode.GRAPH_CONTEXT_MISSING,
        ),
        (
            "legacy-workflow",
            GraphEventHistoryDiagnosticCode.ORCHESTRATION_ALIAS_PRESENT,
        ),
    ],
)
def test_legacy_history_returns_typed_diagnostic_without_replacing_target(
    tmp_path,
    workflow_id: str | None,
    expected_code: GraphEventHistoryDiagnosticCode,
) -> None:
    target = tmp_path / "events.graph.jsonl"
    target.write_bytes(b"previous-qualified-projection\n")
    reader = _Reader(
        [_event(1, include_context=False, workflow_id=workflow_id)]
    )

    result = _adapter(reader).project_graph_history(_request(target))

    assert result.status is GraphEventProjectionApplicationStatus.HISTORY_ONLY
    assert result.projection is None
    assert result.diagnostic is not None
    assert result.diagnostic.code is expected_code
    assert result.diagnostic.disposition == "history_only"
    assert result.diagnostic.resumable is False
    assert result.diagnostic.executable is False
    assert result.diagnostic.projectable is False
    assert result.diagnostic.to_dict()["diagnostic_ref"] == (
        result.diagnostic.diagnostic_ref
    )
    assert (
        type(result.diagnostic).from_dict(result.diagnostic.to_dict())
        == result.diagnostic
    )
    assert target.read_bytes() == b"previous-qualified-projection\n"
    assert reader.write_calls == 0


def test_history_diagnostic_round_trip_rejects_tampering(tmp_path) -> None:
    result = _adapter(
        _Reader([_event(1, include_context=False)])
    ).project_graph_history(_request(tmp_path / "events.graph.jsonl"))
    assert result.diagnostic is not None
    tampered_checksum = result.diagnostic.to_dict()
    tampered_checksum["code"] = (
        GraphEventHistoryDiagnosticCode.GRAPH_CONTEXT_INVALID.value
    )
    invalid_authority_type = result.diagnostic.to_dict()
    invalid_authority_type["resumable"] = 0

    with pytest.raises(EventContractError, match="checksum is invalid"):
        GraphEventHistoryDiagnostic.from_dict(tampered_checksum)
    with pytest.raises(EventContractError, match="resumable must be a boolean"):
        GraphEventHistoryDiagnostic.from_dict(invalid_authority_type)


def test_mixed_graph_and_legacy_history_is_quarantined_atomically(tmp_path) -> None:
    target = tmp_path / "events.graph.jsonl"
    target.write_bytes(b"previous-qualified-projection\n")
    reader = _Reader([_event(1), _event(2, include_context=False)])

    result = _adapter(reader).project_graph_history(_request(target))

    assert result.status is GraphEventProjectionApplicationStatus.HISTORY_ONLY
    assert result.diagnostic is not None
    assert (
        result.diagnostic.code
        is GraphEventHistoryDiagnosticCode.GRAPH_CONTEXT_MISSING
    )
    assert result.diagnostic.observed_sequence == 2
    assert target.read_bytes() == b"previous-qualified-projection\n"
    assert list(tmp_path.glob(".events.graph.jsonl.*.tmp")) == []


def test_conflicting_graph_identity_is_history_only_not_projected(tmp_path) -> None:
    reader = _Reader([_event(1, graph_checksum="sha256:" + "b" * 64)])

    result = _adapter(reader).project_graph_history(
        _request(tmp_path / "events.graph.jsonl")
    )

    assert result.status is GraphEventProjectionApplicationStatus.HISTORY_ONLY
    assert result.diagnostic is not None
    assert (
        result.diagnostic.code
        is GraphEventHistoryDiagnosticCode.GRAPH_IDENTITY_MISMATCH
    )
    assert not (tmp_path / "events.graph.jsonl").exists()


def test_empty_history_does_not_fabricate_graph_projection(tmp_path) -> None:
    reader = _Reader([])

    result = _adapter(reader).project_graph_history(
        _request(tmp_path / "events.graph.jsonl")
    )

    assert result.status is GraphEventProjectionApplicationStatus.HISTORY_ONLY
    assert result.diagnostic is not None
    assert result.diagnostic.code is GraphEventHistoryDiagnosticCode.EMPTY_HISTORY
    assert result.diagnostic.high_watermark is None
    assert not (tmp_path / "events.graph.jsonl").exists()
    assert reader.requests == []


def test_requested_prefix_cannot_exceed_durable_history(tmp_path) -> None:
    request = GraphEventProjectionApplicationRequest(
        graph_identity=_identity(),
        target=tmp_path / "events.graph.jsonl",
        tenant_id="tenant-a",
        through_sequence=2,
    )

    with pytest.raises(EventContractError, match="exceeds durable history"):
        _adapter(_Reader([_event(1)])).project_graph_history(request)


def test_reader_cannot_return_another_tenant_scope(tmp_path) -> None:
    reader = _CrossScopeReader([_event(1)])

    with pytest.raises(EventContractError, match="first durable event"):
        _adapter(reader).project_graph_history(
            _request(tmp_path / "events.graph.jsonl")
        )


@pytest.mark.parametrize("page_size", [True, 0, 1_001])
def test_inactive_adapter_rejects_invalid_page_size(page_size) -> None:
    with pytest.raises(ValueError, match="page_size must be between"):
        InactiveGraphEventProjectionAdapter(
            reader=_Reader([]),
            schema_catalog=default_event_schema_catalog(),
            page_size=page_size,
        )


def test_read_only_migration_port_returns_typed_quarantine_report() -> None:
    adapter = ReadOnlyEventMigrationAssessmentAdapter()
    record = MigrationSourceRecord.issue(
        MigrationSourceKind.LEGACY_RUN_JSONL,
        "legacy/events.jsonl:1",
        "invalid_json",
    )

    report = adapter.assess_event_migration((record,), fail_fast=True)

    assert report.halted is True
    assert report.counts["scanned"] == 1
    assert report.counts["quarantine_total"] == 1


class _Reader:
    def __init__(self, events: list[StoredEvent]) -> None:
        self.events = events
        self.requests: list[StreamReadRequest] = []
        self.write_calls = 0

    def get_event(
        self,
        event_id: str,
        *,
        tenant_id: str | None = None,
    ) -> StoredEvent | None:
        return next(
            (
                event
                for event in self.events
                if event.event_id == event_id and event.tenant_id == tenant_id
            ),
            None,
        )

    def get_stream_high_watermark(
        self,
        stream_id: str,
        *,
        tenant_id: str | None = None,
    ) -> int | None:
        return max(
            (
                event.stream_sequence
                for event in self.events
                if event.stream_id == stream_id and event.tenant_id == tenant_id
            ),
            default=None,
        )

    def read_stream(self, request: StreamReadRequest) -> EventPage:
        self.requests.append(request)
        high_watermark = request.through_sequence
        after_sequence = (
            request.cursor.after_sequence if request.cursor is not None else 0
        )
        matching = tuple(
            event
            for event in self.events
            if event.stream_id == request.stream_id
            and event.tenant_id == request.tenant_id
            and after_sequence < event.stream_sequence <= (high_watermark or 0)
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

    def append_event(self, *_args, **_kwargs) -> None:
        self.write_calls += 1
        raise AssertionError("inactive projection adapter must not append events")


class _CrossScopeReader(_Reader):
    def read_stream(self, request: StreamReadRequest) -> EventPage:
        self.requests.append(request)
        return EventPage(
            stream_id=request.stream_id,
            tenant_id="tenant-b",
            events=(),
            high_watermark=request.through_sequence,
        )


def _adapter(reader: _Reader) -> InactiveGraphEventProjectionAdapter:
    return InactiveGraphEventProjectionAdapter(
        reader=reader,
        schema_catalog=default_event_schema_catalog(),
        page_size=1,
    )


def _request(target) -> GraphEventProjectionApplicationRequest:
    return GraphEventProjectionApplicationRequest(
        graph_identity=_identity(),
        target=target,
        tenant_id="tenant-a",
    )


def _identity(*, checksum: str = "sha256:" + "a" * 64) -> GraphRunIdentity:
    return GraphRunIdentity(
        run_id=_RUN_ID,
        graph_id="research.paper-analysis",
        graph_version="1",
        graph_schema_version="newsroom.normalized-harness-graph/v3",
        compiler_version="3",
        normalized_graph_checksum=checksum,
    )


def _event(
    sequence: int,
    *,
    with_node: bool = False,
    graph_checksum: str = "sha256:" + "a" * 64,
    include_context: bool = True,
    workflow_id: str | None = None,
) -> StoredEvent:
    context = GraphEventContext(
        identity=_identity(checksum=graph_checksum),
        node_id="analyze" if with_node else None,
        node_instance_id="analyze:1" if with_node else None,
    )
    extensions = (
        {GRAPH_EVENT_CONTEXT_EXTENSION: context.to_dict()}
        if include_context
        else {}
    )
    candidate = EventCandidate(
        event_id=f"evt-graph-application-{sequence}",
        event_type=(
            "harness_graph_initialized"
            if sequence == 1
            else "harness_graph_decision_committed"
        ),
        data_schema="newsroom.harness-graph-control-commit/v1",
        source="io.newsroom.harness.control-plane",
        occurred_at=_NOW + timedelta(seconds=sequence),
        stream_id=f"run:{_RUN_ID}",
        correlation_id=_RUN_ID,
        business_context=BusinessContext(
            run_id=_RUN_ID,
            workflow_id=workflow_id,
        ),
        producer=ProducerIdentity(
            component="framework.harness.control_plane",
            version="1",
        ),
        tenant_id="tenant-a",
        payload={"commit": {"sequence": sequence}},
        extensions=extensions,
    )
    return StoredEvent(
        candidate=candidate,
        observed_at=_NOW + timedelta(seconds=sequence, microseconds=1),
        stream_sequence=sequence,
    )
